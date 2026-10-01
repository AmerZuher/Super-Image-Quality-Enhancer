"""Supported input loaders and output formats, with the hard limits each format imposes."""

from dataclasses import dataclass
from typing import Literal

# libvips loader name → short format name. Anything else is refused at upload.
INPUT_LOADERS: dict[str, str] = {
    "jpegload": "jpeg",
    "jpegload_source": "jpeg",
    "pngload": "png",
    "pngload_source": "png",
    "webpload": "webp",
    "webpload_source": "webp",
    "heifload": "heif",
    "heifload_source": "heif",
    "tiffload": "tiff",
    "tiffload_source": "tiff",
    "gifload": "gif",
    "gifload_source": "gif",
}

INPUT_EXTENSIONS = ".jpg .jpeg .png .webp .heic .heif .avif .tif .tiff .gif"

OutputFormat = Literal["jpeg", "png", "webp", "avif", "tiff"]

_INT31 = 2**31 - 1


@dataclass(frozen=True)
class FormatSpec:
    name: OutputFormat
    label: str
    extension: str
    media_type: str
    max_side: int
    lossy: bool
    alpha: bool
    sixteen_bit: bool


OUTPUT_FORMATS: dict[OutputFormat, FormatSpec] = {
    "jpeg": FormatSpec("jpeg", "JPEG", ".jpg", "image/jpeg", 65_535, True, False, False),
    "png": FormatSpec("png", "PNG", ".png", "image/png", _INT31, False, True, True),
    "webp": FormatSpec("webp", "WebP", ".webp", "image/webp", 16_383, True, True, False),
    # libheif encoders handle larger images, but decoders commonly refuse above 16384.
    "avif": FormatSpec("avif", "AVIF", ".avif", "image/avif", 16_384, True, True, False),
    "tiff": FormatSpec("tiff", "TIFF", ".tif", "image/tiff", _INT31, False, True, True),
}
