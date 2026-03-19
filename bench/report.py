"""Output generation: Rich table, CSV, and JSON.

When --reuse-browser is used, two separate comparison reports are generated:
  1. fresh_summary  -- headless vs headful (new Chrome per URL)
  2. reuse_summary  -- headless-reuse vs headful-reuse (single Chrome instance)

Each report is a clear 1:1 headless-vs-headful comparison with overhead metrics.
Raw data files (samples.csv, load_events.csv) always contain all modes combined.

Metrics hierarchy (machine cost first):
  Container (cgroup)  -- total cost to the machine (memory + CPU)
  Chrome USS (psutil)  -- Chrome private memory (no shared lib double-counting)
  Chrome RSS (psutil)  -- Chrome per-process sum (inflated by shared pages)
"""

import csv
import json
import statistics
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.table import Table

from .runner import BenchmarkRun, LoadEvents, PageMetrics

console = Console()

BYTES_PER_MB = 1024 * 1024

LOAD_EVENT_FIELDS = [
    "dns_ms", "connect_ms", "ttfb_ms", "response_ms",
    "dom_interactive_ms", "dom_content_loaded_ms", "dom_complete_ms", "load_event_ms",
]

# (file_prefix, display_label, baseline_mode_name, comparison_mode_name)
STRATEGIES = [
    ("fresh", "Fresh Browser (new Chrome per URL)", "headless", "headful"),
    ("reuse", "Reused Browser (single Chrome instance)", "headless-reuse", "headful-reuse"),
    ("shell_fresh", "Headless Shell vs Headless Chrome (fresh)", "headless", "headless-shell"),
    ("shell_reuse", "Headless Shell vs Headless Chrome (reuse)", "headless-reuse", "headless-shell-reuse"),
]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ModeSummary:
    url: str
    mode: str
    runs: int
    # Container cgroup -- absolute values (the real machine cost)
    cgroup_active_peak_mb: float   # anon + kernel (non-reclaimable)
    cgroup_active_avg_mb: float
    cgroup_total_peak_mb: float    # memory.current (includes page cache)
    cgroup_total_avg_mb: float
    cgroup_cpu_pct: float          # avg CPU % of one core (from usec / duration)
    cgroup_cpu_total_usec: int     # raw total for CSV/JSON
    # Chrome process tree (psutil)
    peak_uss_mb: float
    avg_uss_mb: float
    std_uss_mb: float
    peak_rss_mb: float
    avg_rss_mb: float
    std_rss_mb: float
    peak_cpu_pct: float
    avg_cpu_pct: float
    std_cpu_pct: float
    # Page timing
    avg_page_load_ms: float
    avg_load_events: dict[str, float]
    errors: int
    timeouts: int = 0
    # Chrome process-tree total CPU seconds (matches headless-research cpu_time_s)
    avg_chrome_cpu_time_s: float = 0.0
    # Baseline-subtracted cgroup (per-URL Chrome overhead, isolated from container history)
    cgroup_delta_active_peak_mb: float = 0.0
    cgroup_delta_active_avg_mb: float = 0.0
    cgroup_delta_total_peak_mb: float = 0.0
    cgroup_delta_total_avg_mb: float = 0.0
    # Page-level structural and resource metrics (averaged across runs)
    dom_element_count: float = 0.0
    visible_text_length: float = 0.0
    script_count: float = 0.0
    stylesheet_count: float = 0.0
    image_count: float = 0.0
    iframe_count: float = 0.0
    anchor_count: float = 0.0
    form_count: float = 0.0
    resource_count: float = 0.0
    total_transfer_bytes: float = 0.0
    total_decoded_bytes: float = 0.0
    document_height: float = 0.0
    document_width: float = 0.0


@dataclass
class PairSummary:
    """Per-URL headless vs headful comparison within one lifecycle strategy."""
    url: str
    headless: ModeSummary | None
    headful: ModeSummary | None
    # Overhead: headful - headless (positive = headful costs more)
    cgroup_overhead_mb: float = 0.0
    cgroup_overhead_pct: float = 0.0
    cgroup_cpu_overhead_pp: float = 0.0
    uss_overhead_mb: float = 0.0
    uss_overhead_pct: float = 0.0
    rss_overhead_mb: float = 0.0
    rss_overhead_pct: float = 0.0
    chrome_cpu_overhead_pp: float = 0.0
    load_time_overhead_ms: float = 0.0
    chrome_cpu_time_overhead_s: float = 0.0
    # Baseline-subtracted cgroup overhead (stable across runs)
    cgroup_delta_overhead_mb: float = 0.0
    cgroup_delta_overhead_pct: float = 0.0


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------

def _avg_load_events(runs: list[BenchmarkRun]) -> dict[str, float]:
    """Average each load event field across valid runs (ignoring -1 = not fired)."""
    result = {}
    for field in LOAD_EVENT_FIELDS:
        vals = [getattr(r.load_events, field) for r in runs if getattr(r.load_events, field) >= 0]
        result[field] = statistics.mean(vals) if vals else -1
    return result


