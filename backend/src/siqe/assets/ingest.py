"""Adding a staged file to the library: shared by uploads and the import folder.

The caller has already streamed the bytes into ``tmp/`` and hashed them. This checks the
header (admission), stores the original under its hash, creates the asset row and an
``asset.ingest`` job. The caller starts the job's workflow: the API with its Temporal client,
the import workflow as a child workflow.
"""

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from siqe.assets.records import publish_asset
from siqe.core.logging import get_logger
from siqe.db.models import Asset, AssetStatus, Job
from siqe.imaging.io import inspect
from siqe.jobs.start import create_job
from siqe.storage.store import StagedUpload, get_store

log = get_logger(__name__)

_SAFE_NAME = re.compile(r"[^\w.\- ()]+")
EXTENSIONS = {"jpeg": ".jpg", "png": ".png", "webp": ".webp", "heif": ".heic", "tiff": ".tif", "gif": ".gif"}


def clean_name(name: str) -> str:
    name = Path(name.replace("\\", "/")).name
    return (_SAFE_NAME.sub("_", name).strip(" .") or "image")[:200]


@dataclass
class Added:
    asset: Asset
    job: Job | None  # None when nothing needs preparing
    duplicate: bool


async def _ingest_job(session: AsyncSession, asset: Asset) -> Job:
    return await create_job(
        session,
        kind="asset.ingest",
        title=f"Prepare {asset.original_name}",
        params={"asset_id": str(asset.id)},
    )


async def _existing(session: AsyncSession, asset: Asset, staged: StagedUpload) -> Added:
    """The same bytes are already in the library. Repair the image if its files went missing."""
    store = get_store()
    if store.original(asset.sha256, asset.extension).exists():
        staged.path.unlink(missing_ok=True)
    else:
        await asyncio.to_thread(store.commit, staged, asset.extension)
        log.warning("asset.original_restored", asset_id=str(asset.id))
    previews_ok = (store.previews(asset.id) / "preview.webp").exists()
    if asset.status == AssetStatus.processing or (asset.status == AssetStatus.ready and previews_ok):
        return Added(asset, None, True)
    asset.status = AssetStatus.processing
    asset.error = None
    await publish_asset(session, asset)
    return Added(asset, await _ingest_job(session, asset), True)


async def add_file(
    session: AsyncSession, staged: StagedUpload, filename: str, *, source: dict[str, Any] | None = None
) -> Added:
    """Raises ``AppError`` (and removes the staged file) if the image can't be admitted."""
    store = get_store()
    try:
        existing = (
            await session.execute(select(Asset).where(Asset.sha256 == staged.sha256))
        ).scalar_one_or_none()
        if existing is not None:
            return await _existing(session, existing, staged)
        info = await asyncio.to_thread(inspect, staged.path)
    except BaseException:
        staged.path.unlink(missing_ok=True)
        raise

    extension = EXTENSIONS.get(info.format, ".img")
    await asyncio.to_thread(store.commit, staged, extension)
    width, height = info.oriented_size
    asset = Asset(
        sha256=staged.sha256,
        original_name=clean_name(filename),
        extension=extension,
        format=info.format,
        width=width,
        height=height,
        bit_depth=16 if info.bit_depth == 16 else 8,
        has_alpha=info.has_alpha,
        size_bytes=staged.size_bytes,
        status=AssetStatus.processing,
        exif=info.exif,
        has_gps=info.has_gps,
        gps_lat=info.gps[0] if info.gps else None,
        gps_lon=info.gps[1] if info.gps else None,
        edits={},
        source=source,
    )
    session.add(asset)
    try:
        await session.flush()
    except IntegrityError:
        # The same file finished arriving through another request a moment ago.
        await session.rollback()
        existing = (await session.execute(select(Asset).where(Asset.sha256 == staged.sha256))).scalar_one()
        return Added(existing, None, True)
    await publish_asset(session, asset)
    return Added(asset, await _ingest_job(session, asset), False)
