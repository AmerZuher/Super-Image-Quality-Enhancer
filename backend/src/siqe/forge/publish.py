"""Scoring a trained Forge model before it goes into AI Lab. Needs PyTorch (GPU worker)."""

import time
from pathlib import Path
from typing import Any

import torch
from safetensors.torch import load_file

from siqe.ai.archs.forge import GraphNet
from siqe.forge.trainer import RunSpec, validate

TIMING_SIDE = 256


def benchmark(spec: RunSpec, weights: Path, device: str) -> dict[str, Any]:
    """PSNR and SSIM on the held-out crops (and bicubic's, for comparison), and speed."""
    channels = 1 if spec.color == "y" else 3
    model = GraphNet(spec.plan, spec.scale, channels)
    model.load_state_dict(load_file(str(weights), device="cpu"))
    model.to(device).eval()
    score, structure, bicubic, _ = validate(model, spec, device)
    x = torch.rand(1, channels, TIMING_SIDE, TIMING_SIDE, device=device)
    runs = []
    with torch.no_grad():
        model(x)
        for _ in range(3):
            if device == "cuda":
                torch.cuda.synchronize()
            start = time.perf_counter()
            model(x)
            if device == "cuda":
                torch.cuda.synchronize()
            runs.append(time.perf_counter() - start)
    seconds = min(runs)
    return {
        "psnr": round(score, 3),
        "ssim": round(structure, 4),
        "bicubic_psnr": round(bicubic, 3),
        "gain_db": round(score - bicubic, 3),
        "ms_per_megapixel": round(seconds * 1000 / (TIMING_SIDE * TIMING_SIDE / 1e6), 1),
        "device": "GPU" if device == "cuda" else "CPU",
    }
