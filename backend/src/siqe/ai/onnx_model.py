"""ONNX models on ONNX Runtime (CPU), as a ``siqe.ai.tiling.Backend``. No torch here.

Used for the built-in ONNX image-to-image models (NAFNet deblur) and for models you bring
yourself. The CPU worker runs them, so they never wait behind (or block) the GPU queue.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import onnxruntime as ort

from siqe.core.errors import AppError
from siqe.system.resources import cpu_info


def session(path: Path, threads: int | None = None) -> ort.InferenceSession:
    options = ort.SessionOptions()
    options.intra_op_num_threads = threads or max(1, int(cpu_info().usable_cores))
    options.inter_op_num_threads = 1
    options.log_severity_level = 3  # errors only; exported graphs often carry harmless warnings
    try:
        return ort.InferenceSession(str(path), options, providers=["CPUExecutionProvider"])
    except Exception as exc:  # onnxruntime raises its own exception types for bad graphs
        raise AppError(
            "model.load_failed",
            "ONNX Runtime couldn't load this model.",
            fix="Check that the file is a complete .onnx export (opset 13 or newer).",
        ) from exc


class OnnxBackend:
    """An image-to-image ONNX model with one N×C×H×W float input and one output, values 0..1."""

    def __init__(self, path: Path, *, out_channels: int = 3, threads: int | None = None) -> None:
        self.session = session(path, threads)
        self.input = self.session.get_inputs()[0].name
        self.output = self.session.get_outputs()[0].name
        self.out_channels = out_channels
        self.device: str = "cpu"

    def forward(self, batch: np.ndarray) -> np.ndarray:
        (out,) = self.session.run([self.output], {self.input: np.ascontiguousarray(batch, np.float32)})
        out = np.asarray(out, np.float32)[:, : self.out_channels]
        return np.clip(out, 0.0, 1.0)

    def to_cpu(self) -> None:  # already on the CPU
        return None

    def release(self) -> None:
        return None


@dataclass(frozen=True)
class OnnxIO:
    name: str
    shape: tuple[int | str | None, ...]
    type: str


def describe(sess: ort.InferenceSession) -> tuple[list[OnnxIO], list[OnnxIO]]:
    def io(items: Any) -> list[OnnxIO]:
        return [OnnxIO(i.name, tuple(i.shape), i.type) for i in items]

    return io(sess.get_inputs()), io(sess.get_outputs())
