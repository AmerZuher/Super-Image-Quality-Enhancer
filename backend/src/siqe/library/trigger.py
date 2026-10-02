"""Asking the background indexer to run. Safe to call often: one indexer runs at a time.

Signal-with-start either starts ``LibraryIndexWorkflow`` or, if it is already running,
signals it to take another pass after its current batch, so nothing added meanwhile is missed.
"""

from temporalio.client import Client

from siqe.core.config import CPU_TASK_QUEUE

INDEX_WORKFLOW_ID = "library-index"


async def request_index(client: Client) -> None:
    from siqe.workflows.library import LibraryIndexWorkflow

    await client.start_workflow(
        LibraryIndexWorkflow.run,
        id=INDEX_WORKFLOW_ID,
        task_queue=CPU_TASK_QUEUE,
        start_signal="more",
    )


async def index_running(client: Client) -> bool:
    try:
        desc = await client.get_workflow_handle(INDEX_WORKFLOW_ID).describe()
    except Exception:
        return False
    return desc.status is not None and desc.status.name == "RUNNING"
