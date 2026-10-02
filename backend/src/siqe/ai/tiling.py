"""Tiled inference: any image size runs in fixed memory, without seams.

A model sees one tile at a time: the tile's *core* plus ``context`` pixels of surrounding
image on each side, reflect-padded at the image border and padded up to a fixed square size
(a multiple the model needs). Only the core of each output tile is kept, so as long as the
context covers the model's receptive field, the result equals running on the whole image.

Every tile in a batch has the same padded size, so tiles can be stacked into one forward
pass. When memory runs out, ``run_tiled`` walks the fallback ladder from docs/architecture.md
(section 5.5): free the cache and retry, halve the batch, halve the tile (splitting the tiles
still to do), then move the model to the CPU. Finished cores are never redone, which is also
how a retried activity resumes.

This module needs only numpy; the model is behind the small ``Backend`` protocol.
"""

import math
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Literal, Protocol

import numpy as np

from siqe.ai.oom import InsufficientMemoryError, is_oom_error
from siqe.core.logging import get_logger

log = get_logger(__name__)

MIN_TILE = 64


@dataclass(frozen=True, order=True)
class Rect:
    y: int
    x: int
    h: int
    w: int

    @property
    def area(self) -> int:
        return self.w * self.h

    def as_list(self) -> list[int]:
        return [self.x, self.y, self.w, self.h]

    @classmethod
    def from_list(cls, values: Iterable[int]) -> "Rect":
        x, y, w, h = (int(v) for v in values)
        return cls(y=y, x=x, h=h, w=w)


def grid(rect: Rect, tile: int) -> list[Rect]:
    """Split ``rect`` into row-major pieces no larger than ``tile`` on either side."""
    out: list[Rect] = []
    for y in range(rect.y, rect.y + rect.h, tile):
        for x in range(rect.x, rect.x + rect.w, tile):
            out.append(Rect(y=y, x=x, h=min(tile, rect.y + rect.h - y), w=min(tile, rect.x + rect.w - x)))
    return out


def plan_cores(width: int, height: int, tile: int) -> list[Rect]:
    return grid(Rect(y=0, x=0, h=height, w=width), tile)


def padded_size(tile: int, context: int, multiple: int = 1) -> int:
    """Edge length of every model input: core plus context on both sides, rounded up."""
    return math.ceil((tile + 2 * context) / multiple) * multiple


@dataclass(frozen=True)
class Window:
    """Where a core's input comes from, and how it is padded to ``size`` × ``size``."""

    core: Rect
    source: Rect  # clipped to the image
    pad: tuple[int, int, int, int]  # left, top, right, bottom

    @property
    def core_offset(self) -> tuple[int, int]:
        """(x, y) of the core inside the padded input."""
        return (self.core.x - self.source.x + self.pad[0], self.core.y - self.source.y + self.pad[1])


def window_for(core: Rect, width: int, height: int, context: int, size: int) -> Window:
    x0 = max(0, core.x - context)
    y0 = max(0, core.y - context)
    x1 = min(width, core.x + core.w + context)
    y1 = min(height, core.y + core.h + context)
    left = context - (core.x - x0)
    top = context - (core.y - y0)
    right = size - left - (x1 - x0)
    bottom = size - top - (y1 - y0)
    if right < 0 or bottom < 0:
        raise ValueError(f"core {core} with context {context} does not fit in {size} px")
    return Window(core=core, source=Rect(y=y0, x=x0, h=y1 - y0, w=x1 - x0), pad=(left, top, right, bottom))


def pad_hwc(region: np.ndarray, pad: tuple[int, int, int, int]) -> np.ndarray:
    """Reflect-pad an H×W×C region (edge-pad along an axis that is a single pixel)."""
    left, top, right, bottom = pad
    if not any(pad):
        return region
    h, w = region.shape[:2]
    out = region
    if top or bottom:
        out = np.pad(out, ((top, bottom), (0, 0), (0, 0)), mode="reflect" if h > 1 else "edge")
    if left or right:
        out = np.pad(out, ((0, 0), (left, right), (0, 0)), mode="reflect" if w > 1 else "edge")
    return out


class Backend(Protocol):
    """A loaded model. ``forward`` takes N×C×S×S float32 in 0..1 and returns N×C'×(S·k)×(S·k)."""

    device: str

    def forward(self, batch: np.ndarray) -> np.ndarray: ...

    def to_cpu(self) -> None: ...

    def release(self) -> None: ...


