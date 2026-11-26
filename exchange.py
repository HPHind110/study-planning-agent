"""Validate candidate states in memory. Commit and backup share one SQLite transaction."""
import hashlib
import json
import sqlite3
from collections import Counter
from contextlib import closing
from copy import deepcopy
from datetime import datetime
from uuid import uuid4
from typing import Literal

from pydantic import Field
from academic import clock
from planner import plan, validate
from schemas import FixedEvent, Model, Name, Settings, TaskInput, Minutes


class ImportedTask(TaskInput):
    id: Name
    left: Minutes | None = None


class ImportedEvent(FixedEvent):
    id: Name


class Package(Model):
    version: Literal[2] = 2
    tasks: list[ImportedTask] = Field(default_factory=list)
    events: list[ImportedEvent] = Field(default_factory=list)
    courses: list[Name] = Field(default_factory=list)
    settings: Settings | None = None


class Scope(Model):
    courses: list[Name] = Field(default_factory=list)
    event_ids: list[Name] = Field(default_factory=list)
    settings: bool = False
    full_restore: bool = False


class ImportRequest(Model):
    mode: Literal["append","replace","restore"] = "append"
    scope: Scope = Field(default_factory=Scope)
    document: dict
    token: str | None = None


def snapshot(state):
    return {"format":"study-backup-v2","state":{k:v for k,v in state.items()
            if k in ("courses","tasks","events","settings","history","sessions")}}


def export_data(s):
    return dict(version=2,courses=s["courses"],tasks=[dict(v,id=k) for k,v in s["tasks"].items()],
                events=[dict(v,id=k) for k,v in s.get("events",{}).items()],settings=s["settings"])


def check_snapshot(doc):
    if set(doc)!={"format","state"} or doc["format"]!="study-backup-v2":
        raise ValueError("Khôi phục yêu cầu bản sao study-backup-v2.")
    s=deepcopy(doc["state"])
    if set(s)-{"courses","tasks","settings","history","sessions","events"}:
        raise ValueError("Trường sao lưu không hợp lệ.")
    Package.model_validate(export_data(s))
    validate(s)
    for rows in ("sessions","history"):
        if not isinstance(s[rows],list): raise ValueError("Nhật ký/lịch phải là danh sách.")
        for row in s[rows]:
            a,b=clock(row["start"]),clock(row["end"])
            if b<a or not isinstance(row["task"],str) or type(row["minutes"]) is not int or row["minutes"]<0:
                raise ValueError("Buổi học không hợp lệ.")
            if rows=="history":
                clock(row["at"])
                if (type(row["actual"]) is not int or not 0<=row["actual"]<=1440
                        or type(row["remaining"]) is not int or row["remaining"]<0
                        or not all(isinstance(row[k],str) for k in ("name","status"))):
                    raise ValueError("Dòng nhật ký không hợp lệ.")
            elif row["task"] not in s["tasks"] or not isinstance(row["reason"],str):
                raise ValueError("Buổi học thiếu việc hoặc lý do.")
    return s


