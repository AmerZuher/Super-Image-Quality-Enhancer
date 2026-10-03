"""Colorize black and white photos. No torch here: the network is passed in as a function.

The network predicts colour (CIELAB a and b) from lightness at 256 × 256. The prediction is
scaled up to the full image and combined with the original's own lightness, so every detail
of the photo is kept; only colour is added, and colour changes slowly enough that 256 px of it
is plenty.
"""

from collections.abc import Callable
from pathlib import Path

import numpy as np
import pyvips

from siqe.imaging.io import open_image

SIZE = 256
ColorFn = Callable[[np.ndarray], np.ndarray]  # 256×256 lightness (0..100) → 2×256×256 ab


def colorize_file(
    src: Path,
    out_png: Path,
    predict: ColorFn,
    *,
    on_progress: Callable[[float, str], None] = lambda f, m: None,
    max_megapixels: int | None = None,
) -> tuple[int, int]:
    """Colorize ``src`` and save a PNG. Returns the output size."""
    image = open_image(src, max_megapixels=max_megapixels)
    alpha = image[image.bands - 1].cast("uchar") if image.hasalpha() else None
    rgb = image.colourspace("srgb")
    rgb = rgb[:3] if rgb.bands >= 3 else rgb[0].bandjoin([rgb[0], rgb[0]])
    rgb = rgb.cast("uchar").copy(interpretation="srgb")
    width, height = rgb.width, rgb.height

    on_progress(0.1, "Looking at the photo")
    small = rgb.thumbnail_image(SIZE, height=SIZE, size="force")
    lightness = np.asarray(small.colourspace("lab")[0].numpy(), np.float32)
    lightness = lightness if lightness.ndim == 2 else lightness[..., 0]
    on_progress(0.3, "Choosing colours")
    ab = np.asarray(predict(lightness), np.float32)

    on_progress(0.7, "Adding colour")
    ab_image = pyvips.Image.new_from_array(np.ascontiguousarray(ab.transpose(1, 2, 0)))
    ab_full = ab_image.affine(
        [width / SIZE, 0, 0, height / SIZE],
        interpolate=pyvips.Interpolate.new("bilinear"),
        oarea=[0, 0, width, height],
        extend="copy",
    )
    full_l = rgb.colourspace("lab")[0]
    lab = full_l.bandjoin(ab_full).copy(interpretation="lab")
    out = lab.colourspace("srgb").cast("uchar")
    if alpha is not None:
        out = out.bandjoin(alpha)
    out.pngsave(str(out_png), compression=6)
    on_progress(1.0, "Done")
    return width, height
