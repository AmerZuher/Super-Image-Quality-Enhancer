"""Background removal with ISNet (DIS), run through ONNX Runtime on the CPU.

The model sees the whole image at 1024 × 1024; its mask is scaled back to full resolution
with Lanczos and becomes the alpha channel of a PNG. Preprocessing follows the published
model: scale to 0..1 by the image maximum, subtract 0.5.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import onnxruntime as ort
import pyvips

from siqe.imaging.io import open_image
from siqe.imaging.working import to_working

SIZE = 1024
_sessions: dict[str, Any] = {}


def session(model_path: Path) -> Any:
    key = str(model_path)
    if key not in _sessions:
        options = ort.SessionOptions()
        options.log_severity_level = 3
        _sessions[key] = ort.InferenceSession(key, options, providers=["CPUExecutionProvider"])
    return _sessions[key]


def predict_mask(sess: Any, rgb: pyvips.Image) -> np.ndarray:
    """SIZE × SIZE mask in 0..1 for a float sRGB image."""
    small = rgb.resize(SIZE / rgb.width, vscale=SIZE / rgb.height, kernel="lanczos3")
    small = small.embed(0, 0, SIZE, SIZE, extend="copy")
    arr = np.asarray(small.numpy(), dtype=np.float32).reshape(SIZE, SIZE, 3)
    arr = arr / max(float(arr.max()), 1e-6) - 0.5
    inputs = {sess.get_inputs()[0].name: np.ascontiguousarray(arr.transpose(2, 0, 1)[None])}
    pred = np.asarray(sess.run(None, inputs)[0], dtype=np.float32)[0, 0]
    lo, hi = float(pred.min()), float(pred.max())
    return (pred - lo) / (hi - lo) if hi > lo else np.zeros_like(pred)


def remove_background(
    src: Path,
    out_png: Path,
    model_path: Path,
    *,
    on_progress: Callable[[float, str], None] = lambda f, m: None,
    max_megapixels: int | None = None,
) -> tuple[int, int]:
    work = to_working(open_image(src, max_megapixels=max_megapixels))
    on_progress(0.1, "Finding the subject")
    mask = predict_mask(session(model_path), work.rgb)
    on_progress(0.6, "Cutting out at full resolution")
    small = pyvips.Image.new_from_memory(np.ascontiguousarray(mask), SIZE, SIZE, 1, "float")
    alpha = small.resize(work.width / SIZE, vscale=work.height / SIZE, kernel="lanczos3")
    alpha = alpha.crop(0, 0, work.width, work.height).clamp(min=0.0, max=1.0)
    if work.alpha is not None:
        alpha = alpha * work.alpha
    scale = 65535.0 if work.depth == 16 else 255.0
    fmt = "ushort" if work.depth == 16 else "uchar"
    out = (work.rgb.clamp(min=0.0, max=1.0).bandjoin(alpha) * scale).rint().cast(fmt)
    out = out.copy(interpretation="rgb16" if work.depth == 16 else "srgb")
    staging = out_png.with_name(out_png.name + ".partial.png")
    out.pngsave(str(staging), compression=3)
    staging.replace(out_png)
    on_progress(1.0, "Saved")
    return work.width, work.height
