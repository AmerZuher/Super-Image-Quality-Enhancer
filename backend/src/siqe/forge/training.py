"""Training settings and files, without PyTorch (the API checks settings before queuing a run)."""

import uuid
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from siqe.core.config import get_settings

# A run trains in chunks of about this long on the GPU queue, so other GPU work (an upscale
# you started) waits minutes at most, and a crash costs at most one chunk.
CHUNK_SECONDS = 180
# Charts get a training point this often (steps).
LOG_EVERY = 25
# Validation crops are scored at most this many at a time.
VAL_BATCH = 8
# Consecutive non-finite losses before a run is stopped as diverged.
MAX_NAN_STREAK = 20


class TrainSettings(BaseModel):
    steps: int = Field(default=20_000, ge=10, le=2_000_000, description="Optimiser steps in total.")
    batch: int = Field(
        default=16, ge=1, le=256, description="Patches per step (lowered automatically if memory runs out)."
    )
    patch: int = Field(
        default=48, ge=8, le=256, description="Side of each low-resolution training patch, in pixels."
    )
    lr: float = Field(
        default=2e-4, gt=0, le=1e-2, description="Peak learning rate (Adam), with warm-up and cosine decay."
    )
    loss: Literal["l1", "mse", "charbonnier"] = "l1"
    val_every: int = Field(default=500, ge=10, le=100_000, description="Steps between validations.")
    seed: int = Field(default=0, ge=0, le=2**31 - 1)
    precision: Literal["auto", "fp32"] = Field(
        default="auto", description="auto uses bfloat16 on GPUs that support it (RTX 30 and newer)."
    )


def run_dir(run_id: uuid.UUID | str) -> Path:
    return get_settings().data_dir / "checkpoints" / str(run_id)


def last_checkpoint(run_id: uuid.UUID | str) -> Path:
    return run_dir(run_id) / "last.pt"


def best_weights(run_id: uuid.UUID | str) -> Path:
    return run_dir(run_id) / "best.safetensors"


def onnx_path(run_id: uuid.UUID | str) -> Path:
    return run_dir(run_id) / "model.onnx"


def sample_path(run_id: uuid.UUID | str) -> Path:
    return run_dir(run_id) / "sample.png"


def lr_at(step: int, settings: TrainSettings) -> float:
    """Linear warm-up for the first 2% of steps (at most 500), then cosine decay to 5%."""
    import math

    warmup = max(1, min(500, settings.steps // 50))
    if step < warmup:
        return settings.lr * (step + 1) / warmup
    progress = (step - warmup) / max(1, settings.steps - warmup)
    return settings.lr * (0.05 + 0.95 * 0.5 * (1 + math.cos(math.pi * min(1.0, progress))))
