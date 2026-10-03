"""Erase objects with LaMa: paint over them, and the background is filled in. No torch here.

The mask arrives as brush strokes in image-relative coordinates, so it fits any resolution.
Strokes close to each other form one region; each region is cut out with plenty of surrounding
context, inpainted at the model's 512 px, scaled back and blended into the original with a soft
edge. Everything else in the image is left exactly as it was.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

import numpy as np
import pyvips
from pydantic import BaseModel, Field

from siqe.core.errors import AppError
from siqe.imaging.io import open_image

SIZE = 512
MAX_REGIONS = 24
# A region's crop is this many times the size of what was painted, so the model sees the scene.
CONTEXT = 2.2
GROW = 0.35  # extra brush radius, as a share of the radius (plus 2 px)

InpaintFn = Callable[[np.ndarray, np.ndarray], np.ndarray]  # (512×512×3, 512×512) → 512×512×3, 0..1
ProgressFn = Callable[[float, str], None]


class Stroke(BaseModel):
    points: list[tuple[float, float]] = Field(min_length=1, max_length=4000)
    radius: float = Field(gt=0, le=0.5, description="Brush radius as a share of the image width.")


class Mask(BaseModel):
    strokes: list[Stroke] = Field(min_length=1, max_length=400)


@dataclass(frozen=True)
class Region:
    left: int
    top: int
    side_w: int
    side_h: int
    strokes: tuple[int, ...]


def _radius(stroke: Stroke, width: int) -> int:
    """The painted radius in pixels, grown a little past the brush so the object's own edge pixels
    never reach the model as context: given a sliver of a post at the hole's edge, LaMa continues it."""
    return max(1, round(stroke.radius * width * (1 + GROW)) + 2)


def _stroke_box(stroke: Stroke, width: int, height: int) -> tuple[float, float, float, float]:
    r = _radius(stroke, width)
    xs = [p[0] * width for p in stroke.points]
    ys = [p[1] * height for p in stroke.points]
    return min(xs) - r, min(ys) - r, max(xs) + r, max(ys) + r


def regions(mask: Mask, width: int, height: int) -> list[Region]:
    """Group strokes whose boxes touch (with some slack) and give each group a crop with context."""
    boxes = [_stroke_box(s, width, height) for s in mask.strokes]
    groups: list[list[int]] = []
    merged: list[list[float]] = []
    for i, (x0, y0, x1, y1) in enumerate(boxes):
        slack = max(x1 - x0, y1 - y0) * 0.5
        hit = None
        for g, box in enumerate(merged):
            if (
                x0 - slack <= box[2]
                and box[0] <= x1 + slack
                and y0 - slack <= box[3]
                and box[1] <= y1 + slack
            ):
                hit = g
                break
        if hit is None:
            groups.append([i])
            merged.append([x0, y0, x1, y1])
        else:
            groups[hit].append(i)
            box = merged[hit]
            merged[hit] = [min(box[0], x0), min(box[1], y0), max(box[2], x1), max(box[3], y1)]
    if len(groups) > MAX_REGIONS:
        raise AppError(
            "erase.too_many_regions",
            f"That's {len(groups)} separate areas; at most {MAX_REGIONS} can be erased at once.",
            status=422,
            fix="Erase in a few passes, or join nearby areas into one stroke.",
        )
    out = []
    for group, (x0, y0, x1, y1) in zip(groups, merged, strict=True):
        side = max(x1 - x0, y1 - y0) * CONTEXT
        side = max(side, min(SIZE, width, height))
        w, h = int(min(side, width)), int(min(side, height))
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        left = int(min(max(cx - w / 2, 0), width - w))
        top = int(min(max(cy - h / 2, 0), height - h))
        out.append(Region(left, top, w, h, tuple(group)))
    return out


def _disk(canvas: np.ndarray, cx: float, cy: float, r: int) -> None:
    h, w = canvas.shape
    x0, x1 = max(0, int(cx) - r), min(w, int(cx) + r + 1)
    y0, y1 = max(0, int(cy) - r), min(h, int(cy) + r + 1)
    if x0 >= x1 or y0 >= y1:
        return
    yy, xx = np.ogrid[y0:y1, x0:x1]
    canvas[y0:y1, x0:x1] |= ((xx - cx) ** 2 + (yy - cy) ** 2 <= r * r).astype(np.uint8) * 255


