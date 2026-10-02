import asyncio
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError, CancelledError

with workflow.unsafe.imports_passed_through():
    from siqe.activities.jobs import JobUpdate
    from siqe.activities.models import ModelFailure, install_model, mark_model_failed
    from siqe.core.config import CPU_TASK_QUEUE
    from siqe.workflows.assets import QUICK, _failure, _update

DOWNLOAD = RetryPolicy(maximum_attempts=6, initial_interval=timedelta(seconds=5), backoff_coefficient=2.0)


@workflow.defn
class ModelInstallWorkflow:
    """Download a catalog model, verify it, and convert it if needed."""

    @workflow.run
    async def run(self, job_id: str, model_id: str) -> dict[str, Any]:
        await _update(JobUpdate(job_id, state="running", message="Downloading"))
        try:
            result: dict[str, Any] = await workflow.execute_activity(
                install_model,
                args=[job_id, model_id],
                task_queue=CPU_TASK_QUEUE,
                start_to_close_timeout=timedelta(hours=3),
                heartbeat_timeout=timedelta(minutes=2),
                retry_policy=DOWNLOAD,
            )
        except (asyncio.CancelledError, ActivityError) as exc:
            cancelled = isinstance(exc, asyncio.CancelledError) or isinstance(exc.cause, CancelledError)
            code, message = ("cancelled", "Cancelled") if cancelled else _failure(exc)  # type: ignore[arg-type]
            await workflow.execute_activity(
                mark_model_failed,
                ModelFailure(model_id, code, message),
                task_queue=CPU_TASK_QUEUE,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=QUICK,
            )
            if cancelled:
                await _update(JobUpdate(job_id, state="cancelled", message="Cancelled"))
                raise
            await _update(
                JobUpdate(job_id, state="failed", message=message, error={"code": code, "message": message})
            )
            raise ApplicationError(message, type=code, non_retryable=True) from exc
        size_mb = result["size_bytes"] / 1e6
        await _update(
            JobUpdate(job_id, state="succeeded", message=f"Installed ({size_mb:,.0f} MB)", result=result)
        )
        return result
