"""Unit tests for `normexec.resources` — Phase 3 of the throughput/memory
program. cgroup files are faked via real temp files rather than mocking
`Path.read_text`, so the parsing logic is exercised against real file I/O,
not a mock's idea of what a cgroup file contains.
"""

from __future__ import annotations

import os
from pathlib import Path

import psutil
import pytest
from normexec.resources import detect_cpu_quota, detect_memory_limit_bytes

_HOST_CPUS = os.cpu_count() or 1


@pytest.mark.unit
def test_cpu_quota_falls_back_to_host_cpu_count_when_no_cgroup_files_exist(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "does-not-exist"
    quota = detect_cpu_quota(v2_cpu_max=missing, v1_cpu_quota=missing, v1_cpu_period=missing)
    assert quota == _HOST_CPUS


@pytest.mark.unit
def test_cpu_quota_reads_cgroup_v2_when_more_restrictive_than_host(tmp_path: Path) -> None:
    cpu_max = tmp_path / "cpu.max"
    cpu_max.write_text("200000 100000\n")  # 2.0 CPUs
    quota = detect_cpu_quota(
        v2_cpu_max=cpu_max, v1_cpu_quota=tmp_path / "x", v1_cpu_period=tmp_path / "y"
    )
    assert quota == 2


@pytest.mark.unit
def test_cpu_quota_treats_v2_max_string_as_unlimited(tmp_path: Path) -> None:
    cpu_max = tmp_path / "cpu.max"
    cpu_max.write_text("max 100000\n")
    quota = detect_cpu_quota(
        v2_cpu_max=cpu_max, v1_cpu_quota=tmp_path / "x", v1_cpu_period=tmp_path / "y"
    )
    assert quota == _HOST_CPUS


@pytest.mark.unit
def test_cpu_quota_never_exceeds_host_cpu_count(tmp_path: Path) -> None:
    """A cgroup quota larger than the host's real CPU count (e.g. a
    misconfigured or stale limit) must never be reported as available —
    the host is the hard ceiling."""
    cpu_max = tmp_path / "cpu.max"
    cpu_max.write_text(f"{(_HOST_CPUS + 100) * 100000} 100000\n")
    quota = detect_cpu_quota(
        v2_cpu_max=cpu_max, v1_cpu_quota=tmp_path / "x", v1_cpu_period=tmp_path / "y"
    )
    assert quota == _HOST_CPUS


@pytest.mark.unit
def test_cpu_quota_falls_back_to_v1_when_v2_absent(tmp_path: Path) -> None:
    v2 = tmp_path / "cpu.max"  # does not exist
    quota_file = tmp_path / "cpu.cfs_quota_us"
    period_file = tmp_path / "cpu.cfs_period_us"
    quota_file.write_text("400000\n")
    period_file.write_text("100000\n")
    quota = detect_cpu_quota(v2_cpu_max=v2, v1_cpu_quota=quota_file, v1_cpu_period=period_file)
    assert quota == min(4, _HOST_CPUS)


@pytest.mark.unit
def test_cpu_quota_treats_v1_negative_quota_as_unlimited(tmp_path: Path) -> None:
    """cgroup v1 uses `-1` in cpu.cfs_quota_us for "no limit", not a
    sentinel string the way v2 uses "max"."""
    v2 = tmp_path / "cpu.max"
    quota_file = tmp_path / "cpu.cfs_quota_us"
    period_file = tmp_path / "cpu.cfs_period_us"
    quota_file.write_text("-1\n")
    period_file.write_text("100000\n")
    quota = detect_cpu_quota(v2_cpu_max=v2, v1_cpu_quota=quota_file, v1_cpu_period=period_file)
    assert quota == _HOST_CPUS


@pytest.mark.unit
def test_cpu_quota_always_at_least_one(tmp_path: Path) -> None:
    cpu_max = tmp_path / "cpu.max"
    cpu_max.write_text("1000 100000\n")  # 0.01 CPUs, rounds down to 0 before the floor
    quota = detect_cpu_quota(
        v2_cpu_max=cpu_max, v1_cpu_quota=tmp_path / "x", v1_cpu_period=tmp_path / "y"
    )
    assert quota >= 1


@pytest.mark.unit
def test_memory_limit_falls_back_to_host_total_when_no_cgroup_files_exist(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "does-not-exist"
    limit = detect_memory_limit_bytes(v2_memory_max=missing, v1_memory_limit=missing)
    assert limit == psutil.virtual_memory().total


@pytest.mark.unit
def test_memory_limit_reads_cgroup_v2_when_more_restrictive_than_host(tmp_path: Path) -> None:
    memory_max = tmp_path / "memory.max"
    memory_max.write_text("536870912\n")  # 512 MiB
    limit = detect_memory_limit_bytes(v2_memory_max=memory_max, v1_memory_limit=tmp_path / "x")
    assert limit == 536870912


@pytest.mark.unit
def test_memory_limit_treats_v2_max_string_as_unlimited(tmp_path: Path) -> None:
    memory_max = tmp_path / "memory.max"
    memory_max.write_text("max\n")
    limit = detect_memory_limit_bytes(v2_memory_max=memory_max, v1_memory_limit=tmp_path / "x")
    assert limit == psutil.virtual_memory().total


@pytest.mark.unit
def test_memory_limit_treats_v1_platform_max_sentinel_as_unlimited(tmp_path: Path) -> None:
    v2 = tmp_path / "memory.max"  # does not exist
    v1 = tmp_path / "memory.limit_in_bytes"
    v1.write_text("9223372036854771712\n")  # real cgroup v1 "unlimited" sentinel
    limit = detect_memory_limit_bytes(v2_memory_max=v2, v1_memory_limit=v1)
    assert limit == psutil.virtual_memory().total


@pytest.mark.unit
def test_memory_limit_never_exceeds_host_total(tmp_path: Path) -> None:
    host_total = psutil.virtual_memory().total
    memory_max = tmp_path / "memory.max"
    memory_max.write_text(str(host_total * 10) + "\n")
    limit = detect_memory_limit_bytes(v2_memory_max=memory_max, v1_memory_limit=tmp_path / "x")
    assert limit == host_total