def prepare(original, request, now):
    result=dict(added=[],updated=[],deleted=[],events_added=[],events_updated=[],events_deleted=[],
                duplicates=[],errors=[],warnings=[],workload=0,settings_changed=False)
    s=deepcopy(original)
    try:
        scope=request.scope
        if request.mode=="restore":
            if not scope.full_restore: raise ValueError("Cần xác nhận full_restore.")
            s=check_snapshot(request.document)
        else:
            plan(s,now)
            pkg=Package.model_validate(request.document)
            if scope.full_restore: raise ValueError("full_restore chỉ dùng khi khôi phục.")
            if request.mode=="replace" and not (scope.courses or scope.event_ids or scope.settings):
                raise ValueError("Thay thế cần phạm vi cụ thể.")
            for group in (pkg.tasks,pkg.events):
                counts=Counter(item.id for item in group)
                result["duplicates"].extend(k for k,n in counts.items() if n>1)
            if result["duplicates"]: raise ValueError("Trùng ID trong tệp.")
            events=s.setdefault("events",{})
            task_ids={row.id for row in pkg.tasks}
            event_ids={row.id for row in pkg.events}
            replace=request.mode=="replace"
            for c in pkg.courses:
                if replace and c not in scope.courses and c not in s["courses"]:
                    raise ValueError("Môn nằm ngoài phạm vi thay thế.")
                if c not in s["courses"]: s["courses"].append(c)
            for row in pkg.tasks:
                old=s["tasks"].get(row.id)
                if replace and (row.course not in scope.courses or old and old["course"] not in scope.courses):
                    raise ValueError(f"Việc {row.id} nằm ngoài phạm vi.")
                data=row.model_dump(exclude={"id","left"},exclude_unset=True)
                # Sparse updates retain metadata, estimates and actual remaining effort.
                if old:
                    changed={k:v for k,v in data.items() if old.get(k,TaskInput.model_fields[k].default)!=v}
                    if not changed: result["duplicates"].append(row.id)
                    elif not replace:
                        result["duplicates"].append(row.id)
                        raise ValueError(f"ID {row.id} đã tồn tại với nội dung khác.")
                    else: old.update(changed)
                else:
                    s["tasks"][row.id]=dict(row.model_dump(exclude={"id","left"}),left=row.estimate if row.left is None else row.left)
                if row.course not in s["courses"]: s["courses"].append(row.course)
            for row in pkg.events:
                if replace and row.id not in scope.event_ids: raise ValueError("Sự kiện ngoài phạm vi.")
                data=row.model_dump(exclude={"id"})
                if row.id in events:
                    if FixedEvent.model_validate(events[row.id]).model_dump()==data: result["duplicates"].append(row.id)
                    elif not replace:
                        result["duplicates"].append(row.id)
                        raise ValueError(f"ID sự kiện {row.id} đã tồn tại.")
                events[row.id]=data
            if replace:
                for k,t in list(s["tasks"].items()):
                    if t["course"] in scope.courses and k not in task_ids: del s["tasks"][k]
                for k in set(scope.event_ids)-event_ids: events.pop(k,None)
            if pkg.settings is not None:
                if not scope.settings: raise ValueError("Cần cho phép thay đổi settings.")
                patch=pkg.settings.model_dump(exclude_unset=True,exclude_none=True)
                if "horizon_end" in pkg.settings.model_fields_set: patch["horizon_end"]=pkg.settings.horizon_end
                s["settings"].update(patch)
        for collection,prefix in (("tasks",""),("events","events_")):
            old,new=original.get(collection,{}),s.get(collection,{})
            result[prefix+"added"]=sorted(new.keys()-old.keys())
            result[prefix+"deleted"]=sorted(old.keys()-new.keys())
            result[prefix+"updated"]=sorted(k for k in new.keys()&old.keys() if new[k]!=old[k])
        result["settings_changed"]=original["settings"]!=s["settings"]
        result["workload"]=sum(t["estimate"] for t in s["tasks"].values())
        result["warnings"]=plan(s,now)
        s["warnings"]=result["warnings"]
        previous={r["task"]:r["minutes"] for r in original.get("analysis",{}).get("risks",[])}
        s["recent_risks"]=[r["task"] for r in s["analysis"]["risks"]
                           if r["minutes"]>previous.get(r["task"],0)]
        digest={"base":snapshot(original),"request":request.model_dump(exclude={"token"})}
        # Future session predictions may move with a dashboard refresh. History and inputs guard progress.
        digest["base"]["state"].pop("sessions",None)
        result["token"]=hashlib.sha256(json.dumps(digest,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    except (KeyError,TypeError,ValueError,AttributeError,OverflowError,RecursionError) as exc:
        result["errors"].append(str(exc))
    return result,s


def commit(store,request,now=None):
    with closing(sqlite3.connect(store.path)) as db,db:
        db.execute("BEGIN IMMEDIATE")
        original=json.loads(db.execute("SELECT body FROM state WHERE id=1").fetchone()[0])
        result,s=prepare(original,request,now or datetime.now())
        if result["errors"]: raise ValueError(" · ".join(result["errors"]))
        if request.token!=result["token"]: raise RuntimeError("Dữ liệu hoặc phạm vi đã đổi. Xem trước lại.")
        if request.mode!="append" or result["settings_changed"]:
            key=uuid4().hex
            db.execute("CREATE TABLE IF NOT EXISTS backups (id TEXT PRIMARY KEY, body TEXT NOT NULL)")
            db.execute("INSERT INTO backups VALUES (?,?)",(key,json.dumps(snapshot(original),ensure_ascii=False)))
            result["backup_id"]=key
        db.execute("UPDATE state SET body=? WHERE id=1",(json.dumps(s,ensure_ascii=False),))
    return result


def get_backup(store,key):
    with closing(sqlite3.connect(store.path)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='backups'").fetchone(): return None
        row=db.execute("SELECT body FROM backups WHERE id=?",(key,)).fetchone()
        return json.loads(row[0]) if row else None


def backup_ids(store):
    with closing(sqlite3.connect(store.path)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='backups'").fetchone(): return []
        return [row[0] for row in db.execute("SELECT id FROM backups ORDER BY rowid DESC")]

