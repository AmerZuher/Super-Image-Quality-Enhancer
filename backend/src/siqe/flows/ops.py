"""The image operations behind a flow's Edit blocks, from one working file to the next.

Between steps an image lives in ``tmp/flows/<run>/<item>/`` as a lossless PNG that keeps
16-bit depth and transparency, so a chain of steps never loses quality. Everything streams
through libvips, so a 100-megapixel photo costs little memory.
"""

import html
import math
from pathlib import Path
from typing import Any

import pyvips

from siqe.core.errors import AppError
from siqe.imaging.edits import EditDocument, parse_document
from siqe.imaging.io import open_image
from siqe.imaging.pipeline import render_working, resize_to
from siqe.imaging.working import Working, from_working, to_working

WATERMARK_FONT = "DejaVu Sans Bold"
# Bundled, so text renders the same in every image without system fonts (see fonts/LICENSE.txt).
WATERMARK_FONT_FILE = Path(__file__).parent / "fonts" / "DejaVuSans-Bold.ttf"


def load(path: Path, max_megapixels: int | None = None) -> Working:
    return to_working(open_image(path, max_megapixels=max_megapixels))


def save(work: Working, out: Path) -> tuple[int, int]:
    """Write a working image losslessly (PNG, depth and alpha kept), via a temporary name."""
    out.parent.mkdir(parents=True, exist_ok=True)
    staging = out.with_name(out.name + ".partial.png")
    from_working(work, depth=work.depth).pngsave(str(staging), compression=1, keep="icc")
    staging.replace(out)
    return work.width, work.height


def ratio(aspect: str) -> float:
    w, h = aspect.split(":")
    return float(w) / float(h)


def _map(work: Working, fn: Any) -> Working:
    rgb = fn(work.rgb)
    alpha = fn(work.alpha) if work.alpha is not None else None
    return Working(rgb=rgb, alpha=alpha, depth=work.depth)


def adjust(work: Working, ops: list[dict[str, Any]]) -> Working:
    return render_working(work, EditDocument.model_validate({"ops": ops}))


def studio_edits(work: Working, edits: dict[str, Any]) -> Working:
    return render_working(work, parse_document(edits))


def resize(work: Working, mode: str, size: int, upscale: bool) -> Working:
    current = {"longest": max(work.width, work.height), "width": work.width, "height": work.height}[mode]
    if current == size or (current < size and not upscale):
        return work
    if mode == "longest" and not upscale:
        return resize_to(work, size)
    scale = size / current
    return _map(work, lambda im: im.resize(scale, kernel="lanczos3"))


def crop(work: Working, aspect: str, focus: str) -> Working:
    target = ratio(aspect)
    if work.width / work.height > target:
        w, h = max(1, round(work.height * target)), work.height
    else:
        w, h = work.width, max(1, round(work.width / target))
    if (w, h) == (work.width, work.height):
        return work
    if focus == "centre":
        left, top = (work.width - w) // 2, (work.height - h) // 2
    else:
        # Find the most interesting window on a small copy, then crop the full image.
        preview = from_working(work, depth=8, keep_alpha=False)
        shrink = min(1.0, 1024 / max(work.width, work.height))
        small = preview.resize(shrink) if shrink < 1 else preview
        sw, sh = max(1, round(w * shrink)), max(1, round(h * shrink))
        sw, sh = min(sw, small.width), min(sh, small.height)
        _, extra = small.smartcrop(sw, sh, interesting=focus, attention_x=True, attention_y=True)
        # attention_x/y is the centre of interest; fall back to the window's position for entropy.
        cx = extra.get("attention_x", small.width / 2) / shrink
        cy = extra.get("attention_y", small.height / 2) / shrink
        left = int(min(max(0, round(cx - w / 2)), work.width - w))
        top = int(min(max(0, round(cy - h / 2)), work.height - h))
    return _map(work, lambda im: im.extract_area(left, top, w, h))


def rotate(work: Working, angle: str, flip: str) -> Working:
    turns = {"0": None, "90": "d90", "180": "d180", "270": "d270"}[angle]
    if turns:
        work = _map(work, lambda im: im.rot(turns))
    if flip == "horizontal":
        work = _map(work, lambda im: im.fliphor())
    elif flip == "vertical":
        work = _map(work, lambda im: im.flipver())
    return work


