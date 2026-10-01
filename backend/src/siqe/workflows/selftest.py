import asyncio
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError, CancelledError

with workflow.unsafe.imports_passed_through():
    from siqe.activities.jobs import JobUpdate, update_job
    from siqe.activities.selftest import cpu_probe, gpu_probe
    from siqe.core.config import CPU_TASK_QUEUE, GPU_TASK_QUEUE

SHORT = timedelta(seconds=30)
QUICK_RETRY = RetryPolicy(maximum_attempts=5, initial_interval=timedelta(seconds=1))


def _error_payload(exc: BaseException) -> dict[str, Any]:
    cause = exc.cause if isinstance(exc, ActivityError) and exc.cause else exc
    code = getattr(cause, "type", None) or type(cause).__name__
    return {"code": str(code), "message": str(cause)}


@workflow.defn
class SelfTestWorkflow:
    """Runs a CPU probe and a GPU probe and records the results on the job."""

    @workflow.run
    async def run(self, job_id: str) -> dict[str, Any]:
        await self._update(JobUpdate(job_id, state="running", message="Starting self-test"))
        try:
            cpu = await workflow.execute_activity(
                cpu_probe,
                job_id,
                task_queue=CPU_TASK_QUEUE,
                start_to_close_timeout=timedelta(minutes=5),
                heartbeat_timeout=timedelta(seconds=60),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            gpu = await workflow.execute_activity(
                gpu_probe,
                job_id,
                task_queue=GPU_TASK_QUEUE,
                # Queued behind other GPU work is fine; a dead GPU worker is not.
                schedule_to_start_timeout=timedelta(minutes=10),
                start_to_close_timeout=timedelta(minutes=10),
                heartbeat_timeout=timedelta(seconds=90),
                retry_policy=RetryPolicy(
                    maximum_attempts=3, non_retryable_error_types=["InsufficientMemoryError"]
                ),
            )
        except asyncio.CancelledError:
            await self._update(JobUpdate(job_id, state="cancelled", message="Cancelled"))
            raise
        except ActivityError as exc:
            if isinstance(exc.cause, CancelledError):
                await self._update(JobUpdate(job_id, state="cancelled", message="Cancelled"))
                raise
            error = _error_payload(exc)
            await self._update(JobUpdate(job_id, state="failed", message=error["message"], error=error))
            raise ApplicationError(error["message"], type=error["code"], non_retryable=True) from exc

        result = {"cpu": cpu, "gpu": gpu}
        summary = gpu.get("device_name") or ("CPU only" if gpu.get("device") == "cpu" else "No PyTorch")
        await self._update(
            JobUpdate(job_id, state="succeeded", message=f"All checks passed · {summary}", result=result)
        )
        return result

    async def _update(self, update: JobUpdate) -> None:
        await workflow.execute_activity(
            update_job,
            update,
            task_queue=CPU_TASK_QUEUE,
            start_to_close_timeout=SHORT,
            retry_policy=QUICK_RETRY,
        )
