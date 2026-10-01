"""The only way user images are opened.

``inspect`` reads the header without decoding pixels, so a 100 KB file that claims
50,000 × 50,000 pixels is refused before it costs any memory. ``open_image`` applies the same
checks and returns a lazily evaluated libvips image.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import pyvips
from PIL import Image as PILImage

from siqe.core.config import get_settings
from siqe.core.errors import AppError
from siqe.imaging.formats import INPUT_EXTENSIONS, INPUT_LOADERS

# Second guard for any code path that touches Pillow (pillow-heif, metadata helpers).
PILImage.MAX_IMAGE_PIXELS = get_settings().max_input_megapixels * 1_000_000

_EXIF_FIELDS = {
    "exif-ifd0-Make": "make",
    "exif-ifd0-Model": "model",
    "exif-ifd2-LensModel": "lens",
    "exif-ifd2-DateTimeOriginal": "taken_at",
    "exif-ifd2-ExposureTime": "exposure_time",
    "exif-ifd2-FNumber": "f_number",
    "exif-ifd2-ISOSpeedRatings": "iso",
    "exif-ifd2-FocalLength": "focal_length",
}


@dataclass(frozen=True)
class ImageInfo:
    format: str
    width: int
    height: int
    bands: int
    bit_depth: Literal[8, 16, 32]
    has_alpha: bool
    has_icc: bool
    orientation: int
    pages: int
    exif: dict[str, Any] = field(default_factory=dict)
    has_gps: bool = False

    @property
    def oriented_size(self) -> tuple[int, int]:
        """Width and height after applying the EXIF orientation."""
        return (self.height, self.width) if self.orientation in (5, 6, 7, 8) else (self.width, self.height)

    @property
    def megapixels(self) -> float:
        return self.width * self.height / 1e6


def _clean_exif(raw: str) -> str:
    # libvips formats EXIF values as "value (description, type)"; keep the readable part.
    return raw.split(" (")[0].strip()


def _read_header(path: Path) -> pyvips.Image:
    try:
        return pyvips.Image.new_from_file(str(path), access="sequential", fail=True)
    except pyvips.Error as exc:
        raise AppError(
            "image.unreadable",
            "This file isn't an image SIQE Studio can read, or it is damaged.",
            status=422,
            title="Unreadable image",
            fix=f"Supported formats: {INPUT_EXTENSIONS}. Re-export the file and try again.",
        ) from exc


def inspect(path: Path, *, max_megapixels: int | None = None) -> ImageInfo:
    image = _read_header(path)
    fields = set(image.get_fields())
    loader = image.get("vips-loader") if "vips-loader" in fields else ""
    fmt = INPUT_LOADERS.get(loader)
    if fmt is None:
        raise AppError(
            "image.unsupported_format",
            f"Files of this type ({loader.removesuffix('load') or 'unknown'}) aren't supported.",
            status=415,
            title="Unsupported format",
            fix=f"Convert it to one of: {INPUT_EXTENSIONS}.",
        )
    limit = max_megapixels if max_megapixels is not None else get_settings().max_input_megapixels
    megapixels = image.width * image.height / 1e6
    if megapixels > limit:
        raise AppError(
            "image.too_large",
            f"The image is {image.width} × {image.height} ({megapixels:,.0f} MP); the limit is {limit} MP.",
            status=413,
            title="Image too large",
            fix="Downscale it first, or raise SIQE_MAX_INPUT_MEGAPIXELS in .env if your machine can cope.",
            width=image.width,
            height=image.height,
            limit_megapixels=limit,
        )
    depth: Literal[8, 16, 32] = (
        16 if image.format in ("ushort", "short") else 32 if image.format == "float" else 8
    )
    has_alpha = bool(image.hasalpha())
    exif = {name: _clean_exif(str(image.get(key))) for key, name in _EXIF_FIELDS.items() if key in fields}
    return ImageInfo(
        format=fmt,
        width=image.width,
        height=image.height,
        bands=image.bands,
        bit_depth=depth,
        has_alpha=has_alpha,
        has_icc="icc-profile-data" in fields,
        orientation=int(image.get("orientation")) if "orientation" in fields else 1,
        pages=int(image.get("n-pages")) if "n-pages" in fields else 1,
        exif=exif,
        has_gps=any(f.startswith("exif-ifd3-") for f in fields),
    )


def open_image(path: Path, *, sequential: bool = False, max_megapixels: int | None = None) -> pyvips.Image:
    """Admission-checked, lazily decoded image (first frame for animations)."""
    inspect(path, max_megapixels=max_megapixels)
    return pyvips.Image.new_from_file(str(path), access="sequential" if sequential else "random", fail=True)
