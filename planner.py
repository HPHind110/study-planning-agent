"""Local wall-clock scheduling. All durations are minutes."""
import json
import re
import sqlite3
from contextlib import closing
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from pathlib import Path

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
    tasks = s["tasks"]
    for key, t in tasks.items():
        if not t["name"].strip() or t["course"] not in s["courses"] or t["kind"] not in KINDS:
            raise ValueError("Kiểm tra tên việc, môn và loại việc.")
        due = datetime.strptime(t["due"], "%Y-%m-%d %H:%M")
        if due.strftime("%Y-%m-%d %H:%M") != t["due"]:
            raise ValueError("Hạn cần dạng YYYY-MM-DD HH:MM.")
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
    remaining = {k: t["left"] for k, t in ts.items()}
    deadlines = {k: datetime.fromisoformat(t["due"]) for k, t in ts.items()}
    effective = deadlines.copy()
    for k in reversed(order):
        if remaining[k]:
            for dep in ts[k]["deps"]:
                effective[dep] = min(effective[dep], effective[k])
    spent, resume = Counter(), {}
    sessions, warnings = [], []
    for old in s["sessions"]:
        start, end = map(datetime.fromisoformat, (old["start"], old["end"]))
        k = old["task"]
        if end <= now and k in ts:
            event(s, old, now, 0, ts[k]["left"], "Chưa ghi nhận")
        elif start < now < end and k in ts and remaining[k] >= old["minutes"] and end <= deadlines[k] and not any(remaining[d] for d in ts[k]["deps"]):
            sessions.append(old)
            remaining[k] -= old["minutes"]
            spent[start.date()] += old["minutes"]
            resume[start.date()] = end + cfg["rest"] * MIN
    for h in s["history"]:
        at = datetime.fromisoformat(h["at"])
        study_day = datetime.fromisoformat(h["start"]).date()
        spent[study_day] += h["actual"]
        if h["status"] == "Bỏ buổi":
            end = datetime.fromisoformat(h["end"])
            if end.date() == now.date() and datetime.fromisoformat(h["start"]) <= now:
                resume[now.date()] = max(resume.get(now.date(), now), end)
        if h["actual"] and at.date() == study_day:
            resume[at.date()] = max(resume.get(at.date(), at), at + cfg["rest"] * MIN)
    skipped = {(h["start"], h["end"]) for h in s["history"] if h["status"] == "Bỏ buổi" and h["end"] > stamp(now)}
    groups = defaultdict(list)
    for k,t in ts.items():
        if remaining[k]:
            groups[t["due"][:10]].append(t["name"])
    for day,names in sorted(groups.items()):
        if len(names) > 1:
            warnings.append(f"{day} · Cùng ngày đến hạn: " + ", ".join(names))
    for offset in range(90):
        day = now.date() + timedelta(days=offset)
        if not any(remaining.values()):
            break
        if day.isoformat() in cfg["off"]:
            continue
        for a,b in windows(cfg["windows"][day.weekday()]):
            pos = max(now, datetime.combine(day,a), resume.get(day,now))
            end = datetime.combine(day,b)
            while pos < end and spent[day] < cfg["cap"]:
                blocked = [(datetime.fromisoformat(x),datetime.fromisoformat(y)) for x,y in skipped if x[:10] == day.isoformat()]
                covering = [y for x,y in blocked if x <= pos < y]
                if covering:
                    pos = max(covering)
                    continue
                stop = min([end] + [x for x,y in blocked if x > pos])
                # A missed dependent deadline must not suppress the prerequisite's own later work.
                due = {k:(effective[k] if effective[k] > pos else deadlines[k]) for k in order}
                ready = [k for k in order if remaining[k] and pos < due[k]
                         and all(remaining[d] == 0 for d in ts[k]["deps"])]
                if not ready:
                    break
                k = min(ready, key=lambda i:(due[i] - MIN*remaining[i], -ts[i]["priority"],
                                              -ts[i]["difficulty"], i))
                t = ts[k]
                n = min(cfg["block"], remaining[k], cfg["cap"]-spent[day],
                        int((min(stop,due[k])-pos)/MIN))
                finish = pos + n*MIN
                reason = f"Hạn xét {stamp(due[k])} · còn {remaining[k]} phút · ưu tiên {t['priority']}/5 · khó {t['difficulty']}/5"
                if due[k] < deadlines[k]:
                    reason += " · mở khóa việc đến hạn sớm hơn"
                sessions.append(dict(task=k,start=stamp(pos),end=stamp(finish),minutes=n,reason=reason))
                remaining[k] -= n
                spent[day] += n
                pos = finish + cfg["rest"]*MIN
                resume[day] = pos
    for k,n in remaining.items():
        if n:
            why = "quá hạn" if deadlines[k] <= now else ("vướng tiên quyết" if any(remaining[d] for d in ts[k]["deps"]) else "thiếu giờ trước hạn hoặc ngoài 90 ngày")
            warnings.append(f"{ts[k]['name']} · chưa xếp {n} phút ({why}).")
    s["sessions"] = sessions
    return warnings


class Store:
    def __init__(self, folder):
        folder.mkdir(parents=True, exist_ok=True)
        self.path = folder / "study.sqlite3"
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY, body TEXT)")
            db.execute("INSERT OR IGNORE INTO state VALUES (1,?)",(json.dumps(fresh()),))

    def update(self, mutate=lambda s:None, now=None):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            s = json.loads(db.execute("SELECT body FROM state WHERE id=1").fetchone()[0])
            clock = now or datetime.now()
            plan(s, clock)
            mutate(s)
            alerts = plan(s, clock)
            s["warnings"] = alerts
            db.execute("UPDATE state SET body=? WHERE id=1",(json.dumps(s,ensure_ascii=False),))
            return s, alerts

    def read(self):
        with closing(sqlite3.connect(self.path)) as db:
            return json.loads(db.execute("SELECT body FROM state WHERE id=1").fetchone()[0])