def trim(work: Working, margin: int) -> Working:
    """Crop away transparent borders, or else borders matching the corner colour."""
    if work.alpha is not None:
        mask = (work.alpha * 255).cast("uchar")
        left, top, w, h = mask.find_trim(threshold=8, background=[0])
    else:
        rgb8 = (work.rgb * 255).cast("uchar")
        corner = rgb8.getpoint(0, 0)
        left, top, w, h = rgb8.find_trim(threshold=12, background=corner)
    if w <= 0 or h <= 0:
        return work
    left, top = max(0, left - margin), max(0, top - margin)
    w, h = min(work.width - left, w + 2 * margin), min(work.height - top, h + 2 * margin)
    return _map(work, lambda im: im.extract_area(left, top, w, h))


def _rgb(color: str) -> list[float]:
    return [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]


def canvas(work: Working, aspect: str, color: str, padding: int) -> Working:
    """Centre the image on a canvas of ``aspect``, leaving ``padding`` percent around it."""
    target = ratio(aspect)
    inner = 1 - 2 * padding / 100
    width = max(work.width, round(work.height * target)) / inner
    height = width / target
    if height * inner < work.height:
        height = work.height / inner
        width = height * target
    cw, ch = math.ceil(width), math.ceil(height)
    left, top = (cw - work.width) // 2, (ch - work.height) // 2
    alpha = work.alpha if work.alpha is not None else pyvips.Image.black(work.width, work.height) + 1.0
    if color == "transparent":
        rgb = work.rgb.embed(left, top, cw, ch, extend="black")
        a = alpha.embed(left, top, cw, ch, extend="black")
        return Working(rgb=rgb, alpha=a, depth=work.depth)
    background = pyvips.Image.black(cw, ch, bands=3) + _rgb(color)
    placed = work.rgb.embed(left, top, cw, ch, extend="black")
    a = alpha.embed(left, top, cw, ch, extend="black")
    rgb = placed * a + background * (a * -1 + 1)
    return Working(rgb=rgb.cast("float"), alpha=None, depth=work.depth)


def watermark(work: Working, text: str, position: str, size: float, opacity: int, color: str) -> Working:
    if not text.strip():
        return work
    height = max(8, round(min(work.width, work.height) * size / 100))
    label = pyvips.Image.text(
        html.escape(text, quote=False),  # the text is Pango markup
        font=f"{WATERMARK_FONT} {height}",
        fontfile=str(WATERMARK_FONT_FILE),
        rgba=False,
        dpi=72,
    )
    if label.width == 0 or label.height == 0:
        return work
    if label.width > work.width * 0.9:  # keep long text inside the image
        label = label.resize(work.width * 0.9 / label.width)
    alpha = (label.cast("float") / 255) * (opacity / 100)
    margin = round(height * 0.6)
    vertical, horizontal = position.split("-")
    x = {
        "left": margin,
        "centre": (work.width - label.width) // 2,
        "right": work.width - label.width - margin,
    }[horizontal]
    y = {
        "top": margin,
        "middle": (work.height - label.height) // 2,
        "bottom": work.height - label.height - margin,
    }[vertical]
    x, y = max(0, x), max(0, y)
    a = alpha.embed(x, y, work.width, work.height, extend="black")
    ink = pyvips.Image.black(work.width, work.height, bands=3) + _rgb(color)
    rgb = work.rgb * (a * -1 + 1) + ink * a
    return Working(rgb=rgb.cast("float"), alpha=work.alpha, depth=work.depth)


def apply(
    node_type: str, params: dict[str, Any], work: Working, *, edits: dict[str, Any] | None = None
) -> Working:
    if node_type == "adjust":
        return adjust(work, params["ops"])
    if node_type == "studio_edits":
        return studio_edits(work, edits or {})
    if node_type == "resize":
        return resize(work, params["mode"], params["size"], params["upscale"])
    if node_type == "crop":
        return crop(work, params["aspect"], params["focus"])
    if node_type == "rotate":
        return rotate(work, params["angle"], params["flip"])
    if node_type == "trim":
        return trim(work, params["margin"])
    if node_type == "canvas":
        return canvas(work, params["aspect"], params["color"], params["padding"])
    if node_type == "watermark":
        return watermark(
            work, params["text"], params["position"], params["size"], params["opacity"], params["color"]
        )
    raise AppError("flow.unknown_step", f"No image operation called {node_type}.", status=422)


def run_step(
    node_type: str,
    params: dict[str, Any],
    src: Path,
    out: Path,
    *,
    edits: dict[str, Any] | None = None,
    max_megapixels: int | None = None,
) -> tuple[int, int]:
    """Blocking: one edit step from file to file. Returns the new size."""
    return save(apply(node_type, params, load(src, max_megapixels), edits=edits), out)
