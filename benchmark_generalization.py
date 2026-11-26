"""Held-out procedural workloads, independent of the development and private fixtures."""
import random
from copy import deepcopy
from datetime import datetime,timedelta
from time import perf_counter
from planner import fresh,plan,stamp

NOW=datetime(2031,3,3,8)


def fixture(seed):
    rng=random.Random(seed)
    size=[7,19,43,85][seed%4]
    days=[4,11,22,35][seed%4]
    s=fresh()
    s["courses"]=["Synthetic"]
    s["settings"].update(horizon_end=(NOW+timedelta(days=days-1)).date().isoformat(),
                         windows=[rng.choice(["08:00-11:00","14:00-17:00","09:00-10:00, 18:00-20:00",""]) for _ in range(7)],
                         cap=rng.choice([45,90,210]),block=rng.choice([20,35,50]),rest=rng.choice([5,15]))
    s["events"]={"meeting":dict(name="Synthetic meeting",start=stamp(NOW+timedelta(hours=1)),
                                end=stamp(NOW+timedelta(hours=2)),repeat="weekly")}
    for i in range(size):
        day=rng.randrange(days) if seed%3 else 0
        release=NOW+timedelta(days=day)
        due=release+timedelta(days=rng.randrange(days-day),hours=12)
        deps=[]
        if i and seed%3:
            deps=rng.sample(list(s["tasks"]),rng.randint(0,min(i,seed%3+1)))
        n=rng.randrange(5,125,5) if seed%3 else 10
        s["tasks"][str(i)]=dict(name=f"Task {i}",course="Synthetic",kind="Bài tập",deps=deps,left=n,estimate=n,
                                due=stamp(due),start_at=stamp(release),deadline_type=rng.choice(["hard","soft"]),
                                priority=rng.randint(1,5),difficulty=rng.randint(1,5))
    return s


def main():
    improved=equal=fewer=complete=0
    worst=0
    for seed in range(101,125):
        original=fixture(seed)
        base=deepcopy(original)
        plan(base,NOW,baseline_only=True)
        start=perf_counter()
        plan(original,NOW)
        elapsed=perf_counter()-start
        analysis=original["analysis"]
        o=analysis["optimization"]
        baseline=o["baseline"]
        assert baseline==base["analysis"]["optimization"]["selected"]
        a,b=tuple(baseline.values()),tuple(o["selected"].values())
        assert b<=a
        improved+=b<a
        equal+=b==a
        fewer+=o["selected"]["unscheduled"]>baseline["unscheduled"]
        complete+=analysis["unscheduled"]==0
        worst=max(worst,elapsed)
        print(seed,len(original["tasks"]),baseline["unscheduled"],analysis["unscheduled"],round(elapsed,3))
    print(dict(improved=improved,equal=equal,fewer_minutes=fewer,complete=complete,max_seconds=round(worst,3)))


if __name__=="__main__":main()

