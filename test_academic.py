"""Deterministic academic fixtures. No calls to the user's data directory."""
import json
import sqlite3
import tempfile
import unittest
from collections import Counter
from contextlib import closing
from copy import deepcopy
from datetime import date, datetime, timedelta
from pathlib import Path

from academic import clock
from exchange import ImportRequest, commit, export_data, get_backup, prepare, snapshot
from planner import ROOT, Store, event, plan
from test_planner import add, state

NOW=datetime(2026,11,27,8)


def fixture():
    s=state()
    s["settings"].update(windows=["19:00-22:00"]*7,cap=100,block=40,rest=10,horizon_end="2027-01-10")
    for n in range(9):
        key=(date(2027,1,2)+timedelta(days=n)).isoformat()
        s["settings"].setdefault("overrides",{})[key]={"cap":240,"windows":"08:00-12:00, 19:00-22:00"}
    s["events"]={}
    def meeting(key,start,end,repeat="once",until=None):
        s["events"][key]=dict(name=key,start=start,end=end,repeat=repeat,until=until)
    meeting("exam","2026-11-29 20:00","2026-11-29 20:45")
    meeting("english-final","2026-12-01 20:00","2026-12-01 22:00")
    meeting("weekly-English","2026-12-01 20:00","2026-12-01 22:00","weekly","2027-01-01")
    meeting("lecture","2026-11-27 19:30","2026-11-27 20:30","weekly","2027-01-01")
    meeting("DW-presentation","2026-12-14 19:30","2026-12-14 20:30")
    meeting("SAD-presentation","2026-12-18 19:30","2026-12-18 20:30")
    for k,day,n,release,deps,kind in [
        ("exam-prep","11-29",100,None,[],"hard"),("English","12-01",75,None,[],"hard"),
        ("freeze","12-06",220,None,[],"soft"),("DW","12-14",310,None,["freeze"],"hard"),
        ("correct","12-21",160,"2026-12-15 00:00",["DW"],"soft"),
        ("video","12-23",150,None,["correct"],"hard"),("report","12-24",65,None,["video"],"soft"),
        ("SAD","12-18",320,None,[],"hard"),("SAD-report","12-26",110,"2026-12-18 20:30",["SAD"],"soft"),
        ("finals","01-10",1200,"2027-01-02 00:00",[],"hard")]:
        year="2027" if day.startswith("01") else "2026"
        add(s,k,year+"-"+day+" "+("19:00" if k in ("DW","SAD","exam-prep","English") else "22:00"),
            n,start_at=release,deps=deps,deadline_type=kind)
    return s