def _cgroup_cpu_pct(run: BenchmarkRun) -> float | None:
    """Compute cgroup CPU% for a single run (% of one core)."""
    mr = run.monitor_result
    if mr.cgroup_cpu_total_usec > 0 and mr.duration_s > 0:
        return (mr.cgroup_cpu_total_usec / (mr.duration_s * 1_000_000)) * 100
    return None


def _mode_summary(url: str, mode: str, runs: list[BenchmarkRun]) -> ModeSummary:
    valid = [r for r in runs if not r.error]
    n_timeouts = sum(1 for r in runs if r.timed_out)
    if not valid:
        return ModeSummary(
            url=url, mode=mode, runs=len(runs),
            cgroup_active_peak_mb=0, cgroup_active_avg_mb=0,
            cgroup_total_peak_mb=0, cgroup_total_avg_mb=0,
            cgroup_cpu_pct=0, cgroup_cpu_total_usec=0,
            peak_uss_mb=0, avg_uss_mb=0, std_uss_mb=0,
            peak_rss_mb=0, avg_rss_mb=0, std_rss_mb=0,
            peak_cpu_pct=0, avg_cpu_pct=0, std_cpu_pct=0,
            avg_page_load_ms=0, avg_load_events={f: -1 for f in LOAD_EVENT_FIELDS},
            errors=len(runs), timeouts=n_timeouts,
        )

    # Container cgroup — absolute values
    active_peaks = [
        r.monitor_result.cgroup_peak_active_bytes / BYTES_PER_MB
        for r in valid if r.monitor_result.cgroup_peak_active_bytes > 0
    ]
    active_avgs = [
        r.monitor_result.cgroup_avg_active_bytes / BYTES_PER_MB
        for r in valid if r.monitor_result.cgroup_avg_active_bytes > 0
    ]
    total_peaks = [
        r.monitor_result.cgroup_peak_memory_bytes / BYTES_PER_MB
        for r in valid if r.monitor_result.cgroup_peak_memory_bytes > 0
    ]
    total_avgs = [
        r.monitor_result.cgroup_avg_memory_bytes / BYTES_PER_MB
        for r in valid if r.monitor_result.cgroup_avg_memory_bytes > 0
    ]
    cgroup_cpus_usec = [r.monitor_result.cgroup_cpu_total_usec for r in valid
                        if r.monitor_result.cgroup_cpu_total_usec > 0]
    cgroup_cpu_pcts = [p for r in valid if (p := _cgroup_cpu_pct(r)) is not None]

    # Baseline-subtracted (per-URL Chrome overhead, removes container accumulation)
    delta_active_peaks = [
        (r.monitor_result.cgroup_peak_active_bytes - r.monitor_result.cgroup_active_baseline_bytes) / BYTES_PER_MB
        for r in valid if r.monitor_result.cgroup_peak_active_bytes > 0 and r.monitor_result.cgroup_active_baseline_bytes > 0
    ]
    delta_active_avgs = [
        (r.monitor_result.cgroup_avg_active_bytes - r.monitor_result.cgroup_active_baseline_bytes) / BYTES_PER_MB
        for r in valid if r.monitor_result.cgroup_avg_active_bytes > 0 and r.monitor_result.cgroup_active_baseline_bytes > 0
    ]
    delta_total_peaks = [
        (r.monitor_result.cgroup_peak_memory_bytes - r.monitor_result.cgroup_memory_baseline_bytes) / BYTES_PER_MB
        for r in valid if r.monitor_result.cgroup_peak_memory_bytes > 0 and r.monitor_result.cgroup_memory_baseline_bytes > 0
    ]
    delta_total_avgs = [
        (r.monitor_result.cgroup_avg_memory_bytes - r.monitor_result.cgroup_memory_baseline_bytes) / BYTES_PER_MB
        for r in valid if r.monitor_result.cgroup_avg_memory_bytes > 0 and r.monitor_result.cgroup_memory_baseline_bytes > 0
    ]

    # Chrome process tree (psutil)
    peak_usses = [r.monitor_result.chrome_peak_uss_bytes / BYTES_PER_MB for r in valid]
    avg_usses = [r.monitor_result.chrome_avg_uss_bytes / BYTES_PER_MB for r in valid]
    peak_rsses = [r.monitor_result.chrome_peak_rss_bytes / BYTES_PER_MB for r in valid]
    avg_rsses = [r.monitor_result.chrome_avg_rss_bytes / BYTES_PER_MB for r in valid]
    peak_cpus = [r.monitor_result.chrome_peak_cpu_percent for r in valid]
    avg_cpus = [r.monitor_result.chrome_avg_cpu_percent for r in valid]
    chrome_cpu_times = [r.monitor_result.chrome_cpu_time_s for r in valid
                        if r.monitor_result.chrome_cpu_time_s > 0]

    load_times = [r.page_load_time_ms for r in valid]

    # Page-level metrics (average across runs)
    _pm_fields = [
        "dom_element_count", "visible_text_length", "script_count",
        "stylesheet_count", "image_count", "iframe_count", "anchor_count",
        "form_count", "resource_count", "total_transfer_bytes",
        "total_decoded_bytes", "document_height", "document_width",
    ]
    pm_avgs: dict[str, float] = {}
    for pf in _pm_fields:
        vals = [getattr(r.page_metrics, pf) for r in valid if getattr(r.page_metrics, pf, 0) > 0]
        pm_avgs[pf] = statistics.mean(vals) if vals else 0.0

    return ModeSummary(
        url=url,
        mode=mode,
        runs=len(runs),
        # Container cgroup
        cgroup_active_peak_mb=max(active_peaks) if active_peaks else 0.0,
        cgroup_active_avg_mb=statistics.mean(active_avgs) if active_avgs else 0.0,
        cgroup_total_peak_mb=max(total_peaks) if total_peaks else 0.0,
        cgroup_total_avg_mb=statistics.mean(total_avgs) if total_avgs else 0.0,
        cgroup_cpu_pct=statistics.mean(cgroup_cpu_pcts) if cgroup_cpu_pcts else 0.0,
        cgroup_cpu_total_usec=round(statistics.mean(cgroup_cpus_usec)) if cgroup_cpus_usec else 0,
        # Baseline-subtracted cgroup
        cgroup_delta_active_peak_mb=max(delta_active_peaks) if delta_active_peaks else 0.0,
        cgroup_delta_active_avg_mb=statistics.mean(delta_active_avgs) if delta_active_avgs else 0.0,
        cgroup_delta_total_peak_mb=max(delta_total_peaks) if delta_total_peaks else 0.0,
        cgroup_delta_total_avg_mb=statistics.mean(delta_total_avgs) if delta_total_avgs else 0.0,
        # Chrome USS
        peak_uss_mb=max(peak_usses) if peak_usses else 0.0,
        avg_uss_mb=statistics.mean(avg_usses) if avg_usses else 0.0,
        std_uss_mb=statistics.stdev(avg_usses) if len(avg_usses) > 1 else 0.0,
        # Chrome RSS
        peak_rss_mb=max(peak_rsses),
        avg_rss_mb=statistics.mean(avg_rsses),
        std_rss_mb=statistics.stdev(avg_rsses) if len(avg_rsses) > 1 else 0.0,
        # Chrome CPU
        peak_cpu_pct=max(peak_cpus),
        avg_cpu_pct=statistics.mean(avg_cpus),
        std_cpu_pct=statistics.stdev(avg_cpus) if len(avg_cpus) > 1 else 0.0,
        avg_chrome_cpu_time_s=statistics.mean(chrome_cpu_times) if chrome_cpu_times else 0.0,
        # Timing
        avg_page_load_ms=statistics.mean(load_times),
        avg_load_events=_avg_load_events(valid),
        errors=len(runs) - len(valid),
        timeouts=n_timeouts,
        # Page metrics
        dom_element_count=pm_avgs["dom_element_count"],
        visible_text_length=pm_avgs["visible_text_length"],
        script_count=pm_avgs["script_count"],
        stylesheet_count=pm_avgs["stylesheet_count"],
        image_count=pm_avgs["image_count"],
        iframe_count=pm_avgs["iframe_count"],
        anchor_count=pm_avgs["anchor_count"],
        form_count=pm_avgs["form_count"],
        resource_count=pm_avgs["resource_count"],
        total_transfer_bytes=pm_avgs["total_transfer_bytes"],
        total_decoded_bytes=pm_avgs["total_decoded_bytes"],
        document_height=pm_avgs["document_height"],
        document_width=pm_avgs["document_width"],
    )


