"""Activities for the Library: indexing, duplicate grouping, removing location, the import folder."""

import asyncio
import hashlib
import shutil
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from temporalio import activity

from siqe.assets.ingest import add_file
from siqe.assets.records import get_asset, publish_asset
from siqe.core.config import get_settings
from siqe.core.errors import AppError, NotFoundError
from siqe.core.logging import get_logger
from siqe.db.base import utcnow
from siqe.db.models import AlbumAsset, AppSetting, Asset, AssetStatus, ImportFile, ImportState
from siqe.db.session import session_scope
from siqe.events.bus import publish
from siqe.imaging.io import inspect
from siqe.imaging.metadata import remove_location
from siqe.jobs.progress import ProgressReporter
from siqe.library import embedder, faces, imports, index
from siqe.library.trigger import request_index
from siqe.storage.store import StagedUpload, get_store

log = get_logger(__name__)

LIBRARY_EVENT = "library.updated"
BATCH = 32


@activity.defn
async def index_batch(limit: int = BATCH) -> dict[str, Any]:
    """Analyse (and embed) up to ``limit`` images. Returns how many were done and remain."""
    clip_ready = embedder.installed()
    async with session_scope() as session:
        batch = await index.next_batch(session, limit, clip_ready)
    if not batch:
        return {"done": 0, "remaining": 0, "embedded": clip_ready, "new_from_folder": []}
    task = asyncio.create_task(asyncio.to_thread(index.run_batch, batch))
    while not task.done():
        activity.heartbeat({"batch": len(batch)})
        await asyncio.wait({task}, timeout=5)
    outcomes = task.result()
    async with session_scope() as session:
        await index.save(session, outcomes)
        remaining = await index.count_pending(session, clip_ready)
        await publish(
            session,
            LIBRARY_EVENT,
            {"reason": "indexed", "done": len(outcomes), "remaining": remaining},
        )
    failed = sum(1 for o in outcomes if o.error)
    if failed:
        log.warning("library.batch_failures", failed=failed, batch=len(outcomes))
    new = [str(w.id) for w in batch if w.from_folder]
    return {"done": len(outcomes), "remaining": remaining, "embedded": clip_ready, "new_from_folder": new}


@activity.defn
async def group_duplicates() -> dict[str, Any]:
    async with session_scope() as session:
        items = await index.candidates(session)
    plan = await asyncio.to_thread(index.plan_groups, items)
    async with session_scope() as session:
        groups = await index.save_groups(session, plan)
        await publish(session, LIBRARY_EVENT, {"reason": "duplicates", "groups": groups})
        # Tells the workflow whether face counting (on the GPU queue) has anything to do.
        waiting = await faces.count_pending(session) if faces.detector_ready() else 0
    return {
        "groups": groups,
        "duplicates": sum(1 for _, rank in plan.values() if rank > 0),
        "faces_pending": waiting,
    }


@activity.defn
async def start_indexing() -> None:
    """Called from other workflows (after an import, a model install) to wake the indexer."""
    await request_index(activity.client())


# ------------------------------------------------------------------ remove location


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _clean_copy(src: Path, tmp_dir: Path) -> tuple[Path, str, int]:
    """A copy of ``src`` without location, its SHA-256 and size. Pixels are untouched."""
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp = tmp_dir / f"noloc-{uuid.uuid4()}{src.suffix}"
    try:
        shutil.copyfile(src, tmp)
        remove_location(tmp)
        if inspect(tmp).has_gps:
            raise AppError(
                "library.location_not_removed",
                "This file stores its location in a way SIQE Studio can't remove without re-encoding.",
                status=422,
                fix="Export it instead: exports leave out camera data and location by default.",
            )
        return tmp, _hash(tmp), tmp.stat().st_size
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


_COPIED = (
    "original_name",
    "extension",
    "format",
    "width",
    "height",
    "bit_depth",
    "has_alpha",
    "exif",
    "preview_width",
    "preview_height",
    "edits",
    "tags",
    "auto_tags",
    "analysis_version",
    "phash",
    "dhash",
    "sharpness",
    "color",
    "color_hex",
    "taken_at",
    "embedding",
    "embedding_model",
    "source",
)


async def _replace_one(original_id: uuid.UUID) -> str:
    store = get_store()
    async with session_scope() as session:
        asset = await get_asset(session, original_id)
        await session.refresh(asset, ["embedding"])
        if not asset.has_gps or asset.quarantined_at is not None or asset.status != AssetStatus.ready:
            return "skipped"
        src = store.original(asset.sha256, asset.extension)
        values = {name: getattr(asset, name) for name in _COPIED}
    tmp, sha, size = await asyncio.to_thread(_clean_copy, src, get_settings().data_dir / "tmp")
    async with session_scope() as session:
        existing = (await session.execute(select(Asset).where(Asset.sha256 == sha))).scalar_one_or_none()
        if existing is None:
            await asyncio.to_thread(store.commit, StagedUpload(tmp, sha, size), values["extension"])
            clean = Asset(
                **values,
                sha256=sha,
                size_bytes=size,
                status=AssetStatus.ready,
                has_gps=False,
                derivation={"kind": "location_removed", "from": str(original_id)},
            )
            session.add(clean)
            await session.flush()
            await asyncio.to_thread(
                shutil.copytree, store.previews(original_id), store.previews(clean.id), dirs_exist_ok=True
            )
            albums = (
                await session.execute(select(AlbumAsset.album_id).where(AlbumAsset.asset_id == original_id))
            ).scalars()
            for album_id in albums:
                session.add(AlbumAsset(album_id=album_id, asset_id=clean.id))
            await publish_asset(session, clean)
        else:
            tmp.unlink(missing_ok=True)
        original = await get_asset(session, original_id, for_update=True)
        original.quarantined_at = utcnow()
        original.quarantine_reason = "Replaced by a copy without location"
        original.duplicate_group = None
        original.duplicate_rank = None
        await publish_asset(session, original)
    return "done"


