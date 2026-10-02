"""Planning an AI run before it is queued: output size, device, tiles, memory and disk.

The API has no torch, so it plans from the GPU worker's last heartbeat (which GPU, how much
memory is free) and the model's stored calibration. The worker re-plans with live numbers
when the run starts, and the fallback ladder covers any difference.
"""

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from siqe.ai.governor import Calibration, choose_settings, cpu_settings, estimate_tiles
from siqe.ai.manifest import ModelSpec
from siqe.db.base import utcnow
from siqe.db.models import WorkerHeartbeat
from siqe.imaging.formats import OUTPUT_FORMATS

DevicePreference = Literal["auto", "cpu"]


@dataclass(frozen=True)
class DeviceInfo:
    kind: Literal["cuda", "cpu"]
    name: str
    free_bytes: float | None
    worker_online: bool

    @property
    def key(self) -> str:
        return f"cuda:{self.name}" if self.kind == "cuda" else "cpu"


def device_key(kind: str, name: str) -> str:
    return f"cuda:{name}" if kind == "cuda" else "cpu"


async def current_device(
    session: AsyncSession, preference: DevicePreference, heartbeat_s: float
) -> DeviceInfo:
    """What the GPU worker last reported. CPU when there is no usable GPU or it was asked for."""
    cutoff = utcnow() - timedelta(seconds=heartbeat_s * 3)
    rows = (
        await session.execute(
            select(WorkerHeartbeat)
            .where(WorkerHeartbeat.kind == "gpu")
            .order_by(WorkerHeartbeat.last_seen.desc())
        )
    ).scalars()
    worker = next((w for w in rows if w.last_seen >= cutoff), None)
    online = worker is not None
    if preference == "cpu" or worker is None or not (worker.info.get("torch") or {}).get("cuda"):
        return DeviceInfo("cpu", "CPU", None, online)
    gpus = worker.info.get("gpus") or []
    name = gpus[0]["name"] if gpus else "GPU"
    free = float(gpus[0]["memory_free_bytes"]) if gpus else None
    return DeviceInfo("cuda", name, free, online)


def output_size(spec: ModelSpec, width: int, height: int) -> tuple[int, int]:
    return width * spec.scale, height * spec.scale


def plan_run(
    spec: ModelSpec,
    *,
    width: int,
    height: int,
    bit_depth: int,
    has_alpha: bool,
    device: DeviceInfo,
    calibration: Calibration | None,
    reserve_mb: int,
) -> dict[str, Any]:
    out_w, out_h = output_size(spec, width, height)
    alpha = has_alpha or spec.task == "background"
    channels = 4 if alpha else 3
    sample_bytes = 2 if bit_depth == 16 else 1
    raw_bytes = out_w * out_h * channels * sample_bytes
    tiled = spec.task != "background"
    if not tiled:
        settings = None
    elif device.kind == "cuda":
        free = (device.free_bytes or 0) - reserve_mb * 1024 * 1024
        settings = choose_settings(
            calibration, free, width=width, height=height, context=spec.context, multiple=1
        )
    else:
        settings = cpu_settings(width=width, height=height, context=spec.context, multiple=1)
    warnings: list[str] = []
    if not device.worker_online:
        warnings.append("The AI worker is offline. The run will start when it's back.")
    if device.kind == "cpu" and tiled and spec.speed != "fast" and width * height > 2_000_000:
        warnings.append(
            f"No GPU: {spec.name} will be slow on the CPU. Real-ESRGAN General v3 is much faster."
        )
    for fmt in ("webp", "avif"):
        limit = OUTPUT_FORMATS[fmt].max_side
        if max(out_w, out_h) > limit:
            warnings.append(
                f"The result is wider than {limit:,} px, so it can't be exported as {fmt.upper()}."
            )
            break
    return {
        "model_id": spec.id,
        "task": spec.task,
        "scale": spec.scale,
        "device": device.kind,
        "device_name": device.name,
        "input_width": width,
        "input_height": height,
        "output_width": out_w,
        "output_height": out_h,
        "output_megapixels": round(out_w * out_h / 1e6, 1),
        "bit_depth": 16 if bit_depth == 16 else 8,
        "has_alpha": alpha,
        "tile": settings.tile if settings else None,
        "batch": settings.batch if settings else None,
        "tiles": estimate_tiles(width, height, settings.tile) if settings else 1,
        "calibrated": calibration is not None,
        "estimated_memory_bytes": (
            calibration.bytes_for(settings.tile + 2 * spec.context, settings.batch)
            if calibration and settings and device.kind == "cuda"
            else None
        ),
        "disk_bytes": raw_bytes * 2,
        "warnings": warnings,
    }