class AcademicCalendar(unittest.TestCase):
    def test_realistic_and_impossible_semester(self):
        for overloaded in (False,True):
            with self.subTest(overloaded=overloaded):
                s=fixture()
                if overloaded:
                    s["tasks"]["finals"].update(left=6000,estimate=6000)
                warnings=plan(s,NOW)
                scheduled=Counter()
                daily=Counter()
                prev=None
                for h in s["sessions"]:
                    k=h["task"]; t=s["tasks"][k]
                    a,b=clock(h["start"]),clock(h["end"])
                    self.assertLessEqual(h["end"],t["due"])
                    self.assertGreaterEqual(h["start"],t["start_at"] or "2026-11-27 08:00")
                    self.assertLessEqual(b.date(),date(2027,1,10))
                    if prev: self.assertGreaterEqual(a,prev+timedelta(minutes=10))
                    prev=b
                    for dep in t["deps"]: self.assertEqual(scheduled[dep],s["tasks"][dep]["left"])
                    for ev in s["events"].values():
                        first=clock(ev["start"])
                        occurs=first.date()==a.date() or (ev["repeat"]=="weekly" and a.date()>=first.date()
                            and a.weekday()==first.weekday() and a.date().isoformat()<=ev["until"])
                        if occurs: self.assertFalse(a.time()<clock(ev["end"]).time() and b.time()>first.time())
                    if a.date()<date(2027,1,2): self.assertGreaterEqual(a.hour,19)
                    else: self.assertTrue(8<=a.hour and b.hour<=12 or 19<=a.hour and b.hour<=22)
                    scheduled[k]+=h["minutes"];daily[a.date()]+=h["minutes"]
                for d,n in daily.items(): self.assertLessEqual(n,240 if d>=date(2027,1,2) else 100)
                self.assertEqual(bool(s["analysis"]["unscheduled"]),overloaded)
                if overloaded:
                    self.assertTrue(any("thiếu giờ" in w for w in warnings))
                    self.assertGreaterEqual(s["analysis"]["unscheduled"],6000-9*240)
                self.assertTrue(any("trùng giờ" in w for w in warnings))
                before=deepcopy(s["sessions"])
                plan(s,NOW)
                self.assertEqual(s["sessions"],before)

    def test_future_release_inside_window_and_soft_deadline(self):
        s=state()
        add(s,due="2026-11-27 10:12",n=30,start_at="2026-11-27 10:00",deadline_type="soft")
        warnings=plan(s,NOW)
        self.assertEqual([(h["start"],h["minutes"]) for h in s["sessions"]],[("2026-11-27 10:00",12)])
        self.assertEqual(s["tasks"]["a"]["due"],"2026-11-27 10:12")
        self.assertIn("hạn mềm"," ".join(warnings))
        s["tasks"]["a"]["start_at"]=s["tasks"]["a"]["due"]
        with self.assertRaises(ValueError): plan(s,NOW)

    def test_fixed_event_partial_block_overlap_and_recurrence_end(self):
        s=state();s["settings"].update(cap=240,horizon_end="2026-12-04")
        add(s,n=3000,due="2026-12-05 12:00")
        s["events"]={"class":dict(name="Lớp",start="2026-11-27 09:00",end="2026-11-27 11:00",
                                 repeat="weekly",until="2026-12-03")}
        plan(s,NOW)
        self.assertEqual(s["sessions"][0]["start"],"2026-11-27 11:00")
        self.assertEqual(next(h["start"] for h in s["sessions"] if h["start"].startswith("2026-12-04")),"2026-12-04 09:00")

    def test_horizon_extension_off_and_weekday_override(self):
        s=state();add(s,n=120,start_at="2026-11-28 00:00",due="2026-12-02 22:00")
        cfg=s["settings"];cfg.update(horizon_end="2026-11-27",weekday_caps=[20]*7)
        plan(s,NOW)
        self.assertEqual(s["analysis"]["risks"][0]["status"],"deferred")
        cfg.update(horizon_end="2026-11-30",off=["2026-11-28"],overrides={
            "2026-11-28":{"cap":200},"2026-11-29":{"windows":"13:00-14:00","cap":35}})
        plan(s,NOW)
        self.assertEqual([(h["start"],h["minutes"]) for h in s["sessions"]],
                         [("2026-11-29 13:00",35),("2026-11-30 09:00",20)])

    def test_incomplete_prerequisite_reopens_projection(self):
        s=state()
        for k,deps in [("a",[]),("b",["a"])]:
            add(s,k,due="2026-11-29 18:00",n=30,deps=deps)
        plan(s,NOW)
        old=s["sessions"].pop(0)
        later=clock(old["end"])
        event(s,old,later,30,20,"Đã ghi")
        plan(s,later)
        self.assertEqual([h["task"] for h in s["sessions"]],["a","b"])
        self.assertEqual(s["sessions"][0]["minutes"],20)

    def test_active_session_invalidated_by_event(self):
        s=state();add(s,n=60,due="2026-11-28 12:00")
        plan(s,NOW)
        s["events"]={"e":dict(name="Họp",start="2026-11-27 09:00",end="2026-11-27 10:00")}
        plan(s,NOW.replace(hour=9,minute=10))
        self.assertEqual(s["sessions"][0]["start"],"2026-11-27 10:00")
        self.assertEqual(s["tasks"]["a"]["left"],60)

    def test_last_weekly_overnight_occurrence_spills_into_next_day(self):
        s=state()
        s["settings"].update(windows=["07:00-10:00"]*7,horizon_end="2026-11-28")
        s["events"]={"away":dict(name="Đi xa",start="2026-11-20 19:00",end="2026-11-21 08:30",
                                 repeat="weekly",until="2026-11-27")}
        add(s,start_at="2026-11-28 07:00",due="2026-11-28 10:00",n=45)
        plan(s,NOW)
        self.assertEqual(s["sessions"][0]["start"],"2026-11-28 08:30")

    def test_tight_release_despite_high_total_capacity(self):
        s=state()
        add(s,n=80,start_at="2026-11-28 11:55",due="2026-11-28 12:00")
        plan(s,NOW)
        self.assertGreater(s["analysis"]["capacity"],80)
        self.assertEqual(s["analysis"]["unscheduled"],75)

    def test_reserve_tight_future_exam_window(self):
        s=state()
        add(s,"long",n=50,due="2026-11-29 22:00")
        add(s,"exam",n=15,start_at="2026-11-27 09:15",due="2026-11-27 09:30")
        plan(s,NOW)
        h=next(h for h in s["sessions"] if h["task"]=="exam")
        self.assertEqual((h["start"],h["end"]),("2026-11-27 09:15","2026-11-27 09:30"))

    def test_hard_tie_and_legacy_task(self):
        s=state()
        for k,kind in [("aa","soft"),("bb","hard")]:add(s,k,n=40,due="2026-11-27 15:00",deadline_type=kind)
        del s["tasks"]["bb"]["deadline_type"]
        before=deepcopy(s["settings"])
        plan(s,NOW)
        self.assertEqual(s["sessions"][0]["task"],"bb")
        self.assertEqual(before,s["settings"])


