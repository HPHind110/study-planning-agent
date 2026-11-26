"""Academic calendar constraints. All intervals are half-open, in local wall time."""
from functools import lru_cache
from datetime import date, datetime, timedelta

MIN = timedelta(minutes=1)


def day_value(value):
    day = date.fromisoformat(value)
    if day.isoformat() != value:
        raise ValueError("Ngày cần có dạng YYYY-MM-DD.")
    return day


@lru_cache(maxsize=8192)
def clock(value):
    dt = datetime.strptime(value, "%Y-%m-%d %H:%M")
    if dt.isoformat(sep=" ", timespec="minutes") != value:
        raise ValueError("Giờ cần có dạng YYYY-MM-DD HH:MM.")
    return dt


def validate_calendar(state, windows, integer):
    cfg = state["settings"]
    if cfg.get("horizon_end"):
        day_value(cfg["horizon_end"])
    caps = cfg.get("weekday_caps", [None]*7)
    if not isinstance(caps,list) or len(caps) != 7:
        raise ValueError("Cần 7 giới hạn theo thứ.")
    for cap in caps:
        if cap is not None:
            integer(cap, 0, 720, "Giới hạn theo thứ")
    for key, rule in cfg.get("overrides", {}).items():
        day_value(key)
        if not isinstance(rule,dict) or set(rule)-{"windows","cap"}:
            raise ValueError("Ngoại lệ ngày chỉ nhận windows và cap.")
        if "windows" in rule:
            windows(rule["windows"])
        if "cap" in rule:
            integer(rule["cap"], 0, 720, "Giới hạn theo ngày")
    for ev in state.get("events", {}).values():
        start, end = clock(ev["start"]), clock(ev["end"])
        if not ev["name"].strip() or end <= start:
            raise ValueError("Sự kiện cần tên và giờ kết thúc sau giờ bắt đầu.")
        if ev.get("repeat","once") not in ("once","weekly"):
            raise ValueError("Kiểu lặp không hợp lệ.")
        if ev.get("until") and (ev.get("repeat")!="weekly" or day_value(ev["until"]) < start.date()):
            raise ValueError("Ngày kết thúc lặp không hợp lệ.")


def collisions(intervals):
    """Subtract blockers once even when several events overlap."""
    result = []
    for a,b in sorted(intervals):
        if result and a <= result[-1][1]:
            result[-1] = (result[-1][0],max(b,result[-1][1]))
        else:
            result.append((a,b))
    return result


def day_calendar(state, day, windows, events, skipped):
    cfg = state["settings"]
    key = day.isoformat()
    override = cfg.get("overrides",{}).get(key,{})
    index = day.weekday()
    weekday_cap = cfg.get("weekday_caps",[None]*7)[index]
    cap = override.get("cap", cfg["cap"] if weekday_cap is None else weekday_cap)
    available = [] if key in cfg["off"] else windows(override.get("windows",cfg["windows"][index]))
    occupied = list(skipped.get(day,[]))
    meetings = []
    midnight=datetime.combine(day,datetime.min.time())
    next_day=midnight+timedelta(days=1) if day<date.max else datetime.max
    for ev,first,last in events:
        if ev.get("repeat")=="weekly":
            earliest=max(0,(day-last.date()).days//7)
            latest_day=min(day,day_value(ev["until"])) if ev.get("until") else day
            latest=(latest_day-first.date()).days//7
        else:
            earliest=latest=0
        for occurrence in range(earliest,latest+1):
            delta=timedelta(weeks=occurrence)
            start,end=max(midnight,first+delta),min(next_day,last+delta)
            if start<end:
                occupied.append((start,end))
                meetings.append((start,end))
    blocks = collisions(occupied)
    free = []
    for a,b in available:
        pos,end = datetime.combine(day,a),datetime.combine(day,b)
        for x,y in blocks:
            if x>=end: break
            if y<=pos: continue
            if x>pos: free.append((pos,x))
            pos=max(pos,y)
        if pos<end: free.append((pos,end))
    meetings.sort()
    overlap = any(x[1]>y[0] for x,y in zip(meetings,meetings[1:]))
    return free,cap,overlap


def capacity(free, first, last, cap, block, rest):
    """Study minutes achievable with a single divisible workload and full blocks."""
    result=0
    pos=first
    for start,end in free:
        pos=max(start,pos)
        end=min(end,last)
        while pos<end and result<cap:
            minutes=min(block,int((end-pos)/MIN),cap-result)
            result+=minutes
            pos+=(minutes+rest)*MIN
    return result