def compute_pair_summary(
    runs: list[BenchmarkRun],
    headless_mode: str,
    headful_mode: str,
) -> list[PairSummary]:
    """Compute per-URL headless vs headful comparison for one strategy."""
    by_url: dict[str, dict[str, list[BenchmarkRun]]] = {}
    for r in runs:
        by_url.setdefault(r.url, {}).setdefault(r.mode, []).append(r)

    summaries = []
    for url, modes in by_url.items():
        hl = _mode_summary(url, headless_mode, modes[headless_mode]) if headless_mode in modes else None
        hf = _mode_summary(url, headful_mode, modes[headful_mode]) if headful_mode in modes else None

        ps = PairSummary(url=url, headless=hl, headful=hf)

        if hl and hf:
            has_cgroup = hl.cgroup_cpu_total_usec > 0 and hf.cgroup_cpu_total_usec > 0
            if has_cgroup:
                ps.cgroup_overhead_mb = hf.cgroup_active_avg_mb - hl.cgroup_active_avg_mb
                if hl.cgroup_active_avg_mb > 0:
                    ps.cgroup_overhead_pct = (ps.cgroup_overhead_mb / hl.cgroup_active_avg_mb) * 100
                ps.cgroup_delta_overhead_mb = hf.cgroup_delta_active_avg_mb - hl.cgroup_delta_active_avg_mb
                if hl.cgroup_delta_active_avg_mb > 0:
                    ps.cgroup_delta_overhead_pct = (ps.cgroup_delta_overhead_mb / hl.cgroup_delta_active_avg_mb) * 100
            ps.cgroup_cpu_overhead_pp = hf.cgroup_cpu_pct - hl.cgroup_cpu_pct
            if hl.avg_uss_mb > 0:
                ps.uss_overhead_mb = hf.avg_uss_mb - hl.avg_uss_mb
                ps.uss_overhead_pct = (ps.uss_overhead_mb / hl.avg_uss_mb) * 100
            if hl.avg_rss_mb > 0:
                ps.rss_overhead_mb = hf.avg_rss_mb - hl.avg_rss_mb
                ps.rss_overhead_pct = (ps.rss_overhead_mb / hl.avg_rss_mb) * 100
            ps.chrome_cpu_overhead_pp = hf.avg_cpu_pct - hl.avg_cpu_pct
            ps.chrome_cpu_time_overhead_s = hf.avg_chrome_cpu_time_s - hl.avg_chrome_cpu_time_s
            ps.load_time_overhead_ms = hf.avg_page_load_ms - hl.avg_page_load_ms

        summaries.append(ps)

    return summaries


