"""Reading and updating job rows. Shared by the API and by worker activities."""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from siqe.core.errors import NotFoundError
from siqe.db.base import utcnow
from siqe.db.models import Job, JobState
from siqe.events.bus import publish

JOB_EVENT = "job.updated"


def job_to_dict(job: Job) -> dict[str, Any]:
    return {
        "id": str(job.id),
        "kind": job.kind,
        "title": job.title,
        "state": job.state.value,
        "progress": round(job.progress, 4),
        "message": job.message,
        "params": job.params,
        "result": job.result,
        "error": job.error,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


async def get_job(session: AsyncSession, job_id: uuid.UUID, *, for_update: bool = False) -> Job:
    stmt = select(Job).where(Job.id == job_id)
    if for_update:
        stmt = stmt.with_for_update()
    job = (await session.execute(stmt)).scalar_one_or_none()
    if job is None:
        raise NotFoundError("job.not_found", f"No job with id {job_id}.", title="Job not found")
    return job


async def list_jobs(session: AsyncSession, limit: int = 50) -> list[Job]:
    stmt = select(Job).order_by(Job.created_at.desc()).limit(max(1, min(limit, 200)))
    return list((await session.execute(stmt)).scalars())


async def apply_update(
    session: AsyncSession,
    job_id: uuid.UUID,
    *,
    state: JobState | None = None,
    progress: float | None = None,
    message: str | None = None,
    result: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
) -> Job:
    """Update a job and publish the change. Final states are never overwritten."""
    job = await get_job(session, job_id, for_update=True)
    if job.state.is_final:
        return job
    if state is not None and state != job.state:
        job.state = state
        if state == JobState.running and job.started_at is None:
            job.started_at = utcnow()
        if state.is_final:
            job.finished_at = utcnow()
            if state == JobState.succeeded:
                job.progress = 1.0
    if progress is not None:
        job.progress = max(job.progress, min(1.0, max(0.0, progress)))
    if message is not None:
        job.message = message[:2000]
    if result is not None:
        job.result = result
    if error is not None:
        job.error = error
    job.updated_at = utcnow()
    await session.flush()
    await publish(session, JOB_EVENT, job_to_dict(job))
    return job
