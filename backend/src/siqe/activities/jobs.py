import uuid
from dataclasses import dataclass, field
from typing import Any

from temporalio import activity

from siqe.db.models import JobState
from siqe.db.session import session_scope
from siqe.jobs.records import apply_update


@dataclass
class JobUpdate:
    job_id: str
    state: str | None = None
    progress: float | None = None
    message: str | None = None
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = field(default=None)


@activity.defn
async def update_job(update: JobUpdate) -> None:
    async with session_scope() as session:
        await apply_update(
            session,
            uuid.UUID(update.job_id),
            state=JobState(update.state) if update.state else None,
            progress=update.progress,
            message=update.message,
            result=update.result,
            error=update.error,
        )
