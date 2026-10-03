"""Activities for assets: preparing previews after upload, and exporting edited renditions."""

import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyvips
from temporalio import activity
from temporalio.exceptions import ApplicationError

from siqe.activities.threaded import ThreadProgress, run_threaded
from siqe.assets.records import get_asset, get_rendition, megapixel_limit, publish_asset, publish_rendition
from siqe.core.config import get_settings
from siqe.core.errors import AppError
from siqe.core.logging import get_logger
from siqe.db.base import utcnow
from siqe.db.models import AssetStatus, RenditionStatus
from siqe.db.session import session_scope
from siqe.imaging.edits import parse_document
from siqe.imaging.export import ExportOptions, ExportResult, encode
from siqe.imaging.io import open_image
from siqe.imaging.pipeline import render_working, resize_to
from siqe.imaging.working import from_working, to_working
from siqe.jobs.progress import ProgressReporter
from siqe.storage.store import get_store

log = get_logger(__name__)

PREVIEW_SIDE = 2048
THUMB_SIDE = 320


def _non_retryable(exc: AppError) -> ApplicationError:
    return ApplicationError(exc.detail, {"code": exc.code, "fix": exc.fix}, type=exc.code, non_retryable=True)


# ------------------------------------------------------------------------- prepare


def _attach_progress(
    image: pyvips.Image, state: ThreadProgress, start: float, span: float, message: str
) -> None:
    image.set_progress(True)

    def on_eval(img: pyvips.Image, progress: Any) -> None:
        try:
            state.update(start + span * progress.percent / 100, message)
        except InterruptedError:
            img.set_kill(True)

    image.signal_connect("eval", on_eval)


def _small(src: Path, side: int, limit: int | None = None) -> pyvips.Image:
    """Shrink-on-load thumbnail in the working space, as 8-bit sRGB (alpha kept)."""
    open_image(src, max_megapixels=limit)  # admission check
    thumb = pyvips.Image.thumbnail(str(src), side, size="down", export_profile="srgb")
    return from_working(to_working(thumb), depth=8)


def _prepare(src: Path, out_dir: Path, state: ThreadProgress, limit: int | None = None) -> dict[str, int]:
    staging = out_dir.with_name(out_dir.name + ".partial")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    try:
        state.update(0.05, "Making a thumbnail")
        _small(src, THUMB_SIDE, limit).write_to_file(str(staging / "thumb.webp"), Q=80, keep="none")

        state.update(0.15, "Making a preview")
        preview = _small(src, PREVIEW_SIDE, limit)
        preview.write_to_file(str(staging / "preview.webp"), Q=90, keep="none")

        full = from_working(to_working(open_image(src, max_megapixels=limit)), depth=8)
        _attach_progress(full, state, 0.25, 0.75, "Building the zoom pyramid")
        full.dzsave(str(staging / "image"), suffix=".webp[Q=82]", tile_size=510, overlap=1, keep="none")

        shutil.rmtree(out_dir, ignore_errors=True)
        staging.replace(out_dir)
        return {"preview_width": preview.width, "preview_height": preview.height}
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


@activity.defn
async def prepare_asset(job_id: str, asset_id: str, start: float = 0.0, span: float = 1.0) -> dict[str, int]:
    store = get_store()
    reporter = ProgressReporter(job_id, start=start, span=span)
    async with session_scope() as session:
        asset = await get_asset(session, uuid.UUID(asset_id))
        src = store.original(asset.sha256, asset.extension)
        out_dir = store.previews(asset.id)
        limit = megapixel_limit(asset)
    try:
        try:
            sizes = await run_threaded(lambda state: _prepare(src, out_dir, state, limit), reporter)
        except pyvips.Error as exc:
            # The header was fine at upload, but the pixels aren't: usually a file cut off by an
            # interrupted copy or download.
            log.warning("asset.unreadable", asset_id=asset_id, error=str(exc).splitlines()[-1:])
            raise AppError(
                "image.unreadable",
                "This image is damaged or incomplete, so its pixels can't be read.",
                status=422,
                fix="Copy or download the file again, then add it once more.",
            ) from exc
    except AppError as exc:
        await _mark_asset_failed(asset_id, {"code": exc.code, "message": exc.detail})
        raise _non_retryable(exc) from exc
    async with session_scope() as session:
        asset = await get_asset(session, uuid.UUID(asset_id), for_update=True)
        asset.preview_width = sizes["preview_width"]
        asset.preview_height = sizes["preview_height"]
        asset.status = AssetStatus.ready
        asset.error = None
        asset.updated_at = utcnow()
        await publish_asset(session, asset)
    return sizes


async def _mark_asset_failed(asset_id: str, error: dict[str, Any]) -> None:
    async with session_scope() as session:
        asset = await get_asset(session, uuid.UUID(asset_id), for_update=True)
        asset.status = AssetStatus.failed
        asset.error = error
        await publish_asset(session, asset)


@dataclass
class AssetFailure:
    asset_id: str
    code: str
    message: str


@activity.defn
async def mark_asset_failed(failure: AssetFailure) -> None:
    await _mark_asset_failed(failure.asset_id, {"code": failure.code, "message": failure.message})


# -------------------------------------------------------------------------- export


def _export(
    src: Path,
    edits: dict[str, Any],
    options: ExportOptions,
    out: Path,
    tmp: Path,
    state: ThreadProgress,
    limit: int | None = None,
) -> ExportResult:
    doc = parse_document(edits)
    state.update(0.02, "Rendering edits")
    work = resize_to(render_working(to_working(open_image(src, max_megapixels=limit)), doc), options.max_side)

    def progress(fraction: float) -> None:
        state.update(fraction, "Rendering edits" if fraction < 0.8 else "Encoding")

    return encode(work, options, out, tmp, progress=progress)


@activity.defn
async def export_rendition(job_id: str, rendition_id: str) -> dict[str, Any]:
    store = get_store()
    settings = get_settings()
    reporter = ProgressReporter(job_id)
    async with session_scope() as session:
        rendition = await get_rendition(session, uuid.UUID(rendition_id))
        asset = await get_asset(session, rendition.asset_id)
        src = store.original(asset.sha256, asset.extension)
        options = ExportOptions.model_validate(rendition.options)
        edits = dict(rendition.edits)
        out = store.rendition(asset.id, rendition.id, Path(rendition.filename).suffix)
        limit = megapixel_limit(asset)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = settings.data_dir / "tmp"
    try:
        result = await run_threaded(
            lambda state: _export(src, edits, options, out, tmp, state, limit), reporter
        )
    except AppError as exc:
        await _finish_rendition(rendition_id, failed=True)
        raise _non_retryable(exc) from exc
    async with session_scope() as session:
        rendition = await get_rendition(session, uuid.UUID(rendition_id))
        rendition.status = RenditionStatus.ready
        rendition.width = result.width
        rendition.height = result.height
        rendition.size_bytes = result.size_bytes
        rendition.quality = result.quality
        await publish_rendition(session, rendition)
    return {
        "width": result.width,
        "height": result.height,
        "size_bytes": result.size_bytes,
        "quality": result.quality,
    }


async def _finish_rendition(rendition_id: str, *, failed: bool) -> None:
    async with session_scope() as session:
        rendition = await get_rendition(session, uuid.UUID(rendition_id))
        rendition.status = RenditionStatus.failed if failed else RenditionStatus.ready
        await publish_rendition(session, rendition)


@activity.defn
async def mark_rendition_failed(rendition_id: str) -> None:
    await _finish_rendition(rendition_id, failed=True)