class Bulk(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.db=Store(Path(self.tmp.name))
        s=state()
        add(s,"other",n=5,due="2026-11-29 15:00")
        s["tasks"]["other"]["course"]="Khác"
        s["courses"].append("Khác")
        add(s,"base",n=50,due="2026-11-29 15:00")
        event(s,dict(task="base",start="2026-11-26 09:00",end="2026-11-26 09:30",minutes=30),NOW,30,20,"Đã ghi")
        self.db.update(lambda dest:dest.update(s),NOW)
        self.row=dict(id="dep",name="Bài bổ sung",course="Toán",due="2026-11-30 12:00",estimate=30,deps=["base"])
    def preview(self,**kwargs):
        req=ImportRequest(**kwargs)
        details,_=prepare(self.db.read(),req,NOW)
        req.token=details.get("token")
        return req,details

    def test_preview_is_readonly_and_dependencies_stable(self):
        before=self.db.path.read_bytes()
        req,r=self.preview(document={"tasks":[self.row]})
        self.assertEqual(r["added"],["dep"])
        self.assertEqual(self.db.path.read_bytes(),before)
        commit(self.db,req,NOW)
        self.assertEqual(self.db.read()["tasks"]["dep"]["deps"],["base"])
        _,r=self.preview(document={"tasks":[self.row]})
        self.assertEqual(r["duplicates"],["dep"])

    def test_invalid_duplicate_and_rollback(self):
        before=self.db.read()
        for rows in ([self.row,self.row],[self.row,self.row|dict(id="bad",deps=["missing"])],
                     [self.row|dict(start_at=self.row["due"])],[self.row|dict(estimate=-1)]):
            req,r=self.preview(document={"tasks":rows})
            self.assertTrue(r["errors"])
            with self.assertRaises(ValueError):commit(self.db,req,NOW)
            self.assertEqual(self.db.read(),before)

    def test_progress_scoped_replace_backup_and_restore(self):
        before=snapshot(self.db.read())
        keep=dict(before["state"]["tasks"]["base"],id="base",notes="Đã hiệu chỉnh",left=50)
        req,r=self.preview(mode="replace",scope={"courses":["Toán"]},document={"tasks":[self.row,keep]})
        out=commit(self.db,req,NOW)
        self.assertEqual(r["updated"],["base"])
        self.assertEqual(self.db.read()["tasks"]["base"]["left"],20)
        self.assertIn("other",self.db.read()["tasks"])
        self.assertEqual(before["state"]["history"],self.db.read()["history"])
        backup=get_backup(self.db,out["backup_id"])
        self.assertEqual(backup,before)
        req,r=self.preview(mode="restore",scope={"full_restore":True},document=backup)
        self.assertFalse(r["errors"])
        commit(self.db,req,NOW)
        self.assertEqual(snapshot(self.db.read()),before)

    def test_failed_write_rolls_back_backup(self):
        req,_=self.preview(mode="replace",scope={"courses":["Toán"]},document={})
        with closing(sqlite3.connect(self.db.path)) as db, db:
            db.execute("CREATE TRIGGER reject BEFORE UPDATE ON state BEGIN SELECT RAISE(ABORT,'test failure'); END")
        before=self.db.read()
        with self.assertRaises(sqlite3.IntegrityError):commit(self.db,req,NOW)
        self.assertEqual(self.db.read(),before)
        with closing(sqlite3.connect(self.db.path)) as db:
            self.assertFalse(db.execute("SELECT name FROM sqlite_master WHERE name='backups'").fetchall())

    def test_stale_preview_scope_and_settings(self):
        req,_=self.preview(document={"tasks":[self.row]})
        self.db.update(lambda s:s["tasks"]["base"].update(left=12),NOW)
        with self.assertRaises(RuntimeError):commit(self.db,req,NOW)
        for scope,doc in [({},{}),({"courses":["Khác"]},{"tasks":[self.row]}),
                          ({"courses":["Toán"]},{"settings":{"cap":20}})]:
            _,r=self.preview(mode="replace",scope=scope,document=doc)
            self.assertTrue(r["errors"])
        _,r=self.preview(mode="replace",scope={"courses":["Toán"]},document={})
        self.assertEqual(r["deleted"],["base"])

    def test_export_unicode_events_settings(self):
        doc={"tasks":[self.row],"events":[dict(id="test",name="Thi viết",start="2026-11-29 20:00",end="2026-11-29 20:45")],
             "settings":{"horizon_end":"2027-01-10","overrides":{"2026-11-27":{"cap":70}}}}
        req,r=self.preview(document=doc,scope={"settings":True})
        self.assertFalse(r["errors"]);commit(self.db,req,NOW)
        exported=json.loads(json.dumps(export_data(self.db.read()),ensure_ascii=False))
        self.assertEqual(exported["events"][0]["name"],"Thi viết")
        self.assertEqual(exported["settings"]["overrides"]["2026-11-27"]["cap"],70)

