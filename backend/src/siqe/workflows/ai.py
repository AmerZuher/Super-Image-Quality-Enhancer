import asyncio
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError, CancelledError

with workflow.unsafe.imports_passed_through():
    from siqe.activities.ai import (
        TORCH_ARCHS,
        AiRunRequest,
        discard_run_files,
        register_result,
        run_background,
        run_model,
    )
    from siqe.activities.assets import prepare_asset
    from siqe.activities.jobs import JobUpdate
    from siqe.ai.manifest import MODELS_BY_ID
    from siqe.core.config import CPU_TASK_QUEUE, GPU_TASK_QUEUE
    from siqe.workflows.assets import HEAVY, QUICK, _failure, _update, wake_indexer

# A crashed or restarted worker resumes the run from its last heartbeat (finished tiles).
RUN = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=10))


@workflow.defn
class AiRunWorkflow:
    """Run a model on one image; the result becomes a new image linked to it."""

    @workflow.run
    async def run(self, job_id: str, request: AiRunRequest) -> dict[str, Any]:
        # Models published from Forge aren't in the built-in catalog and run on PyTorch; your own
        # ONNX models aren't either, and the API marks them for the CPU worker.
        spec = MODELS_BY_ID.get(request.model_id)
        await _update(JobUpdate(job_id, state="running", message="Waiting for the AI worker"))
        on_gpu = not request.on_cpu and (spec is None or spec.arch in TORCH_ARCHS)
        try:
            result: dict[str, Any] = await workflow.execute_activity(
                run_model if on_gpu else run_background,
                args=[job_id, request],
                task_queue=GPU_TASK_QUEUE if on_gpu else CPU_TASK_QUEUE,
                # Waiting in the queue behind other GPU jobs is fine; the run itself heartbeats.
                schedule_to_start_timeout=timedelta(hours=12),
                start_to_close_timeout=timedelta(hours=8),
                heartbeat_timeout=timedelta(minutes=3),
                retry_policy=RUN,
            )
            asset_id: str = await workflow.execute_activity(
                register_result,
                args=[job_id, request, result],
                task_queue=CPU_TASK_QUEUE,
                start_to_close_timeout=timedelta(minutes=30),
                retry_policy=QUICK,
            )
            await _update(JobUpdate(job_id, progress=0.9, message="Preparing previews"))
            await workflow.execute_activity(
                prepare_asset,
                args=[job_id, asset_id, 0.9, 0.1],
                task_queue=CPU_TASK_QUEUE,
                start_to_close_timeout=timedelta(hours=2),
                heartbeat_timeout=timedelta(seconds=60),
                retry_policy=HEAVY,
            )
        except (asyncio.CancelledError, ActivityError) as exc:
            cancelled = isinstance(exc, asyncio.CancelledError) or isinstance(exc.cause, CancelledError)
            await workflow.execute_activity(
                discard_run_files,
                job_id,
                task_queue=CPU_TASK_QUEUE,
                start_to_close_timeout=timedelta(minutes=1),
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

        summary = {k: v for k, v in result.items() if k != "path"} | {"asset_id": asset_id}
        where = result["device_name"]
        message = f"{result['width']:,} × {result['height']:,} in {result['seconds']:.0f} s on {where}"
        if result["fallbacks"]:
            message += f" (adjusted: {result['fallbacks'][-1]})"
        if result.get("nonfinite"):
            message += f"; the model produced {result['nonfinite']:,} invalid values, which were replaced"
        await _update(JobUpdate(job_id, state="succeeded", progress=1.0, message=message, result=summary))
        await wake_indexer()
        return summary
