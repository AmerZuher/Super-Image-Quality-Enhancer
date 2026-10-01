"""Encoding renders to files, with format limits, disk checks and target file sizes.

Rendering happens once into an uncompressed temporary file; encoding (possibly several
times, when searching for a target size) reads from that file, so the edit pipeline never
runs twice and memory stays bounded however large the image is.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pyvips
from pydantic import BaseModel, Field, model_validator

from siqe.core.errors import AppError
from siqe.imaging.formats import OUTPUT_FORMATS, OutputFormat
from siqe.imaging.working import Working, from_working
from siqe.system.resources import disk_info

ProgressFn = Callable[[float], None]


class ExportOptions(BaseModel):
    format: OutputFormat = "jpeg"
    quality: int = Field(default=90, ge=1, le=100)
    max_side: int | None = Field(default=None, ge=16, le=200_000)
    target_kb: int | None = Field(default=None, ge=10, le=2_000_000)
    strip_metadata: bool = True

    @model_validator(mode="after")
    def _target_needs_lossy(self) -> "ExportOptions":
        if self.target_kb is not None and not OUTPUT_FORMATS[self.format].lossy:
            raise ValueError(f"a target file size needs a lossy format; {self.format.upper()} is lossless")
        return self


@dataclass(frozen=True)
class ExportResult:
    path: Path
    width: int
    height: int
    size_bytes: int
    quality: int | None


def planned_size(width: int, height: int, max_side: int | None) -> tuple[int, int]:
    longest = max(width, height)
    if max_side and longest > max_side:
        scale = max_side / longest
        return max(1, round(width * scale)), max(1, round(height * scale))
    return width, height


def check_dimensions(width: int, height: int, options: ExportOptions) -> None:
    spec = OUTPUT_FORMATS[options.format]
    if max(width, height) > spec.max_side:
        raise AppError(
            "format.dimension_limit",
            f"{spec.label} can't store an image of {width} × {height}; "
            f"its limit is {spec.max_side:,} px per side.",
            status=422,
            title="Too large for this format",
            fix=f"Choose PNG or TIFF, or set a maximum size of {spec.max_side:,} px or less.",
            width=width,
            height=height,
            format_limit=spec.max_side,
        )


def check_disk(
    directory: Path, width: int, height: int, bands: int, depth: int, min_free_ratio: float
) -> None:
    """Need room for the uncompressed temporary render plus the output (assumed same size)."""
    needed = width * height * bands * (2 if depth == 16 else 1) * 2
    info = disk_info(directory)
    if info.free_bytes - needed < info.total_bytes * min_free_ratio:
        raise AppError(
            "disk.insufficient_space",
            f"Exporting needs about {needed / 1e9:.1f} GB of free disk; "
            f"only {info.free_bytes / 1e9:.1f} GB is free.",
            status=507,
            title="Not enough disk space",
            fix="Free some disk space or export at a smaller maximum size.",
        )


def _save_kwargs(fmt: OutputFormat, quality: int, strip: bool) -> dict[str, object]:
    keep = "icc" if strip else "all"
    if fmt == "jpeg":
        return {"Q": quality, "optimize_coding": True, "interlace": True, "keep": keep}
    if fmt == "webp":
        return {"Q": quality, "effort": 4, "keep": keep}
    if fmt == "avif":
        return {"Q": quality, "compression": "av1", "effort": 4, "keep": keep}
    if fmt == "png":
        return {"compression": 6, "keep": keep}
    return {"compression": "deflate", "predictor": "horizontal", "keep": keep}


def _with_progress(image: pyvips.Image, progress: ProgressFn | None, start: float, span: float) -> None:
    if progress is None:
        return
    image.set_progress(True)

    def on_eval(img: pyvips.Image, p: object) -> None:
        try:
            progress(start + span * p.percent / 100)  # type: ignore[attr-defined]
        except InterruptedError:
            img.set_kill(True)  # cancelled: ask libvips to stop evaluating

    image.signal_connect("eval", on_eval)


def encode(
    work: Working,
    options: ExportOptions,
    out_path: Path,
    tmp_dir: Path,
    *,
    progress: ProgressFn | None = None,
) -> ExportResult:
    spec = OUTPUT_FORMATS[options.format]
    depth: Literal[8, 16] = 16 if (spec.sixteen_bit and work.depth == 16) else 8
    final = from_working(work, depth=depth, keep_alpha=spec.alpha)
    check_dimensions(final.width, final.height, options)

    tmp_dir.mkdir(parents=True, exist_ok=True)
    staged = tmp_dir / f"{out_path.stem}.render.v"
    # Keep the real extension last so libvips picks the right encoder; rename when complete.
    partial = out_path.with_name(f"{out_path.stem}.partial{spec.extension}")
    try:
        _with_progress(final, progress, 0.0, 0.8)
        final.write_to_file(str(staged))

        quality: int | None = options.quality if spec.lossy else None
        if options.target_kb is not None:
            quality = _search_quality(str(staged), options, options.target_kb * 1024)

        rendered = pyvips.Image.new_from_file(str(staged), access="sequential")
        _with_progress(rendered, progress, 0.8, 0.2)
        rendered.write_to_file(
            str(partial), **_save_kwargs(options.format, quality or 90, options.strip_metadata)
        )
        partial.replace(out_path)
        if progress is not None:
            progress(1.0)
        return ExportResult(out_path, final.width, final.height, out_path.stat().st_size, quality)
    finally:
        staged.unlink(missing_ok=True)
        partial.unlink(missing_ok=True)


def _search_quality(staged: str, options: ExportOptions, target_bytes: int) -> int:
    """Highest quality (10..95) whose encoded size fits the target, by binary search."""
    spec = OUTPUT_FORMATS[options.format]

    def size_at(q: int) -> int:
        image = pyvips.Image.new_from_file(staged, access="sequential")
        buf = image.write_to_buffer(spec.extension, **_save_kwargs(options.format, q, options.strip_metadata))
        return len(buf)

    low, high, best = 10, 95, None
    if size_at(low) > target_bytes:
        raise AppError(
            "export.target_unreachable",
            f"Even at the lowest quality the file is larger than {options.target_kb:,} KB.",
            status=422,
            title="Target size can't be reached",
            fix="Set a smaller maximum size, choose AVIF or WebP, or raise the target.",
        )
    while low <= high:
        mid = (low + high) // 2
        if size_at(mid) <= target_bytes:
            best, low = mid, mid + 1
        else:
            high = mid - 1
    return best or 10
