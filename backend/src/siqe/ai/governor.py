"""Choosing how a model runs on this machine: device, tile size and batch.

The first time a model runs on a GPU, ``siqe.ai.runtime.calibrate`` measures its peak memory
at two small tile sizes. Memory grows linearly with the number of input pixels, so two points
give a line (``Calibration``). Later runs pick the largest tile, then the largest batch, that
fits in the free memory minus ``SIQE_GPU_VRAM_RESERVE_MB``. If the estimate is wrong, the
fallback ladder in ``siqe.ai.tiling`` corrects it at run time.

Pure arithmetic; no torch import.
"""

import math
from dataclasses import asdict, dataclass
from typing import Any

from siqe.ai.tiling import MIN_TILE, TileSettings, padded_size

TILE_CANDIDATES = (1024, 768, 512, 384, 256, 192, 128)
CPU_TILE = 512
MAX_BATCH = 8


@dataclass(frozen=True)
class Calibration:
    """Peak device memory ≈ ``base_bytes + bytes_per_px × input pixels`` for batch 1."""

    base_bytes: float
    bytes_per_px: float

    def bytes_for(self, size: int, batch: int = 1) -> float:
        return self.base_bytes + self.bytes_per_px * size * size * batch

    def to_dict(self) -> dict[str, float]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "Calibration | None":
        if not data:
            return None
        try:
            return cls(base_bytes=float(data["base_bytes"]), bytes_per_px=float(data["bytes_per_px"]))
        except (KeyError, TypeError, ValueError):
            return None


def fit_calibration(samples: list[tuple[int, float]]) -> Calibration:
    """Least-squares line through (input pixels, peak bytes) samples."""
    if len(samples) < 2:
        raise ValueError("need at least two samples")
    n = len(samples)
    mean_x = sum(x for x, _ in samples) / n
    mean_y = sum(y for _, y in samples) / n
    var = sum((x - mean_x) ** 2 for x, _ in samples)
    slope = sum((x - mean_x) * (y - mean_y) for x, y in samples) / var if var else 0.0
    slope = max(slope, 1.0)
    base = max(0.0, mean_y - slope * mean_x)
    return Calibration(base_bytes=base, bytes_per_px=slope)


def clamp_tile(tile: int, width: int, height: int, multiple: int = 8) -> int:
    """No point in tiles larger than the image itself."""
    longest = math.ceil(max(width, height) / multiple) * multiple
    return max(MIN_TILE, min(tile, longest))


def choose_settings(
    calibration: Calibration | None,
    free_bytes: float,
    *,
    width: int,
    height: int,
    context: int,
    multiple: int,
    default_tile: int = 512,
) -> TileSettings:
    """Largest tile, then largest batch, that the calibration says fits in ``free_bytes``."""
    if calibration is None:
        tile = clamp_tile(default_tile, width, height, multiple)
        return TileSettings(tile=tile, batch=1, context=context, multiple=multiple)
    for candidate in TILE_CANDIDATES:
        tile = clamp_tile(candidate, width, height, multiple)
        size = padded_size(tile, context, multiple)
        if calibration.bytes_for(size) > free_bytes:
            continue
        per_tile = calibration.bytes_per_px * size * size
        tiles = math.ceil(width / tile) * math.ceil(height / tile)
        batch = int((free_bytes - calibration.base_bytes) // per_tile) if per_tile else 1
        return TileSettings(
            tile=tile, batch=max(1, min(MAX_BATCH, batch, tiles)), context=context, multiple=multiple
        )
    # Nothing fits on paper: start small and let the ladder decide (it can move to the CPU).
    return TileSettings(tile=TILE_CANDIDATES[-1], batch=1, context=context, multiple=multiple)


def cpu_settings(*, width: int, height: int, context: int, multiple: int) -> TileSettings:
    return TileSettings(
        tile=clamp_tile(CPU_TILE, width, height, multiple), batch=1, context=context, multiple=multiple
    )


def estimate_tiles(width: int, height: int, tile: int) -> int:
    return math.ceil(width / tile) * math.ceil(height / tile)
