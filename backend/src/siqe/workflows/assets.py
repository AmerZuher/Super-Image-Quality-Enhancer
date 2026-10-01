import asyncio
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError, CancelledError

with workflow.unsafe.imports_passed_through():
    from siqe.activities.assets import (
        AssetFailure,
        export_rendition,
        mark_asset_failed,
        mark_rendition_failed,
        prepare_asset,
    )
    from siqe.activities.jobs import JobUpdate, update_job
    from siqe.core.config import CPU_TASK_QUEUE

QUICK = RetryPolicy(maximum_attempts=5, initial_interval=timedelta(seconds=1))
HEAVY = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=5))


def _failure(exc: ActivityError) -> tuple[str, str]:
    cause = exc.cause or exc
    code = getattr(cause, "type", None) or type(cause).__name__
    return str(code), str(cause)


async def _update(update: JobUpdate) -> None:
    await workflow.execute_activity(
        update_job,
        update,
        task_queue=CPU_TASK_QUEUE,
        start_to_close_timeout=timedelta(seconds=30),
        retry_policy=QUICK,
    )


@workflow.defn
class IngestAssetWorkflow:
    """Thumbnail, preview and zoom pyramid for a freshly uploaded image."""

    @workflow.run
    async def run(self, job_id: str, asset_id: str) -> dict[str, Any]:
        await _update(JobUpdate(job_id, state="running", message="Preparing previews"))
        try:
            sizes: dict[str, Any] = await workflow.execute_activity(
                prepare_asset,
                args=[job_id, asset_id],
                task_queue=CPU_TASK_QUEUE,
                start_to_close_timeout=timedelta(minutes=30),
                heartbeat_timeout=timedelta(seconds=60),
                retry_policy=HEAVY,
            )
        except asyncio.CancelledError:
            await _update(JobUpdate(job_id, state="cancelled", message="Cancelled"))
            raise
        except ActivityError as exc:
            code, message = _failure(exc)
            await workflow.execute_activity(
                mark_asset_failed,
                AssetFailure(asset_id, code, message),
                task_queue=CPU_TASK_QUEUE,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=QUICK,
            )
            await _update(
                JobUpdate(job_id, state="failed", message=message, error={"code": code, "message": message})
            )
            raise ApplicationError(message, type=code, non_retryable=True) from exc
        await _update(JobUpdate(job_id, state="succeeded", message="Ready to edit", result=sizes))
        return sizes


@workflow.defn
class ExportWorkflow:
    """Render an asset's edits at full resolution and encode the result."""

    @workflow.run
    async def run(self, job_id: str, rendition_id: str) -> dict[str, Any]:
        await _update(JobUpdate(job_id, state="running", message="Rendering edits"))
        try:
            result: dict[str, Any] = await workflow.execute_activity(
                export_rendition,
                args=[job_id, rendition_id],
                task_queue=CPU_TASK_QUEUE,
                start_to_close_timeout=timedelta(hours=1),
                heartbeat_timeout=timedelta(seconds=60),
                retry_policy=HEAVY,
            )
        except (asyncio.CancelledError, ActivityError) as exc:
            cancelled = isinstance(exc, asyncio.CancelledError) or isinstance(exc.cause, CancelledError)
            await workflow.execute_activity(
                mark_rendition_failed,
                rendition_id,
                task_queue=CPU_TASK_QUEUE,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=QUICK,
            )
            if cancelled:
                await _update(JobUpdate(job_id, state="cancelled", message="Cancelled"))
                raise
            assert isinstance(exc, ActivityError)
            code, message = _failure(exc)
            await _update(
                JobUpdate(job_id, state="failed", message=message, error={"code": code, "message": message})
            )
            raise ApplicationError(message, type=code, non_retryable=True) from exc
        size_kb = result["size_bytes"] / 1024
        await _update(
            JobUpdate(
                job_id,
                state="succeeded",
                message=f"{result['width']} × {result['height']} · {size_kb:,.0f} KB",
                result=result,
            )
        )
        return result
