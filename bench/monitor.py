"""Resource monitoring: Chrome process tree (psutil) + container cgroup metrics."""

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import psutil


# --- cgroup v2 readers ---

CGROUP_MEMORY_CURRENT = Path("/sys/fs/cgroup/memory.current")
CGROUP_MEMORY_PEAK = Path("/sys/fs/cgroup/memory.peak")
CGROUP_MEMORY_STAT = Path("/sys/fs/cgroup/memory.stat")
CGROUP_CPU_STAT = Path("/sys/fs/cgroup/cpu.stat")


def _read_int(path: Path) -> int:
    try:
        return int(path.read_text().strip())
    except (FileNotFoundError, ValueError):
        return -1


def _read_cpu_usage_usec() -> int:
    """Read total CPU usage in microseconds from cgroup cpu.stat."""
    try:
        for line in CGROUP_CPU_STAT.read_text().splitlines():
            if line.startswith("usage_usec"):
                return int(line.split()[1])
    except (FileNotFoundError, ValueError):
        pass
    return -1


def _read_memory_stat() -> dict[str, int]:
    """Read key fields from cgroup memory.stat."""
    result = {}
    try:
        for line in CGROUP_MEMORY_STAT.read_text().splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[0] in ("anon", "file", "kernel", "shmem", "sock"):
                result[parts[0]] = int(parts[1])
    except (FileNotFoundError, ValueError):
        pass
    return result


# --- Data classes ---

@dataclass
class Sample:
    timestamp: float
    wall_clock: str
    # Chrome process tree (psutil)
    chrome_num_processes: int
    chrome_rss_bytes: int
    chrome_uss_bytes: int
    chrome_cpu_percent: float
    # Container cgroup
    cgroup_memory_bytes: int
    cgroup_cpu_usec: int
    cgroup_anon_bytes: int
    cgroup_file_bytes: int
    cgroup_kernel_bytes: int


@dataclass
class MonitorResult:
    samples: list[Sample] = field(default_factory=list)
    # Chrome process tree aggregates
    chrome_peak_rss_bytes: int = 0
    chrome_avg_rss_bytes: float = 0.0
    chrome_peak_uss_bytes: int = 0
    chrome_avg_uss_bytes: float = 0.0
    chrome_peak_cpu_percent: float = 0.0
    chrome_avg_cpu_percent: float = 0.0
    # Container cgroup aggregates
    cgroup_peak_memory_bytes: int = 0       # memory.current (includes page cache)
    cgroup_avg_memory_bytes: float = 0.0
    cgroup_peak_active_bytes: int = 0       # anon + kernel (non-reclaimable)
    cgroup_avg_active_bytes: float = 0.0
    cgroup_cpu_total_usec: int = 0
    # Baselines (for computing per-URL deltas)
    cgroup_memory_baseline_bytes: int = 0
    cgroup_active_baseline_bytes: int = 0
    # Timing
    duration_s: float = 0.0
    # Chrome process-tree total CPU seconds (user+system delta, matches headless-research cpu_time_s)
    chrome_cpu_time_s: float = 0.0


def _sample_chrome_tree(proc: psutil.Process) -> tuple[int, int, int, float]:
    """Sample Chrome process tree. Returns (num_procs, total_rss, total_uss, total_cpu_secs)."""
    try:
        children = proc.children(recursive=True)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return (0, 0, 0, 0.0)

    all_procs = [proc] + children
    total_rss = 0
    total_uss = 0
    total_cpu_secs = 0.0
    live = 0

    for p in all_procs:
        try:
            mem = p.memory_full_info()
            total_rss += mem.rss
            total_uss += mem.uss
            ct = p.cpu_times()
            total_cpu_secs += ct.user + ct.system
            live += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            try:
                mem = p.memory_info()
                total_rss += mem.rss
                ct = p.cpu_times()
                total_cpu_secs += ct.user + ct.system
                live += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

    return (live, total_rss, total_uss, total_cpu_secs)


