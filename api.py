"""HTTP interface to the same transactional planner used by the desktop app."""
from datetime import datetime
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from planner import ROOT, Store, event, stamp

from schemas import Course, Rename, TaskInput, Task, TaskEdit, Plan, Replan, Progress, Health, FixedEvent
from exchange import ImportRequest, prepare, commit, export_data, get_backup, backup_ids, snapshot

def create_app(store=None, clock_fn=datetime.now):
    api = FastAPI(title="Study Planning Agent", version="1.0.0")

    def db():
        return store if store is not None else Store(ROOT / "data")

    def update(change=None):
        try:
            return db().update(change, now=clock_fn())
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @api.get("/health", response_model=Health)
    def health():
        db().read()
        return {"status": "ok"}

    @api.post("/tasks", status_code=201, response_model=Task)
    def create_task(task: TaskInput):
        key = uuid4().hex
        def add(s):
            if task.course not in s["courses"]:
                s["courses"].append(task.course)
            s["tasks"][key] = dict(task.model_dump(), left=task.estimate)
        s, _ = update(add)
        return dict(s["tasks"][key], id=key)

    @api.get("/tasks", response_model=list[Task])
    def list_tasks():
        return [dict(t, id=k) for k,t in db().read()["tasks"].items()]

    @api.post("/plans/generate", response_model=Plan)
    def generate():
        state, warnings = update()
        return {"sessions": state["sessions"], "warnings": warnings}

    @api.post("/plans/replan", response_model=Plan)
    def replan(request: Replan):
        def apply(s):
            for skip in request.skip:
                session = next((h for h in s["sessions"] if h["task"] == skip.task
                                and h["start"] == skip.start), None)
                if session is None:
                    raise HTTPException(409, "Buổi đã đổi. Lấy lại lịch hiện tại.")
                event(s,session,clock_fn(),0,s["tasks"][skip.task]["left"],"Bỏ buổi")
                s["sessions"].remove(session)
            for item in request.changes:
                if item.id not in s["tasks"]:
                    raise HTTPException(404, "Không tìm thấy việc.")
                s["tasks"][item.id].update(item.model_dump(exclude={"id"},exclude_none=True))
                if "start_at" in item.model_fields_set:
                    s["tasks"][item.id]["start_at"]=item.start_at
            if request.settings:
                s["settings"].update(request.settings.model_dump(exclude_none=True))
                if "horizon_end" in request.settings.model_fields_set:
                    s["settings"]["horizon_end"] = request.settings.horizon_end
        state, warnings = update(apply)
        return {"sessions": state["sessions"], "warnings": warnings}

    @api.get("/plans/current", response_model=Plan)
    def current():
        state = db().read()
        if "warnings" not in state:  # Migrate pre-API desktop snapshots on first read.
            return generate()
        return {"sessions": state["sessions"], "warnings": state["warnings"]}

    @api.get("/", include_in_schema=False)
    def homepage():
        return FileResponse(ROOT / "web" / "index.html")

    api.mount("/assets", StaticFiles(directory=ROOT / "web"), name="assets")

    @api.get("/dashboard")
    def dashboard():
        state, _ = update()
        state["backups"]=backup_ids(db())
        return state

    @api.post("/courses", status_code=201)
    def add_course(body: Course):
        def add(s):
            if body.name in s["courses"]:
                raise HTTPException(409, "Tên môn đã tồn tại.")
            s["courses"].append(body.name)
        update(add)
        return body

    @api.patch("/courses")
    def rename_course(body: Rename):
        def rename(s):
            if body.name not in s["courses"]:
                raise HTTPException(404, "Không tìm thấy môn.")
            if body.new_name != body.name and body.new_name in s["courses"]:
                raise HTTPException(409, "Tên môn đã tồn tại.")
            s["courses"][s["courses"].index(body.name)] = body.new_name
            for task in s["tasks"].values():
                if task["course"] == body.name:
                    task["course"] = body.new_name
        update(rename)
        return {"name": body.new_name}

    @api.delete("/courses")
    def delete_course(body: Course):
        def remove(s):
            if body.name not in s["courses"]:
                raise HTTPException(404, "Không tìm thấy môn.")
            if any(t["course"] == body.name for t in s["tasks"].values()):
                raise HTTPException(409, "Chuyển hoặc xóa việc trong môn trước.")
            s["courses"].remove(body.name)
        update(remove)
        return {"deleted": body.name}

    @api.put("/tasks/{key:path}", response_model=Task)
    def edit_task(key: str, body: TaskEdit):
        def edit(s):
            if key not in s["tasks"]:
                raise HTTPException(404, "Không tìm thấy việc.")
            if body.course not in s["courses"]:
                s["courses"].append(body.course)
            s["tasks"][key].update(body.model_dump(exclude_unset=True))
        state,_ = update(edit)
        return dict(state["tasks"][key], id=key)

    @api.delete("/tasks/{key:path}")
    def delete_task(key: str):
        def remove(s):
            if key not in s["tasks"]:
                raise HTTPException(404, "Không tìm thấy việc.")
            if any(key in t["deps"] for t in s["tasks"].values()):
                raise HTTPException(409, "Việc này đang là tiên quyết của việc khác.")
            del s["tasks"][key]
        update(remove)
        return {"deleted": key}

    @api.post("/progress")
    def record(body: Progress):
        def log(s):
            if body.task not in s["tasks"]:
                raise HTTPException(404, "Không tìm thấy việc.")
            now = clock_fn()
            session = dict(task=body.task, start=stamp(now), end=stamp(now), minutes=0)
            if body.start:
                session = next((h for h in s["sessions"] if h["start"] == body.start
                                and h["task"] == body.task), None)
                if session is None or session["start"] > stamp(now):
                    raise HTTPException(409, "Buổi đã thay đổi hoặc chưa bắt đầu.")
                s["sessions"].remove(session)
            event(s, session, now, body.actual, body.remaining, "Đã ghi")
        state, _ = update(log)
        return state["tasks"][body.task]

    @api.post("/events", status_code=201)
    def create_event(body: FixedEvent):
        key=uuid4().hex
        update(lambda s:s.setdefault("events",{}).update({key:body.model_dump()}))
        return dict(id=key, **body.model_dump())

    @api.get("/events")
    def list_events():
        return [dict(id=k,**v) for k,v in db().read().get("events",{}).items()]

    @api.put("/events/{key:path}")
    def edit_event(key:str, body:FixedEvent):
        def edit(s):
            if key not in s.get("events",{}): raise HTTPException(404,"Không tìm thấy sự kiện.")
            s["events"][key]=body.model_dump()
        update(edit)
        return dict(id=key,**body.model_dump())

    @api.delete("/events/{key:path}")
    def delete_event(key:str):
        def remove(s):
            if key not in s.get("events",{}): raise HTTPException(404,"Không tìm thấy sự kiện.")
            del s["events"][key]
        update(remove)
        return {"deleted":key}

    @api.get("/planning/export")
    def export(backup:bool=False):
        s=db().read()
        return snapshot(s) if backup else export_data(s)

    @api.get("/planning/backups/{key}")
    def backup(key:str):
        data=get_backup(db(),key)
        if data is None: raise HTTPException(404,"Không tìm thấy bản sao.")
        return data

    @api.post("/planning/preview")
    def preview(body:ImportRequest):
        result,_=prepare(db().read(),body,clock_fn())
        return result

    @api.post("/planning/import")
    def apply_import(body:ImportRequest):
        try: return commit(db(),body,clock_fn())
        except ValueError as exc: raise HTTPException(422,str(exc)) from exc
        except RuntimeError as exc: raise HTTPException(409,str(exc)) from exc

    return api


app = create_app()

