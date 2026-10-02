"""Training a Forge model, one chunk at a time. Needs PyTorch (GPU worker only).

Each chunk loads the last checkpoint (model, optimiser, step, batch settings and every random
generator), trains until its time is up or the run ends, validates on schedule, and saves again.
Resuming therefore continues exactly where the last chunk stopped, even after a crash.

Safety: the batch halves (and gradient accumulation doubles, keeping the effective batch) when
the GPU runs out of memory; a non-finite loss skips the step and halves the learning rate;
gradients are clipped; bfloat16 is used where the GPU supports it.
"""

import io
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
import pyvips
import torch
from safetensors.torch import save_file
from torch.nn import functional as F

from siqe.ai.archs.forge import GraphNet
from siqe.ai.oom import is_oom_error, release_gpu_memory
from siqe.core.errors import AppError
from siqe.forge import datasets
from siqe.forge.degrade import Degradation, pair, to_input
from siqe.forge.training import (
    LOG_EVERY,
    MAX_NAN_STREAK,
    VAL_BATCH,
    TrainSettings,
    best_weights,
    last_checkpoint,
    lr_at,
    run_dir,
    sample_path,
)

_crops: dict[str, list[np.ndarray]] = {}


@dataclass
class RunSpec:
    run_id: str
    dataset_id: str
    plan: list[dict[str, Any]]
    scale: int
    color: str
    settings: TrainSettings
    degradation: Degradation
    # Patches must be a multiple of this (2 per Down block).
    multiple: int = 1


@dataclass
class Metric:
    step: int
    kind: str
    loss: float | None = None
    psnr: float | None = None
    ssim: float | None = None
    lr: float | None = None
    bicubic_psnr: float | None = None


@dataclass
class ChunkResult:
    step: int
    done: bool
    batch: int
    accumulate: int
    device: str
    last_loss: float | None
    best_psnr: float | None
    best_ssim: float | None
    best_step: int | None
    bicubic_psnr: float | None
    notes: list[str] = field(default_factory=list)


def load_crops(dataset_id: str, split: str) -> list[np.ndarray]:
    key = f"{dataset_id}:{split}"
    if key not in _crops:
        if len(_crops) > 4:
            _crops.clear()
        _crops[key] = [
            np.asarray(pyvips.Image.new_from_file(str(p)).numpy(), np.uint8)
            for p in datasets.crops(dataset_id, split)
        ]
    return _crops[key]


def luma(x: torch.Tensor) -> torch.Tensor:
    if x.shape[1] == 1:
        return x
    weights = torch.tensor([0.299, 0.587, 0.114], device=x.device, dtype=x.dtype).view(1, 3, 1, 1)
    return (x * weights).sum(1, keepdim=True)


def psnr(sr: torch.Tensor, hr: torch.Tensor, border: int) -> torch.Tensor:
    """PSNR on brightness, per image, ignoring a border (the usual super-resolution convention)."""
    a, b = luma(sr.clamp(0, 1)), luma(hr)
    if border:
        a, b = a[..., border:-border, border:-border], b[..., border:-border, border:-border]
    mse = ((a - b) ** 2).flatten(1).mean(1).clamp_min(1e-10)
    return 10 * torch.log10(1 / mse)


def ssim(sr: torch.Tensor, hr: torch.Tensor, border: int) -> torch.Tensor:
    a, b = luma(sr.clamp(0, 1)), luma(hr)
    if border:
        a, b = a[..., border:-border, border:-border], b[..., border:-border, border:-border]
    coords = torch.arange(11, device=a.device, dtype=a.dtype) - 5
    g = torch.exp(-(coords**2) / (2 * 1.5**2))
    g = (g / g.sum()).view(1, 1, 1, 11)
    window = (g.transpose(-1, -2) @ g).view(1, 1, 11, 11)

    def blur(t: torch.Tensor) -> torch.Tensor:
        return F.conv2d(t, window)

    mu_a, mu_b = blur(a), blur(b)
    var_a, var_b = blur(a * a) - mu_a**2, blur(b * b) - mu_b**2
    cov = blur(a * b) - mu_a * mu_b
    c1, c2 = 0.01**2, 0.03**2
    s = ((2 * mu_a * mu_b + c1) * (2 * cov + c2)) / ((mu_a**2 + mu_b**2 + c1) * (var_a + var_b + c2))
    return s.flatten(1).mean(1)


