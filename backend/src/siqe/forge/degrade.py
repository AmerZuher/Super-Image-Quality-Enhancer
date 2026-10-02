"""Making training pairs: a high-resolution crop in, a damaged low-resolution copy out.

The chain follows real-world damage: optical blur, bicubic downscaling by the model's factor,
sensor noise, then JPEG compression. Each step's strength is drawn from a range for every
sample, so the model learns to undo a spread of damage, not one fixed recipe. Plain numpy and
libvips, so the API can draw previews and the trainer can feed the GPU.
"""

from typing import Literal

import numpy as np
import pyvips
from pydantic import BaseModel, Field, model_validator

# Full-range BT.601 luma, the same as AI Lab's brightness-only models (siqe.ai.pipeline).
LUMA = np.array([0.299, 0.587, 0.114], np.float32)


class Range(BaseModel):
    low: float
    high: float

    @model_validator(mode="after")
    def _ordered(self) -> "Range":
        if self.high < self.low:
            self.low, self.high = self.high, self.low
        return self


class Degradation(BaseModel):
    blur: Range = Field(
        default=Range(low=0.2, high=1.5), description="Gaussian blur sigma, in pixels; 0 is off."
    )
    noise: Range = Field(default=Range(low=0, high=8), description="Noise sigma on a 0 to 255 scale.")
    jpeg: Range = Field(default=Range(low=60, high=95), description="JPEG quality; 100 skips compression.")
    blur_chance: float = Field(default=0.7, ge=0, le=1)
    noise_chance: float = Field(default=0.5, ge=0, le=1)
    jpeg_chance: float = Field(default=0.6, ge=0, le=1)

    @model_validator(mode="after")
    def _limits(self) -> "Degradation":
        self.blur = Range(low=min(max(self.blur.low, 0), 5), high=min(max(self.blur.high, 0), 5))
        self.noise = Range(low=min(max(self.noise.low, 0), 50), high=min(max(self.noise.high, 0), 50))
        self.jpeg = Range(low=min(max(self.jpeg.low, 10), 100), high=min(max(self.jpeg.high, 10), 100))
        return self


def _vips(array: np.ndarray) -> pyvips.Image:
    h, w, c = array.shape
    return pyvips.Image.new_from_memory(np.ascontiguousarray(array), w, h, c, "uchar")


def _array(image: pyvips.Image) -> np.ndarray:
    return np.asarray(image.numpy(), np.uint8).reshape(image.height, image.width, image.bands)


def degrade(hr: np.ndarray, scale: int, settings: Degradation, rng: np.random.Generator) -> np.ndarray:
    """A damaged copy of an RGB uint8 crop at 1/scale size. ``hr``'s sides must divide by scale."""
    image = _vips(hr)
    if rng.random() < settings.blur_chance:
        sigma = rng.uniform(settings.blur.low, settings.blur.high)
        if sigma >= 0.1:
            image = image.gaussblur(sigma, min_ampl=0.01).cast("uchar")
    if scale > 1:
        image = image.resize(1 / scale, kernel="cubic").cast("uchar")
        # Rounding can leave a pixel over; crop to the exact size.
        image = image.crop(0, 0, hr.shape[1] // scale, hr.shape[0] // scale)
    out = _array(image).astype(np.float32)
    if rng.random() < settings.noise_chance:
        sigma = rng.uniform(settings.noise.low, settings.noise.high)
        if sigma > 0:
            out = out + rng.normal(0, sigma, out.shape).astype(np.float32)
    lr = np.clip(np.rint(out), 0, 255).astype(np.uint8)
    if rng.random() < settings.jpeg_chance:
        quality = int(rng.uniform(settings.jpeg.low, settings.jpeg.high))
        if quality < 100:
            buffer = _vips(lr).jpegsave_buffer(Q=quality, strip=True)
            lr = _array(pyvips.Image.new_from_buffer(buffer, "", access="sequential"))
    return lr


def augment(hr: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """One of the eight flips and quarter turns."""
    turns = int(rng.integers(4))
    out = np.rot90(hr, turns) if turns else hr
    if rng.random() < 0.5:
        out = out[:, ::-1]
    return np.ascontiguousarray(out)


def random_crop(image: np.ndarray, size: int, rng: np.random.Generator) -> np.ndarray:
    h, w = image.shape[:2]
    top = int(rng.integers(0, h - size + 1))
    left = int(rng.integers(0, w - size + 1))
    return image[top : top + size, left : left + size]


def to_input(image: np.ndarray, color: Literal["rgb", "y"]) -> np.ndarray:
    """uint8 H×W×3 → float32 C×H×W in 0..1, as the network sees it."""
    x = image.astype(np.float32) / 255.0
    if color == "y":
        return (x @ LUMA)[None]
    return np.ascontiguousarray(x.transpose(2, 0, 1))


def pair(
    hr_crop: np.ndarray,
    patch: int,
    scale: int,
    settings: Degradation,
    rng: np.random.Generator,
    *,
    train: bool = True,
) -> tuple[np.ndarray, np.ndarray]:
    """One training pair (uint8): an HR patch of ``patch × scale`` pixels and its damaged LR copy."""
    size = patch * scale
    hr = random_crop(hr_crop, size, rng) if train else hr_crop[:size, :size]
    if train:
        hr = augment(hr, rng)
    return hr, degrade(hr, scale, settings, rng)
