"""Forge datasets: high-resolution crops cut from Library images.

A dataset keeps only clean crops (lossless PNG); the damaged low-resolution inputs are made
fresh for every training step by ``siqe.forge.degrade``, so one dataset serves models of any
scale and the damage never repeats. Every tenth usable image goes to the validation set, so
scores are measured on photos the model never trained on.
"""

import shutil
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pyvips
from pydantic import BaseModel, Field

from siqe.core.config import get_settings
from siqe.forge.degrade import Degradation, pair
from siqe.imaging.io import open_image
from siqe.imaging.working import from_working, to_working

# Big photos are shrunk to this many megapixels before cropping, which keeps memory bounded
# and still leaves real detail in every crop.
WORKING_MEGAPIXELS = 24
MAX_VAL_CROPS = 64


class DatasetSettings(BaseModel):
    crop: int = Field(
        default=256, ge=64, le=1024, description="Side of each high-resolution crop, in pixels."
    )
    crops_per_image: int = Field(default=8, ge=1, le=64)
    min_width: int = Field(default=600, ge=64, le=20_000, description="Smaller images are skipped.")
    min_height: int = Field(default=300, ge=64, le=20_000)
    val_every: int = Field(
        default=10, ge=2, le=100, description="One image in this many is kept for validation."
    )
    max_images: int = Field(default=2000, ge=1, le=20_000)


@dataclass
class Built:
    images: int = 0
    skipped: int = 0
    train: int = 0
    val: int = 0
    size_bytes: int = 0
    reasons: dict[str, int] = field(default_factory=dict)


def root(dataset_id: uuid.UUID | str) -> Path:
    return get_settings().data_dir / "datasets" / str(dataset_id)


def crops(dataset_id: uuid.UUID | str, split: str) -> list[Path]:
    folder = root(dataset_id) / split
    return sorted(folder.glob("*.png")) if folder.is_dir() else []


def _rgb8(image: pyvips.Image) -> pyvips.Image:
    """8-bit sRGB with the orientation applied and transparency on white, like an export."""
    return from_working(to_working(image), depth=8, keep_alpha=False)


def add_image(
    path: Path,
    name: str,
    split: str,
    out: Path,
    settings: DatasetSettings,
    rng: np.random.Generator,
    limit: int,
) -> tuple[int, int, str | None]:
    """Cut crops from one image. Returns (crops written, bytes, reason skipped)."""
    image = _rgb8(open_image(path, max_megapixels=get_settings().max_input_megapixels))
    if image.width < settings.min_width or image.height < settings.min_height:
        return 0, 0, "too small"
    megapixels = image.width * image.height / 1e6
    if megapixels > WORKING_MEGAPIXELS:
        image = image.resize((WORKING_MEGAPIXELS / megapixels) ** 0.5, kernel="lanczos3")
    if image.width < settings.crop or image.height < settings.crop:
        return 0, 0, "smaller than one crop"
    pixels = np.asarray(image.numpy(), np.uint8).reshape(image.height, image.width, 3)
    count = min(limit, settings.crops_per_image if split == "train" else 2)
    written, size = 0, 0
    for index in range(count):
        top = int(rng.integers(0, pixels.shape[0] - settings.crop + 1))
        left = int(rng.integers(0, pixels.shape[1] - settings.crop + 1))
        crop = np.ascontiguousarray(pixels[top : top + settings.crop, left : left + settings.crop])
        if crop.std() < 2.0:
            continue  # flat sky or a blank wall teaches nothing
        target = out / split / f"{name}-{index}.png"
        staging = target.with_suffix(".partial.png")
        pyvips.Image.new_from_memory(crop, settings.crop, settings.crop, 3, "uchar").pngsave(
            str(staging), compression=3, keep="none"
        )
        staging.replace(target)
        written += 1
        size += target.stat().st_size
    return written, size, None


def build(
    dataset_id: uuid.UUID,
    images: list[tuple[uuid.UUID, Path]],
    settings: DatasetSettings,
    progress: Callable[[int, int], None] = lambda done, total: None,
) -> Built:
    """Blocking: (re)build a dataset from the given images. Safe to repeat after a crash."""
    out = root(dataset_id)
    shutil.rmtree(out, ignore_errors=True)
    for split in ("train", "val"):
        (out / split).mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(uuid.UUID(str(dataset_id)).int % 2**32)
    built = Built()
    usable = 0
    for index, (asset_id, path) in enumerate(images[: settings.max_images]):
        progress(index, len(images))
        split = "val" if usable % settings.val_every == settings.val_every - 1 else "train"
        if split == "val" and built.val >= MAX_VAL_CROPS:
            split = "train"
        try:
            written, size, reason = add_image(
                path,
                asset_id.hex[:12],
                split,
                out,
                settings,
                rng,
                MAX_VAL_CROPS - built.val if split == "val" else 64,
            )
        except Exception:
            written, size, reason = 0, 0, "couldn't be read"
        if reason or not written:
            built.skipped += 1
            key = reason or "no detail"
            built.reasons[key] = built.reasons.get(key, 0) + 1
            continue
        usable += 1
        built.images += 1
        built.size_bytes += size
        if split == "val":
            built.val += written
        else:
            built.train += written
    progress(len(images), len(images))
    return built


def preview(
    dataset_id: uuid.UUID | str, scale: int, degradation: Degradation, *, count: int = 4, seed: int = 0
) -> bytes:
    """Blocking: a PNG grid; each row is a damaged input (enlarged, nearest) beside its clean crop."""
    files = crops(dataset_id, "train") or crops(dataset_id, "val")
    if not files:
        raise FileNotFoundError("the dataset has no crops yet")
    rng = np.random.default_rng(seed)
    rows = []
    for path in rng.choice(np.array(files, dtype=object), size=min(count, len(files)), replace=False):
        clean = np.asarray(pyvips.Image.new_from_file(str(path)).numpy(), np.uint8)
        patch = min(clean.shape[0], clean.shape[1]) // scale
        hr, lr = pair(clean, patch, scale, degradation, rng)
        big = np.repeat(np.repeat(lr, scale, 0), scale, 1)
        gap = np.full((hr.shape[0], 8, 3), 18, np.uint8)
        rows.append(np.concatenate([big, gap, hr], 1))
        rows.append(np.full((8, rows[-1].shape[1], 3), 18, np.uint8))
    grid = np.ascontiguousarray(np.concatenate(rows[:-1], 0))
    image = pyvips.Image.new_from_memory(grid, grid.shape[1], grid.shape[0], 3, "uchar")
    return bytes(image.pngsave_buffer(compression=3))
