import uuid
from datetime import timedelta

from fastapi import APIRouter, Query, status
from temporalio.service import RPCError

from siqe.api.deps import SessionDep, TemporalDep
from siqe.api.schemas import JobOut
from siqe.core.errors import AppError
from siqe.db.models import Job
from siqe.jobs.records import apply_update, get_job, job_to_dict, list_jobs
from siqe.jobs.start import create_job, start_workflow
from siqe.workflows.selftest import SelfTestWorkflow

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _out(job: Job) -> JobOut:
    return JobOut.model_validate(job_to_dict(job))


@router.get("", response_model=list[JobOut], summary="Recent jobs, newest first")
async def recent_jobs(session: SessionDep, limit: int = Query(50, ge=1, le=200)) -> list[JobOut]:
    return [_out(j) for j in await list_jobs(session, limit)]


@router.get("/{job_id}", response_model=JobOut, summary="One job")
async def one_job(job_id: uuid.UUID, session: SessionDep) -> JobOut:
    return _out(await get_job(session, job_id))


@router.post(
    "/self-test",
    response_model=JobOut,
    status_code=status.HTTP_201_CREATED,
    summary="Run the system self-test (CPU and GPU workers)",
)
async def start_self_test(session: SessionDep, temporal: TemporalDep) -> JobOut:
    job = await create_job(session, kind="system.self_test", title="System self-test", params={})
    await start_workflow(
        session, temporal, job, SelfTestWorkflow.run, [str(job.id)], run_timeout=timedelta(minutes=30)
    )
    return _out(job)


@router.post(
    "/{job_id}/cancel",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ask a running job to stop",
)
async def cancel_job(job_id: uuid.UUID, session: SessionDep, temporal: TemporalDep) -> JobOut:
    job = await get_job(session, job_id)
    if job.state.is_final:
        raise AppError("job.already_finished", "This job has already finished.", status=409)
    if job.workflow_id:
        client = await temporal.client()
        try:
            await client.get_workflow_handle(job.workflow_id).cancel()
        except RPCError as exc:
            raise AppError("job.cancel_failed", f"Couldn't cancel: {exc.message}", status=409) from exc
    await apply_update(session, job.id, message="Cancelling…")
    return _out(job)
