"""PyTorch side of AI runs: loading models safely, the tiling backend, VRAM calibration.

Imported only by the GPU worker (the ``ai`` image has torch). Weights are loaded with
``torch.load(weights_only=True)`` or from safetensors, never with full pickle or TorchScript.
"""

import contextlib
import gc
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np
import torch
from safetensors.torch import load_file
from spandrel import ImageModelDescriptor, ModelLoader, canonicalize_state_dict

from siqe.ai.governor import Calibration, fit_calibration
from siqe.ai.tiling import padded_size

Device = Literal["cuda", "cpu"]


class ModelLoadError(RuntimeError):
    pass


@dataclass
class LoadedModel:
    module: torch.nn.Module
    scale: int
    in_channels: int
    out_channels: int
    multiple: int
    half_ok: bool


def pick_device(preference: str = "auto") -> Device:
    if preference == "cpu":
        return "cpu"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def device_name(device: str) -> str:
    return str(torch.cuda.get_device_name(0)) if device == "cuda" else "CPU"


def load_spandrel(path: Path) -> LoadedModel:
    if path.suffix == ".safetensors":
        state = load_file(str(path), device="cpu")
    else:
        try:
            state = torch.load(path, map_location="cpu", weights_only=True)
        except Exception as exc:  # pickle with code in it, or a corrupt file
            raise ModelLoadError(f"{path.name} can't be loaded safely: {exc}") from exc
    try:
        descriptor = ModelLoader(device="cpu").load_from_state_dict(canonicalize_state_dict(state))
    except Exception as exc:
        raise ModelLoadError(f"{path.name} isn't a supported architecture: {exc}") from exc
    if not isinstance(descriptor, ImageModelDescriptor):
        raise ModelLoadError(f"{path.name} is not an image-to-image model")
    return LoadedModel(
        module=descriptor.model.eval(),
        scale=descriptor.scale,
        in_channels=descriptor.input_channels,
        out_channels=descriptor.output_channels,
        multiple=max(1, descriptor.size_requirements.multiple_of),
        half_ok=bool(descriptor.supports_half),
    )


def load_siqe_classic(path: Path) -> LoadedModel:
    from siqe.ai.archs.siqe_classic import SiqeClassic

    module = SiqeClassic()
    module.load_state_dict(load_file(str(path), device="cpu"))
    return LoadedModel(module=module.eval(), scale=3, in_channels=1, out_channels=1, multiple=1, half_ok=True)


def load_forge(path: Path, info: dict[str, Any]) -> LoadedModel:
    """A model published from Forge: rebuilt from its plan, weights from safetensors."""
    from siqe.ai.archs.forge import GraphNet

    channels = 1 if info.get("color") == "y" else 3
    module = GraphNet(list(info["plan"]), int(info["scale"]), channels)
    try:
        module.load_state_dict(load_file(str(path), device="cpu"))
    except Exception as exc:
        raise ModelLoadError(f"{path.parent.name} doesn't match its saved design: {exc}") from exc
    return LoadedModel(
        module=module.eval(),
        scale=int(info["scale"]),
        in_channels=channels,
        out_channels=channels,
        multiple=int(info.get("multiple", 1)),
        # Your own models run in full precision: we can't know they're safe in float16.
        half_ok=False,
    )


class TorchBackend:
    """``siqe.ai.tiling.Backend`` for a PyTorch module."""

    def __init__(self, model: LoadedModel, device: Device, *, half: bool = True) -> None:
        self.model = model
        self.device: str = device
        self.half = half and model.half_ok and device == "cuda"
        model.module.to(device)

    def forward(self, batch: np.ndarray) -> np.ndarray:
        with torch.inference_mode():
            x = torch.from_numpy(batch).to(self.device)
            ctx = torch.autocast("cuda", dtype=torch.float16) if self.half else contextlib.nullcontext()
            with ctx:
                y = self.model.module(x)
            return y.float().clamp_(0, 1).cpu().numpy()

    def to_cpu(self) -> None:
        self.model.module.to("cpu")
        self.device = "cpu"
        self.half = False
        self.release()

    def release(self) -> None:
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


def budget_bytes(reserve_mb: int) -> float:
    """Memory this process may still use on the GPU: free plus what it already holds, minus the reserve."""
    free, _total = torch.cuda.mem_get_info()
    return float(free + torch.cuda.memory_allocated() - reserve_mb * 1024 * 1024)


def calibrate(backend: TorchBackend, *, context: int, multiple: int) -> Calibration:
    """Measure peak memory at two tile sizes and fit a line (CUDA only)."""
    samples: list[tuple[int, float]] = []
    channels = backend.model.in_channels
    for tile in (128, 256):
        size = padded_size(tile, context, multiple)
        backend.release()
        torch.cuda.reset_peak_memory_stats()
        batch = np.random.default_rng(0).random((1, channels, size, size), dtype=np.float32)
        backend.forward(batch)
        torch.cuda.synchronize()
        samples.append((size * size, float(torch.cuda.max_memory_allocated())))
    backend.release()
    return fit_calibration(samples)


class FaceDetector:
    """RetinaFace alone, for counting faces in the Library."""

    def __init__(self, detector_path: Path, device: Device) -> None:
        from siqe.ai.archs.retinaface import RetinaFace, load_state

        self.device: str = device
        try:
            state = torch.load(detector_path, map_location="cpu", weights_only=True)
        except Exception as exc:
            raise ModelLoadError(f"{detector_path.name} can't be loaded safely: {exc}") from exc
        self.model = load_state(RetinaFace(), state).to(device)

    def detect(self, rgb: np.ndarray) -> list[tuple[float, np.ndarray, np.ndarray]]:
        from siqe.ai.archs.retinaface import detect

        with torch.inference_mode():
            return detect(self.model, rgb, self.device)


class FaceRestorer:
    """GFPGAN v1.4 on faces found by RetinaFace; plugs into ``siqe.ai.faces.restore_faces``."""

    def __init__(self, gfpgan_path: Path, detector_path: Path, device: Device) -> None:
        from siqe.ai.archs.retinaface import RetinaFace, load_state

        self.device: str = device
        self.gfpgan = load_spandrel(gfpgan_path).module.eval().to(device)
        try:
            state = torch.load(detector_path, map_location="cpu", weights_only=True)
        except Exception as exc:
            raise ModelLoadError(f"{detector_path.name} can't be loaded safely: {exc}") from exc
        self.detector = load_state(RetinaFace(), state).to(device)

    def detect(self, rgb: np.ndarray) -> list[Any]:
        from siqe.ai.archs.retinaface import detect
        from siqe.ai.faces import Face

        return [Face(s, b, lm) for s, b, lm in detect(self.detector, rgb, self.device)]

    def restore(self, face: np.ndarray) -> np.ndarray:
        with torch.inference_mode():
            x = torch.from_numpy(np.ascontiguousarray(face.transpose(2, 0, 1)))[None].to(self.device) * 2 - 1
            y = self.gfpgan(x, return_rgb=False, randomize_noise=False)[0]
            return ((y.float() + 1) / 2).clamp_(0, 1)[0].permute(1, 2, 0).cpu().numpy()

    def release(self) -> None:
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
