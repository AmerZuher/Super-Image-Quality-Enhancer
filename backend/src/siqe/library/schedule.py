"""The Temporal Schedule that checks the import folder every few seconds."""

from datetime import timedelta

from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleAlreadyRunningError,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
    ScheduleUpdate,
    ScheduleUpdateInput,
)
from temporalio.service import RPCError

from siqe.core.config import CPU_TASK_QUEUE, Settings
from siqe.core.logging import get_logger

log = get_logger(__name__)

SCHEDULE_ID = "library-import-folder"


def _schedule(seconds: int) -> Schedule:
    from siqe.workflows.library import IMPORT_WORKFLOW_ID, ImportFolderWorkflow

    return Schedule(
        action=ScheduleActionStartWorkflow(
            ImportFolderWorkflow.run,
            id=IMPORT_WORKFLOW_ID,
            task_queue=CPU_TASK_QUEUE,
            execution_timeout=timedelta(hours=6),
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(seconds=seconds))]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )


async def ensure_import_schedule(client: Client, settings: Settings) -> None:
    """Create or update the schedule to match settings; delete it when imports are off."""
    handle = client.get_schedule_handle(SCHEDULE_ID)
    if settings.import_scan_seconds <= 0:
        try:
            await handle.delete()
            log.info("library.import_schedule_removed")
        except RPCError:
            pass
        return
    schedule = _schedule(max(10, settings.import_scan_seconds))
    try:
        await client.create_schedule(SCHEDULE_ID, schedule)
        log.info("library.import_schedule_created", every=settings.import_scan_seconds)
    except ScheduleAlreadyRunningError:

        def update(_: ScheduleUpdateInput) -> ScheduleUpdate:
            return ScheduleUpdate(schedule=schedule)

        await handle.update(update)
