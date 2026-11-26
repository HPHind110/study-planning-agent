"""Bounded deterministic portfolio search over a single minute-resolution snapshot."""
from bisect import bisect_right
from collections import Counter, defaultdict
from datetime import datetime, timedelta, time
from time import perf_counter

from academic import capacity, clock, day_calendar, MIN


def signature(h):
    return h["task"], h["start"], h["end"]


class Problem:
    def __init__(self,state,now,order,horizon,windows):
        self.tasks=state["tasks"]
        self.cfg=state["settings"]
        self.now=now
        self.original=tuple(state["sessions"])
        self.original_keys={signature(h) for h in self.original}
        self.near_until=(now.date()+timedelta(days=1)).isoformat()
        self.order=order
        self.left={k:t["left"] for k,t in self.tasks.items()}
        self.due={k:clock(t["due"]) for k,t in self.tasks.items()}
        old_due=state.get("analysis",{}).get("due_at_plan",{})
        self.deadline_edit=any(k in old_due and old_due[k]!=t["due"] for k,t in self.tasks.items())
        self.release={k:clock(t["start_at"]) if t.get("start_at") else datetime.min for k,t in self.tasks.items()}
        self.parents={k:[d for d in self.tasks[k]["deps"] if self.left[d]] for k in order}
        self.desc={k:set() for k in order}
        self.anc={k:set() for k in order}
        for k in order:
            for dep in self.parents[k]:
                self.anc[k].update(self.anc[dep],{dep})
        for k in reversed(order):
            if self.left[k]:
                for dep in self.parents[k]:
                    self.desc[dep].update(self.desc[k],{k})
        self.target={k:min([self.due[k]]+[self.due[d] for d in self.desc[k]]) for k in order}
        self.hard={k:self.tasks[k].get("deadline_type","hard")=="hard" for k in order}
        self.official={k:any(self.hard[d] for d in self.desc[k]|{k}) for k in order}
        self.importance={k:max(self.tasks[d]["priority"] for d in self.desc[k]|{k}) for k in order}

        self.days={}
        spent=Counter()
        skipped=defaultdict(list)
        self.resume=datetime.min
        for h in state["history"]:
            day=clock(h["start"]).date()
            spent[day]+=h["actual"]
            if h["status"]=="Bỏ buổi": skipped[day].append((clock(h["start"]),clock(h["end"])))
            if h["actual"] and clock(h["at"]).date()==day:
                self.resume=max(self.resume,clock(h["at"])+self.cfg["rest"]*MIN)
        events=[(e,clock(e["start"]),clock(e["end"])) for e in state.get("events",{}).values()]
        self.bound_cache={}
        self.break_time=self.cfg["rest"]*MIN
        self.horizon=horizon
        self.starts=[]
        self.ends=[]
        self.prefix=[]
        self.accumulated=0
        for i in range((horizon-now.date()).days+1):
            day=now.date()+timedelta(days=i)
            free,cap,_=day_calendar(state,day,windows,events,skipped)
            cap=max(0,cap-spent[day])
            self.days[day]=free,cap
            first=max(now,self.resume)
            for a,b in free:
                a=max(a,first)
                if a>=b or not cap: continue
                minutes=capacity([(a,b)],a,b,cap,self.cfg["block"],self.cfg["rest"])
                self.starts.append(a)
                self.ends.append(b)
                self.prefix.append(self.accumulated)
                self.accumulated+=minutes
                cap-=minutes
                first=a+(minutes+((minutes-1)//self.cfg["block"]+1)*self.cfg["rest"])*MIN
        self.at_due={k:self.coordinate(v) for k,v in self.due.items()}
        self.at_target={k:self.coordinate(v) for k,v in self.target.items()}
        self.active=None
        for h in self.original:
            if h["start"]<now.isoformat(sep=" ",timespec="minutes")<h["end"]:
                if not self.validate([h],require_active=False): self.active=h
                break

    def coordinate(self,dt):
        """Cumulative estimated study minutes up to a time, for ranking only."""
        i=bisect_right(self.starts,dt)-1
        if i<0:return 0
        end=self.prefix[i+1] if i+1<len(self.prefix) else self.accumulated
        elapsed=int((min(dt,self.ends[i])-self.starts[i])/MIN)
        blocks,tail=divmod(elapsed,self.cfg["block"]+self.cfg["rest"])
        return min(end,self.prefix[i]+blocks*self.cfg["block"]+min(tail,self.cfg["block"]))

    def upper(self,lo,hi):
        """Optimistic necessary-condition bound: ignore breaks and competing tasks."""
        key=(lo,hi)
        if key not in self.bound_cache:
            result=0
            for free,cap in self.days.values():
                minutes=sum(max(0,int((min(b,hi)-max(a,lo,self.now,self.resume))/MIN)) for a,b in free)
                result+=min(cap,minutes)
            # Count the whole pinned session as additional possible capacity. This
            # deliberately loosens the bound and cannot create a false shortage.
            if self.active and clock(self.active["start"])<hi and clock(self.active["end"])>lo:
                result+=self.active["minutes"]
            self.bound_cache[key]=result
        return self.bound_cache[key]

    def validate(self,rows,require_active=True):
        left=self.left.copy()
        spent=Counter()
        previous=self.resume
        active_seen=False
        for h in rows:
            if not isinstance(h,dict) or not {"task","start","end","minutes"}<=h.keys():return "missing fields"
            k=h["task"]
            if k not in left:return "unknown task"
            try:
                a,b=clock(h["start"]),clock(h["end"])
            except (TypeError,ValueError):
                return "invalid timestamp"
            n=h["minutes"]
            active=a<self.now<b and signature(h) in self.original_keys
            active_seen |= active and self.active is not None and signature(h)==signature(self.active)
            if a<self.now and not active:return "past session"
            if not (type(n) is int and 0<n<=self.cfg["block"] and b-a==n*MIN):return "duration"
            if a<previous:return "overlap or break"
            if a<self.release[k] or b>self.due[k]:return "release or deadline"
            if a.date() not in self.days:return "horizon"
            free,cap=self.days[a.date()]
            if not any(x<=a<b<=y for x,y in free):return "calendar window"
            if spent[a.date()]+n>cap:return "daily capacity"
            if any(left[d] for d in self.parents[k]):return "prerequisite"
            if n>left[k]:return "excess allocation"
            left[k]-=n
            spent[a.date()]+=n
            previous=b+self.break_time
        if require_active and self.active and not active_seen:return "lost active session"
        return None


def evaluate(p,rows):
    left=p.left.copy()
    for h in rows:left[h["task"]]-=h["minutes"]
    missing={k:n for k,n in left.items() if n}
    blocked={k:n for k,n in missing.items() if any(left[d] for d in p.parents[k])}
    switches=sum(a["task"]!=b["task"] for a,b in zip(rows,rows[1:]))
    # Consecutive unrelated sessions in reverse deadline order expose earlier work
    # to delay; inherited deadlines avoid penalizing prerequisites.
    inversions=sum(p.target[a["task"]]>p.target[b["task"]] for a,b in zip(rows,rows[1:]))
    changed=p.original_keys.symmetric_difference(signature(h) for h in rows)
    metrics=dict(hard_minutes=sum(n for k,n in missing.items() if p.hard[k]),
                 hard_tasks=sum(p.hard[k] for k in missing),weighted=sum(p.tasks[k]["priority"]*n for k,n in missing.items()),
                 unscheduled=sum(missing.values()),incomplete=len(missing),blocked=sum(blocked.values()),
                 deadline_inversions=inversions if p.deadline_edit else 0,near_changes=sum(a[:10]<=p.near_until for _,a,_ in changed),
                 changes=len(changed),short=sum(h["minutes"]<20 for h in rows),fragments=len(rows),switches=switches)
    return tuple(metrics.values()),metrics,left


def generate(p,mode,focus,deadline):
    left=p.left.copy()
    rows=[p.active] if p.active else []
    resume=max(p.now,p.resume)
    if p.active:
        left[p.active["task"]]-=p.active["minutes"]
        resume=clock(p.active["end"])+p.break_time
    for day,(free,cap) in p.days.items():
        if p.active and day==p.now.date():cap-=p.active["minutes"]
        for a,b in free:
            pos=max(a,resume)
            while cap>0 and pos<b:
                if perf_counter()>deadline:raise TimeoutError
                eligible=[k for k in p.order if left[k] and pos<p.due[k] and not any(left[d] for d in p.parents[k])]
                ready=[k for k in eligible if p.release[k]<=pos]
                if not ready:
                    pos=min((p.release[k] for k in eligible if p.release[k]>pos),default=b)
                    continue
                current=p.coordinate(pos)
                def key(k):
                    target=p.target[k] if p.target[k]>pos else p.due[k]
                    downstream=p.desc[k]
                    space=p.at_target[k]-current if p.target[k]>pos else p.at_due[k]-current
                    slack=space-left[k]
                    if mode=="edf": rank=(target,)
                    elif mode=="official":rank=(not p.official[k],target)
                    elif mode=="capacity":rank=(slack,)
                    else:
                        # Evaluate every reachable deadline with outstanding ancestors;
                        # sets ensure a shared ancestor contributes once per chain.
                        chain_slack=min((p.at_due[d]-current-left[d]-sum(left[x] for x in p.anc[d])
                                         for d in downstream if left[d]),default=slack)
                        rank=(min(slack,chain_slack),-p.importance[k],target)
                    return (k not in focus,rank,not p.hard[k],-p.tasks[k]["priority"],-p.tasks[k]["difficulty"],k)
                k=min(ready,key=key)
                end=min(b,p.due[k])
                for w in eligible:
                    release=p.release[w]
                    if pos<release<end and p.due[w]<p.due[k] and p.at_due[w]-p.coordinate(release)<=left[w]:
                        end=min(end,max(pos,release-p.break_time))
                if end<=pos:
                    pos=min(p.release[w] for w in eligible if p.release[w]>pos)
                    continue
                n=min(p.cfg["block"],cap,left[k],int((end-pos)/MIN))
                finish=pos+n*MIN
                rows.append(dict(task=k,start=pos.isoformat(sep=" ",timespec="minutes"),
                                 end=finish.isoformat(sep=" ",timespec="minutes"),minutes=n,
                                 reason=f"{mode} · hạn {p.tasks[k]['due']} · còn {left[k]} phút"+
                                 (" · mở khóa việc phụ thuộc" if p.desc[k] else "")))
                left[k]-=n
                cap-=n
                pos=resume=finish+p.break_time
    return rows


def refill(p, retained, preferred, deadline):
    """Pack missing work into gaps without shifting retained appointments."""
    rows=list(retained)
    allocated=Counter()
    used=Counter()
    ends={}
    for h in rows:
        k=h["task"]
        allocated[k]+=h["minutes"]
        end=clock(h["end"])
        ends[k]=max(ends.get(k,end),end)
        used[end.date()]+=h["minutes"]
    todo={k for k in p.order if allocated[k]<p.left[k]}
    while todo:
        if perf_counter()>deadline:raise TimeoutError
        ready=[k for k in todo if all(allocated[d]==p.left[d] for d in p.parents[k])]
        if not ready:break
        k=min(ready,key=lambda i:(i not in preferred, not p.official[i],p.target[i],-p.importance[i],i))
        todo.remove(k)
        first=max([p.now,p.resume,p.release[k]]+[ends[d]+p.break_time for d in p.parents[k]])
        for day,(free,cap) in p.days.items():
            if perf_counter()>deadline:raise TimeoutError
            if day<first.date() or day>p.due[k].date() or used[day]>=cap:continue
            busy=[(clock(h["start"])-p.break_time,clock(h["end"])+p.break_time)
                  for h in rows if abs((clock(h["start"]).date()-day).days)<=1]
            for a,b in free:
                pos=max(first,a)
                stop=min(b,p.due[k])
                for x,y in busy+[(stop,stop)]:
                    gap=min(stop,x)
                    while pos<gap and allocated[k]<p.left[k] and used[day]<cap:
                        n=min(p.cfg["block"],int((gap-pos)/MIN),p.left[k]-allocated[k],cap-used[day])
                        finish=pos+n*MIN
                        rows.append(dict(task=k,start=pos.isoformat(sep=" ",timespec="minutes"),
                                         end=finish.isoformat(sep=" ",timespec="minutes"),minutes=n,
                                         reason="Bổ sung vào giờ trống · hạn "+p.tasks[k]["due"]))
                        ends[k]=max(ends.get(k,finish),finish)
                        allocated[k]+=n
                        used[day]+=n
                        first=pos=finish+p.break_time
                    pos=max(pos,y)
                    if pos>=stop:break
            if allocated[k]==p.left[k]:break
        rows.sort(key=lambda h:h["start"])
    return rows



def optimize(p,baseline,started,seconds=3):
    deadline=started+seconds
    rejected={}
    evaluated=0
    best=None
    name=None
    score=None
    baseline_metrics=None
    def consider(label,rows):
        nonlocal rejected,evaluated,best,name,score,baseline_metrics
        violation=p.validate(rows)
        if violation:
            rejected[label]=violation
            return
        evaluated+=1
        value,metrics,_=evaluate(p,rows)
        if label=="baseline":baseline_metrics=metrics
        if score is None or value<score:
            best,name,score=rows,label,value

    consider("baseline",baseline)
    consider("existing",p.original)
    if best is None:consider("active-only",[p.active] if p.active else [])
    # Salvage unaffected sessions if a deadline, release or workload changed.
    retained=None
    if p.original and p.validate(p.original) and perf_counter()<deadline:
        retained=[p.active] if p.active else []
        for h in p.original:
            if perf_counter()>=deadline:break
            if h is p.active:continue
            if not p.validate([*retained,h]):retained.append(h)
        consider("retained",retained)
    timed_out=False
    try:
        if retained is not None:
            consider("retain-and-fill",refill(p,retained,set(),deadline))
        for strategy in ("edf","capacity","chain","official"):
            if perf_counter()>=deadline:raise TimeoutError
            consider(strategy,generate(p,strategy,set(),deadline))
        # Deterministic priority-dispatch repair: reinsert a bottleneck chain
        # ahead of competing sessions, then rebuild its displaced suffix.
        for iteration in range(2):
            _,_,left=evaluate(p,best)
            targets=sorted((k for k in p.order if left[k]),key=lambda k:(
                not p.official[k],-sum(left[d]*p.tasks[d]["priority"] for d in p.desc[k]),left[k],k))
            previous=score
            for k in targets[:4]:
                if perf_counter()>=deadline:raise TimeoutError
                consider("repair-chain",generate(p,"chain",p.anc[k]|{k},deadline))
            if targets:
                root=targets[0]
                focus=p.anc[root]|{root}
                consider("gap-fill",refill(p,best,focus,deadline))
                # Evict one competitor (and its projected dependents), try
                # the bottleneck first, then reinsert displaced work.
                overlap=Counter()
                for h in best:
                    k=h["task"]
                    if k not in focus and h is not p.active and clock(h["start"])<p.due[root] and clock(h["end"])>p.release[root]:
                        overlap[k]+=h["minutes"]
                for k in sorted(overlap,key=lambda i:(p.hard[i],-overlap[i],i))[:3]:
                    remove=p.desc[k]|{k}
                    retained=[h for h in best if h is p.active or h["task"] not in remove]
                    consider("relocate",refill(p,retained,focus,deadline))
            if score==previous:break
    except TimeoutError:
        timed_out=True
    _,chosen,left=evaluate(p,best)
    diagnostics=dict(strategy=name,evaluated=evaluated,rejected=rejected,baseline=baseline_metrics,
                     selected=chosen,timeout=timed_out,seconds=round(perf_counter()-started,4))
    return list(best),left,diagnostics

