"""Forge rows: serialising them, fetching them, and their live events."""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from siqe.core.errors import NotFoundError
from siqe.db.models import ForgeDataset, ForgeProject, ForgeRun
from siqe.events.bus import publish

PROJECT_EVENT = "forge.project"
DATASET_EVENT = "forge.dataset"
RUN_EVENT = "forge.run"
METRIC_EVENT = "forge.metrics"


def _iso(value: Any) -> str | None:
    return value.isoformat() if value else None


def dataset_to_dict(d: ForgeDataset) -> dict[str, Any]:
    return {
        "id": str(d.id),
        "name": d.name,
        "source": d.source,
        "settings": d.settings,
        "degradation": d.degradation,
        "state": d.state.value,
        "job_id": str(d.job_id) if d.job_id else None,
        "images": d.images,
        "skipped": d.skipped,
        "train_crops": d.train_crops,
        "val_crops": d.val_crops,
        "size_bytes": d.size_bytes,
        "error": d.error,
        "created_at": _iso(d.created_at),
        "updated_at": _iso(d.updated_at),
    }


def run_to_dict(r: ForgeRun) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "project_id": str(r.project_id) if r.project_id else None,
        "project_name": r.project_name,
        "dataset_id": str(r.dataset_id) if r.dataset_id else None,
        "job_id": str(r.job_id) if r.job_id else None,
        "scale": r.scale,
        "color": r.color,
        "settings": r.settings,
        "state": r.state.value,
        "paused": r.paused,
        "step": r.step,
        "total_steps": r.total_steps,
        "batch": r.batch,
        "accumulate": r.accumulate,
        "device": r.device,
        "last_loss": r.last_loss,
        "best_psnr": r.best_psnr,
        "best_ssim": r.best_ssim,
        "best_step": r.best_step,
        "bicubic_psnr": r.bicubic_psnr,
        "notes": r.notes or [],
        "error": r.error,
        "model_id": r.model_id,
        "sample_url": f"/api/forge/runs/{r.id}/sample" if r.best_step is not None else None,
        "onnx": {**r.onnx_export, "url": f"/api/forge/runs/{r.id}/onnx"} if r.onnx_export else None,
        "created_at": _iso(r.created_at),
        "started_at": _iso(r.started_at),
        "finished_at": _iso(r.finished_at),
    }


async def get_project(session: AsyncSession, project_id: uuid.UUID) -> ForgeProject:
    project = await session.get(ForgeProject, project_id)
    if project is None:
        raise NotFoundError("forge.project_not_found", "That model project doesn't exist.", title="Not found")
    return project


async def get_dataset(session: AsyncSession, dataset_id: uuid.UUID) -> ForgeDataset:
    dataset = await session.get(ForgeDataset, dataset_id)
    if dataset is None:
        raise NotFoundError("forge.dataset_not_found", "That dataset doesn't exist.", title="Not found")
    return dataset


async def get_run(session: AsyncSession, run_id: uuid.UUID, *, for_update: bool = False) -> ForgeRun:
    stmt = select(ForgeRun).where(ForgeRun.id == run_id)
    if for_update:
        stmt = stmt.with_for_update()
    run = (await session.execute(stmt)).scalar_one_or_none()
    if run is None:
        raise NotFoundError("forge.run_not_found", "That training run doesn't exist.", title="Not found")
    return run


async def publish_dataset(session: AsyncSession, dataset: ForgeDataset) -> None:
    await session.flush()
    await publish(session, DATASET_EVENT, dataset_to_dict(dataset))


async def publish_run(session: AsyncSession, run: ForgeRun) -> None:
    await session.flush()
    data = run_to_dict(run)
    data.pop("settings", None)
    await publish(session, RUN_EVENT, data)


async def publish_project(session: AsyncSession, project_id: uuid.UUID) -> None:
    await session.flush()
    await publish(session, PROJECT_EVENT, {"id": str(project_id)})
