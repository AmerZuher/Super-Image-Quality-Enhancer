"""Per-image measurements for the Library: perceptual hashes, sharpness, colour and metadata.

Everything here reads the 2,048 px preview SIQE Studio made at import, never the original, so
analysing a 100-megapixel photo costs the same as a small one.
"""

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Any

import numpy as np
import pyvips

ANALYSIS_VERSION = 1
SHARPNESS_SIDE = 768
# Variance of the Laplacian at SHARPNESS_SIDE that maps to a sharpness of about 0.63.
SHARPNESS_SCALE = 300.0

COLOURS = ("red", "orange", "yellow", "green", "teal", "blue", "purple", "pink")
# Hue (degrees) where each colour's range starts; red wraps around 345.
_HUE_STARTS = (345, 15, 45, 70, 160, 195, 255, 290)


@dataclass(frozen=True)
class Analysis:
    phash: int
    dhash: int
    sharpness: float
    color: str
    color_hex: str


def _signed(bits: np.ndarray) -> int:
    """64 booleans → a signed 64-bit integer (PostgreSQL BIGINT)."""
    value = 0
    for bit in bits.ravel():
        value = (value << 1) | int(bool(bit))
    return value - (1 << 64) if value >= 1 << 63 else value


def hamming(a: int, b: int) -> int:
    return ((a ^ b) & ((1 << 64) - 1)).bit_count()


@cache
def _dct_matrix(n: int) -> np.ndarray:
    k = np.arange(n)[:, None]
    i = np.arange(n)[None, :]
    m = np.cos(np.pi * (2 * i + 1) * k / (2 * n)) * math.sqrt(2 / n)
    m[0] /= math.sqrt(2)
    return m


def phash(gray32: np.ndarray) -> int:
    """DCT hash of a 32 × 32 grayscale image: the 8 × 8 lowest frequencies against their median."""
    d = _dct_matrix(32)
    freq = d @ gray32.astype(np.float64) @ d.T
    low = freq[:8, :8].ravel()
    return _signed(low > np.median(low[1:]))


def dhash(gray9x8: np.ndarray) -> int:
    """Gradient hash of a 9 × 8 (width × height) grayscale image."""
    g = gray9x8.astype(np.int16)
    return _signed(g[:, 1:] > g[:, :-1])


def sharpness(gray: np.ndarray) -> float:
    """0 (blurred) to 1 (crisp) from the variance of the Laplacian, measured at a fixed size."""
    g = gray.astype(np.float32)
    lap = -4 * g[1:-1, 1:-1] + g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:]
    return float(1 - math.exp(-float(lap.var()) / SHARPNESS_SCALE))


def dominant_colour(rgb: np.ndarray) -> tuple[str, str]:
    """The main colour family of a small RGB image, and its average colour as hex."""
    px = rgb.reshape(-1, 3).astype(np.float32) / 255
    mx, mn = px.max(1), px.min(1)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0)
    vivid = (sat > 0.25) & (mx > 0.2)
    if vivid.mean() < 0.12:
        mean = px.mean(0)
        return "neutral", _hex(mean)
    r, g, b = px[vivid].T
    delta = np.maximum(mx[vivid] - mn[vivid], 1e-6)
    hue = (
        np.where(
            mx[vivid] == r,
            ((g - b) / delta) % 6,
            np.where(mx[vivid] == g, (b - r) / delta + 2, (r - g) / delta + 4),
        )
        * 60
    )
    bins = np.zeros(len(COLOURS))
    weights = sat[vivid]
    for index, start in enumerate(_HUE_STARTS):
        end = _HUE_STARTS[(index + 1) % len(_HUE_STARTS)]
        inside = (hue >= start) | (hue < end) if start > end else (hue >= start) & (hue < end)
        bins[index] = weights[inside].sum()
    best = int(bins.argmax())
    start, end = _HUE_STARTS[best], _HUE_STARTS[(best + 1) % len(_HUE_STARTS)]
    inside = (hue >= start) | (hue < end) if start > end else (hue >= start) & (hue < end)
    return COLOURS[best], _hex(px[vivid][inside].mean(0))


def _hex(rgb: np.ndarray) -> str:
    r, g, b = (round(float(c) * 255) for c in np.clip(rgb, 0, 1))
    return f"#{r:02x}{g:02x}{b:02x}"


def _flatten(image: pyvips.Image) -> pyvips.Image:
    if image.hasalpha():
        image = image.flatten(background=[255, 255, 255])
    if image.bands == 1:
        image = image.bandjoin([image, image])
    return image.cast("uchar")


def analyse(preview: Path) -> Analysis:
    """Measure one image from its preview file."""
    base = _flatten(pyvips.Image.new_from_file(str(preview), access="sequential"))
    base = base.copy_memory()
    gray = base.colourspace("b-w")[0]
    g32 = gray.resize(32 / gray.width, vscale=32 / gray.height, kernel="linear").numpy()
    g98 = gray.resize(9 / gray.width, vscale=8 / gray.height, kernel="linear").numpy()
    side = max(base.width, base.height)
    sharp_src = gray.resize(SHARPNESS_SIDE / side) if side > SHARPNESS_SIDE else gray
    small = base.resize(64 / side) if side > 64 else base
    colour, color_hex = dominant_colour(np.asarray(small.numpy())[..., :3])
    return Analysis(
        phash=phash(np.asarray(g32).reshape(32, 32)),
        dhash=dhash(np.asarray(g98).reshape(8, 9)),
        sharpness=round(sharpness(np.asarray(sharp_src.numpy())), 4),
        color=colour,
        color_hex=color_hex,
    )


def clip_pixels(preview: Path, size: int = 224) -> np.ndarray:
    """The preview resized and centre-cropped to ``size`` square, as float RGB 0..1."""
    image = pyvips.Image.thumbnail(str(preview), size, height=size, crop="centre", size="both")
    image = _flatten(image)
    if image.width != size or image.height != size:  # very thin images
        image = image.gravity("centre", size, size, extend="copy")
    return np.asarray(image.numpy(), np.float32)[..., :3] / 255


# ------------------------------------------------------------------------- metadata


def taken_at(exif: dict[str, Any]) -> datetime | None:
    """EXIF DateTimeOriginal ("2024:06:01 18:22:05") as a UTC-naive-as-UTC datetime."""
    raw = str(exif.get("taken_at") or "").strip()
    try:
        return datetime.strptime(raw[:19], "%Y:%m:%d %H:%M:%S").replace(tzinfo=UTC)
    except ValueError:
        return None
