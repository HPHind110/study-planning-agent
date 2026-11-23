"""HTTP interface to the same transactional planner used by the desktop app."""
from datetime import datetime
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from planner import ROOT, Store, event, stamp

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=250)]
Minutes = Annotated[int, Field(strict=True, ge=0, le=100000)]
Level = Annotated[int, Field(strict=True, ge=1, le=5)]
Deadline = Annotated[str, Field(pattern=r"^\d{4}-\d\d-\d\d \d\d:\d\d$")]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TaskInput(Model):
    name: Name
    course: Name
    kind: Literal["Bài tập", "Kỳ thi", "Mục tiêu"] = "Bài tập"
    due: Deadline
    estimate: Annotated[int, Field(strict=True, ge=1, le=100000)]
    difficulty: Level = 3
    priority: Level = 3
    deps: list[Name] = Field(default_factory=list)


class Task(TaskInput):
    id: str
    left: Minutes


class Session(Model):
    task: str
    start: str
    end: str
    minutes: int
    reason: str


class Plan(Model):
    sessions: list[Session]
    warnings: list[str]


class Change(Model):
    id: Name
    due: Deadline | None = None
    left: Minutes | None = None
    priority: Level | None = None


class Settings(Model):
    windows: Annotated[list[str], Field(min_length=7, max_length=7)] | None = None
    off: list[str] | None = None
    cap: Annotated[int, Field(strict=True, ge=1, le=720)] | None = None
    block: Annotated[int, Field(strict=True, ge=5, le=120)] | None = None
    rest: Annotated[int, Field(strict=True, ge=1, le=60)] | None = None


class Skip(Model):
    task: Name
    start: Deadline


class Replan(Model):
    changes: list[Change] = Field(default_factory=list)
    settings: Settings | None = None
    skip: list[Skip] = Field(default_factory=list)


class Health(Model):
    status: Literal["ok"]


class Course(Model):
    name: Name


class Rename(Course):
    new_name: Name


class TaskEdit(TaskInput):
    left: Minutes


class Progress(Model):
    task: Name
    actual: Annotated[int, Field(strict=True, ge=0, le=1440)]
    remaining: Minutes
    start: Deadline | None = None


def create_app(store=None):
    api = FastAPI(title="Study Planning Agent", version="1.0.0")

    def db():
        return store if store is not None else Store(ROOT / "data")

    def update(change=lambda s: None):
        try:
            return db().update(change)
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
                event(s,session,datetime.now(),0,s["tasks"][skip.task]["left"],"Bỏ buổi")
                s["sessions"].remove(session)
            for item in request.changes:
                if item.id not in s["tasks"]:
                    raise HTTPException(404, "Không tìm thấy việc.")
                s["tasks"][item.id].update(item.model_dump(exclude={"id"},exclude_none=True))
            if request.settings:
                s["settings"].update(request.settings.model_dump(exclude_none=True))
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
            s["tasks"][key] = body.model_dump()
        update(edit)
        return dict(body.model_dump(), id=key)

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
            now = datetime.now()
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

    return api


app = create_app()

