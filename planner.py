"""Local wall-clock scheduling. All durations are minutes."""
import json
import re
import sqlite3
from contextlib import closing
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from pathlib import Path
from academic import clock, day_value, validate_calendar, day_calendar, capacity

ROOT = Path(__file__).resolve().parent
MIN = timedelta(minutes=1)
KINDS = ("Bài tập", "Kỳ thi", "Mục tiêu")


def fresh():
    return dict(courses=[], tasks={}, history=[], sessions=[],
                settings=json.loads((ROOT / "defaults.json").read_text(encoding="utf8")))


def integer(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{label} cần là số nguyên từ {low} đến {high}.")


def windows(value):
    result = []
    for part in filter(None, (s.strip() for s in value.split(","))):
        if not re.fullmatch(r"\d\d:\d\d-\d\d:\d\d", part):
            raise ValueError("Dùng khung HH:MM-HH:MM, cách nhau bằng dấu phẩy.")
        a, b = (time.fromisoformat(s) for s in part.split("-"))
        if a >= b:
            raise ValueError("Giờ kết thúc phải sau giờ bắt đầu trong cùng ngày.")
        result.append((a, b))
    result.sort()
    if any(a[1] > b[0] for a, b in zip(result, result[1:])):
        raise ValueError("Các khung giờ bị chồng lấn.")
    return result


def validate(s):
    cfg = s["settings"]
    for k, lo, hi in [("cap", 1, 720), ("block", 5, 120), ("rest", 1, 60)]:
        integer(cfg[k], lo, hi, k)
    if len(cfg["windows"]) != 7:
        raise ValueError("Cần lịch cho cả 7 ngày.")
    for w in cfg["windows"]:
        windows(w)
    for d in cfg["off"]:
        date.fromisoformat(d)
    validate_calendar(s,windows,integer)
    tasks = s["tasks"]
    for key, t in tasks.items():
        if not t["name"].strip() or t["course"] not in s["courses"] or t["kind"] not in KINDS:
            raise ValueError("Kiểm tra tên việc, môn và loại việc.")
        due = datetime.strptime(t["due"], "%Y-%m-%d %H:%M")
        if due.strftime("%Y-%m-%d %H:%M") != t["due"]:
            raise ValueError("Hạn cần dạng YYYY-MM-DD HH:MM.")
        if t.get("start_at") is not None and clock(t["start_at"])>=due:
            raise ValueError("Thời điểm bắt đầu phải trước hạn.")
        if t.get("deadline_type","hard") not in ("hard","soft"):
            raise ValueError("Loại hạn không hợp lệ.")
        for k in ("priority", "difficulty"):
            integer(t[k], 1, 5, k)
        integer(t["estimate"], 1, 100000, "Khối lượng")
        integer(t["left"], 0, 100000, "Còn lại")
        if not isinstance(t["deps"], list) or any(p not in tasks for p in t["deps"]):
            raise ValueError("Không tìm thấy việc tiên quyết.")
    return ordered(tasks)


def ordered(tasks):
    result, seen, path = [], set(), set()
    def visit(k):
        if k in path:
            raise ValueError("Các việc phụ thuộc vòng tròn.")
        if k in seen:
            return
        path.add(k)
        for dep in tasks[k]["deps"]:
            visit(dep)
        path.remove(k)
        seen.add(k)
        result.append(k)
    for k in tasks:
        visit(k)
    return result


def stamp(d):
    return d.strftime("%Y-%m-%d %H:%M")


def event(s, session, now, actual, remaining, status):
    t = s["tasks"][session["task"]]
    integer(actual, 0, 1440, "Thời gian thực học")
    integer(remaining, 0, 100000, "Phút còn lại")
    t["left"] = remaining
    s["history"].append(dict(session, name=t["name"], at=stamp(now),
                             actual=actual, remaining=remaining, status=status))


def plan(s, now):
    order = validate(s)
    now = now.replace(second=0, microsecond=0)
    ts, cfg = s["tasks"], s["settings"]
    horizon = day_value(cfg["horizon_end"]) if cfg.get("horizon_end") else now.date()+timedelta(days=89)
    left = {k:t["left"] for k,t in ts.items()}
    due = {k:clock(t["due"]) for k,t in ts.items()}
    release = {k:clock(t["start_at"]) if t.get("start_at") else datetime.min for k,t in ts.items()}
    effective = due.copy()
    hard = {k:t.get("deadline_type","hard")=="hard" for k,t in ts.items()}
    for k in reversed(order):
        if left[k]:
            for dep in ts[k]["deps"]:
                if effective[k] < effective[dep]:
                    effective[dep],hard[dep] = effective[k],hard[k]
                elif effective[k] == effective[dep]:
                    hard[dep] |= hard[k]

    active = None
    for h in s["sessions"]:
        if h["task"] not in ts:
            continue
        if clock(h["end"]) <= now:
            event(s,h,now,0,left[h["task"]],"Chưa ghi nhận")
        elif clock(h["start"]) < now < clock(h["end"]):
            active=h
    spent, skipped = Counter(), defaultdict(list)
    last_break = datetime.min
    for h in s["history"]:
        a,b = clock(h["start"]),clock(h["end"])
        spent[a.date()] += h["actual"]
        if h["status"]=="Bỏ buổi":
            skipped[a.date()].append((a,b))
        if h["actual"] and a.date()==clock(h["at"]).date():
            last_break=max(last_break,clock(h["at"])+cfg["rest"]*MIN)
    events=[(ev,clock(ev["start"]),clock(ev["end"])) for ev in s.get("events",{}).values()]
    sessions,warnings,risks,dates,weeks,limits=[],[],[],{}, {}, {}
    course=Counter()
    for t in ts.values():
        course[t["course"]] += t["left"]
    deadlines=sorted({d for k,d in due.items() if left[k]})
    cumulative=0
    def week(d):
        return (d-timedelta(days=d.weekday())).isoformat()
    def bucket(container,key):
        return container.setdefault(key, dict(capacity=0,required=0,scheduled=0))
    blocked_by_events = defaultdict(list)
    for step in range((horizon-now.date()).days+1):
        day=now.date()+timedelta(days=step)
        free,cap,overlap=day_calendar(s,day,windows,events,skipped)
        if events:
            without_events,_,_=day_calendar(s,day,windows,[],skipped)
            if without_events!=free:
                blocked_by_events[day]=(without_events,free)
        if overlap:
            warnings.append(f"{day} · các sự kiện cố định trùng giờ.")
        start_day=datetime.combine(day,time.min)
        first=max(now,start_day,last_break)
        available=max(0,cap-spent[day])
        end_day=datetime.combine(day,time.max).replace(second=0,microsecond=0)
        keep=0
        if active and day==now.date():
            k=active["task"]
            a,b=clock(active["start"]),clock(active["end"])
            if (release[k]<=a and b<=due[k] and active["minutes"]<=min(left[k],available,cfg["block"])
                    and all(left[d]==0 for d in ts[k]["deps"])
                    and a>=last_break and any(x<=a<b<=y for x,y in free)):
                keep=active["minutes"]
                sessions.append(active)
                left[k]-=keep
                first=b+cfg["rest"]*MIN
                last_break=first
                available-=keep
        # Baseline capacity is independent of which tasks the heuristic selects.
        daily_capacity=keep+capacity(free,first,end_day,available,cfg["block"],cfg["rest"])
        date_row=bucket(dates,day.isoformat())
        week_row=bucket(weeks,week(day))
        date_row["capacity"]=daily_capacity
        week_row["capacity"]+=daily_capacity
        for d in deadlines:
            if d.date()==day:
                limits[d]=cumulative+(keep if not keep or clock(active["end"])<=d else 0)+capacity(
                    free,first,d,available,cfg["block"],cfg["rest"])
        cumulative+=daily_capacity
        allocated=keep
        for a,b in free:
            pos=max(first,a,last_break)
            while pos<b and available:
                eligible=[k for k in order if left[k] and pos<due[k]
                          and all(left[d]==0 for d in ts[k]["deps"])]
                ready=[k for k in eligible if release[k]<=pos]
                if not ready:
                    future=[release[k] for k in eligible if pos<release[k]<b]
                    if not future: break
                    pos=min(future)
                    continue
                target={k:effective[k] if pos<effective[k] else due[k] for k in ready}
                # Translate remaining effort into calendar days using typical daily capacity.
                def rank(k):
                    slack=(target[k]-pos).total_seconds()/60-left[k]*min(8,1440/max(1,cap))
                    return slack,not hard[k],-ts[k]["priority"],-ts[k]["difficulty"],k
                k=min(ready,key=rank)
                stop=min(b,target[k])
                # Leave time for a newly released task whose whole deadline window
                # would be consumed by the current block and its mandatory break.
                for waiting in eligible:
                    opens=release[waiting]
                    if not pos<opens<stop or due[waiting]>=target[k]: continue
                    if opens+left[waiting]*MIN >= due[waiting]:
                        stop=min(stop,max(pos,opens-cfg["rest"]*MIN))
                if stop<=pos:
                    pos=min(release[i] for i in eligible if release[i]>pos)
                    continue
                n=min(cfg["block"],left[k],available,int((stop-pos)/MIN))
                finish=pos+n*MIN
                reason=f"Hạn xét {stamp(target[k])} · còn {left[k]} phút · ưu tiên {ts[k]['priority']}/5 · khó {ts[k]['difficulty']}/5"
                if target[k]<due[k]:
                    reason+=" · mở khóa việc đến hạn sớm hơn"
                sessions.append(dict(task=k,start=stamp(pos),end=stamp(finish),minutes=n,reason=reason))
                left[k]-=n
                available-=n
                allocated+=n
                pos=finish+cfg["rest"]*MIN
                last_break=pos
        date_row["scheduled"]=allocated
        week_row["scheduled"]+=allocated
    for k,n in left.items():
        if not n: continue
        t=ts[k]
        causes=[]
        if due[k]<=now: causes.append("quá hạn")
        if any(left[d] for d in t["deps"]): causes.append("vướng tiên quyết")
        if due[k].date()>horizon: causes.append("ngoài kỳ lập lịch")
        if release[k]>now: causes.append("giới hạn ngày bắt đầu")
        for day,(unblocked,free) in blocked_by_events.items():
            lo=max(now,release[k],datetime.combine(day,time.min))
            hi=min(due[k],datetime.combine(day,time.max))
            if lo<hi:
                def span(intervals):
                    return sum(max(0,(min(b,hi)-max(a,lo))/MIN) for a,b in intervals)
                if span(unblocked)>span(free):
                    causes.append("sự kiện cố định giảm giờ rảnh")
                    break
        if not causes or (due[k]>now and due[k].date()<=horizon and not any(left[d] for d in t["deps"])):
            causes.append("thiếu giờ khả dụng trước hạn")
        if due[k].date()>horizon:
            suggestion="Kéo dài kỳ lập lịch để xét phần còn lại."
        elif any(left[d] for d in t["deps"]):
            suggestion="Ghi lại tiến độ và kiểm tra hạn của việc tiên quyết."
        else:
            suggestion="Xem lại ước lượng, giảm việc tùy chọn hoặc thêm khung giờ khả thi."
        if t.get("deadline_type")=="soft":
            suggestion+=" Cân nhắc dời hạn mềm."
        status="overdue" if due[k]<=now else "deferred" if due[k].date()>horizon else "unscheduled"
        risks.append(dict(task=k,minutes=n,status=status,causes=causes,recommendation=suggestion))
        warnings.append(f"{t['name']} · chưa xếp {n} phút ({', '.join(causes)}). {suggestion}")
    comparisons=[]
    for k,t in ts.items():
        if t["left"] and due[k].date()<=horizon:
            bucket(dates,due[k].date().isoformat())["required"]+=t["left"]
            bucket(weeks,week(due[k].date()))["required"]+=t["left"]
    for d in deadlines:
        if d.date()>horizon: continue
        demand=sum(t["left"] for k,t in ts.items() if due[k]<=d)
        comparisons.append(dict(due=stamp(d),required=demand,capacity=limits.get(d,0)))
    for d,count in Counter(t["due"][:10] for t in ts.values() if t["left"]).items():
        if count>1: warnings.append(f"{d} · {count} việc cùng ngày đến hạn.")
    total=sum(t["left"] for t in ts.values())
    s["analysis"]=dict(horizon_end=horizon.isoformat(),remaining=total,capacity=cumulative,
                       scheduled=total-sum(left.values()),unscheduled=sum(left.values()),courses=dict(course),
                       dates=dates,weeks=weeks,deadlines=comparisons,risks=risks)
    s["sessions"]=sessions
    return warnings



class Store:
    def __init__(self, folder):
        folder.mkdir(parents=True, exist_ok=True)
        self.path = folder / "study.sqlite3"
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY, body TEXT)")
            db.execute("INSERT OR IGNORE INTO state VALUES (1,?)",(json.dumps(fresh()),))

    def update(self, mutate=None, now=None):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            s = json.loads(db.execute("SELECT body FROM state WHERE id=1").fetchone()[0])
            clock = now or datetime.now()
            old_risks={r["task"]:r["minutes"] for r in s.get("analysis",{}).get("risks",[])}
            plan(s, clock)
            if mutate is not None:
                mutate(s)
            alerts = plan(s, clock)
            recent=set(s.get("recent_risks",[])) if mutate is None else set()
            s["recent_risks"]=[r["task"] for r in s["analysis"]["risks"]
                              if r["task"] in recent or r["minutes"]>old_risks.get(r["task"],0)]
            s["warnings"] = alerts
            db.execute("UPDATE state SET body=? WHERE id=1",(json.dumps(s,ensure_ascii=False),))
            return s, alerts

    def read(self):
        with closing(sqlite3.connect(self.path)) as db:
            return json.loads(db.execute("SELECT body FROM state WHERE id=1").fetchone()[0])

