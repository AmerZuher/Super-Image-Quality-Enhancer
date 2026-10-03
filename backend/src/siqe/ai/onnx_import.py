"""Adding your own ONNX model: check what it is by running it, then describe it. No torch here.

An ONNX file says little about how to use it: input names and shapes, sometimes not even those.
So the import runs the model on small test images and measures what it needs to know: the scale
(output size over input size), whether sides must be a multiple of something, whether output is
0..1 or 0..255, and how long it takes on this CPU. Only image-to-image models with one picture
in and one picture out are accepted, which is what the tiled pipeline can run.
"""

import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

from siqe.ai.onnx_model import OnnxIO, describe, session
from siqe.core.errors import AppError

PROBE_SIDES = (64, 128, 256, 384)
MULTIPLES = (1, 2, 4, 8, 16, 32, 64)
MAX_SCALE = 8
IMAGE_TASKS = ("upscale", "denoise", "deblur")

ProgressFn = Callable[[float, str], None]


@dataclass(frozen=True)
class Probe:
    input_name: str
    input_type: str
    in_channels: int
    out_channels: int
    scale: int
    multiple: int
    min_input: int
    output_range: int
    seconds_per_mp: float
    producer: str
    description: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _refuse(code: str, detail: str, fix: str) -> AppError:
    return AppError(code, detail, status=422, title="Model not supported", fix=fix)


def _test_image(side: int, channels: int, dtype: type) -> np.ndarray:
    """A smooth gradient with a little texture: realistic enough that outputs mean something."""
    y, x = np.mgrid[0:side, 0:side].astype(np.float32) / max(1, side - 1)
    image = np.stack([x, y, (x + y) / 2][:channels])[None] * 0.8 + 0.1
    image += 0.03 * np.sin(np.arange(side, dtype=np.float32) * 1.7)[None, None, None, :]
    return np.ascontiguousarray(image, dtype)


def _image_input(inputs: list[OnnxIO]) -> OnnxIO:
    if len(inputs) != 1:
        names = ", ".join(i.name for i in inputs)
        raise _refuse(
            "onnx.unsupported_inputs",
            f"This model takes {len(inputs)} inputs ({names}); "
            "only models with one image input can run here.",
            "Export the model with a single N×C×H×W image input.",
        )
    (first,) = inputs
    if first.type not in ("tensor(float)", "tensor(float16)") or len(first.shape) != 4:
        raise _refuse(
            "onnx.unsupported_inputs",
            f"The input '{first.name}' is {first.type} with {len(first.shape)} dimensions; "
            "an image input is a float tensor shaped N×C×H×W.",
            "Export the model with a float32 or float16 N×C×H×W input.",
        )
    h, w = first.shape[2], first.shape[3]
    if isinstance(h, int) and isinstance(w, int):
        raise _refuse(
            "onnx.fixed_size",
            f"This model only accepts {w} × {h} images, so it can't be run tile by tile on large photos.",
            "Export it with dynamic height and width (dynamic_axes in torch.onnx.export).",
        )
    return first


