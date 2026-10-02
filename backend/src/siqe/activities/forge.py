"""Forge activities: building datasets (CPU) and training in chunks (GPU queue)."""

import asyncio
import contextlib
import hashlib
import json
import re
import shutil
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any

from sqlalchemy import select
from temporalio import activity
from temporalio.exceptions import ApplicationError

from siqe.activities.threaded import ThreadProgress, run_threaded
from siqe.ai.registry import FORGE_FILE, FORGE_WEIGHTS, get_spec, models_root, publish_model
from siqe.core.errors import AppError
from siqe.core.logging import get_logger
from siqe.db.base import utcnow
from siqe.db.models import AiModel, Asset, ForgeMetric, JobState, ModelStatus
from siqe.db.session import session_scope
from siqe.events.bus import publish
from siqe.forge import datasets
from siqe.forge.records import METRIC_EVENT, get_dataset, get_run, publish_dataset, publish_run
from siqe.forge.training import CHUNK_SECONDS, TrainSettings, best_weights, last_checkpoint
from siqe.jobs.progress import ProgressReporter
from siqe.jobs.records import apply_update
from siqe.library.rules import RuleSet
from siqe.library.selection import select_images
from siqe.storage.store import get_store

log = get_logger(__name__)
MAX_NOTES = 20


def _fail(code: str, message: str, fix: str | None = None) -> ApplicationError:
    return ApplicationError(message, {"code": code, "fix": fix}, type=code, non_retryable=True)


# ------------------------------------------------------------------------------ datasets


@activity.defn
async def forge_build_dataset(dataset_id: str) -> dict[str, Any]:
    async with session_scope() as session:
        dataset = await get_dataset(session, uuid.UUID(dataset_id))
        dataset.state = JobState.running
        dataset.error = None
        await publish_dataset(session, dataset)
        await session.commit()
        source = dict(dataset.source or {})
        settings = datasets.DatasetSettings.model_validate(dataset.settings or {})
        job_id = str(dataset.job_id) if dataset.job_id else None
        ids, _ = await select_images(
            session,
            source.get("kind", "all"),
            asset_ids=source.get("asset_ids"),
            album_id=source.get("album_id"),
            rules=RuleSet.model_validate(source["rules"]) if source.get("rules") else None,
            empty_code="forge.no_images",
        )
        rows = (
            await session.execute(select(Asset.id, Asset.sha256, Asset.extension).where(Asset.id.in_(ids)))
        ).tuples()
        store = get_store()
        images = [(asset_id, store.original(sha, ext)) for asset_id, sha, ext in rows]
    if not images:
        raise _fail(
            "forge.no_images", "There are no images to build the dataset from.", "Choose some images."
        )
    reporter = ProgressReporter(job_id) if job_id else None

    def work(state: ThreadProgress) -> datasets.Built:
        return datasets.build(
            uuid.UUID(dataset_id),
            images,
            settings,
            lambda done, total: state.update(done / max(1, total), f"Cutting crops: image {done} of {total}"),
        )

    if reporter is not None:
        built = await run_threaded(work, reporter)
    else:
        built = await asyncio.to_thread(work, ThreadProgress())
    async with session_scope() as session:
        dataset = await get_dataset(session, uuid.UUID(dataset_id))
        dataset.images = built.images
        dataset.skipped = built.skipped
        dataset.train_crops = built.train
        dataset.val_crops = built.val
        dataset.size_bytes = built.size_bytes
        if built.train == 0:
            dataset.state = JobState.failed
            dataset.error = {
                "code": "forge.dataset_empty",
                "message": "No image was big enough or detailed enough for a crop.",
                "skipped": built.reasons,
            }
        else:
            dataset.state = JobState.succeeded
        await publish_dataset(session, dataset)
        await session.commit()
    if built.train == 0:
        raise _fail(
            "forge.dataset_empty",
            "No image was big enough or detailed enough for a crop.",
            "Choose larger photos, or lower the minimum size and crop size.",
        )
    return {
        "images": built.images,
        "skipped": built.skipped,
        "train": built.train,
        "val": built.val,
        "reasons": built.reasons,
    }


@activity.defn
async def forge_dataset_failed(dataset_id: str, error: dict[str, Any]) -> None:
    async with session_scope() as session:
        dataset = await get_dataset(session, uuid.UUID(dataset_id))
        if dataset.state != JobState.failed:
            dataset.state = JobState.failed
            dataset.error = error
            await publish_dataset(session, dataset)
            await session.commit()


# --------------------------------------------------------------------------------- runs


@activity.defn
async def forge_run_start(run_id: str) -> dict[str, Any]:
    async with session_scope() as session:
        run = await get_run(session, uuid.UUID(run_id), for_update=True)
        if run.state == JobState.queued:
            run.state = JobState.running
            run.started_at = utcnow()
        if run.job_id:
            await apply_update(session, run.job_id, state=JobState.running, message="Starting")
        await publish_run(session, run)
        await session.commit()
        return {"paused": run.paused}


