"""Exercise the real HTTP transport and the same SQLite file as the desktop."""
import json
import socket
import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from datetime import date, timedelta
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import uvicorn

from api import create_app
from planner import ROOT, Store


class HTTPWorkflow(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(temp.cleanup)
        self.db = Store(Path(temp.name))
        # Keep each test's first session in the future, regardless of the wall clock.
        self.db.update(lambda s: s["settings"].update(off=[date.today().isoformat()]))
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        self.addCleanup(sock.close)
        self.base = f"http://127.0.0.1:{sock.getsockname()[1]}"
        self.server = uvicorn.Server(uvicorn.Config(create_app(self.db), log_level="error"))
        thread = threading.Thread(target=self.server.run, kwargs={"sockets":[sock]}, daemon=True)
        thread.start()
        def stop():
            self.server.should_exit = True
            thread.join(5)
        self.addCleanup(stop)
        for _ in range(200):
            if self.server.started:
                break
            time.sleep(.01)
        self.assertTrue(self.server.started)
        self.task = dict(name="Practice PDE", course="PDE", estimate=75,
                         due=f"{date.today()+timedelta(days=10)} 22:00")

    def call(self, method, path, body=None):
        data = None if body is None else json.dumps(body).encode()
        req = Request(self.base+path, data=data, method=method,
                      headers={"Content-Type":"application/json"})
        try:
            response = urlopen(req,timeout=5)
        except HTTPError as exc:
            response = exc
        with response:
            return response.status, json.load(response)

    def test_end_to_end(self):
        self.assertEqual(self.call("GET","/health"), (200,{"status":"ok"}))
        code, task = self.call("POST","/tasks",self.task)
        self.assertEqual(code,201)
        self.assertEqual(task["left"],75)
        self.assertEqual(self.call("GET","/tasks"), (200,[task]))
        code, original = self.call("POST","/plans/generate")
        self.assertEqual(code,200)
        self.assertEqual(sum(s["minutes"] for s in original["sessions"]),75)
        self.assertEqual(self.call("GET","/plans/current"),(200,original))
        change = {"changes":[{"id":task["id"],"left":45}], "settings":{"block":15}}
        code, revised = self.call("POST","/plans/replan",change)
        self.assertEqual(code,200)
        self.assertEqual(sum(s["minutes"] for s in revised["sessions"]),45)
        self.assertLessEqual(max(s["minutes"] for s in revised["sessions"]),15)
        self.assertEqual(self.call("GET","/plans/current"),(200,revised))
        self.assertEqual(self.db.read()["tasks"][task["id"]]["left"],45)

    def test_web_crud_and_progress(self):
        self.assertEqual(self.call("POST","/courses",{"name":"PDE"})[0],201)
        self.assertEqual(self.call("POST","/courses",{"name":"PDE"})[0],409)
        _,task=self.call("POST","/tasks",self.task)
        key=task["id"]
        self.assertEqual(self.call("PATCH","/courses",{"name":"PDE","new_name":"Math"})[0],200)
        self.assertEqual(self.call("DELETE","/courses",{"name":"Math"})[0],409)
        edited=self.task | dict(course="Math",name="Exam",priority=5,left=45)
        self.assertEqual(self.call("PUT","/tasks/"+key,edited)[0],200)
        self.assertEqual(self.call("PUT","/tasks/"+key,edited | dict(deps=[key]))[0],422)
        self.assertEqual(self.call("POST","/progress",dict(task=key,actual=30,remaining=0))[0],200)
        _,state=self.call("GET","/dashboard")
        self.assertEqual(state["tasks"][key]["left"],0)
        self.assertEqual(state["tasks"][key]["course"],"Math")
        self.assertEqual(state["history"][-1]["actual"],30)
        self.assertFalse(state["sessions"])
        self.assertEqual(self.call("DELETE","/tasks/"+key)[0],200)
        self.assertEqual(self.call("DELETE","/courses",{"name":"Math"})[0],200)
        self.assertTrue(self.db.read()["history"])

    def test_local_web_assets(self):
        for path,marker in [("/","/assets/app.js"),("/assets/app.js","/dashboard"),("/assets/style.css",".week")]:
            with urlopen(self.base+path,timeout=5) as response:
                self.assertIn(marker,response.read().decode())

    def test_browser_workflow(self):
        edge=Path(os.environ.get("ProgramFiles(x86)",""))/"Microsoft/Edge/Application/msedge.exe"
        if not edge.is_file() or not shutil.which("node"):
            self.skipTest("Browser smoke test requires Windows Edge and Node 22+")
        with tempfile.TemporaryDirectory(dir=ROOT,ignore_cleanup_errors=True) as profile:
            subprocess.run(["node",ROOT/"tests/web-smoke.mjs",edge,profile,self.base],
                           check=True,timeout=60)
        self.assertEqual(self.db.read()["history"][-1]["actual"],35)

    def test_validation_and_atomicity(self):
        for patch in ({"due":"not a date"},{"due":"2026-02-30 20:00"},{"deps":["missing"]},
                      {"estimate":0},{"priority":9}):
            self.assertEqual(self.call("POST","/tasks",self.task | patch)[0],422)
        self.assertEqual(self.call("GET","/tasks"),(200,[]))
        _, task = self.call("POST","/tasks",self.task)
        change = {"changes":[{"id":task["id"],"left":12},{"id":"unknown","left":0}]}
        self.assertEqual(self.call("POST","/plans/replan",change)[0],404)
        self.assertEqual(self.call("GET","/tasks"),(200,[task]))
        self.assertEqual(self.call("POST","/plans/replan",{"settings":{"windows":["bad"]*7}})[0],422)

    def test_skip_and_overdue(self):
        _,task = self.call("POST","/tasks",self.task)
        _,plan = self.call("GET","/plans/current")
        first = plan["sessions"][0]
        skip = {"skip":[{"task":task["id"],"start":first["start"]}]}
        code,new = self.call("POST","/plans/replan",skip)
        self.assertEqual(code,200)
        self.assertGreaterEqual(new["sessions"][0]["start"],first["end"])
        self.assertEqual(self.call("POST","/plans/replan",skip)[0],409)
        code,new = self.call("POST","/plans/replan",{"changes":[{"id":task["id"],"due":"2000-01-01 12:00"}]})
        self.assertEqual(code,200)
        self.assertFalse(new["sessions"])
        self.assertTrue(new["warnings"])

