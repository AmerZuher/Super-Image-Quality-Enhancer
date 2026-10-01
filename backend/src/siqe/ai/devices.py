"""GPU discovery. Works without a GPU, without NVML and without PyTorch installed."""

import contextlib
from typing import Any

from siqe.core.logging import get_logger

log = get_logger(__name__)


def nvml_devices() -> list[dict[str, Any]]:
    """Per-GPU name, memory and utilisation via NVML. Empty list when unavailable."""
    try:
        import pynvml
    except ImportError:
        return []
    try:
        pynvml.nvmlInit()
    except Exception:  # no driver or no GPU passed into the container
        return []
    devices: list[dict[str, Any]] = []
    try:
        driver = pynvml.nvmlSystemGetDriverVersion()
        for index in range(pynvml.nvmlDeviceGetCount()):
            handle = pynvml.nvmlDeviceGetHandleByIndex(index)
            mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
            try:
                util = pynvml.nvmlDeviceGetUtilizationRates(handle).gpu
            except Exception:
                util = None
            try:
                temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
            except Exception:
                temp = None
            name = pynvml.nvmlDeviceGetName(handle)
            devices.append(
                {
                    "index": index,
                    "name": name.decode() if isinstance(name, bytes) else name,
                    "memory_total_bytes": int(mem.total),
                    "memory_used_bytes": int(mem.used),
                    "memory_free_bytes": int(mem.free),
                    "utilization_percent": util,
                    "temperature_c": temp,
                    "driver_version": driver.decode() if isinstance(driver, bytes) else driver,
                }
            )
    except Exception as exc:
        log.warning("gpu.nvml_failed", error=str(exc))
    finally:
        with contextlib.suppress(Exception):
            pynvml.nvmlShutdown()
    return devices


def torch_runtime() -> dict[str, Any]:
    """What PyTorch can use in this process."""
    try:
        import torch
    except ImportError:
        return {"available": False, "cuda": False}
    cuda = bool(torch.cuda.is_available())
    info: dict[str, Any] = {
        "available": True,
        "version": torch.__version__,
        "cuda": cuda,
        "cuda_version": torch.version.cuda,
    }
    if cuda:
        info["device_count"] = torch.cuda.device_count()
        info["bf16"] = bool(torch.cuda.is_bf16_supported())
        major, minor = torch.cuda.get_device_capability(0)
        info["compute_capability"] = f"{major}.{minor}"
    return info
