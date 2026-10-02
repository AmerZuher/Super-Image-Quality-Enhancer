"""Reading, serialising and updating asset and rendition rows (shared by API and activities)."""

import math
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from siqe.core.config import get_settings
from siqe.core.errors import NotFoundError
from siqe.db.models import Asset, Rendition
from siqe.events.bus import publish

ASSET_EVENT = "asset.updated"
RENDITION_EVENT = "rendition.updated"
ASSET_DELETED_EVENT = "asset.deleted"
RENDITION_DELETED_EVENT = "rendition.deleted"


def asset_to_dict(asset: Asset) -> dict[str, Any]:
    base = f"/api/assets/{asset.id}"
    ready = asset.status.value == "ready"
    return {
        "id": str(asset.id),
        "original_name": asset.original_name,
        "format": asset.format,
        "width": asset.width,
        "height": asset.height,
        "bit_depth": asset.bit_depth,
        "has_alpha": asset.has_alpha,
        "size_bytes": asset.size_bytes,
        "status": asset.status.value,
        "error": asset.error,
        "exif": asset.exif,
        "has_gps": asset.has_gps,
        "preview_width": asset.preview_width,
        "preview_height": asset.preview_height,
        "edits": asset.edits or {},
        "created_at": asset.created_at.isoformat() if asset.created_at else None,
        "thumb_url": f"{base}/thumb" if ready else None,
        "preview_url": f"{base}/preview" if ready else None,
        "dzi_url": f"{base}/dz/image.dzi" if ready else None,
        "original_url": f"{base}/original",
        "parent_id": str(asset.parent_id) if asset.parent_id else None,
        "derivation": asset.derivation,
        "tags": list(asset.tags or []),
        "auto_tags": list(asset.auto_tags or []),
        "analysed": asset.analysis_version > 0,
        "sharpness": asset.sharpness,
        "faces": asset.faces,
        "color": asset.color,
        "color_hex": asset.color_hex,
        "taken_at": asset.taken_at.isoformat() if asset.taken_at else None,
        "gps": [asset.gps_lat, asset.gps_lon] if asset.gps_lat is not None else None,
        "duplicate_group": str(asset.duplicate_group) if asset.duplicate_group else None,
        "duplicate_rank": asset.duplicate_rank,
        "quarantined_at": asset.quarantined_at.isoformat() if asset.quarantined_at else None,
        "quarantine_reason": asset.quarantine_reason,
        "source": asset.source,
    }


def megapixel_limit(asset: Asset) -> int | None:
    """Admission limit for this asset's file. AI results may legitimately exceed the upload limit."""
    if asset.parent_id is None:
        return None
    return max(get_settings().max_input_megapixels, math.ceil(asset.width * asset.height / 1e6) + 1)


def rendition_to_dict(rendition: Rendition) -> dict[str, Any]:
    return {
        "id": str(rendition.id),
        "asset_id": str(rendition.asset_id),
        "job_id": str(rendition.job_id) if rendition.job_id else None,
        "status": rendition.status.value,
        "format": rendition.format,
        "filename": rendition.filename,
        "options": rendition.options,
        "width": rendition.width,
        "height": rendition.height,
        "size_bytes": rendition.size_bytes,
        "quality": rendition.quality,
        "created_at": rendition.created_at.isoformat() if rendition.created_at else None,
        "download_url": f"/api/renditions/{rendition.id}/download"
        if rendition.status.value == "ready"
        else None,
    }


async def get_asset(session: AsyncSession, asset_id: uuid.UUID, *, for_update: bool = False) -> Asset:
    stmt = select(Asset).where(Asset.id == asset_id)
    if for_update:
        stmt = stmt.with_for_update()
    asset = (await session.execute(stmt)).scalar_one_or_none()
    if asset is None:
        raise NotFoundError("asset.not_found", f"No image with id {asset_id}.", title="Image not found")
    return asset


async def get_rendition(session: AsyncSession, rendition_id: uuid.UUID) -> Rendition:
    rendition = await session.get(Rendition, rendition_id)
    if rendition is None:
        raise NotFoundError(
            "rendition.not_found", f"No export with id {rendition_id}.", title="Export not found"
        )
    return rendition


async def publish_asset(session: AsyncSession, asset: Asset) -> None:
    await session.flush()
    data = asset_to_dict(asset)
    data.pop("edits")  # edits can be large; clients refetch them when they need them
    await publish(session, ASSET_EVENT, data)


async def publish_rendition(session: AsyncSession, rendition: Rendition) -> None:
    await session.flush()
    data = rendition_to_dict(rendition)
    data.pop("options")
    await publish(session, RENDITION_EVENT, data)


async def publish_deleted(session: AsyncSession, event_type: str, record_id: uuid.UUID, **extra: str) -> None:
    await publish(session, event_type, {"id": str(record_id), **extra})
