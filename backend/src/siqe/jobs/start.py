"""Creating a job and starting its workflow, the same way for every job type."""

from collections.abc import Sequence
from datetime import timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from temporalio.service import RPCError

from siqe.core.config import CPU_TASK_QUEUE
from siqe.core.errors import AppError
from siqe.db.models import Job, JobState
from siqe.events.bus import publish
from siqe.jobs.records import JOB_EVENT, apply_update, job_to_dict
from siqe.orchestration.client import TemporalGateway


async def create_job(session: AsyncSession, *, kind: str, title: str, params: dict[str, Any]) -> Job:
    job = Job(kind=kind, title=title[:200], params=params, state=JobState.queued)
    session.add(job)
    await session.flush()
    job.workflow_id = f"job-{job.id}"
    await publish(session, JOB_EVENT, job_to_dict(job))
    return job


async def start_workflow(
    session: AsyncSession,
    temporal: TemporalGateway,
    job: Job,
    workflow: Any,
    args: Sequence[Any],
    *,
    run_timeout: timedelta = timedelta(hours=2),
) -> None:
    """Commit first so the workflow's activities always find the job row, then start it.

    If the job engine is unreachable the job is marked failed and a typed 503 is raised.
    """
    await session.commit()
    try:
        client = await temporal.client()
        await client.start_workflow(
            workflow,
            args=list(args),
            id=job.workflow_id or f"job-{job.id}",
            task_queue=CPU_TASK_QUEUE,
            execution_timeout=run_timeout,
        )
    except (AppError, RPCError) as exc:
        await apply_update(
            session,
            job.id,
            state=JobState.failed,
            message="The job engine is not reachable.",
            error={"code": "temporal.unavailable", "message": str(exc)},
        )
        await session.commit()
        if isinstance(exc, AppError):
            raise
        raise AppError("temporal.unavailable", str(exc), status=503) from exc
