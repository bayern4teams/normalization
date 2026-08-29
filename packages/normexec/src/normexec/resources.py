"""Container-aware CPU and memory limit detection — Source.txt-independent
infrastructure for the throughput/memory program's Phase 3 process pool.

Non-negotiable per that program's plan: worker count and memory budget
must be read from the environment at startup, never hardcoded or tuned to
one machine. `os.cpu_count()` reports the HOST's logical CPUs even inside
a cgroup CPU-quota-limited container — a silent overcommit hazard this
module exists to close, by reading cgroup v2 first (`/sys/fs/cgroup/cpu.max`,
`/sys/fs/cgroup/memory.max`), falling back to cgroup v1, and falling back
again to the host's own reported limits (`os.cpu_count()`, `psutil`) when
no cgroup applies at all — the common case on a bare dev machine, which is
where this module's own test suite runs.
"""

from __future__ import annotations

import math
import os
from pathlib import Path

import psutil

CGROUP_V2_CPU_MAX = Path("/sys/fs/cgroup/cpu.max")
CGROUP_V2_MEMORY_MAX = Path("/sys/fs/cgroup/memory.max")
CGROUP_V1_CPU_QUOTA = Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us")
CGROUP_V1_CPU_PERIOD = Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us")
CGROUP_V1_MEMORY_LIMIT = Path("/sys/fs/cgroup/memory/memory.limit_in_bytes")

# cgroup v1's memory.limit_in_bytes reports a huge platform-max sentinel
# instead of the string "max" v2 uses for "unlimited" — anything at or
# above this is treated as no limit.
_V1_UNLIMITED_MEMORY_THRESHOLD = 1 << 62


def detect_cpu_quota(
    *,
    v2_cpu_max: Path = CGROUP_V2_CPU_MAX,
    v1_cpu_quota: Path = CGROUP_V1_CPU_QUOTA,
    v1_cpu_period: Path = CGROUP_V1_CPU_PERIOD,
) -> int:
    """CPUs this process may actually use concurrently: the cgroup quota
    if one applies and is more restrictive than the host, else the host's
    own logical CPU count. Always >= 1."""
    host_cpus = os.cpu_count() or 1
    quota = _read_cgroup_v2_cpu_quota(v2_cpu_max) or _read_cgroup_v1_cpu_quota(
        v1_cpu_quota, v1_cpu_period
    )
    if quota is None:
        return host_cpus
    return max(1, min(host_cpus, quota))


def detect_memory_limit_bytes(
    *,
    v2_memory_max: Path = CGROUP_V2_MEMORY_MAX,
    v1_memory_limit: Path = CGROUP_V1_MEMORY_LIMIT,
) -> int:
    """Memory budget available to this process: the cgroup limit if one
    applies and is more restrictive than the host, else the host's total
    physical memory (via `psutil` — `os` has no portable equivalent)."""
    host_bytes: int = psutil.virtual_memory().total
    limit = _read_cgroup_v2_memory_limit(v2_memory_max) or _read_cgroup_v1_memory_limit(
        v1_memory_limit
    )
    if limit is None:
        return host_bytes
    return min(host_bytes, limit)


def _read_cgroup_v2_cpu_quota(path: Path) -> int | None:
    raw = _read_text(path)
    if raw is None:
        return None
    quota_str, _, period_str = raw.partition(" ")
    if quota_str == "max":
        return None
    try:
        quota, period = int(quota_str), int(period_str)
    except ValueError:
        return None
    if period <= 0:
        return None
    return max(1, math.floor(quota / period))


def _read_cgroup_v1_cpu_quota(quota_path: Path, period_path: Path) -> int | None:
    quota_raw = _read_text(quota_path)
    period_raw = _read_text(period_path)
    if quota_raw is None or period_raw is None:
        return None
    try:
        quota, period = int(quota_raw), int(period_raw)
    except ValueError:
        return None
    if quota <= 0 or period <= 0:
        return None
    return max(1, math.floor(quota / period))


def _read_cgroup_v2_memory_limit(path: Path) -> int | None:
    raw = _read_text(path)
    if raw is None or raw == "max":
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _read_cgroup_v1_memory_limit(path: Path) -> int | None:
    raw = _read_text(path)
    if raw is None:
        return None
    try:
        limit = int(raw)
    except ValueError:
        return None
    if limit >= _V1_UNLIMITED_MEMORY_THRESHOLD:
        return None
    return limit


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except OSError:
        return None