def _loss(kind: str, sr: torch.Tensor, hr: torch.Tensor) -> torch.Tensor:
    if kind == "mse":
        return F.mse_loss(sr, hr)
    if kind == "charbonnier":
        return torch.sqrt((sr - hr) ** 2 + 1e-6).mean()
    return F.l1_loss(sr, hr)


def _batch(
    crops: list[np.ndarray], n: int, spec: RunSpec, rng: np.random.Generator, device: str
) -> tuple[torch.Tensor, torch.Tensor]:
    color: Literal["rgb", "y"] = "y" if spec.color == "y" else "rgb"
    lrs, hrs = [], []
    for index in rng.integers(0, len(crops), n):
        hr, lr = pair(crops[int(index)], spec.settings.patch, spec.scale, spec.degradation, rng)
        hrs.append(to_input(hr, color))
        lrs.append(to_input(lr, color))
    return torch.from_numpy(np.stack(lrs)).to(device), torch.from_numpy(np.stack(hrs)).to(device)


def _validation_set(spec: RunSpec) -> list[tuple[np.ndarray, np.ndarray]]:
    """Fixed pairs (the same damage every time) so scores are comparable across the run."""
    crops = load_crops(spec.dataset_id, "val") or load_crops(spec.dataset_id, "train")[:8]
    pairs = []
    for index, crop in enumerate(crops):
        rng = np.random.default_rng(1_000 + index)
        patch = min(crop.shape[0], crop.shape[1]) // spec.scale
        patch -= patch % spec.multiple
        pairs.append(pair(crop, patch, spec.scale, spec.degradation, rng, train=False))
    return pairs


def _save_sample(run_id: str, lr: np.ndarray, sr: np.ndarray, hr: np.ndarray, scale: int) -> None:
    """Bicubic | model | original, side by side."""
    h, w = hr.shape[:2]
    bicubic = pyvips.Image.new_from_memory(np.ascontiguousarray(lr), lr.shape[1], lr.shape[0], 3, "uchar")
    bicubic = bicubic.resize(scale, kernel="cubic").crop(0, 0, w, h) if scale > 1 else bicubic
    gap = np.full((h, 6, 3), 18, np.uint8)
    row = np.concatenate([np.asarray(bicubic.numpy(), np.uint8).reshape(h, w, 3), gap, sr, gap, hr], 1)
    target = sample_path(run_id)
    staging = target.with_suffix(".partial.png")
    image = pyvips.Image.new_from_memory(np.ascontiguousarray(row), row.shape[1], h, 3, "uchar")
    image.pngsave(str(staging), compression=3)
    staging.replace(target)


def _to_rgb8(t: torch.Tensor, reference: np.ndarray, color: str) -> np.ndarray:
    """Model output (C×H×W) as uint8 RGB; brightness-only output borrows colour from the reference."""
    out = np.asarray(t.detach().float().clamp(0, 1).cpu().numpy(), np.float32)
    if color != "y":
        rgb8: np.ndarray = np.rint(out.transpose(1, 2, 0) * 255).astype(np.uint8)
        return rgb8
    ref = reference.astype(np.float32) / 255
    old_y = ref @ np.array([0.299, 0.587, 0.114], np.float32)
    rgb = ref + (out[0] - old_y)[..., None]
    result: np.ndarray = np.rint(np.clip(rgb, 0, 1) * 255).astype(np.uint8)
    return result


