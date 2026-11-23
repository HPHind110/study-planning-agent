"""Exercise the real HTTP transport and the same SQLite file as the desktop."""
import json
import socket
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