def probe(path: Path, *, on_progress: ProgressFn = lambda f, m: None, threads: int | None = None) -> Probe:
    """Load and run ``path``; raise a typed AppError if it can't be used as an image model."""
    on_progress(0.05, "Loading the model")
    sess = session(path, threads)
    inputs, outputs = describe(sess)
    first = _image_input(inputs)
    dtype = np.float16 if first.type == "tensor(float16)" else np.float32
    declared = first.shape[1]
    channel_options = [declared] if isinstance(declared, int) else [3, 1]
    if any(c not in (1, 3) for c in channel_options):
        raise _refuse(
            "onnx.unsupported_inputs",
            f"The input has {declared} channels; images here have 3 (RGB) or 1 (brightness).",
            "Export the model with a 3-channel or 1-channel input.",
        )

    def run(side_h: int, side_w: int, channels: int) -> np.ndarray | None:
        image = _test_image(max(side_h, side_w), channels, dtype)[:, :, :side_h, :side_w]
        try:
            (out,) = sess.run([outputs[0].name], {first.name: np.ascontiguousarray(image)})
        except Exception:  # onnxruntime raises its own types for shape errors
            return None
        return np.asarray(out, np.float32)

    # The smallest square side the model accepts, and with how many channels.
    on_progress(0.2, "Trying test images")
    found: tuple[int, int, np.ndarray] | None = None
    for side in PROBE_SIDES:
        for channels in channel_options:
            out = run(side, side, channels)
            if out is not None:
                found = (side, channels, out)
                break
        if found:
            break
    if found is None:
        raise _refuse(
            "onnx.probe_failed",
            "The model failed on every test image (64 to 384 px), so it isn't an image-to-image model "
            "this app can run.",
            "Check that it takes an N×C×H×W image with values 0 to 1 and returns an image.",
        )
    base, in_channels, out = found
    if out.ndim != 4 or out.shape[1] < in_channels:
        raise _refuse(
            "onnx.not_image_to_image",
            f"The output is shaped {list(out.shape)}, not an image with {in_channels} or more channels.",
            "Only models that return an image (N×C×H×W) can run here.",
        )
    scale_h, scale_w = out.shape[2] / base, out.shape[3] / base
    scale = round(scale_h)
    if scale_h != scale_w or scale != scale_h or not 1 <= scale <= MAX_SCALE:
        raise _refuse(
            "onnx.not_image_to_image",
            f"A {base} px test image came out {out.shape[3]} × {out.shape[2]}; the scale must be the same "
            f"whole number (1 to {MAX_SCALE}) in both directions.",
            "Only upscalers and same-size restoration models can run here.",
        )
    if not np.isfinite(out).all():
        raise _refuse(
            "onnx.probe_failed",
            "The model returned NaN or infinite values on a test image.",
            "Check the export; float16 models sometimes overflow, so try a float32 export.",
        )

    # Sides that aren't a multiple of something (down-sampling inside) fail; find the step.
    on_progress(0.5, "Checking which sizes it accepts")

    def fits(side_h: int, side_w: int) -> bool:
        result = run(side_h, side_w, in_channels)
        return result is not None and result.shape[2:] == (side_h * scale, side_w * scale)

    multiple = next((m for m in MULTIPLES if fits(base + m, base + m)), None)
    if multiple is None:
        raise _refuse(
            "onnx.fixed_size",
            f"The model accepts {base} × {base} test images but not slightly larger ones.",
            "Export it with dynamic height and width (dynamic_axes in torch.onnx.export).",
        )
    if not fits(base, base + multiple):
        raise _refuse(
            "onnx.fixed_size",
            "The model only accepts square images.",
            "Export it with independent dynamic height and width.",
        )

    # 0..1 or 0..255 output: the test image's values are 0.1 to 0.9.
    output_range = 255 if float(np.percentile(out[:, :in_channels], 99)) > 2.0 else 1

    on_progress(0.75, "Measuring speed")
    side = max(base, 256 - 256 % multiple)
    started = time.perf_counter()
    timed = run(side, side, in_channels)
    seconds = time.perf_counter() - started
    if timed is None:
        side, seconds = base, 0.0  # fine at its smallest size; time that instead
        started = time.perf_counter()
        run(base, base, in_channels)
        seconds = time.perf_counter() - started
    seconds_per_mp = seconds / (side * side / 1e6)

    meta = sess.get_modelmeta()
    on_progress(1.0, "Checked")
    return Probe(
        input_name=first.name,
        input_type=first.type,
        in_channels=in_channels,
        out_channels=int(out.shape[1]),
        scale=scale,
        multiple=multiple,
        min_input=base if base > PROBE_SIDES[0] else 0,
        output_range=output_range,
        seconds_per_mp=round(seconds_per_mp, 2),
        producer=str(meta.producer_name or "")[:80],
        description=str(meta.description or "")[:300],
    )


def speed_label(seconds_per_mp: float) -> str:
    return "fast" if seconds_per_mp < 3 else "balanced" if seconds_per_mp < 20 else "slow"


def task_for(probe: Probe, requested: str | None) -> str:
    """Upscalers are upscalers; same-size models do what you say they do (denoise by default)."""
    if probe.scale > 1:
        return "upscale"
    if requested in ("denoise", "deblur"):
        return requested
    return "denoise"
