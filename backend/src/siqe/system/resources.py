"""Container-aware CPU, memory and disk readings.

Inside Docker, ``psutil`` reports the host's totals. The limits that actually apply to us
come from cgroups, so every reading here takes the smaller of the two.
"""

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import psutil

CGROUP_ROOT = Path("/sys/fs/cgroup")
_UNLIMITED = 1 << 60  # cgroup v1 reports "unlimited" as a huge number


def _read(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except OSError:
        return None


def cgroup_memory_limit(root: Path = CGROUP_ROOT) -> int | None:
    for raw in (_read(root / "memory.max"), _read(root / "memory" / "memory.limit_in_bytes")):
        if raw is None:
            continue
        if raw == "max":
            return None
        try:
            value = int(raw)
        except ValueError:
            continue
        return None if value >= _UNLIMITED else value
    return None


def cgroup_memory_usage(root: Path = CGROUP_ROOT) -> int | None:
    for raw in (_read(root / "memory.current"), _read(root / "memory" / "memory.usage_in_bytes")):
        if raw is not None:
            try:
                return int(raw)
            except ValueError:
                continue
    return None


def cgroup_cpu_limit(root: Path = CGROUP_ROOT) -> float | None:
    raw = _read(root / "cpu.max")
    if raw:
        quota, _, period = raw.partition(" ")
        if quota != "max" and period:
            return int(quota) / int(period)
    return None


@dataclass(frozen=True)
class MemoryInfo:
    total_bytes: int
    available_bytes: int
    limited_by_container: bool


@dataclass(frozen=True)
class DiskInfo:
    path: str
    total_bytes: int
    free_bytes: int

    @property
    def free_ratio(self) -> float:
        return self.free_bytes / self.total_bytes if self.total_bytes else 0.0


@dataclass(frozen=True)
class CpuInfo:
    logical_cores: int
    usable_cores: float
    load_percent: float


def memory_info(root: Path = CGROUP_ROOT) -> MemoryInfo:
    vm = psutil.virtual_memory()
    limit = cgroup_memory_limit(root)
    if limit is None or limit >= vm.total:
        return MemoryInfo(vm.total, vm.available, limited_by_container=False)
    used = cgroup_memory_usage(root) or 0
    return MemoryInfo(limit, max(0, min(vm.available, limit - used)), limited_by_container=True)


def disk_info(path: Path) -> DiskInfo:
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    usage = psutil.disk_usage(str(probe))
    return DiskInfo(str(path), usage.total, usage.free)


def cpu_info(root: Path = CGROUP_ROOT) -> CpuInfo:
    logical = os.cpu_count() or 1
    quota = cgroup_cpu_limit(root)
    usable = min(float(logical), quota) if quota else float(logical)
    return CpuInfo(logical, round(usable, 2), psutil.cpu_percent(interval=None))


def snapshot(data_dir: Path) -> dict[str, Any]:
    disk = disk_info(data_dir)
    return {
        "cpu": asdict(cpu_info()),
        "memory": asdict(memory_info()),
        "disk": {**asdict(disk), "free_ratio": round(disk.free_ratio, 4)},
    }
