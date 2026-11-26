"""Local wall-clock scheduling. All durations are minutes."""
import json
import re
import sqlite3
from time import perf_counter
from optimizer import Problem, optimize
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


def settle(s,now):
    """Record expired appointments exactly once before capturing planning inputs."""
    keep=[]
    for row in s["sessions"]:
        if clock(row["end"])<=now:
            k=row["task"]
            if k in s["tasks"]:
                event(s,row,now,0,s["tasks"][k]["left"],"Chưa ghi nhận")
        else:
            keep.append(row)
    s["sessions"]=keep


def plan(s, now, *, settled=False, baseline_only=False, seconds=3):
    started=perf_counter()
    if not settled:
        settle(s,now)
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
        if clock(h["start"]) < now < clock(h["end"]):
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
    baseline_seconds=perf_counter()-started
    problem=Problem(s,now,order,horizon,windows)
    if baseline_only:
        from optimizer import evaluate
        invalid=problem.validate(sessions)
        if invalid: raise ValueError(invalid)
        metrics=evaluate(problem,sessions)[1]
        optimization=dict(strategy="baseline",evaluated=1,rejected=0,baseline=metrics,selected=metrics,
                          timeout=False,seconds=baseline_seconds)
    else:
        sessions,left,optimization=optimize(problem,sessions,started,seconds)
        for collection in (dates,weeks):
            for row in collection.values(): row["scheduled"]=0
        for row in sessions:
            day=clock(row["start"]).date()
            dates[day.isoformat()]["scheduled"]+=row["minutes"]
            weeks[week(day)]["scheduled"]+=row["minutes"]
    optimization["baseline_seconds"]=round(baseline_seconds,4)
    reasons={}
    impacts={}
    for k,n in left.items():
        if not n: continue
        parents=[d for d in problem.parents[k] if left[d]]
        bound=problem.upper(max(now,release[k]),due[k])
        causes=[]
        if due[k]<=now: causes.append("quá hạn")
        if due[k].date()>horizon: causes.append("ngoài kỳ lập lịch")
        if parents:
            causes.append("vướng tiên quyết: "+", ".join(f"{ts[d]['name']} ({left[d]} phút, hạn {ts[d]['due']})" for d in parents))
        if due[k]>now and due[k].date()<=horizon and bound<ts[k]["left"]:
            causes.append(f"thiếu giờ trong cửa sổ cho phép: tối đa {bound} / cần {ts[k]['left']} phút")
        if not causes: causes.append("chưa xếp hết sau tìm kiếm giới hạn")
        reasons[k]=causes
        affected=sorted(d for d in problem.desc[k] if left[d])
        if affected: impacts[k]=dict(tasks=affected,minutes=sum(left[d] for d in affected))
    optimization["impacts"]=impacts
    optimization["blocked_unique"]=sum(n for k,n in left.items() if any(left[d] for d in problem.parents[k]))
    optimization["direct_minutes"]=sum(left.values())-optimization["blocked_unique"]
    projected=problem.left.copy()
    by_day=defaultdict(list)
    for row in sessions: by_day[row["start"][:10]].append(row)
    idle=[]
    for day_key,row in dates.items():
        for session in by_day[day_key]: projected[session["task"]]-=session["minutes"]
        spare=row["capacity"]-row["scheduled"]
        if spare<=0:continue
        free,nominal=problem.days[date.fromisoformat(day_key)]
        reasons_idle=Counter()
        for k,n in projected.items():
            if not n:continue
            if due[k].date().isoformat()<day_key: explanation="đã qua hạn"
            elif release[k].date().isoformat()>day_key: explanation="chưa đến ngày bắt đầu"
            elif any(projected[d] for d in problem.parents[k]): explanation="chờ tiên quyết"
            elif not any(max(now,a,release[k])<min(b,due[k]) for a,b in free): explanation="không có khung hợp lệ"
            else: explanation="cần xét giờ trống, nghỉ và cạnh tranh trong ngày"
            reasons_idle[explanation]+=1
        idle.append(dict(day=day_key,unused=spare,nominal=nominal,reasons=dict(reasons_idle)))
    optimization["idle"]=idle
    # Test necessary interval bounds around unfinished tasks. Keep the number
    # of intervals bounded; absence of a certificate is inconclusive.
    bottlenecks=[]
    pending=[k for k in order if left[k] and now<due[k] and due[k].date()<=horizon]
    for end in sorted({due[k] for k in pending})[:8]:
        starts={max(now,release[k]) for k in order if problem.left[k] and due[k]<=end}
        for start in sorted(starts,reverse=True)[:16]:
            group=[k for k in order if max(now,release[k])>=start and due[k]<=end and problem.left[k]]
            demand=sum(problem.left[k] for k in group)
            bound=problem.upper(start,end)
            if demand>bound:
                bottlenecks.append(dict(start=stamp(start),end=stamp(end),required=demand,upper_bound=bound,
                                        minimum_shortfall=demand-bound))
    optimization["bottlenecks"]=sorted(bottlenecks,key=lambda row:-row["minimum_shortfall"])[:5]
    for k,n in left.items():
        if not n: continue
        t=ts[k]
        causes=reasons[k]
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
        upper=problem.upper(now,d)
        comparisons.append(dict(due=stamp(d),required=demand,capacity=limits.get(d,0),
                                upper_bound=upper,proven_shortfall=max(0,demand-upper)))
    for d,count in Counter(t["due"][:10] for t in ts.values() if t["left"]).items():
        if count>1: warnings.append(f"{d} · {count} việc cùng ngày đến hạn.")
    total=sum(t["left"] for t in ts.values())
    s["analysis"]=dict(horizon_end=horizon.isoformat(),remaining=total,capacity=cumulative,
                       scheduled=total-sum(left.values()),unscheduled=sum(left.values()),courses=dict(course),
                       dates=dates,weeks=weeks,deadlines=comparisons,risks=risks,optimization=optimization,
                       due_at_plan={k:t["due"] for k,t in ts.items()})
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
            settle(s,clock)
            if mutate is not None:
                mutate(s)
            alerts = plan(s, clock, settled=True)
            recent=set(s.get("recent_risks",[])) if mutate is None else set()
            s["recent_risks"]=[r["task"] for r in s["analysis"]["risks"]
                              if r["task"] in recent or r["minutes"]>old_risks.get(r["task"],0)]
            s["warnings"] = alerts
            db.execute("UPDATE state SET body=? WHERE id=1",(json.dumps(s,ensure_ascii=False),))
            return s, alerts

    def read(self):
        with closing(sqlite3.connect(self.path)) as db:
            return json.loads(db.execute("SELECT body FROM state WHERE id=1").fetchone()[0])