# ---------------------------------------------------------------------------
# Rich table
# ---------------------------------------------------------------------------

def _overhead_style(pct: float) -> str:
    if abs(pct) < 10:
        return "green"
    if abs(pct) < 50:
        return "yellow"
    return "red"


def print_rich_table(summaries: list[PairSummary], title: str) -> None:
    """Print a Rich comparison table for one lifecycle strategy.

    Column order: container-level cost first, then Chrome-specific detail.
    """
    table = Table(title=title)
    table.add_column("URL", max_width=40)
    table.add_column("Mode", style="cyan")
    # Container cost (what the machine pays)
    table.add_column("Container\nActive (MB)", justify="right")
    table.add_column("Container\nTotal (MB)", justify="right")
    table.add_column("Container\nCPU%", justify="right")
    # Chrome detail
    table.add_column("Chrome\nUSS (MB)", justify="right")
    table.add_column("Chrome\nRSS (MB)", justify="right")
    table.add_column("Chrome\nCPU%", justify="right")
    table.add_column("Chrome\nCPU(s)", justify="right")
    # Timing
    table.add_column("Load\n(ms)", justify="right")
    # Overhead (container-based)
    table.add_column("Overhead\n(container)", justify="right")
    table.add_column("Overhead\n(per-URL \u0394)", justify="right")

    for s in summaries:
        for ms, is_first in [(s.headless, True), (s.headful, False)]:
            if ms is None:
                continue

            overhead_str = ""
            delta_str = ""
            if not is_first and s.headless is not None:
                if s.cgroup_overhead_mb != 0:
                    style = _overhead_style(s.cgroup_overhead_pct)
                    sign = "+" if s.cgroup_overhead_mb >= 0 else ""
                    if s.cgroup_overhead_pct != 0:
                        overhead_str = (
                            f"[{style}]{sign}{s.cgroup_overhead_mb:.1f} MB "
                            f"({s.cgroup_overhead_pct:+.1f}%)[/{style}]"
                        )
                    else:
                        overhead_str = f"[{style}]{sign}{s.cgroup_overhead_mb:.1f} MB[/{style}]"
                if s.cgroup_delta_overhead_mb != 0 or s.cgroup_delta_overhead_pct != 0:
                    d_style = _overhead_style(s.cgroup_delta_overhead_pct)
                    d_sign = "+" if s.cgroup_delta_overhead_mb >= 0 else ""
                    if s.cgroup_delta_overhead_pct != 0:
                        delta_str = (
                            f"[{d_style}]{d_sign}{s.cgroup_delta_overhead_mb:.1f} MB "
                            f"({s.cgroup_delta_overhead_pct:+.1f}%)[/{d_style}]"
                        )
                    else:
                        delta_str = f"[{d_style}]{d_sign}{s.cgroup_delta_overhead_mb:.1f} MB[/{d_style}]"

            has_cgroup = ms.cgroup_cpu_total_usec > 0
            active_str = f"{ms.cgroup_active_peak_mb:.0f} / {ms.cgroup_active_avg_mb:.0f}" if has_cgroup else "n/a"
            total_str = f"{ms.cgroup_total_peak_mb:.0f} / {ms.cgroup_total_avg_mb:.0f}" if has_cgroup else "n/a"
            cgroup_cpu = f"{ms.cgroup_cpu_pct:.1f}" if has_cgroup else "n/a"
            uss_str = f"{ms.peak_uss_mb:.0f} / {ms.avg_uss_mb:.0f}" if ms.avg_uss_mb > 0 else "n/a"

            table.add_row(
                s.url if is_first else "",
                ms.mode,
                active_str,
                total_str,
                cgroup_cpu,
                uss_str,
                f"{ms.avg_rss_mb:.0f} +/- {ms.std_rss_mb:.0f}",
                f"{ms.avg_cpu_pct:.1f} +/- {ms.std_cpu_pct:.1f}",
                f"{ms.avg_chrome_cpu_time_s:.2f}" if ms.avg_chrome_cpu_time_s > 0 else "n/a",
                f"{ms.avg_page_load_ms:.0f}",
                overhead_str,
                delta_str,
            )
        table.add_section()

    console.print(table)
    console.print(
        "[dim]Container Active = anon+kernel (non-reclaimable). "
        "Total = incl. page cache. "
        "USS = Chrome private mem. "
        "RSS = per-process sum (inflated). "
        "All peak/avg. "
        "\u0394 = baseline-subtracted (per-URL Chrome overhead, stable across runs).[/dim]"
    )