def validate(
    model: GraphNet, spec: RunSpec, device: str
) -> tuple[float, float, float, tuple[Any, ...] | None]:
    pairs = _validation_set(spec)
    color: Literal["rgb", "y"] = "y" if spec.color == "y" else "rgb"
    scores, structure, baseline = [], [], []
    first = None
    model.eval()
    with torch.no_grad():
        for start in range(0, len(pairs), VAL_BATCH):
            chunk = pairs[start : start + VAL_BATCH]
            lr = torch.from_numpy(np.stack([to_input(lr, color) for _, lr in chunk])).to(device)
            hr = torch.from_numpy(np.stack([to_input(hr, color) for hr, _ in chunk])).to(device)
            sr = model(lr).float()
            border = max(spec.scale, 2)
            scores.extend(psnr(sr, hr, border).tolist())
            structure.extend(ssim(sr, hr, border).tolist())
            up = (
                F.interpolate(lr, scale_factor=spec.scale, mode="bicubic", align_corners=False)
                if spec.scale > 1
                else lr
            )
            baseline.extend(psnr(up, hr, border).tolist())
            if first is None:
                hr0, lr0 = chunk[0]
                first = (lr0, _to_rgb8(sr[0], np.asarray(_upscaled(lr0, spec.scale)), color), hr0)
    model.train()
    return float(np.mean(scores)), float(np.mean(structure)), float(np.mean(baseline)), first


def _upscaled(lr: np.ndarray, scale: int) -> np.ndarray:
    image = pyvips.Image.new_from_memory(np.ascontiguousarray(lr), lr.shape[1], lr.shape[0], 3, "uchar")
    if scale > 1:
        image = image.resize(scale, kernel="cubic").crop(0, 0, lr.shape[1] * scale, lr.shape[0] * scale)
    return np.asarray(image.numpy(), np.uint8).reshape(image.height, image.width, 3)


def _rng_state(rng: np.random.Generator) -> dict[str, Any]:
    return {
        "numpy": rng.bit_generator.state,
        "python": random.getstate(),
        "torch": torch.get_rng_state(),
    }


def _restore_rng(state: dict[str, Any]) -> np.random.Generator:
    rng = np.random.default_rng()
    rng.bit_generator.state = state["numpy"]
    random.setstate(_tuplify(state["python"]))
    torch.set_rng_state(state["torch"])
    return rng


