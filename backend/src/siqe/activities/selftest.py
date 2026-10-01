"""System self-test: proves the whole pipeline (API → Temporal → CPU and GPU workers → events).

The GPU half doubles as a hardware check: it measures matrix-multiply throughput and the
largest size that fits in VRAM, using the same OOM halving the AI tasks will use.
"""

import asyncio
import platform
import time
from pathlib import Path
from typing import Any

from temporalio import activity

from siqe.ai.devices import nvml_devices, torch_runtime
from siqe.ai.oom import InsufficientMemoryError, release_gpu_memory, run_with_halving
from siqe.core.config import get_settings
from siqe.jobs.progress import ProgressReporter
from siqe.system.resources import snapshot


def _libvips_benchmark(size: int = 4096) -> dict[str, Any]:
    import pyvips

    start = time.perf_counter()
    image = pyvips.Image.gaussnoise(size, size, mean=128, sigma=30).gaussblur(2.0)
    mean = image.avg()  # forces evaluation, streamed in small regions
    elapsed = time.perf_counter() - start
    return {
        "libvips": f"{pyvips.version(0)}.{pyvips.version(1)}.{pyvips.version(2)}",
        "blur_megapixels": round(size * size / 1e6, 1),
        "seconds": round(elapsed, 3),
        "mean": round(float(mean), 2),
    }


@activity.defn
async def cpu_probe(job_id: str) -> dict[str, Any]:
    reporter = ProgressReporter(job_id, start=0.0, span=0.4)
    settings = get_settings()
    await reporter.report(0.1, "Checking CPU, memory and disk", force=True)
    system = await asyncio.to_thread(snapshot, settings.data_dir)
    await reporter.report(0.4, "Running an image-processing benchmark")
    vips = await asyncio.to_thread(_libvips_benchmark)
    writable = await asyncio.to_thread(data_dir_writable)
    await reporter.report(1.0, "CPU checks passed", force=True)
    return {
        "python": platform.python_version(),
        "system": system,
        "imaging": vips,
        "data_dir_writable": writable,
    }


def _matmul_tflops(size: int, device: str, dtype_name: str, repeats: int = 8) -> float:
    import torch

    dtype = getattr(torch, dtype_name)
    a = torch.randn(size, size, device=device, dtype=dtype)
    b = torch.randn(size, size, device=device, dtype=dtype)
    try:
        torch.matmul(a, b)  # warm-up
        if device == "cuda":
            torch.cuda.synchronize()
        start = time.perf_counter()
        for _ in range(repeats):
            torch.matmul(a, b)
        if device == "cuda":
            torch.cuda.synchronize()
        elapsed = time.perf_counter() - start
    finally:
        del a, b
    return 2 * size**3 * repeats / elapsed / 1e12


@activity.defn
async def gpu_probe(job_id: str) -> dict[str, Any]:
    reporter = ProgressReporter(job_id, start=0.4, span=0.6)
    await reporter.report(0.0, "Detecting GPU", force=True)
    runtime = await asyncio.to_thread(torch_runtime)
    devices = await asyncio.to_thread(nvml_devices)
    result: dict[str, Any] = {"runtime": runtime, "devices": devices, "benchmarks": []}

    if not runtime.get("available"):
        await reporter.report(1.0, "PyTorch is not installed in this worker; skipped GPU checks", force=True)
        result["device"] = "none"
        return result

    cuda = bool(runtime.get("cuda"))
    device = "cuda" if cuda else "cpu"
    dtype = "float16" if cuda else "float32"
    sizes = [1024, 2048, 4096, 8192, 16384] if cuda else [512, 1024, 2048]
    result["device"] = device
    if cuda:
        import torch

        free, total = torch.cuda.mem_get_info()
        result["vram"] = {"free_bytes": int(free), "total_bytes": int(total)}
        result["device_name"] = torch.cuda.get_device_name(0)

    largest_ok = 0
    for index, requested in enumerate(sizes):
        await reporter.report(
            index / len(sizes), f"Matrix multiply {requested}x{requested} on {device.upper()}"
        )
        try:
            tflops, used = await asyncio.to_thread(
                run_with_halving,
                lambda s: _matmul_tflops(s, device, dtype),
                requested,
                minimum=max(256, requested // 4),
            )
        except InsufficientMemoryError:
            result["benchmarks"].append({"size": requested, "status": "out_of_memory"})
            break
        largest_ok = max(largest_ok, used)
        result["benchmarks"].append({"size": used, "dtype": dtype, "tflops": round(tflops, 2)})
        if used < requested:
            break  # VRAM ceiling reached; larger sizes would only fail
    await asyncio.to_thread(release_gpu_memory)

    best = max((b.get("tflops", 0.0) for b in result["benchmarks"]), default=0.0)
    result["peak_tflops"] = best
    result["largest_matrix"] = largest_ok
    label = result.get("device_name") or "CPU"
    await reporter.report(1.0, f"{label}: {best:.1f} TFLOPS {dtype}", force=True)
    return result


def data_dir_writable() -> bool:
    probe = Path(get_settings().data_dir) / ".write-test"
    try:
        probe.parent.mkdir(parents=True, exist_ok=True)
        probe.write_text("ok")
        probe.unlink()
        return True
    except OSError:
        return False