# ---------------------------------------------------------------------------
# Raw data CSV (all modes combined)
# ---------------------------------------------------------------------------

def write_csv_samples(runs: list[BenchmarkRun], output_dir: Path) -> Path:
    """Write every raw sample to CSV (Chrome tree + cgroup)."""
    path = output_dir / "samples.csv"
    fieldnames = [
        "url", "mode", "run_index", "timestamp", "wall_clock",
        "chrome_num_processes", "chrome_rss_bytes", "chrome_uss_bytes", "chrome_cpu_percent",
        "cgroup_memory_bytes", "cgroup_cpu_usec",
        "cgroup_anon_bytes", "cgroup_file_bytes", "cgroup_kernel_bytes",
    ]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in runs:
            for s in r.monitor_result.samples:
                writer.writerow({
                    "url": r.url,
                    "mode": r.mode,
                    "run_index": r.run_index,
                    "timestamp": s.timestamp,
                    "wall_clock": s.wall_clock,
                    "chrome_num_processes": s.chrome_num_processes,
                    "chrome_rss_bytes": s.chrome_rss_bytes,
                    "chrome_uss_bytes": s.chrome_uss_bytes,
                    "chrome_cpu_percent": s.chrome_cpu_percent,
                    "cgroup_memory_bytes": s.cgroup_memory_bytes,
                    "cgroup_cpu_usec": s.cgroup_cpu_usec,
                    "cgroup_anon_bytes": s.cgroup_anon_bytes,
                    "cgroup_file_bytes": s.cgroup_file_bytes,
                    "cgroup_kernel_bytes": s.cgroup_kernel_bytes,
                })
    return path


def write_csv_load_events(runs: list[BenchmarkRun], output_dir: Path) -> Path:
    """Write per-run load event timings to CSV."""
    path = output_dir / "load_events.csv"
    page_metric_fields = [
        "dom_element_count", "visible_text_length", "script_count",
        "stylesheet_count", "image_count", "iframe_count", "anchor_count",
        "form_count", "resource_count", "total_transfer_bytes",
        "total_decoded_bytes", "document_height", "document_width",
    ]
    fieldnames = (
        ["url", "mode", "run_index"]
        + LOAD_EVENT_FIELDS
        + page_metric_fields
        + ["http_status", "timed_out", "content_length", "final_url", "error"]
    )
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in runs:
            row: dict = {
                "url": r.url,
                "mode": r.mode,
                "run_index": r.run_index,
                "http_status": r.http_status,
                "timed_out": r.timed_out,
                "content_length": r.content_length,
                "final_url": r.final_url,
                "error": r.error,
            }
            for field in LOAD_EVENT_FIELDS:
                row[field] = f"{getattr(r.load_events, field):.1f}"
            for field in page_metric_fields:
                row[field] = getattr(r.page_metrics, field, 0)
            writer.writerow(row)
    return path


# ---------------------------------------------------------------------------
# Per-strategy summary CSV
# ---------------------------------------------------------------------------

def _mode_csv_fields(prefix: str) -> list[str]:
    """CSV columns: container first, then Chrome detail."""
    base = [
        # Container (cgroup)
        f"{prefix}_cgroup_active_peak_mb", f"{prefix}_cgroup_active_avg_mb",
        f"{prefix}_cgroup_total_peak_mb", f"{prefix}_cgroup_total_avg_mb",
        f"{prefix}_cgroup_cpu_pct", f"{prefix}_cgroup_cpu_usec",
        # Baseline-subtracted cgroup
        f"{prefix}_cgroup_delta_active_avg_mb",
        # Chrome USS
        f"{prefix}_peak_uss_mb", f"{prefix}_avg_uss_mb", f"{prefix}_std_uss_mb",
        # Chrome RSS
        f"{prefix}_peak_rss_mb", f"{prefix}_avg_rss_mb", f"{prefix}_std_rss_mb",
        # Chrome CPU
        f"{prefix}_peak_cpu_pct", f"{prefix}_avg_cpu_pct", f"{prefix}_std_cpu_pct",
        f"{prefix}_chrome_cpu_time_s",
        # Timing
        f"{prefix}_avg_load_ms", f"{prefix}_errors",
    ]
    events = [f"{prefix}_{f}" for f in LOAD_EVENT_FIELDS]
    page = [
        f"{prefix}_dom_element_count", f"{prefix}_visible_text_length",
        f"{prefix}_script_count", f"{prefix}_stylesheet_count",
        f"{prefix}_image_count", f"{prefix}_iframe_count",
        f"{prefix}_anchor_count", f"{prefix}_form_count",
        f"{prefix}_resource_count", f"{prefix}_total_transfer_bytes",
        f"{prefix}_total_decoded_bytes",
        f"{prefix}_document_height", f"{prefix}_document_width",
    ]
    return base + events + page