def _mask_image(mask: Mask, strokes: Sequence[int], region: Region, width: int, height: int) -> pyvips.Image:
    """The painted area inside ``region``, at the crop's resolution, 0 or 255."""
    canvas = np.zeros((region.side_h, region.side_w), np.uint8)
    for i in strokes:
        stroke = mask.strokes[i]
        r = _radius(stroke, width)
        pts = [(p[0] * width - region.left, p[1] * height - region.top) for p in stroke.points]
        _disk(canvas, *pts[0], r)
        for (ax, ay), (bx, by) in pairwise(pts):
            steps = max(1, int(np.hypot(bx - ax, by - ay) / max(1.0, r / 2)))
            for t in np.linspace(0, 1, steps + 1)[1:]:
                _disk(canvas, ax + (bx - ax) * t, ay + (by - ay) * t, r)
    return pyvips.Image.new_from_array(canvas)


def _to_square(image: pyvips.Image, kernel: str) -> pyvips.Image:
    return image.resize(SIZE / image.width, vscale=SIZE / image.height, kernel=kernel)


def inpaint_file(
    src: Path,
    out_png: Path,
    mask: Mask,
    run: InpaintFn,
    *,
    on_progress: ProgressFn = lambda f, m: None,
    max_megapixels: int | None = None,
) -> tuple[int, int]:
    """Erase the painted areas of ``src`` and save a PNG. Returns the output size."""
    image = open_image(src, max_megapixels=max_megapixels).colourspace("srgb")
    alpha = image[image.bands - 1] if image.hasalpha() else None
    rgb = (image[:3] if image.bands >= 3 else image[0].bandjoin([image[0], image[0]])).cast("uchar")
    width, height = rgb.width, rgb.height
    parts = regions(mask, width, height)
    result = rgb.copy_memory()
    for n, region in enumerate(parts):
        on_progress(n / len(parts), f"Erasing area {n + 1} of {len(parts)}")
        crop = result.crop(region.left, region.top, region.side_w, region.side_h)
        painted = _mask_image(mask, region.strokes, region, width, height)
        small = np.asarray(_to_square(crop, "linear").numpy(), np.float32) / 255
        mask_px = np.asarray(_to_square(painted, "nearest").numpy(), np.float32)
        small_mask = (mask_px if mask_px.ndim == 2 else mask_px[..., 0]) > 127
        filled = np.clip(run(small[..., :3], small_mask.astype(np.float32)), 0, 1)
        patch = pyvips.Image.new_from_array((filled * 255).round().astype(np.uint8)).copy(
            interpretation="srgb"
        )
        patch = patch.resize(region.side_w / SIZE, vscale=region.side_h / SIZE, kernel="lanczos3")
        patch = patch.crop(0, 0, region.side_w, region.side_h).cast("uchar")
        # Soft edge, two to three pixels wide at full resolution, grown slightly past the strokes.
        soft = painted.gaussblur(max(1.0, region.side_w / 600), precision="approximate") / 255 * 1.6
        soft = (soft > 1).ifthenelse(1.0, soft)
        blended = (patch * soft + crop * (1 - soft)).cast("uchar")
        result = result.insert(blended, region.left, region.top).copy_memory()
    out = result if alpha is None else result.bandjoin(alpha.cast("uchar"))
    out.copy(interpretation="srgb").pngsave(str(out_png), compression=6)
    on_progress(1.0, "Done")
    return width, height


def lama_runner(session: object) -> InpaintFn:
    """Wrap a LaMa ONNX Runtime session (inputs ``image`` and ``mask``, output in 0..255)."""

    def run(image: np.ndarray, mask: np.ndarray) -> np.ndarray:
        x = np.ascontiguousarray(image.transpose(2, 0, 1)[None], np.float32)
        m = np.ascontiguousarray(mask[None, None], np.float32)
        (out,) = session.run(None, {"image": x, "mask": m})  # type: ignore[attr-defined]
        return np.asarray(out[0], np.float32).transpose(1, 2, 0) / 255.0

    return run
