import itertools
import random
import unittest
from copy import deepcopy
from datetime import timedelta
from time import perf_counter

from optimizer import Problem, evaluate, generate, optimize
from planner import plan, validate, windows
from test_planner import NOW, add, state
from academic import day_value


def small():
    s=state()
    s["settings"].update(cap=30,block=20,rest=5,horizon_end=NOW.date().isoformat(),
                         windows=["09:00-09:35"]*7)
    return s


def problem(s,now=NOW):
    return Problem(s,now,validate(s),day_value(s["settings"]["horizon_end"]),windows)


def session(k,start,end):
    return dict(task=k,start=f"2026-11-23 09:{start:02}",end=f"2026-11-23 09:{end:02}",
                minutes=end-start,reason="fixture")


class Optimization(unittest.TestCase):
    def test_exhaustive_priority_and_hard_protection(self):
        # Tiny horizon admits exactly one 20-minute job or partial combinations.
        s=small()
        s["settings"].update(cap=20,windows=["09:00-09:20"]*7)
        add(s,"soft",due="2026-11-23 09:20",n=30,deadline_type="soft",priority=5)
        add(s,"hard",due="2026-11-23 09:20",n=10,priority=1)
        plan(s,NOW)
        o=s["analysis"]["optimization"]
        self.assertLess(o["selected"]["hard_minutes"],o["baseline"]["hard_minutes"])
        # Enumerate all amounts and both orders; contiguous runs suffice for two
        # jobs released together, as further switches only consume extra rest.
        costs=[]
        for a,b in itertools.product(range(21),range(11)):
            for order in itertools.permutations([(a,30,5),(b,10,1)]):
                if sum(x[0] for x in order)+(5 if a and b else 0)<=20:
                    costs.append((10-b,int(b<10),(30-a)*5+10-b,40-a-b))
        self.assertEqual(tuple(o["selected"][k] for k in ("hard_minutes","hard_tasks","weighted","unscheduled")),min(costs))
        self.assertLess(o["baseline"]["unscheduled"],o["selected"]["unscheduled"])

    def test_shared_descendants_counted_once(self):
        s=small()
        for k,n,deps in [("root",30,[]),("other",30,[]),("joint",240,["root","other"]),("last",150,["joint"])]:
            add(s,k,n=n,due="2026-11-23 09:10",deps=deps)
        plan(s,NOW)
        o=s["analysis"]["optimization"]
        self.assertEqual(o["blocked_unique"],390)
        self.assertEqual(o["impacts"]["root"]["minutes"],390)
        self.assertEqual(o["impacts"]["other"]["minutes"],390)
        self.assertEqual(s["analysis"]["deadlines"][0]["proven_shortfall"],440)

    def test_validator_rejects_constraints(self):
        s=small()
        add(s,"a",due="2026-11-23 09:32",n=25,start_at="2026-11-23 09:03")
        add(s,"b",due="2026-11-23 09:35",n=5,deps=["a"])
        p=problem(s)
        good=session("a",3,13)
        for rows in ([session("b",0,5)],[session("a",0,8)],[session("a",25,33)],
                     [session("a",3,25)],[good,session("a",15,25)],[dict(good,minutes=8)],
                     [dict(good,task="unknown")],[good,session("a",18,34)],
                     [dict(good,start="2026-11-24 09:03",end="2026-11-24 09:13")]):
            self.assertTrue(p.validate(rows))
        self.assertIsNone(p.validate([good]))
        s["events"]={"x":dict(name="Workshop",start=good["start"],end=good["end"],repeat="weekly")}
        self.assertTrue(problem(s).validate([good]))

    def test_snapshot_active_partial_and_timeout(self):
        s=small();add(s,n=50,due="2026-11-23 10:00",left=15)
        s["sessions"]=[session("a",0,10)]
        now=NOW.replace(hour=9,minute=5)
        before=deepcopy(s)
        p=problem(s,now)
        rows=generate(p,"edf",set(),perf_counter()+10)
        self.assertEqual(s,before)
        self.assertEqual(rows[0],s["sessions"][0])
        self.assertEqual(sum(h["minutes"] for h in rows),15)
        selected,_,info=optimize(p,rows,perf_counter(),seconds=0)
        self.assertTrue(info["timeout"])
        self.assertIsNone(p.validate(selected))
        self.assertEqual(evaluate(p,selected)[0],evaluate(p,rows)[0])

    def test_preserve_valid_future_and_history(self):
        s=small();add(s,n=10,due="2026-11-23 09:35")
        s["sessions"]=[session("a",20,30)]
        plan(s,NOW)
        self.assertEqual(s["sessions"],[session("a",20,30)])
        plan(s,NOW.replace(hour=10))
        plan(s,NOW.replace(hour=10))
        self.assertEqual(len(s["history"]),1)
        self.assertEqual(s["tasks"]["a"]["left"],10)

    def test_fragmentation_tiebreak(self):
        s=small();add(s,n=20,due="2026-11-23 09:35")
        p=problem(s)
        split=[session("a",0,5),session("a",10,25)]
        whole=[session("a",0,20)]
        self.assertIsNone(p.validate(split))
        # Equal disruption to the original when compared with no prior investment
        # in either alternative. Compact schedule also needs fewer new slots.
        self.assertLess(evaluate(p,whole)[0],evaluate(p,split)[0])
        self.assertEqual(evaluate(p,whole)[1]["short"],0)
        self.assertEqual(evaluate(p,split)[1]["short"],2)

    def test_deterministic_with_task_and_calendar_edits(self):
        s=small();add(s,n=30,due="2026-11-24 12:00")
        for action in ("add","progress","event","delete"):
            if action=="add":add(s,"b",n=10,due="2026-11-23 09:30")
            if action=="progress":s["tasks"]["a"]["left"]=12
            if action=="event":s["settings"]["overrides"]={"2026-11-23":{"cap":12}}
            if action=="delete":del s["tasks"]["b"]
            clone=deepcopy(s)
            plan(s,NOW);plan(clone,NOW)
            self.assertEqual(s["sessions"],clone["sessions"])
            o=s["analysis"]["optimization"]
            self.assertLessEqual(tuple(o["selected"].values()),tuple(o["baseline"].values()))
            self.assertIsNone(problem(s).validate(s["sessions"]))

    def test_idle_due_to_future_release(self):
        s=small();add(s,n=15,start_at="2026-11-24 08:00",due="2026-11-25 10:00")
        plan(s,NOW)
        self.assertIn("chưa đến ngày bắt đầu",s["analysis"]["optimization"]["idle"][0]["reasons"])