async def monitor_process_tree(
    pid: int,
    interval_s: float,
    stop_event: asyncio.Event,
) -> MonitorResult:
    """Monitor Chrome process tree + container cgroup until stop_event is set."""
    try:
        proc = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return MonitorResult()

    # Record cgroup baselines for delta calculation
    cpu_usec_start = _read_cpu_usage_usec()
    memory_baseline = _read_int(CGROUP_MEMORY_CURRENT)
    mem_stat_base = _read_memory_stat()
    active_baseline = (
        mem_stat_base.get("anon", 0) + mem_stat_base.get("kernel", 0)
        if mem_stat_base.get("anon", -1) >= 0 and mem_stat_base.get("kernel", -1) >= 0
        else 0
    )

    # Take baseline reading for CPU time delta computation
    prev_cpu_secs = 0.0
    start_cpu_secs = 0.0
    prev_time = time.monotonic()
    baseline = _sample_chrome_tree(proc)
    if baseline[0] > 0:
        prev_cpu_secs = baseline[3]
        start_cpu_secs = baseline[3]

    await asyncio.sleep(interval_s)

    samples: list[Sample] = []
    t0 = time.monotonic()

    while not stop_event.is_set():
        num_procs, rss, uss, cpu_secs = _sample_chrome_tree(proc)
        if num_procs > 0:
            now = time.monotonic()
            dt = now - prev_time
            cpu_pct = max(0.0, ((cpu_secs - prev_cpu_secs) / dt) * 100) if dt > 0 else 0.0
            prev_cpu_secs = cpu_secs
            prev_time = now

            mem_stat = _read_memory_stat()
            samples.append(Sample(
                timestamp=now,
                wall_clock=datetime.now(timezone.utc).isoformat(),
                chrome_num_processes=num_procs,
                chrome_rss_bytes=rss,
                chrome_uss_bytes=uss,
                chrome_cpu_percent=cpu_pct,
                cgroup_memory_bytes=_read_int(CGROUP_MEMORY_CURRENT),
                cgroup_cpu_usec=_read_cpu_usage_usec(),
                cgroup_anon_bytes=mem_stat.get("anon", -1),
                cgroup_file_bytes=mem_stat.get("file", -1),
                cgroup_kernel_bytes=mem_stat.get("kernel", -1),
            ))
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_s)
        except asyncio.TimeoutError:
            pass

    # One final sample after stop
    num_procs, rss, uss, cpu_secs = _sample_chrome_tree(proc)
    if num_procs > 0:
        now = time.monotonic()
        dt = now - prev_time
        cpu_pct = ((cpu_secs - prev_cpu_secs) / dt) * 100 if dt > 0 else 0.0

        mem_stat = _read_memory_stat()
        samples.append(Sample(
            timestamp=now,
            wall_clock=datetime.now(timezone.utc).isoformat(),
            chrome_num_processes=num_procs,
            chrome_rss_bytes=rss,
            chrome_uss_bytes=uss,
            chrome_cpu_percent=cpu_pct,
            cgroup_memory_bytes=_read_int(CGROUP_MEMORY_CURRENT),
            cgroup_cpu_usec=_read_cpu_usage_usec(),
            cgroup_anon_bytes=mem_stat.get("anon", -1),
            cgroup_file_bytes=mem_stat.get("file", -1),
            cgroup_kernel_bytes=mem_stat.get("kernel", -1),
        ))

    end_cpu_secs = cpu_secs if num_procs > 0 else prev_cpu_secs
    cpu_usec_end = _read_cpu_usage_usec()
    duration = time.monotonic() - t0

    if not samples:
        return MonitorResult(duration_s=duration)

    # Chrome tree aggregates
    chrome_peak_rss = max(s.chrome_rss_bytes for s in samples)
    chrome_avg_rss = sum(s.chrome_rss_bytes for s in samples) / len(samples)
    chrome_peak_uss = max(s.chrome_uss_bytes for s in samples)
    chrome_avg_uss = sum(s.chrome_uss_bytes for s in samples) / len(samples)
    chrome_peak_cpu = max(s.chrome_cpu_percent for s in samples)
    chrome_avg_cpu = sum(s.chrome_cpu_percent for s in samples) / len(samples)

    # Container cgroup aggregates
    cgroup_mems = [s.cgroup_memory_bytes for s in samples if s.cgroup_memory_bytes >= 0]
    cgroup_peak_mem = max(cgroup_mems) if cgroup_mems else 0
    cgroup_avg_mem = sum(cgroup_mems) / len(cgroup_mems) if cgroup_mems else 0.0

    # Active (non-reclaimable) = anon + kernel; excludes page cache
    cgroup_actives = [
        s.cgroup_anon_bytes + s.cgroup_kernel_bytes
        for s in samples
        if s.cgroup_anon_bytes >= 0 and s.cgroup_kernel_bytes >= 0
    ]
    cgroup_peak_active = max(cgroup_actives) if cgroup_actives else 0
    cgroup_avg_active = sum(cgroup_actives) / len(cgroup_actives) if cgroup_actives else 0.0

    cgroup_cpu_delta = 0
    if cpu_usec_start >= 0 and cpu_usec_end >= 0:
        cgroup_cpu_delta = cpu_usec_end - cpu_usec_start

    return MonitorResult(
        samples=samples,
        chrome_peak_rss_bytes=chrome_peak_rss,
        chrome_avg_rss_bytes=chrome_avg_rss,
        chrome_peak_uss_bytes=chrome_peak_uss,
        chrome_avg_uss_bytes=chrome_avg_uss,
        chrome_peak_cpu_percent=chrome_peak_cpu,
        chrome_avg_cpu_percent=chrome_avg_cpu,
        cgroup_peak_memory_bytes=cgroup_peak_mem,
        cgroup_avg_memory_bytes=cgroup_avg_mem,
        cgroup_peak_active_bytes=cgroup_peak_active,
        cgroup_avg_active_bytes=cgroup_avg_active,
        cgroup_cpu_total_usec=cgroup_cpu_delta,
        cgroup_memory_baseline_bytes=max(memory_baseline, 0),
        cgroup_active_baseline_bytes=active_baseline,
        duration_s=duration,
        chrome_cpu_time_s=end_cpu_secs - start_cpu_secs,
    )


def find_chrome_pid(browser) -> int | None:
    """Extract the Chrome main process PID from a Playwright Browser object."""
    try:
        transport = browser._impl_obj._connection._transport
        if hasattr(transport, "_proc") and transport._proc is not None:
            return transport._proc.pid
    except (AttributeError, TypeError):
        pass

    # Fallback: scan for most recently started chrome process
    candidates = []
    for p in psutil.process_iter(["pid", "name", "create_time"]):
        try:
            if "chrome" in (p.info["name"] or "").lower():
                candidates.append((p.info["create_time"], p.info["pid"]))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if candidates:
        candidates.sort(reverse=True)
        return candidates[0][1]

    return None
