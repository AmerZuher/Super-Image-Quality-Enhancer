"""Render an edit document onto a source image, streamed through libvips."""

from pathlib import Path

import pyvips

from siqe.imaging import ops
from siqe.imaging.edits import EditDocument, Geometry
from siqe.imaging.io import open_image
from siqe.imaging.working import Working, to_working

_ROT = {90: "d90", 180: "d180", 270: "d270"}


def apply_geometry(image: pyvips.Image, geometry: Geometry) -> pyvips.Image:
    """Rotate (clockwise), then flip, then crop in normalised coordinates of the result."""
    if geometry.rotate:
        image = image.rot(_ROT[geometry.rotate])
    if geometry.flip_h:
        image = image.fliphor()
    if geometry.flip_v:
        image = image.flipver()
    if geometry.crop is not None:
        image = image.extract_area(*crop_box(image.width, image.height, geometry))
    return image


def crop_box(width: int, height: int, geometry: Geometry) -> tuple[int, int, int, int]:
    """Pixel rectangle (left, top, width, height) for the crop, never empty or out of bounds."""
    crop = geometry.crop
    if crop is None:
        return 0, 0, width, height
    left = min(width - 1, max(0, round(crop.x * width)))
    top = min(height - 1, max(0, round(crop.y * height)))
    w = max(1, min(width - left, round(crop.w * width)))
    h = max(1, min(height - top, round(crop.h * height)))
    return left, top, w, h


def output_size(width: int, height: int, geometry: Geometry) -> tuple[int, int]:
    """Size after geometry, from the oriented source size, without touching pixels."""
    if geometry.rotate in (90, 270):
        width, height = height, width
    _, _, w, h = crop_box(width, height, geometry)
    return w, h


def render_working(work: Working, doc: EditDocument) -> Working:
    rgb = apply_geometry(work.rgb, doc.geometry)
    alpha = apply_geometry(work.alpha, doc.geometry) if work.alpha is not None else None
    active = doc.active()
    source_luma = ops.luma(rgb) if "sharpen" in active else None
    rgb = ops.apply_adjustments(rgb, active, source_luma=source_luma)
    return Working(rgb=rgb, alpha=alpha, depth=work.depth)


def render(path: Path, doc: EditDocument) -> Working:
    return render_working(to_working(open_image(path)), doc)


def resize_to(work: Working, max_side: int | None) -> Working:
    if not max_side:
        return work
    longest = max(work.width, work.height)
    if longest <= max_side:
        return work
    scale = max_side / longest
    rgb = work.rgb.resize(scale, kernel="lanczos3")
    alpha = work.alpha.resize(scale, kernel="lanczos3") if work.alpha is not None else None
    return Working(rgb=rgb, alpha=alpha, depth=work.depth)