class _RunReporter:
    """Heartbeats, job progress, and the run's live metrics, written from the event loop."""

    def __init__(self, run_id: str, job_id: str | None, total: int, queue: deque[Any]) -> None:
        self.run_id = uuid.UUID(run_id)
        self.job = ProgressReporter(job_id, min_interval=1.0) if job_id else None
        self.total = max(1, total)
        self.queue = queue
        self._last_flush = 0.0

    async def report(
        self,
        fraction: float,
        message: str | None = None,
        *,
        force: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        if self.job is not None:
            await self.job.report(fraction, message, force=force, details=details)
        elif activity.in_activity():
            activity.heartbeat(details or {})
        now = time.monotonic()
        if force or now - self._last_flush > 1.0:
            self._last_flush = now
            await self.flush((details or {}).get("step"))

    async def flush(self, step: int | None = None) -> None:
        points = []
        while self.queue:
            points.append(self.queue.popleft())
        if not points and step is None:
            return
        async with session_scope() as session:
            run = await get_run(session, self.run_id)
            for m in points:
                session.add(
                    ForgeMetric(
                        run_id=run.id,
                        step=m.step,
                        kind=m.kind,
                        loss=m.loss,
                        psnr=m.psnr,
                        ssim=m.ssim,
                        lr=m.lr,
                    )
                )
                if m.kind == "train" and m.loss is not None:
                    run.last_loss = m.loss
                if m.kind == "val":
                    run.bicubic_psnr = m.bicubic_psnr
                    if m.psnr is not None and (run.best_psnr is None or m.psnr > run.best_psnr):
                        run.best_psnr, run.best_ssim, run.best_step = m.psnr, m.ssim, m.step
            if step is not None:
                run.step = max(run.step, int(step))
            if points:
                await publish(
                    session,
                    METRIC_EVENT,
                    {
                        "run_id": str(run.id),
                        "points": [
                            {
                                "step": m.step,
                                "kind": m.kind,
                                "loss": m.loss,
                                "psnr": m.psnr,
                                "ssim": m.ssim,
                                "lr": m.lr,
                            }
                            for m in points
                        ],
                    },
                )
            await publish_run(session, run)
            await session.commit()


async def _run_spec(run_id: str) -> tuple[Any, TrainSettings, str | None]:
    """The trainer's view of a run: its plan, data and settings."""
    from siqe.forge import trainer
    from siqe.forge.degrade import Degradation
    from siqe.forge.graph import ForgeGraph, analyze

    async with session_scope() as session:
        run = await get_run(session, uuid.UUID(run_id))
        if run.dataset_id is None:
            raise _fail("forge.dataset_missing", "The dataset for this run was deleted.", "Start a new run.")
        dataset = await get_dataset(session, run.dataset_id)
        settings = TrainSettings.model_validate(run.settings)
        multiple = analyze(ForgeGraph.model_validate(run.graph)).stats.patch_multiple
        spec = trainer.RunSpec(
            run_id=run_id,
            dataset_id=str(dataset.id),
            plan=list(run.plan),
            scale=run.scale,
            color=run.color,
            settings=settings,
            degradation=Degradation.model_validate(dataset.degradation or {}),
            multiple=multiple,
        )
        return spec, settings, str(run.job_id) if run.job_id else None


@activity.defn
async def forge_train_chunk(run_id: str) -> dict[str, Any]:
    """Train for up to CHUNK_SECONDS. Cancelling it (pause, stop) saves a checkpoint first."""
    from siqe.ai import runtime
    from siqe.forge import trainer

    spec, settings, job_id = await _run_spec(run_id)
    device = runtime.pick_device("auto")
    queue: deque[Any] = deque()
    reporter = _RunReporter(run_id, job_id, settings.steps, queue)
    state = ThreadProgress()

    def progress(step: int, message: str) -> None:
        # While stopping, update() refuses; the training loop sees the flag and saves.
        with contextlib.suppress(InterruptedError):
            state.update(step / settings.steps, message, {"step": step})

    def work() -> Any:
        return trainer.train_chunk(
            spec,
            device,
            CHUNK_SECONDS,
            should_stop=state.cancelled.is_set,
            on_progress=progress,
            on_metric=queue.append,
        )

    task = asyncio.create_task(asyncio.to_thread(work))
    try:
        while not task.done():
            await reporter.report(state.fraction, state.message, details=state.details)
            await asyncio.wait({task}, timeout=0.5)
        result = task.result()
    except asyncio.CancelledError:
        state.cancelled.set()
        await asyncio.wait({task}, timeout=300)
        if task.done() and task.exception() is None:
            await _record_chunk(run_id, task.result(), runtime.device_name(device), reporter)
        raise
    except AppError as exc:
        await reporter.flush()
        raise _fail(exc.code, exc.detail, exc.fix) from exc
    await _record_chunk(run_id, result, runtime.device_name(device), reporter)
    return {"step": result.step, "done": result.done}


async def _record_chunk(run_id: str, result: Any, device_name: str, reporter: _RunReporter) -> None:
    await reporter.flush(result.step)
    async with session_scope() as session:
        run = await get_run(session, uuid.UUID(run_id), for_update=True)
        run.step = result.step
        run.batch = result.batch
        run.accumulate = result.accumulate
        run.device = device_name
        if result.best_psnr is not None:
            run.best_psnr, run.best_ssim, run.best_step = result.best_psnr, result.best_ssim, result.best_step
        if result.bicubic_psnr is not None:
            run.bicubic_psnr = result.bicubic_psnr
        if result.notes:
            run.notes = [*(run.notes or []), *result.notes][-MAX_NOTES:]
        await publish_run(session, run)
        await session.commit()


@activity.defn
async def forge_run_finish(run_id: str, state: str, error: dict[str, Any] | None = None) -> dict[str, Any]:
    async with session_scope() as session:
        run = await get_run(session, uuid.UUID(run_id), for_update=True)
        run.state = JobState(state)
        run.paused = False
        run.finished_at = utcnow()
        run.error = error
        if run.best_psnr is not None:
            message = f"Best {run.best_psnr:.2f} dB PSNR at step {run.best_step:,}"
            if run.bicubic_psnr is not None:
                message += f" (bicubic: {run.bicubic_psnr:.2f} dB)"
        else:
            message = f"Stopped at step {run.step:,}" if state != "failed" else "Training failed"
        if run.job_id:
            await apply_update(
                session,
                run.job_id,
                state=run.state,
                progress=1.0 if run.state == JobState.succeeded else None,
                message=error.get("message", message) if error else message,
                error=error,
                result={"step": run.step, "best_psnr": run.best_psnr, "best_step": run.best_step},
            )
        await publish_run(session, run)
        await session.commit()
        return {"step": run.step, "best_psnr": run.best_psnr}


# ------------------------------------------------------------------------------ publish


def model_slug(name: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40].strip("-")
    return text or "model"


def _next_model_id(name: str) -> str:
    root = models_root()
    slug = model_slug(name)
    taken = {p.name for p in root.glob(f"forge-{slug}-v*")} if root.is_dir() else set()
    version = 1
    while f"forge-{slug}-v{version}" in taken:
        version += 1
    return f"forge-{slug}-v{version}"


@activity.defn
async def forge_publish(run_id: str, name: str, summary: str = "") -> dict[str, Any]:
    """Benchmark a run's best checkpoint and add it to AI Lab as a new model version."""
    from siqe.ai import runtime
    from siqe.forge.graph import ForgeGraph, analyze
    from siqe.forge.publish import benchmark

    spec, _, _ = await _run_spec(run_id)
    async with session_scope() as session:
        run = await get_run(session, uuid.UUID(run_id))
        stats = analyze(ForgeGraph.model_validate(run.graph)).stats
        project_name = run.project_name
    weights = best_weights(run_id)
    if not weights.exists():
        raise _fail(
            "forge.nothing_to_publish",
            "This run hasn't saved a validated checkpoint yet.",
            "Let it train past its first validation, then publish.",
        )
    device = runtime.pick_device("auto")
    activity.heartbeat("benchmarking")
    scores = await asyncio.to_thread(benchmark, spec, weights, device)
    model_id = _next_model_id(name)
    folder = models_root() / model_id
    staging = folder.with_name(folder.name + ".partial")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    await asyncio.to_thread(shutil.copyfile, weights, staging / FORGE_WEIGHTS)
    sha, size = await asyncio.to_thread(_hash, staging / FORGE_WEIGHTS)
    version = int(model_id.rsplit("-v", 1)[1])
    info = {
        "name": f"{name} v{version}",
        "summary": summary
        or f"Trained in Forge from {project_name}: ×{spec.scale}, {stats.params:,} parameters, "
        f"{scores['psnr']:.2f} dB on held-out photos (bicubic {scores['bicubic_psnr']:.2f} dB).",
        "scale": spec.scale,
        "color": spec.color,
        "plan": spec.plan,
        "context": stats.context,
        "multiple": stats.patch_multiple,
        "params": stats.params,
        "sha256": sha,
        "size": size,
        "run_id": run_id,
        "step": run_step(run_id),
        "benchmark": scores,
        "published_at": utcnow().isoformat(),
    }
    (staging / FORGE_FILE).write_text(json.dumps(info, indent=2), encoding="utf-8")
    staging.replace(folder)
    model_spec = get_spec(model_id)
    async with session_scope() as session:
        row = AiModel(
            id=model_id, status=ModelStatus.installed, source="forge", spec=info, installed_at=utcnow()
        )
        session.add(row)
        run = await get_run(session, uuid.UUID(run_id), for_update=True)
        run.model_id = model_id
        await publish_model(session, model_spec, row)
        await publish_run(session, run)
        await session.commit()
    return {"model_id": model_id, "name": info["name"], **scores}


def run_step(run_id: str) -> int | None:
    import torch

    path = last_checkpoint(run_id)
    if not path.exists():
        return None
    return int(torch.load(path, map_location="cpu", weights_only=True)["step"])


def _hash(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size
