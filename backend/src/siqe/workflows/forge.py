import asyncio
import contextlib
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError
from temporalio.workflow import ActivityCancellationType, ActivityHandle

with workflow.unsafe.imports_passed_through():
    from siqe.activities.forge import (
        forge_build_dataset,
        forge_dataset_failed,
        forge_export_onnx,
        forge_publish,
        forge_run_finish,
        forge_run_start,
        forge_train_chunk,
    )
    from siqe.activities.jobs import JobUpdate
    from siqe.core.config import CPU_TASK_QUEUE, GPU_TASK_QUEUE
    from siqe.workflows.assets import QUICK, _failure, _update

CHUNK_RETRY = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=10))
# Start afresh (continue-as-new) after this many chunks to keep the event history small.
MAX_CHUNKS = 100


@workflow.defn
class ForgeDatasetWorkflow:
    """Cut training crops from Library images."""

    @workflow.run
    async def run(self, job_id: str, dataset_id: str) -> dict[str, Any]:
        await _update(JobUpdate(job_id, state="running", message="Choosing images"))
        try:
            result: dict[str, Any] = await workflow.execute_activity(
                forge_build_dataset,
                dataset_id,
                task_queue=CPU_TASK_QUEUE,
                start_to_close_timeout=timedelta(hours=4),
                heartbeat_timeout=timedelta(minutes=2),
                retry_policy=CHUNK_RETRY,
            )
        except asyncio.CancelledError:
            await _dataset_failed(dataset_id, {"code": "job.cancelled", "message": "Cancelled"})
            await _update(JobUpdate(job_id, state="cancelled", message="Cancelled"))
            raise
        except ActivityError as exc:
            code, message = _failure(exc)
            await _dataset_failed(dataset_id, {"code": code, "message": message})
            await _update(
                JobUpdate(job_id, state="failed", message=message, error={"code": code, "message": message})
            )
            raise ApplicationError(message, type=code, non_retryable=True) from exc
        crops = result["train"] + result["val"]
        message = f"{crops:,} crops from {result['images']:,} images"
        if result["skipped"]:
            message += f"; {result['skipped']:,} skipped"
        await _update(JobUpdate(job_id, state="succeeded", progress=1.0, message=message, result=result))
        return result


async def _dataset_failed(dataset_id: str, error: dict[str, Any]) -> None:
    await workflow.execute_activity(
        forge_dataset_failed,
        args=[dataset_id, error],
        task_queue=CPU_TASK_QUEUE,
        start_to_close_timeout=timedelta(minutes=1),
        retry_policy=QUICK,
    )


@workflow.defn
class ForgeTrainWorkflow:
    """Train a Forge model in chunks on the GPU queue; pause, resume and stop at any time.

    Pausing or stopping cancels the running chunk, which saves a checkpoint before it ends.
    Other GPU work can run between chunks.
    """

    def __init__(self) -> None:
        self._paused = False
        self._stop = False

    @workflow.signal
    def pause(self) -> None:
        self._paused = True

    @workflow.signal
    def resume(self) -> None:
        self._paused = False

    @workflow.signal
    def stop(self) -> None:
        self._stop = True

    async def _finish(self, run_id: str, state: str, error: dict[str, Any] | None = None) -> dict[str, Any]:
        result: dict[str, Any] = await workflow.execute_activity(
            forge_run_finish,
            args=[run_id, state, error],
            task_queue=CPU_TASK_QUEUE,
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=QUICK,
        )
        return result

    @workflow.run
    async def run(self, run_id: str, paused: bool = False) -> dict[str, Any]:
        self._paused = self._paused or paused
        info: dict[str, Any] = await workflow.execute_activity(
            forge_run_start,
            run_id,
            task_queue=CPU_TASK_QUEUE,
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=QUICK,
        )
        self._paused = self._paused or bool(info.get("paused"))
        try:
            for _ in range(MAX_CHUNKS):
                if self._stop:
                    break
                if self._paused:
                    await workflow.wait_condition(lambda: not self._paused or self._stop)
                    continue
                handle = workflow.start_activity(
                    forge_train_chunk,
                    run_id,
                    task_queue=GPU_TASK_QUEUE,
                    start_to_close_timeout=timedelta(minutes=30),
                    heartbeat_timeout=timedelta(minutes=2),
                    retry_policy=CHUNK_RETRY,
                    cancellation_type=ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
                )

                def interrupted(h: ActivityHandle[Any] = handle) -> bool:
                    return h.done() or self._paused or self._stop

                await workflow.wait_condition(interrupted)
                if not handle.done():
                    handle.cancel()
                    # The chunk saves its checkpoint, then ends as cancelled.
                    with contextlib.suppress(ActivityError, asyncio.CancelledError):
                        await handle
                    continue
                result: dict[str, Any] = await handle
                if result["done"]:
                    return await self._finish(run_id, "succeeded")
            else:
                workflow.continue_as_new(args=[run_id, self._paused])
        except asyncio.CancelledError:
            await self._finish(run_id, "cancelled")
            raise
        except ActivityError as exc:
            code, message = _failure(exc)
            await self._finish(run_id, "failed", {"code": code, "message": message})
            raise ApplicationError(message, type=code, non_retryable=True) from exc
        # Stopped early: keep what was learned so far.
        return await self._finish(run_id, "succeeded")


