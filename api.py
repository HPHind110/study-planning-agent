"""HTTP interface to the same transactional planner used by the desktop app."""
from datetime import datetime
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException
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

    return api


app = create_app()

