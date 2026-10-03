"""Activities for the model registry: downloading, verifying and installing weights."""

import asyncio
import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from temporalio import activity
from temporalio.exceptions import ApplicationError

from siqe.activities.threaded import ThreadProgress, run_threaded
from siqe.ai.registry import (
    USER_FILE,
    USER_WEIGHTS,
    get_row,
    get_spec,
    install_files,
    models_root,
    publish_model,
    user_staging,
)
from siqe.core.errors import AppError
from siqe.db.base import utcnow
from siqe.db.models import AiModel, ModelStatus
from siqe.db.session import session_scope
from siqe.jobs.progress import ProgressReporter

# Network hiccups are retried (and resume from the partial file); anything else is final.
RETRYABLE = frozenset({"model.download_failed"})


@activity.defn
async def install_model(job_id: str, model_id: str) -> dict[str, Any]:
    spec = get_spec(model_id)
    reporter = ProgressReporter(job_id)

    def work(state: ThreadProgress) -> str:
        timeout = httpx.Timeout(30.0, read=120.0)
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            path = install_files(
                spec,
                client,
                on_progress=lambda done, total: state.update(
                    done / total, f"{done / 1e6:,.0f} of {total / 1e6:,.0f} MB"
                ),
                should_stop=state.cancelled.is_set,
            )
        return str(path)

    try:
        path = await run_threaded(work, reporter)
    except AppError as exc:
        raise ApplicationError(
            exc.detail,
            {"code": exc.code, "fix": exc.fix},
            type=exc.code,
            non_retryable=exc.code not in RETRYABLE,
        ) from exc

    async with session_scope() as session:
        row = await get_row(session, model_id, for_update=True)
        if row is not None:
            row.status = ModelStatus.installed
            row.bytes_done = spec.size_bytes
            row.installed_at = utcnow()
            row.error = None
            await publish_model(session, spec, row)
    return {"path": path, "size_bytes": spec.size_bytes}


@dataclass
class ModelFailure:
    model_id: str
    code: str
    message: str


@activity.defn
async def mark_model_failed(failure: ModelFailure) -> None:
    spec = get_spec(failure.model_id)
    async with session_scope() as session:
        row = await get_row(session, failure.model_id, for_update=True)
        if row is None:
            return
        if failure.code == "cancelled":
            # A cancelled download leaves the model as if it had never been requested.
            await session.delete(row)
            await publish_model(session, spec, None)
            return
        row.status = ModelStatus.failed
        row.error = {"code": failure.code, "message": failure.message}
        await publish_model(session, spec, row)


# ------------------------------------------------------------ your own ONNX models


@dataclass
class OnnxImport:
    job_id: str
    staged: str  # the uploaded file in tmp/, on the data volume
    model_id: str
    name: str
    task: str | None
    sha256: str
    size: int


def _install_onnx(req: OnnxImport, probe: dict[str, Any], task: str, speed: str) -> None:
    """Move the checked file into models/<id>/ with its descriptor, all or nothing."""
    folder = models_root() / req.model_id
    staging = user_staging(req.model_id)
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    shutil.move(req.staged, staging / USER_WEIGHTS)
    descriptor = {
        "name": req.name,
        "task": task,
        "speed": speed,
        "sha256": req.sha256,
        "size": req.size,
        "probe": probe,
        "summary": probe.get("description") or None,
    }
    (staging / USER_FILE).write_text(json.dumps(descriptor, indent=2), encoding="utf-8")
    staging.replace(folder)


def _already_installed(req: OnnxImport) -> bool:
    """A retry after the files were moved: the descriptor is there with this file's hash."""
    try:
        info = json.loads((models_root() / req.model_id / USER_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return bool(info.get("sha256") == req.sha256)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


@activity.defn
async def import_onnx(req: OnnxImport) -> dict[str, Any]:
    """Check an uploaded ONNX file by running it, then install it as a model."""
    from siqe.ai.onnx_import import probe, speed_label, task_for

    reporter = ProgressReporter(req.job_id)
    if not await asyncio.to_thread(_already_installed, req):
        staged = Path(req.staged)

        def work(state: ThreadProgress) -> dict[str, Any]:
            if not staged.is_file():
                raise AppError(
                    "upload.missing",
                    "The uploaded file is gone (the app may have restarted and cleaned up).",
                    fix="Add the model again.",
                )
            if _sha256(staged) != req.sha256:
                raise AppError("upload.corrupt", "The uploaded file changed on disk.", fix="Add it again.")
            found = probe(staged, on_progress=lambda f, m: state.update(f * 0.9, m))
            details = found.to_dict()
            state.update(0.95, "Installing")
            _install_onnx(req, details, task_for(found, req.task), speed_label(found.seconds_per_mp))
            return details

        try:
            await run_threaded(work, reporter)
        except AppError as exc:
            raise ApplicationError(
                exc.detail, {"code": exc.code, "fix": exc.fix}, type=exc.code, non_retryable=True
            ) from exc

    spec = get_spec(req.model_id)
    async with session_scope() as session:
        row = await get_row(session, req.model_id, for_update=True)
        if row is None:
            row = AiModel(id=req.model_id, source="user")
            session.add(row)
        row.status = ModelStatus.installed
        row.bytes_total = row.bytes_done = spec.size_bytes
        row.installed_at = utcnow()
        row.error = None
        await publish_model(session, spec, row)
    return {
        "model_id": spec.id,
        "name": spec.name,
        "task": spec.task,
        "scale": spec.scale,
        "size_bytes": spec.size_bytes,
    }


def _discard(req: OnnxImport) -> None:
    Path(req.staged).unlink(missing_ok=True)
    shutil.rmtree(user_staging(req.model_id), ignore_errors=True)


@activity.defn
async def discard_onnx_upload(req: OnnxImport) -> None:
    """Remove the upload and the reserved folder of an import that failed (idempotent)."""
    await asyncio.to_thread(_discard, req)
