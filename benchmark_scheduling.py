"""Compare candidates on one read-only SQLite snapshot. Prints aggregate metrics only."""
import argparse
from contextlib import closing
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import sqlite3
from time import perf_counter

from planner import plan, validate, windows
from optimizer import Problem, evaluate
from academic import day_value


def compare(source,now):
    runs={}
    for label in ("baseline","optimized"):
        candidate=deepcopy(source)
        start=perf_counter()
        plan(candidate,now,baseline_only=label=="baseline")
        analysis=candidate["analysis"]
        opt=analysis["optimization"]
        runs[label]=dict(required=analysis["remaining"],capacity=analysis["capacity"],
                         scheduled=analysis["scheduled"],**opt["selected"],violations=0,
                         strategy=opt["strategy"],evaluated=opt["evaluated"],timeout=opt["timeout"],
                         seconds=round(perf_counter()-start,3))
    return runs


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    inputs=parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--database",type=Path)
    inputs.add_argument("--backup",type=Path)
    parser.add_argument("--at",required=True,help="Frozen local timestamp YYYY-MM-DD HH:MM")
    args=parser.parse_args()
    now=datetime.strptime(args.at,"%Y-%m-%d %H:%M")
    if args.backup:
        raw=args.backup.read_text(encoding="utf-8-sig")
        package=json.loads(raw)
        if package["format"]!="study-backup-v2":raise ValueError("Expected study-backup-v2")
        original=package["state"]
    else:
        uri=args.database.resolve().as_uri()+"?mode=ro"
        with closing(sqlite3.connect(uri,uri=True)) as db:
            db.execute("PRAGMA query_only=ON")
            raw=db.execute("SELECT body FROM state WHERE id=1").fetchone()[0]
        original=json.loads(raw)
    horizon=original["settings"].get("horizon_end")
    problem=Problem(original,now,validate(original),day_value(horizon) if horizon else now.date()+timedelta(days=89),windows)
    violation=problem.validate(original["sessions"])
    print("Stored schedule:",violation or "valid",evaluate(problem,original["sessions"])[1])
    print("Snapshot",hashlib.sha256(raw.encode()).hexdigest()[:16],args.at,len(original["tasks"]),"tasks")
    variants=[("observed",original)]
    soft=sorted(k for k,t in original["tasks"].items() if t.get("deadline_type")=="soft" and t["left"])
    stored_left=evaluate(problem,original["sessions"])[2]
    soft.sort(key=lambda k:(not bool(stored_left[k]),k))
    for i,k in enumerate(soft[:3]):
        state=deepcopy(original)
        task=state["tasks"][k]
        delta=(1,-1,2)[i]
        due=datetime.fromisoformat(task["due"])+timedelta(days=delta)
        if task.get("start_at") and datetime.fromisoformat(task["start_at"])>=due:continue
        task["due"]=due.strftime("%Y-%m-%d %H:%M")
        variants.append((f"soft-{i+1} {delta:+}d",state))
    relaxed=deepcopy(original)
    for k in soft:
        if stored_left[k] and relaxed["tasks"][k].get("start_at"):
            relaxed["tasks"][k]["start_at"]=None
    variants.append(("changed constraints: remove releases of incomplete soft tasks",relaxed))
    for label,state in variants:
        print(label,json.dumps(compare(state,now),ensure_ascii=True))


if __name__=="__main__":
    main()

