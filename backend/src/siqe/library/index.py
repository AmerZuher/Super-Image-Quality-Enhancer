"""Keeping the Library's analysis current: which images need work, doing it, saving it.

Indexing runs in small batches in the background (``LibraryIndexWorkflow``). Each batch
analyses images that are new or were analysed by an older version, and, once CLIP is
installed, adds their embedding and automatic tags. Duplicate groups are recomputed after
the last batch.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import ColumnElement, and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from siqe.ai.manifest import CLIP_MODEL_ID
from siqe.core.logging import get_logger
from siqe.db.models import Asset, AssetStatus
from siqe.imaging.io import inspect
from siqe.library import duplicates, embedder
from siqe.library.analysis import ANALYSIS_VERSION, analyse, clip_pixels, taken_at
from siqe.storage.store import get_store

log = get_logger(__name__)


def pending_clause(clip_ready: bool) -> ColumnElement[bool]:
    stale = Asset.analysis_version < ANALYSIS_VERSION
    if clip_ready:
        stale = or_(stale, Asset.embedding_model.is_distinct_from(CLIP_MODEL_ID))
    return and_(Asset.status == AssetStatus.ready, stale)


async def count_pending(session: AsyncSession, clip_ready: bool) -> int:
    return int(
        (
            await session.execute(select(func.count()).select_from(Asset).where(pending_clause(clip_ready)))
        ).scalar_one()
    )


@dataclass
class Work:
    id: uuid.UUID
    preview: Path
    original: Path
    exif: dict[str, Any]
    has_gps: bool
    needs_gps: bool
    needs_analysis: bool
    needs_embedding: bool
    # Analysed for the first time and imported from the folder: flows may be watching for it.
    from_folder: bool = False


@dataclass
class Outcome:
    id: uuid.UUID
    values: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


async def next_batch(session: AsyncSession, limit: int, clip_ready: bool) -> list[Work]:
    store = get_store()
    rows = (
        await session.execute(
            select(Asset).where(pending_clause(clip_ready)).order_by(Asset.created_at.desc()).limit(limit)
        )
    ).scalars()
    return [
        Work(
            id=a.id,
            preview=store.previews(a.id) / "preview.webp",
            original=store.original(a.sha256, a.extension),
            exif=dict(a.exif or {}),
            has_gps=a.has_gps,
            needs_gps=a.has_gps and a.gps_lat is None,
            needs_analysis=a.analysis_version < ANALYSIS_VERSION,
            from_folder=a.analysis_version == 0 and (a.source or {}).get("kind") == "folder",
            needs_embedding=clip_ready and a.embedding_model != CLIP_MODEL_ID,
        )
        for a in rows
    ]


def run_batch(batch: list[Work]) -> list[Outcome]:
    """Blocking: analyse, embed and tag a batch. Runs in a worker thread."""
    outcomes: list[Outcome] = []
    to_embed: list[tuple[int, np.ndarray]] = []
    for item in batch:
        out = Outcome(item.id)
        outcomes.append(out)
        if not item.preview.is_file():
            out.error = "preview missing"
            out.values["analysis_version"] = ANALYSIS_VERSION
            if item.needs_embedding:
                out.values["embedding_model"] = CLIP_MODEL_ID
            continue
        try:
            if item.needs_analysis:
                a = analyse(item.preview)
                out.values.update(
                    phash=a.phash,
                    dhash=a.dhash,
                    sharpness=a.sharpness,
                    color=a.color,
                    color_hex=a.color_hex,
                    taken_at=taken_at(item.exif),
                    analysis_version=ANALYSIS_VERSION,
                )
                if item.needs_gps and item.original.is_file():
                    gps = inspect(item.original).gps
                    if gps:
                        out.values.update(gps_lat=gps[0], gps_lon=gps[1])
            if item.needs_embedding:
                to_embed.append((len(outcomes) - 1, clip_pixels(item.preview)))
        except Exception as exc:  # one bad image must not stop the batch
            log.warning("library.analysis_failed", asset_id=str(item.id), error=str(exc))
            out.error = str(exc)[:200]
            out.values["analysis_version"] = ANALYSIS_VERSION
            if item.needs_embedding:
                out.values["embedding_model"] = CLIP_MODEL_ID
    if to_embed:
        vectors = embedder.encode_images(np.stack([p for _, p in to_embed]))
        tags = embedder.tags_for(vectors)
        for (index, _), vector, chosen in zip(to_embed, vectors, tags, strict=True):
            outcomes[index].values.update(
                embedding=vector.astype(np.float32), embedding_model=CLIP_MODEL_ID, auto_tags=chosen
            )
    return outcomes


async def save(session: AsyncSession, outcomes: list[Outcome]) -> None:
    for out in outcomes:
        if out.values:
            await session.execute(update(Asset).where(Asset.id == out.id).values(**out.values))


# ---------------------------------------------------------------------- duplicates


async def candidates(session: AsyncSession) -> list[duplicates.Candidate]:
    rows = await session.execute(
        select(
            Asset.id,
            Asset.phash,
            Asset.dhash,
            Asset.embedding,
            Asset.width,
            Asset.height,
            Asset.sharpness,
            Asset.size_bytes,
            Asset.format,
            Asset.created_at,
            Asset.duplicate_ok,
        ).where(
            Asset.status == AssetStatus.ready,
            Asset.quarantined_at.is_(None),
            Asset.parent_id.is_(None),
            Asset.phash.is_not(None),
            Asset.dhash.is_not(None),
        )
    )
    out: list[duplicates.Candidate] = []
    for r in rows:
        created: datetime = r.created_at
        out.append(
            duplicates.Candidate(
                id=str(r.id),
                phash=int(r.phash),
                dhash=int(r.dhash),
                embedding=None if r.embedding is None else np.asarray(r.embedding, np.float32),
                width=r.width,
                height=r.height,
                sharpness=float(r.sharpness or 0.0),
                size_bytes=int(r.size_bytes),
                format=r.format,
                created=created.timestamp(),
                ok=bool(r.duplicate_ok),
            )
        )
    return out


def plan_groups(items: list[duplicates.Candidate]) -> dict[str, tuple[str, int]]:
    """asset id → (group id, rank). The group id is the id of the copy to keep, so it is stable."""
    plan: dict[str, tuple[str, int]] = {}
    for members in duplicates.groups(items):
        group = [items[i] for i in members]
        order = duplicates.rank(group)
        keep = group[order[0]].id
        for rank, index in enumerate(order):
            plan[group[index].id] = (keep, rank)
    return plan


async def save_groups(session: AsyncSession, plan: dict[str, tuple[str, int]]) -> int:
    await session.execute(
        update(Asset)
        .where(Asset.duplicate_group.is_not(None))
        .values(duplicate_group=None, duplicate_rank=None)
    )
    for asset_id, (group, rank) in plan.items():
        await session.execute(
            update(Asset)
            .where(Asset.id == uuid.UUID(asset_id))
            .values(duplicate_group=uuid.UUID(group), duplicate_rank=rank)
        )
    return len({g for g, _ in plan.values()})
