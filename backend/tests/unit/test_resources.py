from pathlib import Path

from siqe.system.resources import cgroup_cpu_limit, cgroup_memory_limit, cgroup_memory_usage, disk_info


def test_cgroup_v2_limits(tmp_path: Path) -> None:
    (tmp_path / "memory.max").write_text("2147483648\n")
    (tmp_path / "memory.current").write_text("1073741824\n")
    (tmp_path / "cpu.max").write_text("200000 100000\n")
    assert cgroup_memory_limit(tmp_path) == 2 * 1024**3
    assert cgroup_memory_usage(tmp_path) == 1024**3
    assert cgroup_cpu_limit(tmp_path) == 2.0


def test_cgroup_unlimited(tmp_path: Path) -> None:
    (tmp_path / "memory.max").write_text("max\n")
    (tmp_path / "cpu.max").write_text("max 100000\n")
    assert cgroup_memory_limit(tmp_path) is None
    assert cgroup_cpu_limit(tmp_path) is None


def test_cgroup_v1_unlimited_sentinel(tmp_path: Path) -> None:
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "memory.limit_in_bytes").write_text("9223372036854771712\n")
    assert cgroup_memory_limit(tmp_path) is None


def test_no_cgroup_files(tmp_path: Path) -> None:
    assert cgroup_memory_limit(tmp_path) is None
    assert cgroup_cpu_limit(tmp_path) is None


def test_disk_info_walks_up_to_an_existing_directory(tmp_path: Path) -> None:
    info = disk_info(tmp_path / "does" / "not" / "exist")
    assert info.total_bytes > 0
    assert 0 < info.free_ratio <= 1
