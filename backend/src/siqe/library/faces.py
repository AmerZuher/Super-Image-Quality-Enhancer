"""Counting the faces in Library images, so you can filter for photos with (or without) people.

The count comes from RetinaFace, the detector that ships with the face restoration model
(GFPGAN v1.4, MIT), run on each image's preview on the GPU queue. Nothing about the faces is
kept, only how many there are: no crops, no identities.

``Asset.faces`` is NULL until an image is counted, and -1 if its preview couldn't be read.
"""

import uuid
from collections.abc import Callable
from pathlib import Path

import numpy as np
from sqlalchemy import ColumnElement, and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from siqe.ai.manifest import FACE_MODEL_ID
from siqe.ai.oom import run_with_halving
from siqe.ai.registry import files_present, get_spec
from siqe.db.models import Asset, AssetStatus
from siqe.imaging.io import open_image
from siqe.storage.store import get_store

DETECT_SIDE = 1280
# Faces smaller than this, in pixels at the detection size, are background crowd and ignored.
MIN_FACE = 20
BATCH = 24
UNREADABLE = -1

Detect = Callable[[np.ndarray], list[tuple[float, np.ndarray, np.ndarray]]]


def detector_ready() -> bool:
    return files_present(get_spec(FACE_MODEL_ID))


def pending_clause() -> ColumnElement[bool]:
    return and_(
        Asset.status == AssetStatus.ready,
        Asset.faces.is_(None),
        Asset.quarantined_at.is_(None),
        Asset.preview_width.is_not(None),
    )


async def count_pending(session: AsyncSession) -> int:
    return int((await session.execute(select(func.count()).where(pending_clause()))).scalar_one())


async def next_batch(session: AsyncSession, limit: int = BATCH) -> list[tuple[uuid.UUID, Path]]:
    store = get_store()
    ids = (
        await session.execute(
            select(Asset.id).where(pending_clause()).order_by(Asset.created_at).limit(limit)
        )
    ).scalars()
    return [(i, store.previews(i) / "preview.webp") for i in ids]


def count(detect: Detect, preview: Path) -> int:
    """Faces in one preview. Blocking; halves the detection size if the GPU runs out of memory."""
    image = open_image(preview)
    if image.hasalpha():
        image = image.flatten(background=[255, 255, 255])
    image = image.colourspace("srgb").extract_band(0, n=3).cast("uchar")

    def at(side: int) -> int:
        scale = min(1.0, side / max(image.width, image.height))
        small = image.resize(scale) if scale < 1 else image
        pixels = np.asarray(small.numpy(), np.uint8).reshape(small.height, small.width, 3)
        found = detect(pixels)
        smallest = MIN_FACE * (small.width / min(image.width, DETECT_SIDE))
        return sum(1 for _, box, _ in found if min(box[2] - box[0], box[3] - box[1]) >= smallest)

    faces, _ = run_with_halving(at, DETECT_SIDE, minimum=320)
    return faces


async def save(session: AsyncSession, counts: dict[uuid.UUID, int]) -> None:
    for asset_id, n in counts.items():
        await session.execute(update(Asset).where(Asset.id == asset_id).values(faces=n))
    await session.commit()
