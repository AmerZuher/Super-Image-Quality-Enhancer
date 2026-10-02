"""Running an image model over a whole image, from file to PNG, in bounded memory.

* Input tiles are read on demand from the libvips working image (sRGB float, 0..1).
* Output goes into a disk-backed array (``numpy.memmap``) in the data volume's ``tmp/``,
  so a 500-megapixel result never has to fit in RAM, and a retried run can continue it.
* Brightness-only models (SIQE Classic) run on Y; colour (Cb, Cr) is upscaled with Lanczos
  and recombined, as in the original app.
* Alpha never goes through a model: it is upscaled separately and reattached.

No torch here: the model is a ``siqe.ai.tiling.Backend``.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pyvips

from siqe.ai.tiling import Backend, Rect, TiledResult, TileSettings, run_tiled
from siqe.imaging.io import open_image
from siqe.imaging.working import Working, to_working

# Full-range BT.601, as PIL's "YCbCr" mode (what SIQE v10 was trained with). Cb/Cr centred on 0.5.
_TO_YCC = ((0.299, 0.587, 0.114), (-0.168736, -0.331264, 0.5), (0.5, -0.418688, -0.081312))


def rgb_to_ycbcr(rgb: pyvips.Image) -> tuple[pyvips.Image, pyvips.Image, pyvips.Image]:
    y = rgb.recomb([list(_TO_YCC[0])])
    cb = rgb.recomb([list(_TO_YCC[1])]) + 0.5
    cr = rgb.recomb([list(_TO_YCC[2])]) + 0.5
    return y, cb, cr


def ycbcr_to_rgb(y: pyvips.Image, cb: pyvips.Image, cr: pyvips.Image) -> pyvips.Image:
    cb = cb - 0.5
    cr = cr - 0.5
    r = y + cr * 1.402
    g = y - cb * 0.344136 - cr * 0.714136
    b = y + cb * 1.772
    return r.bandjoin([g, b])


class OutputCanvas:
    """The result image as a disk-backed H×W×C array of 8- or 16-bit samples."""

    def __init__(self, path: Path, width: int, height: int, channels: int, depth: Literal[8, 16]) -> None:
        self.path = path
        self.width = width
        self.height = height
        self.channels = channels
        self.dtype = np.uint16 if depth == 16 else np.uint8
        self.max = 65535.0 if depth == 16 else 255.0
        shape = (height, width, channels)
        expected = height * width * channels * np.dtype(self.dtype).itemsize
        mode: Literal["r+", "w+"] = "r+" if path.exists() and path.stat().st_size == expected else "w+"
        self.resumed = mode == "r+"
        self.array = np.memmap(path, dtype=self.dtype, mode=mode, shape=shape)

    def write(self, rect: Rect, tile: np.ndarray, scale: int) -> None:
        y0, x0 = rect.y * scale, rect.x * scale
        h, w = tile.shape[:2]
        self.array[y0 : y0 + h, x0 : x0 + w] = np.rint(np.clip(tile, 0, 1) * self.max).astype(self.dtype)

    def image(self) -> pyvips.Image:
        self.array.flush()
        fmt = "ushort" if self.dtype == np.uint16 else "uchar"
        return pyvips.Image.new_from_memory(self.array, self.width, self.height, self.channels, fmt)

    def close(self, *, delete: bool) -> None:
        del self.array
        if delete:
            self.path.unlink(missing_ok=True)


def save_png(rgb: pyvips.Image, work: Working, scale: int, out_png: Path) -> None:
    """Quantise a float RGB result to the source's bit depth, reattach (scaled) alpha, write PNG."""
    peak = 65535.0 if work.depth == 16 else 255.0
    fmt = "ushort" if work.depth == 16 else "uchar"
    out = (rgb.clamp(min=0.0, max=1.0) * peak).rint().cast(fmt)
    if work.alpha is not None:
        alpha = work.alpha if scale == 1 else work.alpha.resize(scale, kernel="lanczos3")
        alpha = alpha.crop(0, 0, out.width, out.height)
        out = out.bandjoin((alpha.clamp(min=0.0, max=1.0) * peak).rint().cast(fmt))
    out = out.copy(interpretation="rgb16" if work.depth == 16 else "srgb")
    staging = out_png.with_name(out_png.name + ".partial.png")
    out.pngsave(str(staging), compression=3)
    staging.replace(out_png)


def run_post_on_file(
    src: Path,
    out_png: Path,
    post: Callable[[pyvips.Image], pyvips.Image],
    *,
    max_megapixels: int | None = None,
) -> tuple[int, int]:
    """Run an image-level step (such as face restoration) at the source's own size."""
    work = to_working(open_image(src, max_megapixels=max_megapixels))
    save_png(post(work.rgb), work, 1, out_png)
    return work.width, work.height


def _region(image: pyvips.Image, r: Rect) -> np.ndarray:
    data = np.asarray(image.crop(r.x, r.y, r.w, r.h).numpy(), dtype=np.float32)
    return data.reshape(r.h, r.w, -1)


@dataclass
class RunOutput:
    path: Path
    width: int
    height: int
    tiled: TiledResult


ProgressFn = Callable[[float, str, dict[str, Any] | None], None]


def run_model_on_file(
    src: Path,
    out_png: Path,
    canvas_path: Path,
    *,
    backend: Backend,
    scale: int,
    channels: Literal["rgb", "y"],
    settings: TileSettings,
    done: set[Rect] | None = None,
    on_progress: ProgressFn = lambda f, m, d: None,
    should_stop: Callable[[], bool] = lambda: False,
    max_megapixels: int | None = None,
    post: Callable[[pyvips.Image], pyvips.Image] | None = None,
) -> RunOutput:
    """Tile ``backend`` over ``src``; ``post`` may change the float RGB result before it is saved."""
    work: Working = to_working(open_image(src, max_megapixels=max_megapixels))
    width, height = work.width, work.height
    out_w, out_h = width * scale, height * scale
    if channels == "y":
        source, cb, cr = rgb_to_ycbcr(work.rgb)
    else:
        source = work.rgb
    canvas = OutputCanvas(canvas_path, out_w, out_h, 1 if channels == "y" else 3, work.depth)
    if not canvas.resumed:
        done = set()

    def progress(fraction: float, finished: set[Rect], s: TileSettings) -> None:
        on_progress(
            0.9 * fraction,
            f"Tile {len(finished)} · {s.tile} px tiles",
            {"done": [r.as_list() for r in sorted(finished)], "tile": s.tile, "batch": s.batch},
        )

    try:
        tiled = run_tiled(
            width=width,
            height=height,
            scale=scale,
            read=lambda r: _region(source, r),
            write=lambda r, t: canvas.write(r, t, scale),
            backend=backend,
            settings=settings,
            done=done,
            on_progress=progress,
            should_stop=should_stop,
        )
        result = canvas.image().cast("float") / canvas.max
        if channels == "y":
            cb_up = cb.resize(scale, kernel="lanczos3").crop(0, 0, out_w, out_h)
            cr_up = cr.resize(scale, kernel="lanczos3").crop(0, 0, out_w, out_h)
            result = ycbcr_to_rgb(result, cb_up, cr_up)
        if post is not None:
            result = post(result)
        on_progress(0.95, "Saving the result", None)
        save_png(result, work, scale, out_png)
    except BaseException:
        canvas.close(delete=False)  # keep it so a retry can continue
        raise
    canvas.close(delete=True)
    return RunOutput(path=out_png, width=out_w, height=out_h, tiled=tiled)