@workflow.defn
class ForgePublishWorkflow:
    """Benchmark a run's best checkpoint and add it to AI Lab."""

    @workflow.run
    async def run(self, job_id: str, run_id: str, name: str, summary: str = "") -> dict[str, Any]:
        await _update(JobUpdate(job_id, state="running", message="Scoring on held-out photos"))
        try:
            result: dict[str, Any] = await workflow.execute_activity(
                forge_publish,
                args=[run_id, name, summary],
                task_queue=GPU_TASK_QUEUE,
                schedule_to_start_timeout=timedelta(hours=12),
                start_to_close_timeout=timedelta(minutes=30),
                heartbeat_timeout=timedelta(minutes=10),
                retry_policy=QUICK,
            )
        except asyncio.CancelledError:
            await _update(JobUpdate(job_id, state="cancelled", message="Cancelled"))
            raise
        except ActivityError as exc:
            code, message = _failure(exc)
            await _update(
                JobUpdate(job_id, state="failed", message=message, error={"code": code, "message": message})
            )
            raise ApplicationError(message, type=code, non_retryable=True) from exc
        message = (
            f"Added {result['name']} to AI Lab: {result['psnr']:.2f} dB "
            f"(bicubic {result['bicubic_psnr']:.2f} dB)"
        )
        await _update(JobUpdate(job_id, state="succeeded", progress=1.0, message=message, result=result))
        return result


@workflow.defn
class ForgeExportWorkflow:
    """Export a run's best checkpoint to ONNX and check the file against PyTorch."""

    @workflow.run
    async def run(self, job_id: str, run_id: str) -> dict[str, Any]:
        await _update(JobUpdate(job_id, state="running", message="Waiting for the AI worker"))
        try:
            result: dict[str, Any] = await workflow.execute_activity(
                forge_export_onnx,
                args=[job_id, run_id],
                task_queue=GPU_TASK_QUEUE,
                schedule_to_start_timeout=timedelta(hours=12),
                start_to_close_timeout=timedelta(minutes=20),
                heartbeat_timeout=timedelta(minutes=2),
                retry_policy=QUICK,
            )
        except asyncio.CancelledError:
            await _update(JobUpdate(job_id, state="cancelled", message="Cancelled"))
            raise
        except ActivityError as exc:
            code, message = _failure(exc)
            await _update(
                JobUpdate(job_id, state="failed", message=message, error={"code": code, "message": message})
            )
            raise ApplicationError(message, type=code, non_retryable=True) from exc
        size_mb = result["size"] / 1e6
        message = f"Exported step {result['step']} ({size_mb:,.1f} MB), matches PyTorch"
        await _update(JobUpdate(job_id, state="succeeded", progress=1.0, message=message, result=result))
        return result
