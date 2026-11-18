"""Container-aware CPU and memory budgets; no provider or network access."""

import os
from pathlib import Path


def cpu_count():
    count = os.cpu_count() or 1
    try:
        count = min(count, len(os.sched_getaffinity(0)))
    except (AttributeError, OSError):
        pass
    try:
        quota, period = Path("/sys/fs/cgroup/cpu.max").read_text().split()
        if quota != "max":
            count = min(count, max(1, int(quota) // int(period)))
    except (OSError, ValueError):
        pass
    return max(1, count)


def memory_available():
    limits = []
    try:
        limit = Path("/sys/fs/cgroup/memory.max").read_text().strip()
        used = int(Path("/sys/fs/cgroup/memory.current").read_text())
        if limit != "max":
            limits.append(max(0, int(limit) - used))
    except (OSError, ValueError):
        pass
    try:
        values = dict(
            line.split(":", 1)
            for line in Path("/proc/meminfo").read_text().splitlines()
        )
        limits.append(int(values["MemAvailable"].split()[0]) * 1024)
    except (OSError, ValueError, KeyError):
        pass
    return min(limits) if limits else None


def render_workers():
    cpus = cpu_count()
    desired = max(1, min(4, cpus - 1))
    explicit = os.environ.get("RENDER_WORKERS", "").strip()
    if explicit:
        desired = max(1, min(16, int(explicit), cpus))
    memory = memory_available()
    if memory is not None:
        desired = min(desired, max(1, (memory - 512 * 1024**2) // (384 * 1024**2)))
    return desired
