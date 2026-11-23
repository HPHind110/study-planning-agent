import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from tkinter import Tk

from app import App, load_sample
from planner import ROOT, Store, event, fresh, plan, validate

NOW = datetime(2026,11,23,8)
def state():
    s = fresh()
    s["courses"] = ["Toán"]
    s["settings"].update(windows=["09:00-13:00"]*7,cap=90,block=40,rest=10)
    return s

def add(s,k="a",due="2026-11-24 12:00",n=120,**kw):
    s["tasks"][k] = dict(name=k,course="Toán",kind="Bài tập",due=due,
                         estimate=n,left=n,priority=3,difficulty=3,deps=[]) | kw

class Scheduling(unittest.TestCase):
    def test_cap_break_split(self):
        s=state()
        add(s)
        plan(s,NOW)
        self.assertEqual([(x["start"][-5:],x["minutes"]) for x in s["sessions"]],
                         [("09:00",40),("09:50",40),("10:40",10),("09:00",30)])
    def test_inherited_deadline(self):
        s=state()
        add(s,"base","2026-12-01 18:00",20)
        add(s,"exam","2026-11-23 11:00",20,deps=["base"])
        add(s,"other","2026-11-24 09:00",20)
        plan(s,NOW)
        self.assertEqual([x["task"] for x in s["sessions"]],["base","exam","other"])
        self.assertIn("mở khóa",s["sessions"][0]["reason"])
    def test_priority_tie(self):
        s=state()
        add(s,n=20)
        add(s,"b",n=20,priority=5)
        plan(s,NOW)
        self.assertEqual(s["sessions"][0]["task"],"b")
    def test_constraints_and_shortfall(self):
        s=state()
        s["settings"]["off"]=["2026-11-23"]
        add(s,due="2026-11-24 09:15")
        self.assertTrue(plan(s,NOW))
        self.assertEqual([x["minutes"] for x in s["sessions"]],[15])
    def test_new_work_and_deadline_edit(self):
        s=state()
        add(s)
        plan(s,NOW)
        add(s,"b","2026-11-23 10:00",15)
        plan(s,NOW)
        self.assertEqual(s["sessions"][0]["task"],"b")
        s["tasks"]["b"]["due"]="2026-11-30 10:00"
        plan(s,NOW)
        self.assertEqual(s["sessions"][0]["task"],"a")
    def test_missed_on_reopen(self):
        s=state()
        add(s)
        plan(s,NOW)
        later=NOW.replace(hour=9,minute=45)
        plan(s,later)
        plan(s,later)
        self.assertEqual(len(s["history"]),1)
        self.assertEqual(s["tasks"]["a"]["left"],120)
        self.assertTrue(all(x["start"] >= "2026-11-23 09:45" for x in s["sessions"]))
    def test_skip_future(self):
        s=state()
        add(s)
        plan(s,NOW)
        old=s["sessions"].pop(0)
        event(s,old,NOW,0,120,"Bỏ buổi")
        plan(s,NOW)
        self.assertGreaterEqual(s["sessions"][0]["start"],old["end"])
    def test_partial_work(self):
        s=state()
        add(s)
        plan(s,NOW)
        event(s,s["sessions"].pop(0),NOW.replace(hour=9,minute=25),25,110,"Đã ghi")
        plan(s,NOW.replace(hour=9,minute=25))
        self.assertEqual(sum(x["minutes"] for x in s["sessions"] if x["start"][:10]=="2026-11-23"),65)
        self.assertEqual(sum(x["minutes"] for x in s["sessions"]),110)
    def test_cycle_and_invalid_deadline(self):
        s=state()
        add(s,deps=["a"])
        with self.assertRaises(ValueError): validate(s)
        s["tasks"]["a"].update(deps=[],due="2026-02-30 20:00")
        with self.assertRaises(ValueError): validate(s)
    def test_overdue_and_blocked(self):
        s=state()
        add(s,due="2026-11-20 12:00")
        add(s,"b",deps=["a"])
        warnings=plan(s,NOW)
        self.assertEqual(s["sessions"],[])
        self.assertTrue(any("quá hạn" in w for w in warnings))
        self.assertTrue(any("tiên quyết" in w for w in warnings))
    def test_atomic_import_and_reopen(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as d:
            db=Store(Path(d))
            db.update(lambda s:load_sample(s,ROOT/"sample.json"))
            with self.assertRaises(ValueError):
                db.update(lambda s:load_sample(s,ROOT/"sample.json"))
            s,_=Store(Path(d)).update()
            self.assertEqual(len(s["tasks"]),3)
    def test_intersecting_windows(self):
        s=state()
        s["settings"]["windows"][0]="09:00-10:00,09:30-11:00"
        with self.assertRaises(ValueError): validate(s)
    def test_desktop_sample(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as d:
            root=Tk()
            root.withdraw()
            try:
                app=App(root,Store(Path(d)))
                app.import_file(True)
                root.update_idletasks()
                self.assertEqual(len(app.tables["tasks"].get_children()),3)
                self.assertTrue(app.tables["plan"].get_children())
                root.after_cancel(app.timer)
            finally:
                root.destroy()

if __name__=="__main__":
    unittest.main()

