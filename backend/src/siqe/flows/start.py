"""Creating a flow run and its items, and starting or waking its workflow.

Shared by the API (a run you start) and the import trigger (a flow watching a folder). A
watching flow keeps one run open: new images are added to it and the run is woken with a
signal; after a minute without new images it finishes, and the next image opens a new run.
"""

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from temporalio.client import Client
from temporalio.service import RPCError

from siqe.core.config import CPU_TASK_QUEUE, get_settings
from siqe.core.errors import AppError
from siqe.core.logging import get_logger
from siqe.db.base import utcnow
from siqe.db.models import Asset, Flow, FlowRun, FlowRunItem, ItemState, Job, JobState, RunKind
from siqe.db.session import get_engine
from siqe.flows.document import FlowDocument, check
from siqe.flows.records import publish_run, run_folder
from siqe.jobs.start import create_job

log = get_logger(__name__)

RUN_TIMEOUT = timedelta(days=30)
MAX_ITEMS = 20_000


async def require_models(session: AsyncSession, document: dict[str, Any]) -> None:
    """Refuse a run up front when an AI block's model isn't downloaded, instead of failing every image."""
    from siqe.ai.manifest import FACE_MODEL_ID
    from siqe.ai.registry import get_spec, require_installed
    from siqe.flows.catalog import NODES_BY_TYPE

    needed: list[str] = []
    for node in document.get("nodes", []):
        spec = NODES_BY_TYPE.get(node.get("type", ""))
        if spec is None or not spec.ai:
            continue
        params = node.get("params") or {}
        if params.get("model"):
            needed.append(str(params["model"]))
        if params.get("restore_faces"):
            needed.append(FACE_MODEL_ID)
    for model_id in dict.fromkeys(needed):
        await require_installed(session, get_spec(model_id))


def runnable_document(flow: Flow) -> dict[str, Any]:
    doc, problems = check(FlowDocument.model_validate(flow.document or {}))
    if problems:
        raise AppError(
            "flow.invalid",
            f"This flow can't run yet: {problems[0].message}.",
            status=422,
            title="Flow not ready",
            fix="Fix the blocks marked in red in the editor, then run it again.",
            problems=[p.model_dump() for p in problems],
        )
    return doc.model_dump()


async def create_run(
    session: AsyncSession,
    flow: Flow,
    asset_ids: list[uuid.UUID],
    *,
    kind: RunKind,
    dry_run: bool,
    source: dict[str, Any],
) -> tuple[FlowRun, Job]:
    """Rows for a new run, its items and its job. The caller commits and starts the workflow."""
    document = runnable_document(flow)
    await require_models(session, document)
    if len(asset_ids) > MAX_ITEMS:
        raise AppError(
            "flow.too_many_images",
            f"A run can take up to {MAX_ITEMS:,} images; this one has {len(asset_ids):,}.",
            status=422,
            fix="Run the flow on an album or a filtered view instead.",
        )
    rows = await session.execute(select(Asset.id, Asset.original_name).where(Asset.id.in_(asset_ids)))
    names = {asset_id: name for asset_id, name in rows.tuples()}
    ordered = [a for a in dict.fromkeys(asset_ids) if a in names]
    if not ordered:
        raise AppError(
            "flow.no_images",
            "There are no images to run the flow on.",
            status=422,
            fix="Choose some images first.",
        )
    now = utcnow()
    run = FlowRun(
        flow_id=flow.id,
        flow_name=flow.name,
        kind=kind,
        dry_run=dry_run,
        document=document,
        source=source,
        state=JobState.queued,
        total=len(ordered),
        output_dir=run_folder(flow.name, now, dry_run),
    )
    session.add(run)
    await session.flush()
    session.add_all(
        FlowRunItem(run_id=run.id, position=i, asset_id=a, name=names[a], state=ItemState.pending)
        for i, a in enumerate(ordered)
    )
    count = len(ordered)
    label = "Dry run of" if dry_run else "Run"
    job = await create_job(
        session,
        kind="flow.run",
        title=f"{label} {flow.name} on {count} image{'s' if count != 1 else ''}",
        params={"flow_id": str(flow.id), "run_id": str(run.id), "dry_run": dry_run},
    )
    run.job_id = job.id
    await publish_run(session, run)
    return run, job


