"""Response models. These define the OpenAPI schema the frontend client is generated from."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

JobStateName = Literal["queued", "running", "succeeded", "failed", "cancelled"]


class JobOut(BaseModel):
    id: str
    kind: str
    title: str
    state: JobStateName
    progress: float = Field(ge=0, le=1)
    message: str
    params: dict[str, Any]
    result: dict[str, Any] | None
    error: dict[str, Any] | None
    created_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None


class WorkerOut(BaseModel):
    id: str
    kind: Literal["cpu", "gpu"]
    hostname: str
    version: str
    online: bool
    last_seen: datetime
    started_at: datetime
    info: dict[str, Any]


class ServicesOut(BaseModel):
    database: bool
    temporal: bool
    events: bool


class SystemOut(BaseModel):
    version: str
    environment: str
    services: ServicesOut
    api: dict[str, Any]
    workers: list[WorkerOut]


class ReleaseOut(BaseModel):
    tag: str
    version: str
    name: str
    notes: str = Field(description="Release notes in GitHub-flavoured Markdown.")
    url: str
    published_at: datetime | None
    prerelease: bool


class UpdateStatusOut(BaseModel):
    current_version: str
    latest_version: str | None
    update_available: bool
    newer: list[ReleaseOut] = Field(description="Releases newer than the running version, newest first.")
    current: ReleaseOut | None = Field(description="Release notes for the running version, if published.")
    checked_at: datetime | None
    error: str | None
    repo_url: str
    releases_url: str


class HealthOut(BaseModel):
    status: Literal["ok", "degraded"]
    checks: dict[str, bool] = {}
