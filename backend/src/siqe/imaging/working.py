"""Conversion to and from the working space: sRGB-encoded float RGB in 0..1, alpha kept apart.

* EXIF orientation is applied, so pixels and what the user sees agree.
* Embedded ICC profiles (CMYK, Adobe RGB, Display P3) are converted to sRGB.
* 16-bit sources stay 16-bit through the pipeline and on export to PNG or TIFF.
"""

import contextlib
from dataclasses import dataclass
from typing import Literal

import pyvips


@dataclass
class Working:
    rgb: pyvips.Image  # float, 3 bands, sRGB-encoded 0..1
    alpha: pyvips.Image | None  # float, 1 band, 0..1
    depth: Literal[8, 16]

    @property
    def width(self) -> int:
        return int(self.rgb.width)

    @property
    def height(self) -> int:
        return int(self.rgb.height)


def to_working(image: pyvips.Image) -> Working:
    image = image.autorot()
    depth: Literal[8, 16] = 16 if image.format in ("ushort", "short") else 8
    if "icc-profile-data" in image.get_fields():
        # A broken profile shouldn't block editing; fall back to the colour-space tag.
        with contextlib.suppress(pyvips.Error):
            image = image.icc_transform("srgb", embedded=True, depth=depth, intent="relative")
    target = "rgb16" if depth == 16 else "srgb"
    if image.interpretation not in (target,):
        image = image.colourspace(target)
    alpha = None
    if image.hasalpha():
        alpha = image[image.bands - 1]
        image = image.extract_band(0, n=3)
    elif image.bands > 3:
        image = image.extract_band(0, n=3)
    scale = 65535.0 if depth == 16 else 255.0
    rgb = image.cast("float") / scale
    return Working(rgb=rgb, alpha=alpha.cast("float") / scale if alpha is not None else None, depth=depth)


def from_working(work: Working, *, depth: Literal[8, 16] = 8, keep_alpha: bool = True) -> pyvips.Image:
    scale = 65535.0 if depth == 16 else 255.0
    band_format = "ushort" if depth == 16 else "uchar"
    rgb = work.rgb.clamp(min=0.0, max=1.0)
    out = (rgb * scale).rint().cast(band_format)
    if keep_alpha and work.alpha is not None:
        alpha = (work.alpha.clamp(min=0.0, max=1.0) * scale).rint().cast(band_format)
        out = out.bandjoin(alpha)
    return out.copy(interpretation="rgb16" if depth == 16 else "srgb")