def workflow_args(run: FlowRun) -> list[Any]:
    return [str(run.id), 0, get_settings().flow_concurrency]


async def start_run(client: Client, run: FlowRun, job: Job) -> None:
    from siqe.workflows.flows import FlowRunWorkflow

    await client.start_workflow(
        FlowRunWorkflow.run,
        args=workflow_args(run),
        id=job.workflow_id or f"job-{job.id}",
        task_queue=CPU_TASK_QUEUE,
        execution_timeout=RUN_TIMEOUT,
    )


def _matches(folder: str | None, path: str) -> bool:
    prefix = (folder or "").strip("/")
    return not prefix or path == prefix or path.startswith(prefix + "/")


async def trigger(session: AsyncSession, client: Client, asset: Asset) -> int:
    """Hand an image imported from the folder to every flow watching that folder."""
    source = asset.source or {}
    if source.get("kind") != "folder":
        return 0
    path = str(source.get("path") or "")
    flows = (await session.execute(select(Flow).where(Flow.watch_enabled.is_(True)))).scalars().all()
    started = 0
    for flow in flows:
        if not _matches(flow.watch_folder, path):
            continue
        # One trigger at a time per flow, so two imports never open two runs. The lock lives on
        # its own connection because the work below commits more than once.
        async with get_engine().connect() as lock:
            await lock.execute(text("SELECT pg_advisory_lock(hashtext(:k))"), {"k": f"flow:{flow.id}"})
            try:
                await _add_to_watch_run(session, client, flow, asset)
                started += 1
            except AppError as exc:
                log.warning("flow.trigger_skipped", flow=flow.name, error=exc.detail)
            finally:
                await lock.execute(text("SELECT pg_advisory_unlock(hashtext(:k))"), {"k": f"flow:{flow.id}"})
    return started


async def _add_to_watch_run(session: AsyncSession, client: Client, flow: Flow, asset: Asset) -> None:
    from siqe.workflows.flows import FlowRunWorkflow

    open_run = (
        await session.execute(
            select(FlowRun)
            .where(
                FlowRun.flow_id == flow.id,
                FlowRun.kind == RunKind.watch,
                FlowRun.state.in_([JobState.queued, JobState.running]),
            )
            .order_by(FlowRun.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if open_run is not None and open_run.job_id is not None:
        position = (
            await session.execute(
                select(func.coalesce(func.max(FlowRunItem.position), -1)).where(
                    FlowRunItem.run_id == open_run.id
                )
            )
        ).scalar_one()
        session.add(
            FlowRunItem(
                run_id=open_run.id,
                position=int(position) + 1,
                asset_id=asset.id,
                name=asset.original_name,
                state=ItemState.pending,
            )
        )
        open_run.total += 1
        await session.commit()
        try:
            await client.get_workflow_handle(f"job-{open_run.job_id}").signal(FlowRunWorkflow.more)
            return
        except RPCError:
            # The run finished a moment ago; move the image into a fresh run.
            item = (
                await session.execute(
                    select(FlowRunItem).where(
                        FlowRunItem.run_id == open_run.id, FlowRunItem.asset_id == asset.id
                    )
                )
            ).scalar_one_or_none()
            if item is not None and item.state == ItemState.pending:
                await session.delete(item)
                open_run.total -= 1
                await session.commit()
    run, job = await create_run(
        session,
        flow,
        [asset.id],
        kind=RunKind.watch,
        dry_run=False,
        source={"kind": "watch", "folder": flow.watch_folder or ""},
    )
    await session.commit()
    await start_run(client, run, job)