OVERHEAD_FIELDS = [
    "cgroup_overhead_mb", "cgroup_overhead_pct",
    "cgroup_delta_overhead_mb", "cgroup_delta_overhead_pct",
    "cgroup_cpu_overhead_pp",
    "uss_overhead_mb", "uss_overhead_pct",
    "rss_overhead_mb", "rss_overhead_pct",
    "chrome_cpu_overhead_pp", "chrome_cpu_time_overhead_s", "load_time_overhead_ms",
]


def _fill_mode_csv(row: dict, prefix: str, ms: ModeSummary) -> None:
    # Container (cgroup)
    row[f"{prefix}_cgroup_active_peak_mb"] = f"{ms.cgroup_active_peak_mb:.2f}"
    row[f"{prefix}_cgroup_active_avg_mb"] = f"{ms.cgroup_active_avg_mb:.2f}"
    row[f"{prefix}_cgroup_total_peak_mb"] = f"{ms.cgroup_total_peak_mb:.2f}"
    row[f"{prefix}_cgroup_total_avg_mb"] = f"{ms.cgroup_total_avg_mb:.2f}"
    row[f"{prefix}_cgroup_cpu_pct"] = f"{ms.cgroup_cpu_pct:.2f}"
    row[f"{prefix}_cgroup_cpu_usec"] = ms.cgroup_cpu_total_usec
    # Baseline-subtracted cgroup
    row[f"{prefix}_cgroup_delta_active_avg_mb"] = f"{ms.cgroup_delta_active_avg_mb:.2f}"
    # Chrome USS
    row[f"{prefix}_peak_uss_mb"] = f"{ms.peak_uss_mb:.2f}"
    row[f"{prefix}_avg_uss_mb"] = f"{ms.avg_uss_mb:.2f}"
    row[f"{prefix}_std_uss_mb"] = f"{ms.std_uss_mb:.2f}"
    # Chrome RSS
    row[f"{prefix}_peak_rss_mb"] = f"{ms.peak_rss_mb:.2f}"
    row[f"{prefix}_avg_rss_mb"] = f"{ms.avg_rss_mb:.2f}"
    row[f"{prefix}_std_rss_mb"] = f"{ms.std_rss_mb:.2f}"
    # Chrome CPU
    row[f"{prefix}_peak_cpu_pct"] = f"{ms.peak_cpu_pct:.2f}"
    row[f"{prefix}_avg_cpu_pct"] = f"{ms.avg_cpu_pct:.2f}"
    row[f"{prefix}_std_cpu_pct"] = f"{ms.std_cpu_pct:.2f}"
    row[f"{prefix}_chrome_cpu_time_s"] = f"{ms.avg_chrome_cpu_time_s:.3f}"
    # Timing
    row[f"{prefix}_avg_load_ms"] = f"{ms.avg_page_load_ms:.0f}"
    row[f"{prefix}_errors"] = ms.errors
    for field in LOAD_EVENT_FIELDS:
        val = ms.avg_load_events.get(field, -1)
        row[f"{prefix}_{field}"] = f"{val:.1f}" if val >= 0 else ""
    # Page metrics
    row[f"{prefix}_dom_element_count"] = round(ms.dom_element_count)
    row[f"{prefix}_visible_text_length"] = round(ms.visible_text_length)
    row[f"{prefix}_script_count"] = round(ms.script_count)
    row[f"{prefix}_stylesheet_count"] = round(ms.stylesheet_count)
    row[f"{prefix}_image_count"] = round(ms.image_count)
    row[f"{prefix}_iframe_count"] = round(ms.iframe_count)
    row[f"{prefix}_anchor_count"] = round(ms.anchor_count)
    row[f"{prefix}_form_count"] = round(ms.form_count)
    row[f"{prefix}_resource_count"] = round(ms.resource_count)
    row[f"{prefix}_total_transfer_bytes"] = round(ms.total_transfer_bytes)
    row[f"{prefix}_total_decoded_bytes"] = round(ms.total_decoded_bytes)
    row[f"{prefix}_document_height"] = round(ms.document_height)
    row[f"{prefix}_document_width"] = round(ms.document_width)


def write_csv_summary(
    summaries: list[PairSummary],
    output_dir: Path,
    file_prefix: str,
    baseline_label: str = "headless",
    comparison_label: str = "headful",
) -> Path:
    """Write per-URL comparison CSV for one lifecycle strategy."""
    path = output_dir / f"{file_prefix}_summary.csv"
    fieldnames = (
        ["url"]
        + _mode_csv_fields(baseline_label)
        + _mode_csv_fields(comparison_label)
        + OVERHEAD_FIELDS
    )

    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for s in summaries:
            row: dict = {"url": s.url}
            if s.headless:
                _fill_mode_csv(row, baseline_label, s.headless)
            if s.headful:
                _fill_mode_csv(row, comparison_label, s.headful)
            row["cgroup_overhead_mb"] = f"{s.cgroup_overhead_mb:.2f}"
            row["cgroup_overhead_pct"] = f"{s.cgroup_overhead_pct:.1f}"
            row["cgroup_delta_overhead_mb"] = f"{s.cgroup_delta_overhead_mb:.2f}"
            row["cgroup_delta_overhead_pct"] = f"{s.cgroup_delta_overhead_pct:.1f}"
            row["cgroup_cpu_overhead_pp"] = f"{s.cgroup_cpu_overhead_pp:.1f}"
            row["uss_overhead_mb"] = f"{s.uss_overhead_mb:.2f}"
            row["uss_overhead_pct"] = f"{s.uss_overhead_pct:.1f}"
            row["rss_overhead_mb"] = f"{s.rss_overhead_mb:.2f}"
            row["rss_overhead_pct"] = f"{s.rss_overhead_pct:.1f}"
            row["chrome_cpu_overhead_pp"] = f"{s.chrome_cpu_overhead_pp:.1f}"
            row["chrome_cpu_time_overhead_s"] = f"{s.chrome_cpu_time_overhead_s:.3f}"
            row["load_time_overhead_ms"] = f"{s.load_time_overhead_ms:.0f}"
            writer.writerow(row)
    return path


