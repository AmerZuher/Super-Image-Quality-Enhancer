"""Export a Forge model to ONNX, and prove the export computes the same thing. Needs torch (GPU
worker only).

The model is rebuilt from the run's plan (``GraphNet``) with its best checkpoint and exported with
a dynamic batch, height and width; height and width move in steps of the model's patch multiple,
so models with Down blocks keep working at any size they accept. The result is then run with ONNX
Runtime next to PyTorch at a few sizes, and only kept if they agree.
"""

import hashlib
import io
import warnings
from collections.abc import Callable
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

import numpy as np
import torch
from safetensors.torch import load_file

from siqe.ai.archs.forge import GraphNet
from siqe.core.errors import AppError

OPSET = 18
TOLERANCE = 1e-3  # outputs are 0..1; float32 reorderings differ by about 1e-6
MAX_SIDE = 8192

ProgressFn = Callable[[float, str], None]


def _module(plan: list[dict[str, Any]], scale: int, channels: int, weights: Path) -> GraphNet:
    module = GraphNet(plan, scale, channels)
    module.load_state_dict(load_file(str(weights), device="cpu"))
    return module.float().eval()


def _export(module: GraphNet, example: torch.Tensor, multiple: int, out: Path) -> str:
    """Write ``out``; returns which exporter managed it."""
    names = {"input_names": ["input"], "output_names": ["output"]}
    try:
        batch = torch.export.Dim("batch", min=1, max=64)
        steps = MAX_SIDE // multiple
        if multiple > 1:
            h = multiple * torch.export.Dim("h_steps", min=1, max=steps)
            w = multiple * torch.export.Dim("w_steps", min=1, max=steps)
        else:
            h = torch.export.Dim("h", min=2, max=MAX_SIDE)
            w = torch.export.Dim("w", min=2, max=MAX_SIDE)
        with redirect_stdout(io.StringIO()), warnings.catch_warnings():
            warnings.simplefilter("ignore")
            program = torch.onnx.export(
                module,
                (example,),
                dynamo=True,
                dynamic_shapes=({0: batch, 2: h, 3: w},),
                opset_version=OPSET,
                external_data=False,
                verbose=False,
                **names,
            )
        if program is None:
            raise RuntimeError("the exporter returned nothing")
        program.save(str(out), external_data=False)
        return "torch.export"
    except Exception:
        # Graphs the new exporter can't trace usually still work with the TorchScript one.
        out.unlink(missing_ok=True)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            torch.onnx.export(
                module,
                (example,),
                str(out),
                dynamo=False,
                opset_version=17,
                dynamic_axes={
                    "input": {0: "batch", 2: "height", 3: "width"},
                    "output": {0: "batch", 2: "out_height", 3: "out_width"},
                },
                **names,
            )
        return "torchscript"


def _verify(module: GraphNet, path: Path, channels: int, multiple: int) -> float:
    """Largest difference between PyTorch and ONNX Runtime over a few batches and sizes."""
    import onnxruntime as ort

    session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    step = max(multiple, 1)
    worst = 0.0
    generator = torch.Generator().manual_seed(0)
    for batch, h, w in ((1, 8, 8), (2, 13, 21), (1, 40, 24)):
        x = torch.rand(batch, channels, h * step, w * step, generator=generator)
        with torch.inference_mode():
            expected = module(x).numpy()
        (got,) = session.run(None, {"input": x.numpy()})
        if got.shape != expected.shape:
            raise AppError(
                "forge.export_mismatch",
                f"The ONNX file returns {list(got.shape)} where the model returns {list(expected.shape)}.",
                fix="Download the safetensors weights and the generated code instead.",
            )
        worst = max(worst, float(np.abs(got - expected).max()))
    if not worst <= TOLERANCE:
        raise AppError(
            "forge.export_mismatch",
            f"The ONNX file differs from the model by up to {worst:.2g}, more than {TOLERANCE:g}.",
            fix="Download the safetensors weights and the generated code instead.",
        )
    return worst


def export_onnx(
    *,
    plan: list[dict[str, Any]],
    scale: int,
    color: str,
    multiple: int,
    weights: Path,
    out: Path,
    on_progress: ProgressFn = lambda f, m: None,
) -> dict[str, Any]:
    """Export ``weights`` to ``out`` (via a temporary name) and describe what was written."""
    channels = 1 if color == "y" else 3
    on_progress(0.1, "Loading the best checkpoint")
    module = _module(plan, scale, channels, weights)
    side = max(multiple, 1) * max(1, 64 // max(multiple, 1))
    example = torch.rand(1, channels, side, side)
    tmp = out.with_name(out.name + ".partial")
    on_progress(0.3, "Exporting")
    try:
        exporter = _export(module, example, max(multiple, 1), tmp)
        on_progress(0.7, "Checking it against PyTorch")
        difference = _verify(module, tmp, channels, multiple)
    except AppError:
        tmp.unlink(missing_ok=True)
        raise
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        raise AppError(
            "forge.export_failed",
            "This model couldn't be exported to ONNX.",
            fix="Download the safetensors weights and the generated code instead.",
        ) from exc
    digest = hashlib.sha256(tmp.read_bytes()).hexdigest()
    size = tmp.stat().st_size
    tmp.replace(out)
    on_progress(1.0, "Exported")
    return {
        "exporter": exporter,
        "opset": OPSET if exporter == "torch.export" else 17,
        "max_difference": difference,
        "size": size,
        "sha256": digest,
        "channels": channels,
        "scale": scale,
        "multiple": max(multiple, 1),
        "input": "input",
        "output": "output",
        "range": "0..1",
    }