@activity.defn
async def remove_location_batch(job_id: str, asset_ids: list[str]) -> dict[str, Any]:
    """Replace each image with a copy without location; originals go to quarantine.

    Idempotent: an image already replaced is in quarantine and is skipped on a retry.
    """
    reporter = ProgressReporter(job_id)
    done = skipped = 0
    failures: list[dict[str, str]] = []
    for position, raw in enumerate(asset_ids):
        await reporter.report(position / max(1, len(asset_ids)), f"{position} of {len(asset_ids)}")
        try:
            outcome = await _replace_one(uuid.UUID(raw))
        except NotFoundError:
            outcome = "skipped"
        except AppError as exc:
            failures.append({"asset_id": raw, "code": exc.code, "message": exc.detail})
            continue
        if outcome == "done":
            done += 1
        else:
            skipped += 1
    async with session_scope() as session:
        await publish(session, LIBRARY_EVENT, {"reason": "location", "changed": done})
    return {"done": done, "skipped": skipped, "failed": failures}


# --------------------------------------------------------------------- import folder

IMPORT_LOCK = 0x51_49_51_45  # advisory lock key: one folder scan at a time
IMPORT_STATUS_KEY = "library.import"


async def _set_import_status(**values: Any) -> None:
    async with session_scope() as session:
        row = await session.get(AppSetting, IMPORT_STATUS_KEY)
        merged = {**(row.value if row else {}), **values}
        if row is None:
            session.add(AppSetting(key=IMPORT_STATUS_KEY, value=merged))
        else:
            row.value = merged
        await publish(session, LIBRARY_EVENT, {"reason": "import"})


async def _record(path: str, size: int, mtime: float, state: ImportState, **extra: Any) -> None:
    async with session_scope() as session:
        values = {"size_bytes": size, "mtime": mtime, "state": state, "updated_at": utcnow(), **extra}
        stmt = pg_insert(ImportFile).values(path=path, **values)
        await session.execute(stmt.on_conflict_do_update(index_elements=[ImportFile.path], set_=values))


async def _import_one(root: Path, seen: imports.Seen) -> list[str] | None:
    """Stage and add one file. Returns [job id, asset id] when an ingest workflow should start."""
    settings = get_settings()
    try:
        staged = await asyncio.to_thread(
            imports.stage, root, seen.path, settings.data_dir / "tmp", settings.max_upload_mb * 1024 * 1024
        )
    except OverflowError:
        error = {"code": "upload.too_large", "message": f"Larger than the {settings.max_upload_mb} MB limit."}
        await _record(seen.path, seen.size, seen.mtime, ImportState.failed, error=error)
        return None
    except (OSError, ValueError) as exc:
        error = {"code": "import.unreadable", "message": f"Couldn't read the file: {exc}"[:300]}
        await _record(seen.path, seen.size, seen.mtime, ImportState.failed, error=error)
        return None
    try:
        async with session_scope() as session:
            source = {"kind": "folder", "path": seen.path}
            added = await add_file(session, staged, Path(seen.path).name, source=source)
            asset_id, job_id = added.asset.id, added.job.id if added.job else None
            duplicate = added.duplicate
    except AppError as exc:
        error = {"code": exc.code, "message": exc.detail}
        await _record(seen.path, seen.size, seen.mtime, ImportState.failed, error=error)
        return None
    state = ImportState.duplicate if duplicate else ImportState.imported
    await _record(seen.path, seen.size, seen.mtime, state, asset_id=asset_id, error=None)
    return [str(job_id), str(asset_id)] if job_id else None


@activity.defn
async def scan_import_folder(limit: int = 100) -> dict[str, Any]:
    """Import new, finished files from the import folder, at most ``limit`` per call."""
    settings = get_settings()
    root = settings.import_dir
    if not root.is_dir():
        await _set_import_status(available=False, last_scan=utcnow().isoformat())
        return {"started": [], "more": False, "available": False}
    async with session_scope() as lock:
        got = (await lock.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": IMPORT_LOCK})).scalar()
        if not got:
            return {"started": [], "more": False, "busy": True}
        try:
            return await _scan(root, limit)
        finally:
            await lock.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": IMPORT_LOCK})


async def _scan(root: Path, limit: int) -> dict[str, Any]:
    settings = get_settings()
    found = await asyncio.to_thread(lambda: list(imports.walk(root)))
    activity.heartbeat({"files": len(found)})
    async with session_scope() as session:
        known = {
            r.path: imports.Known(r.size_bytes, r.mtime, r.state.value)
            for r in (await session.execute(select(ImportFile))).scalars()
        }
    moment = imports.now()
    queue: list[imports.Seen] = []
    for seen in found:
        decision = imports.decide(
            seen, known.get(seen.path), now=moment, settle=settings.import_settle_seconds
        )
        if decision == "record":
            await _record(seen.path, seen.size, seen.mtime, ImportState.waiting)
        elif decision == "import":
            queue.append(seen)
    started: list[list[str]] = []
    for seen in queue[:limit]:
        activity.heartbeat({"importing": seen.path})
        try:
            get_store().ensure_space(settings, seen.size * 2)
        except AppError:
            log.warning("library.import_paused_disk_full")
            break
        pair = await _import_one(root, seen)
        if pair:
            started.append(pair)
    await _set_import_status(available=True, last_scan=utcnow().isoformat(), files=len(found))
    return {"started": started, "more": len(queue) > limit, "available": True, "imported": len(started)}
