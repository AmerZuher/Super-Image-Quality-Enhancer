"""Flow, run and item rows: serialising them, counting progress, and where outputs go."""

import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from siqe.core.config import get_settings
from siqe.core.errors import NotFoundError
from siqe.db.models import Flow, FlowRun, FlowRunItem, ItemState
from siqe.events.bus import publish

FLOW_EVENT = "flow.updated"
RUN_EVENT = "flow.run"

_SLUG = re.compile(r"[^\w\- ]+")


def slug(name: str) -> str:
    return (_SLUG.sub("", name).strip() or "flow")[:60]


def outputs_root() -> Path:
    """The mounted output folder if it's writable, else a folder on the data volume."""
    settings = get_settings()
    root = settings.output_dir
    try:
        root.mkdir(parents=True, exist_ok=True)
        if os.access(root, os.W_OK):
            return root
    except OSError:
        pass
    return settings.data_dir / "outputs"


def run_folder(flow_name: str, when: datetime, dry_run: bool) -> str:
    stamp = when.strftime("%Y-%m-%d %H%M%S")
    return f"{slug(flow_name)}/{stamp}{' dry run' if dry_run else ''}"


def flow_to_dict(flow: Flow) -> dict[str, Any]:
    return {
        "id": str(flow.id),
        "name": flow.name,
        "description": flow.description,
        "document": flow.document,
        "watch_folder": flow.watch_folder,
        "watch_enabled": flow.watch_enabled,
        "recipe": flow.recipe,
        "created_at": flow.created_at.isoformat() if flow.created_at else None,
        "updated_at": flow.updated_at.isoformat() if flow.updated_at else None,
    }


def run_to_dict(run: FlowRun) -> dict[str, Any]:
    return {
        "id": str(run.id),
        "flow_id": str(run.flow_id) if run.flow_id else None,
        "flow_name": run.flow_name,
        "job_id": str(run.job_id) if run.job_id else None,
        "kind": run.kind.value,
        "dry_run": run.dry_run,
        "source": run.source,
        "state": run.state.value,
        "total": run.total,
        "done": run.done,
        "failed": run.failed,
        "skipped": run.skipped,
        "output_dir": run.output_dir,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "download_url": f"/api/flows/runs/{run.id}/download" if run.done else None,
    }


def item_to_dict(item: FlowRunItem) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "position": item.position,
        "asset_id": str(item.asset_id) if item.asset_id else None,
        "name": item.name,
        "state": item.state.value,
        "steps": item.steps or [],
        "outputs": item.outputs or [],
        "error": item.error,
        "thumb_url": f"/api/assets/{item.asset_id}/thumb" if item.asset_id else None,
        "started_at": item.started_at.isoformat() if item.started_at else None,
        "finished_at": item.finished_at.isoformat() if item.finished_at else None,
    }


async def get_flow(session: AsyncSession, flow_id: uuid.UUID, *, for_update: bool = False) -> Flow:
    stmt = select(Flow).where(Flow.id == flow_id)
    if for_update:
        stmt = stmt.with_for_update()
    flow = (await session.execute(stmt)).scalar_one_or_none()
    if flow is None:
        raise NotFoundError("flow.not_found", "That flow doesn't exist.", title="Flow not found")
    return flow


async def get_run(session: AsyncSession, run_id: uuid.UUID, *, for_update: bool = False) -> FlowRun:
    stmt = select(FlowRun).where(FlowRun.id == run_id)
    if for_update:
        stmt = stmt.with_for_update()
    run = (await session.execute(stmt)).scalar_one_or_none()
    if run is None:
        raise NotFoundError("flow.run_not_found", "That run doesn't exist.", title="Run not found")
    return run


async def recount(session: AsyncSession, run: FlowRun) -> None:
    rows = await session.execute(
        select(FlowRunItem.state, func.count())
        .where(FlowRunItem.run_id == run.id)
        .group_by(FlowRunItem.state)
    )
    counts = {state: int(n) for state, n in rows.tuples()}
    run.total = sum(counts.values())
    run.done = counts.get(ItemState.done, 0)
    run.failed = counts.get(ItemState.failed, 0)
    run.skipped = counts.get(ItemState.skipped, 0)


async def publish_run(session: AsyncSession, run: FlowRun) -> None:
    await session.flush()
    data = run_to_dict(run)
    data.pop("source", None)
    await publish(session, RUN_EVENT, data)


async def publish_flow(session: AsyncSession, flow: Flow) -> None:
    await session.flush()
    await publish(session, FLOW_EVENT, {"id": str(flow.id), "name": flow.name})
