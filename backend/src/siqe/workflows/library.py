import asyncio
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError
from temporalio.workflow import ParentClosePolicy

with workflow.unsafe.imports_passed_through():
    from siqe.activities.jobs import JobUpdate
    from siqe.activities.library import (
        group_duplicates,
        index_batch,
        remove_location_batch,
        scan_import_folder,
    )
    from siqe.core.config import CPU_TASK_QUEUE
    from siqe.workflows.assets import HEAVY, IngestAssetWorkflow, _failure, _update, wake_indexer

RETRY = RetryPolicy(maximum_attempts=5, initial_interval=timedelta(seconds=5), backoff_coefficient=2.0)
# Keep the event history small: start afresh after this many batches.
MAX_BATCHES = 300


@workflow.defn
class LibraryIndexWorkflow:
    """Analyse new images in batches, then regroup duplicates. One runs at a time (fixed id).

    Started with signal-with-start; a ``more`` signal during a run asks for another pass,
    so images added while it works are always picked up.
    """

    def __init__(self) -> None:
        self._more = False

    @workflow.signal
    def more(self) -> None:
        self._more = True

    @workflow.run
    async def run(self) -> dict[str, Any]:
        indexed = 0
        for _ in range(MAX_BATCHES):
            self._more = False
            result: dict[str, Any] = await workflow.execute_activity(
                index_batch,
                task_queue=CPU_TASK_QUEUE,
                start_to_close_timeout=timedelta(minutes=15),
                heartbeat_timeout=timedelta(minutes=1),
                retry_policy=RETRY,
            )
            indexed += result["done"]
            if result["remaining"] == 0 or result["done"] == 0:
                groups: dict[str, Any] = await workflow.execute_activity(
                    group_duplicates,
                    task_queue=CPU_TASK_QUEUE,
                    start_to_close_timeout=timedelta(minutes=15),
                    retry_policy=RETRY,
                )
                if not self._more:
                    return {"indexed": indexed, **groups}
        workflow.continue_as_new()


@workflow.defn
class RemoveLocationWorkflow:
    """Replace images with copies that have no GPS location; originals go to quarantine."""

    @workflow.run
    async def run(self, job_id: str, asset_ids: list[str]) -> dict[str, Any]:
        await _update(JobUpdate(job_id, state="running", message="Removing location"))
        try:
            result: dict[str, Any] = await workflow.execute_activity(
                remove_location_batch,
                args=[job_id, asset_ids],
                task_queue=CPU_TASK_QUEUE,
                start_to_close_timeout=timedelta(hours=2),
                heartbeat_timeout=timedelta(minutes=2),
                retry_policy=HEAVY,
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
        done, failed = result["done"], len(result["failed"])
        message = f"Removed location from {done} image{'s' if done != 1 else ''}"
        if failed:
            message += f"; {failed} couldn't be changed (export those instead)"
        await _update(JobUpdate(job_id, state="succeeded", progress=1.0, message=message, result=result))
        await wake_indexer()
        return result


IMPORT_WORKFLOW_ID = "library-import"
MAX_IMPORT_PAGES = 50


@workflow.defn
class ImportFolderWorkflow:
    """Import new files from the import folder; each becomes an image with its own ingest job."""

    @workflow.run
    async def run(self) -> dict[str, Any]:
        imported = 0
        for _ in range(MAX_IMPORT_PAGES):
            result: dict[str, Any] = await workflow.execute_activity(
                scan_import_folder,
                task_queue=CPU_TASK_QUEUE,
                start_to_close_timeout=timedelta(hours=1),
                heartbeat_timeout=timedelta(minutes=2),
                retry_policy=RETRY,
            )
            for job_id, asset_id in result["started"]:
                await workflow.start_child_workflow(
                    IngestAssetWorkflow.run,
                    args=[job_id, asset_id],
                    id=f"job-{job_id}",
                    task_queue=CPU_TASK_QUEUE,
                    parent_close_policy=ParentClosePolicy.ABANDON,
                    execution_timeout=timedelta(hours=2),
                )
                imported += 1
            if not result.get("more"):
                break
        return {"imported": imported}