# ---------------------------------------------------------------------------
# Per-strategy summary JSON
# ---------------------------------------------------------------------------

def _mode_to_json(ms: ModeSummary) -> dict:
    return {
        "runs": ms.runs,
        # Container (cgroup) — the real machine cost
        "cgroup_active_peak_mb": round(ms.cgroup_active_peak_mb, 2),
        "cgroup_active_avg_mb": round(ms.cgroup_active_avg_mb, 2),
        "cgroup_total_peak_mb": round(ms.cgroup_total_peak_mb, 2),
        "cgroup_total_avg_mb": round(ms.cgroup_total_avg_mb, 2),
        "cgroup_cpu_pct": round(ms.cgroup_cpu_pct, 2),
        "cgroup_cpu_total_usec": ms.cgroup_cpu_total_usec,
        # Baseline-subtracted cgroup
        "cgroup_delta_active_peak_mb": round(ms.cgroup_delta_active_peak_mb, 2),
        "cgroup_delta_active_avg_mb": round(ms.cgroup_delta_active_avg_mb, 2),
        "cgroup_delta_total_peak_mb": round(ms.cgroup_delta_total_peak_mb, 2),
        "cgroup_delta_total_avg_mb": round(ms.cgroup_delta_total_avg_mb, 2),
        # Chrome USS
        "peak_uss_mb": round(ms.peak_uss_mb, 2),
        "avg_uss_mb": round(ms.avg_uss_mb, 2),
        "std_uss_mb": round(ms.std_uss_mb, 2),
        # Chrome RSS (inflated by shared libs)
        "peak_rss_mb": round(ms.peak_rss_mb, 2),
        "avg_rss_mb": round(ms.avg_rss_mb, 2),
        "std_rss_mb": round(ms.std_rss_mb, 2),
        # Chrome CPU
        "peak_cpu_pct": round(ms.peak_cpu_pct, 2),
        "avg_cpu_pct": round(ms.avg_cpu_pct, 2),
        "std_cpu_pct": round(ms.std_cpu_pct, 2),
        "chrome_cpu_time_s": round(ms.avg_chrome_cpu_time_s, 3),
        # Timing
        "avg_page_load_ms": round(ms.avg_page_load_ms, 1),
        "load_events": {k: round(v, 1) for k, v in ms.avg_load_events.items()},
        "errors": ms.errors,
        "timeouts": ms.timeouts,
        # Page-level metrics
        "dom_element_count": round(ms.dom_element_count),
        "visible_text_length": round(ms.visible_text_length),
        "script_count": round(ms.script_count),
        "stylesheet_count": round(ms.stylesheet_count),
        "image_count": round(ms.image_count),
        "iframe_count": round(ms.iframe_count),
        "anchor_count": round(ms.anchor_count),
        "form_count": round(ms.form_count),
        "resource_count": round(ms.resource_count),
        "total_transfer_bytes": round(ms.total_transfer_bytes),
        "total_decoded_bytes": round(ms.total_decoded_bytes),
        "document_height": round(ms.document_height),
        "document_width": round(ms.document_width),
    }


