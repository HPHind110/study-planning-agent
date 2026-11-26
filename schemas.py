from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

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
    start_at: Deadline | None = None
    deadline_type: Literal["hard","soft"] = "hard"
    notes: str | None = None
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
    start_at: Deadline | None = None
    deadline_type: Literal["hard","soft"] | None = None
    due: Deadline | None = None
    left: Minutes | None = None
    priority: Level | None = None


class Override(Model):
    windows: str | None = None
    cap: Annotated[int, Field(strict=True, ge=0, le=720)] | None = None


class Settings(Model):
    weekday_caps: list[int | None] | None = None
    overrides: dict[str, Override] | None = None
    horizon_end: str | None = None
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


class FixedEvent(Model):
    name: Name
    start: Deadline
    end: Deadline
    repeat: Literal["once","weekly"] = "once"
    until: str | None = None