def _tuplify(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(_tuplify(v) for v in value)
    return value


def train_chunk(
    spec: RunSpec,
    device: str,
    budget_seconds: float,
    *,
    should_stop: Callable[[], bool],
    on_progress: Callable[[int, str], None],
    on_metric: Callable[[Metric], None],
) -> ChunkResult:
    s = spec.settings
    crops = load_crops(spec.dataset_id, "train")
    if not crops:
        raise AppError(
            "forge.dataset_empty", "The dataset has no training crops.", fix="Build the dataset again."
        )
    need = s.patch * spec.scale
    if min(crops[0].shape[:2]) < need:
        raise AppError(
            "forge.patch_too_big",
            f"Patches of {s.patch} px at ×{spec.scale} need crops of at least {need} px.",
            fix="Use a smaller patch, or rebuild the dataset with bigger crops.",
        )
    in_channels = 1 if spec.color == "y" else 3
    model = GraphNet(spec.plan, spec.scale, in_channels).to(device)
    optimiser = torch.optim.Adam(model.parameters(), lr=s.lr, betas=(0.9, 0.99))
    path = last_checkpoint(spec.run_id)
    notes: list[str] = []
    if path.exists():
        state = torch.load(path, map_location=device, weights_only=True)
        model.load_state_dict(state["model"])
        optimiser.load_state_dict(state["optimiser"])
        step, batch, accumulate = int(state["step"]), int(state["batch"]), int(state["accumulate"])
        lr_scale, nan_streak = float(state["lr_scale"]), int(state["nan_streak"])
        best = state.get("best") or {}
        bicubic = state.get("bicubic")
        rng = _restore_rng(state["rng"])
    else:
        torch.manual_seed(s.seed)
        random.seed(s.seed)
        rng = np.random.default_rng(s.seed)
        step, batch, accumulate, lr_scale, nan_streak = 0, s.batch, 1, 1.0, 0
        best, bicubic = {}, None
        run_dir(spec.run_id).mkdir(parents=True, exist_ok=True)
    use_bf16 = (
        s.precision == "auto"
        and device == "cuda"
        and torch.cuda.is_available()
        and torch.cuda.is_bf16_supported()
    )
    model.train()
    started = time.monotonic()
    saved_step = step if path.exists() else -1
    losses: list[float] = []
    last_loss: float | None = None

    def save() -> None:
        state = {
            "model": model.state_dict(),
            "optimiser": optimiser.state_dict(),
            "step": step,
            "batch": batch,
            "accumulate": accumulate,
            "lr_scale": lr_scale,
            "nan_streak": nan_streak,
            "best": best,
            "bicubic": bicubic,
            "rng": _rng_state(rng),
        }
        buffer = io.BytesIO()
        torch.save(state, buffer)
        staging = path.with_suffix(".partial")
        staging.write_bytes(buffer.getvalue())
        staging.replace(path)

    def run_validation() -> None:
        nonlocal best, bicubic
        score, structure, baseline, sample = validate(model, spec, device)
        bicubic = baseline
        on_metric(Metric(step, "val", psnr=score, ssim=structure, bicubic_psnr=baseline))
        if not best or score > best["psnr"]:
            best = {"psnr": score, "ssim": structure, "step": step}
            target = best_weights(spec.run_id)
            staging = target.with_suffix(".partial")
            weights = {k: v.detach().cpu().contiguous() for k, v in model.state_dict().items()}
            save_file(weights, str(staging))
            staging.replace(target)
            if sample is not None:
                _save_sample(spec.run_id, sample[0], sample[1], sample[2], spec.scale)

    while step < s.steps:
        if should_stop():
            break
        if time.monotonic() - started > budget_seconds:
            break
        lr = lr_at(step, s) * lr_scale
        for group in optimiser.param_groups:
            group["lr"] = lr
        optimiser.zero_grad(set_to_none=True)
        total = 0.0
        try:
            for _ in range(accumulate):
                lr_t, hr_t = _batch(crops, batch, spec, rng, device)
                with torch.autocast(device_type="cuda", dtype=torch.bfloat16, enabled=use_bf16):
                    sr = model(lr_t)
                loss = _loss(s.loss, sr.float(), hr_t) / accumulate
                loss.backward()
                total += float(loss.detach())
        except Exception as exc:
            if not is_oom_error(exc):
                raise
            optimiser.zero_grad(set_to_none=True)
            release_gpu_memory()
            if batch == 1:
                raise AppError(
                    "forge.out_of_memory",
                    "This model doesn't fit in GPU memory even one patch at a time.",
                    fix="Use a smaller patch or fewer channels, or close other programs using the GPU.",
                ) from exc
            batch //= 2
            accumulate *= 2
            notes.append(f"GPU memory ran out at step {step}: now {batch} patches × {accumulate} accumulated")
            continue
        if not np.isfinite(total):
            optimiser.zero_grad(set_to_none=True)
            nan_streak += 1
            lr_scale *= 0.5
            notes.append(f"Step {step} gave a non-finite loss; skipped it and halved the learning rate")
            if nan_streak >= MAX_NAN_STREAK:
                raise AppError(
                    "forge.diverged",
                    f"Training became unstable: {MAX_NAN_STREAK} steps in a row gave non-finite losses.",
                    fix="Lower the learning rate, or use L1 loss.",
                )
            continue
        nan_streak = 0
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimiser.step()
        step += 1
        losses.append(total)
        last_loss = total
        if step % LOG_EVERY == 0 or step == s.steps:
            on_metric(Metric(step, "train", loss=float(np.mean(losses)), lr=lr))
            losses = []
        on_progress(step, f"Step {step:,} of {s.steps:,}")
        if step % s.val_every == 0 or step == s.steps:
            run_validation()
            save()
            saved_step = step
    if step != saved_step:
        save()
    return ChunkResult(
        step=step,
        done=step >= s.steps,
        batch=batch,
        accumulate=accumulate,
        device=device,
        last_loss=last_loss,
        best_psnr=best.get("psnr"),
        best_ssim=best.get("ssim"),
        best_step=best.get("step"),
        bicubic_psnr=bicubic,
        notes=notes,
    )