def write_json_summary(
    summaries: list[PairSummary],
    meta: dict,
    output_dir: Path,
    file_prefix: str,
    baseline_label: str = "headless",
    comparison_label: str = "headful",
) -> Path:
    """Write structured comparison JSON for one lifecycle strategy."""
    path = output_dir / f"{file_prefix}_summary.json"
    results = []
    for s in summaries:
        entry: dict = {"url": s.url}
        if s.headless:
            entry[baseline_label] = _mode_to_json(s.headless)
        if s.headful:
            entry[comparison_label] = _mode_to_json(s.headful)
        entry["overhead"] = {
            "cgroup_mb": round(s.cgroup_overhead_mb, 2),
            "cgroup_pct": round(s.cgroup_overhead_pct, 1),
            "cgroup_delta_mb": round(s.cgroup_delta_overhead_mb, 2),
            "cgroup_delta_pct": round(s.cgroup_delta_overhead_pct, 1),
            "cgroup_cpu_pp": round(s.cgroup_cpu_overhead_pp, 1),
            "uss_mb": round(s.uss_overhead_mb, 2),
            "uss_pct": round(s.uss_overhead_pct, 1),
            "rss_mb": round(s.rss_overhead_mb, 2),
            "rss_pct": round(s.rss_overhead_pct, 1),
            "chrome_cpu_pp": round(s.chrome_cpu_overhead_pp, 1),
            "chrome_cpu_time_s": round(s.chrome_cpu_time_overhead_s, 3),
            "load_time_ms": round(s.load_time_overhead_ms, 1),
        }
        results.append(entry)

    output = {"meta": meta, "results": results}
    with open(path, "w") as f:
        json.dump(output, f, indent=2)
    return path


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def print_validation_warnings(runs: list[BenchmarkRun]) -> None:
    """Print warnings about pages that may not have loaded correctly."""
    by_url: dict[str, list[BenchmarkRun]] = {}
    for r in runs:
        by_url.setdefault(r.url, []).append(r)

    warnings: list[tuple[str, list[str]]] = []

    for url, url_runs in by_url.items():
        issues: list[str] = []
        timeouts = [r for r in url_runs if r.timed_out]
        errors = [r for r in url_runs if r.error]
        bad_status = [r for r in url_runs if 0 < r.http_status >= 400]
        empty = [r for r in url_runs if r.content_length == 0]
        redirected = [r for r in url_runs if r.final_url and r.final_url != url]

        if timeouts:
            modes = sorted({r.mode for r in timeouts})
            issues.append(f"{len(timeouts)} timeout(s) [{', '.join(modes)}]")
        if bad_status:
            statuses = sorted({r.http_status for r in bad_status})
            issues.append(f"HTTP {', '.join(map(str, statuses))}")
        if empty:
            modes = sorted({r.mode for r in empty})
            issues.append(f"empty page [{', '.join(modes)}]")
        if errors:
            issues.append(f"{len(errors)} error(s)")

        # Content divergence: headless vs headful
        by_mode: dict[str, list[int]] = {}
        for r in url_runs:
            if r.content_length >= 0 and not r.error:
                by_mode.setdefault(r.mode, []).append(r.content_length)
        # Check if any mode pair has >50% divergence
        for hl, hf in [
            ("headless", "headful"), ("headless-reuse", "headful-reuse"),
            ("headless", "headless-shell"), ("headless-reuse", "headless-shell-reuse"),
        ]:
            hl_lens = by_mode.get(hl, [])
            hf_lens = by_mode.get(hf, [])
            if hl_lens and hf_lens:
                hl_avg = sum(hl_lens) / len(hl_lens)
                hf_avg = sum(hf_lens) / len(hf_lens)
                if hl_avg > 0 and hf_avg > 0:
                    ratio = min(hl_avg, hf_avg) / max(hl_avg, hf_avg)
                    if ratio < 0.5:
                        issues.append(
                            f"content divergence: {hl}={int(hl_avg)} vs {hf}={int(hf_avg)} chars"
                        )

        if redirected and not all(r.final_url == redirected[0].final_url for r in redirected):
            # Different final URLs across modes — possible anti-bot
            final_by_mode = {r.mode: r.final_url for r in redirected}
            unique_finals = set(final_by_mode.values())
            if len(unique_finals) > 1:
                issues.append(f"different redirects across modes")

        if issues:
            warnings.append((url, issues))

    if warnings:
        console.print(f"\n[bold yellow]Page Load Warnings ({len(warnings)} URL(s)):[/bold yellow]")
        for url, issues in warnings:
            console.print(f"  {url[:60]}: {'; '.join(issues)}")
    else:
        console.print("\n[green]All pages loaded successfully across all modes[/green]")


def generate_all_reports(
    runs: list[BenchmarkRun],
    meta: dict,
    output_dir: Path,
) -> None:
    """Generate all output formats.

    Raw data CSVs contain all modes.  Summary reports are split per lifecycle
    strategy so each is a clean headless-vs-headful comparison.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Validation warnings
    print_validation_warnings(runs)

    # Raw data — all modes combined
    samples_path = write_csv_samples(runs, output_dir)
    events_path = write_csv_load_events(runs, output_dir)
    console.print(f"\nRaw data written to:")
    console.print(f"  Samples CSV:     {samples_path}")
    console.print(f"  Load Events CSV: {events_path}")

    # Per-strategy comparison reports
    modes_present = {r.mode for r in runs}

    for prefix, label, hl_mode, hf_mode in STRATEGIES:
        if hl_mode not in modes_present or hf_mode not in modes_present:
            continue

        strategy_runs = [r for r in runs if r.mode in (hl_mode, hf_mode)]
        summaries = compute_pair_summary(strategy_runs, hl_mode, hf_mode)

        console.print(f"\n{'=' * 60}")
        print_rich_table(summaries, label)

        csv_path = write_csv_summary(
            summaries, output_dir, prefix,
            baseline_label=hl_mode, comparison_label=hf_mode,
        )
        json_path = write_json_summary(
            summaries, meta, output_dir, prefix,
            baseline_label=hl_mode, comparison_label=hf_mode,
        )
        console.print(f"  Summary CSV:  {csv_path}")
        console.print(f"  Summary JSON: {json_path}")