ReadRegion = Callable[[Rect], np.ndarray]  # H×W×C float32 in 0..1
WriteCore = Callable[[Rect, np.ndarray], None]  # input-space core rect, output H·k×W·k×C' float32


@dataclass
class LadderStep:
    kind: Literal["retry", "batch", "tile", "cpu"]
    detail: str


@dataclass
class TileSettings:
    tile: int
    batch: int
    context: int
    multiple: int = 1
    min_tile: int = MIN_TILE


@dataclass
class TiledResult:
    settings: TileSettings
    device: str
    steps: list[LadderStep] = field(default_factory=list)
    tiles_run: int = 0
    seconds: float = 0.0
    # Output samples that came back NaN or infinite (replaced: NaN → 0, ±inf → 1 / 0).
    nonfinite: int = 0


class Cancelled(Exception):
    """Raised between batches when ``should_stop`` returns true."""


def run_tiled(
    *,
    width: int,
    height: int,
    scale: int,
    read: ReadRegion,
    write: WriteCore,
    backend: Backend,
    settings: TileSettings,
    done: set[Rect] | None = None,
    on_progress: Callable[[float, set[Rect], TileSettings], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> TiledResult:
    """Run ``backend`` over the whole image in tiles. ``done`` holds cores already written."""
    s = TileSettings(**settings.__dict__)
    finished: set[Rect] = set(done or ())
    total = width * height
    done_area = sum(r.area for r in finished)
    queue = [r for r in plan_cores(width, height, s.tile) if r not in finished]
    # Cores from an earlier, larger tile plan that were finished stay finished: drop any
    # planned core that lies inside one of them.
    if finished:
        queue = [r for r in queue if not any(_inside(r, f) for f in finished)]
    result = TiledResult(settings=s, device=backend.device)
    retried = False
    start = time.perf_counter()

    while queue:
        if should_stop and should_stop():
            raise Cancelled
        size = padded_size(s.tile, s.context, s.multiple)
        cores = queue[: s.batch]
        windows = [window_for(c, width, height, s.context, size) for c in cores]
        inputs = np.stack([pad_hwc(read(w.source), w.pad).transpose(2, 0, 1) for w in windows])
        try:
            outputs = backend.forward(np.ascontiguousarray(inputs, dtype=np.float32))
        except Exception as exc:
            if not is_oom_error(exc):
                raise
            del inputs
            backend.release()
            step = _next_step(s, backend, retried)
            if step is None:
                raise InsufficientMemoryError(
                    f"Out of memory even with {s.tile} px tiles on the {backend.device}; "
                    "close other programs using the GPU or try a smaller image."
                ) from exc
            retried = step.kind == "retry"
            if step.kind == "tile":
                queue = [piece for r in queue for piece in grid(r, s.tile)]
            elif step.kind == "cpu":
                result.device = backend.device
            log.warning("tiling.fallback", kind=step.kind, detail=step.detail)
            result.steps.append(step)
            continue
        retried = False
        bad = ~np.isfinite(outputs)
        if bad.any():
            result.nonfinite += int(bad.sum())
            outputs = np.nan_to_num(outputs, nan=0.0, posinf=1.0, neginf=0.0)
        for window, out in zip(windows, outputs, strict=True):
            ox, oy = window.core_offset
            c = window.core
            core = out[:, oy * scale : (oy + c.h) * scale, ox * scale : (ox + c.w) * scale]
            write(c, core.transpose(1, 2, 0))
            finished.add(c)
            done_area += c.area
        queue = queue[len(cores) :]
        result.tiles_run += len(cores)
        if on_progress:
            on_progress(done_area / total, finished, s)

    result.seconds = time.perf_counter() - start
    return result


def _inside(inner: Rect, outer: Rect) -> bool:
    return (
        outer.x <= inner.x
        and outer.y <= inner.y
        and inner.x + inner.w <= outer.x + outer.w
        and inner.y + inner.h <= outer.y + outer.h
    )


def _next_step(s: TileSettings, backend: Backend, retried: bool) -> LadderStep | None:
    """Advance the fallback ladder one rung, mutating ``s`` (and the backend for CPU)."""
    if not retried:
        return LadderStep("retry", "freed cached memory and retried")
    if s.batch > 1:
        s.batch //= 2
        return LadderStep("batch", f"batch reduced to {s.batch}")
    if s.tile // 2 >= s.min_tile:
        s.tile //= 2
        return LadderStep("tile", f"tile reduced to {s.tile} px")
    if backend.device != "cpu":
        backend.to_cpu()
        return LadderStep("cpu", "moved to the CPU")
    return None
