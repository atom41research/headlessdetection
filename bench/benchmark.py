"""Main orchestrator: CLI parsing, URL loading, benchmark loop."""

import asyncio
import json
import os
import sys
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn

from . import config
from .monitor import Sample, MonitorResult
from .monitor import find_chrome_pid as _find_chrome_pid
from .runner import (
    BenchmarkRun, LoadEvents, PageMetrics, WEBDRIVER_PATCH,
    run_benchmark, run_benchmark_reuse,
)
from .report import generate_all_reports

console = Console()


def load_urls(args) -> list[str]:
    """Load URLs from --url or --urls-file."""
    if args.url:
        return [args.url]
    if not args.urls_file:
        console.print("[red]Either --url or --urls-file is required (unless using --report)[/red]")
        sys.exit(1)
    path: Path = args.urls_file
    if not path.exists():
        console.print(f"[red]File not found: {path}[/red]")
        sys.exit(1)
    urls = [line.strip() for line in path.read_text().splitlines() if line.strip() and not line.startswith("#")]
    if not urls:
        console.print(f"[red]No URLs found in {path}[/red]")
        sys.exit(1)
    return urls


def _serialize_runs(runs: list[BenchmarkRun]) -> list[dict]:
    """Serialize BenchmarkRun objects to JSON-safe dicts."""
    return [asdict(r) for r in runs]


def _save_runs(runs: list[BenchmarkRun], meta: dict, path: Path) -> None:
    """Save raw runs + metadata to a JSON file (atomic write)."""
    data = {"meta": meta, "runs": _serialize_runs(runs)}
    # Write to temp file first, then atomic rename on success
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        Path(tmp_path).chmod(0o666)
        Path(tmp_path).replace(path)
    except Exception:
        Path(tmp_path).unlink(missing_ok=True)
        raise
    console.print(f"  Raw runs saved to: {path} ({len(runs)} runs)")


def _load_runs(path: Path) -> tuple[dict, list[BenchmarkRun]]:
    """Load raw runs from a JSON file back into BenchmarkRun objects."""
    with open(path) as f:
        data = json.load(f)

    runs = []
    for rd in data["runs"]:
        mr = rd["monitor_result"]

        # Handle both old and new Sample field names
        samples = []
        for s in mr["samples"]:
            samples.append(Sample(
                timestamp=s["timestamp"],
                wall_clock=s["wall_clock"],
                chrome_num_processes=s.get("chrome_num_processes", s.get("num_processes", 0)),
                chrome_rss_bytes=s.get("chrome_rss_bytes", s.get("total_rss_bytes", 0)),
                chrome_uss_bytes=s.get("chrome_uss_bytes", 0),
                chrome_cpu_percent=s.get("chrome_cpu_percent", s.get("total_cpu_percent", 0.0)),
                cgroup_memory_bytes=s.get("cgroup_memory_bytes", -1),
                cgroup_cpu_usec=s.get("cgroup_cpu_usec", -1),
                cgroup_anon_bytes=s.get("cgroup_anon_bytes", -1),
                cgroup_file_bytes=s.get("cgroup_file_bytes", -1),
                cgroup_kernel_bytes=s.get("cgroup_kernel_bytes", -1),
            ))

        monitor = MonitorResult(
            samples=samples,
            chrome_peak_rss_bytes=mr.get("chrome_peak_rss_bytes", mr.get("peak_rss_bytes", 0)),
            chrome_avg_rss_bytes=mr.get("chrome_avg_rss_bytes", mr.get("avg_rss_bytes", 0.0)),
            chrome_peak_uss_bytes=mr.get("chrome_peak_uss_bytes", 0),
            chrome_avg_uss_bytes=mr.get("chrome_avg_uss_bytes", 0.0),
            chrome_peak_cpu_percent=mr.get("chrome_peak_cpu_percent", mr.get("peak_cpu_percent", 0.0)),
            chrome_avg_cpu_percent=mr.get("chrome_avg_cpu_percent", mr.get("avg_cpu_percent", 0.0)),
            cgroup_peak_memory_bytes=mr.get("cgroup_peak_memory_bytes", 0),
            cgroup_avg_memory_bytes=mr.get("cgroup_avg_memory_bytes", 0.0),
            cgroup_peak_active_bytes=mr.get("cgroup_peak_active_bytes", 0),
            cgroup_avg_active_bytes=mr.get("cgroup_avg_active_bytes", 0.0),
            cgroup_cpu_total_usec=mr.get("cgroup_cpu_total_usec", 0),
            cgroup_memory_baseline_bytes=mr.get("cgroup_memory_baseline_bytes", 0),
            cgroup_active_baseline_bytes=mr.get("cgroup_active_baseline_bytes", 0),
            duration_s=mr["duration_s"],
            chrome_cpu_time_s=mr.get("chrome_cpu_time_s", 0.0),
        )
        # Page metrics (optional — missing in older data)
        pm_data = rd.get("page_metrics", {})
        page_metrics = PageMetrics(
            dom_element_count=pm_data.get("dom_element_count", 0),
            visible_text_length=pm_data.get("visible_text_length", 0),
            script_count=pm_data.get("script_count", 0),
            stylesheet_count=pm_data.get("stylesheet_count", 0),
            image_count=pm_data.get("image_count", 0),
            iframe_count=pm_data.get("iframe_count", 0),
            anchor_count=pm_data.get("anchor_count", 0),
            form_count=pm_data.get("form_count", 0),
            resource_count=pm_data.get("resource_count", 0),
            total_transfer_bytes=pm_data.get("total_transfer_bytes", 0),
            total_decoded_bytes=pm_data.get("total_decoded_bytes", 0),
            resources_by_type=pm_data.get("resources_by_type", {}),
            document_height=pm_data.get("document_height", 0),
            document_width=pm_data.get("document_width", 0),
        )

        runs.append(BenchmarkRun(
            url=rd["url"],
            mode=rd["mode"],
            run_index=rd["run_index"],
            monitor_result=monitor,
            page_load_time_ms=rd["page_load_time_ms"],
            load_events=LoadEvents(**rd["load_events"]),
            page_metrics=page_metrics,
            error=rd["error"],
            http_status=rd.get("http_status", 0),
            final_url=rd.get("final_url", ""),
            timed_out=rd.get("timed_out", False),
            content_length=rd.get("content_length", -1),
        ))

    return data["meta"], runs


def _merge_meta(metas: list[dict]) -> dict:
    """Merge metadata from multiple runs into a single meta dict."""
    merged = dict(metas[0])
    all_modes = []
    all_urls = set()
    run_indices = set()
    for m in metas:
        all_modes.extend(m.get("modes", []))
        all_urls.update(m.get("urls", []))
        if "run_index" in m:
            run_indices.add(m["run_index"])
    merged["modes"] = sorted(set(all_modes))
    merged["urls"] = sorted(all_urls)
    merged["runs_per_mode"] = len(run_indices) if run_indices else 1
    merged.pop("run_index", None)
    return merged


async def _run_fresh_modes(
    pw, urls, modes, args, real_ua, progress, task, all_runs,
) -> None:
    """Run fresh-browser modes: new Chrome per URL (single pass)."""
    run_idx = args.run_index
    workers = getattr(args, 'workers', 1)

    if workers <= 1:
        # Original sequential behavior
        for url in urls:
            for mode in modes:
                desc = f"{url[:50]} | {mode} | run {run_idx}"
                progress.update(task, description=desc)

                try:
                    result = await asyncio.wait_for(
                        run_benchmark(
                            pw, url, mode, run_idx,
                            args.sample_interval, args.settle_time,
                            args.page_timeout, user_agent=real_ua,
                        ),
                        timeout=args.run_timeout,
                    )
                except asyncio.TimeoutError:
                    result = BenchmarkRun(
                        url=url, mode=mode, run_index=run_idx,
                        error=f"Run timed out after {args.run_timeout}s",
                    )
                all_runs.append(result)

                if result.error:
                    console.print(f"  [yellow]Error: {result.error}[/yellow]")

                progress.advance(task)
    else:
        # Concurrent: semaphore-limited workers
        sem = asyncio.Semaphore(workers)

        async def _bench_one(url, mode):
            async with sem:
                desc = f"{url[:50]} | {mode} | run {run_idx} (w={workers})"
                progress.update(task, description=desc)
                try:
                    result = await asyncio.wait_for(
                        run_benchmark(
                            pw, url, mode, run_idx,
                            args.sample_interval, args.settle_time,
                            args.page_timeout, user_agent=real_ua,
                        ),
                        timeout=args.run_timeout,
                    )
                except asyncio.TimeoutError:
                    result = BenchmarkRun(
                        url=url, mode=mode, run_index=run_idx,
                        error=f"Run timed out after {args.run_timeout}s",
                    )
                all_runs.append(result)
                if result.error:
                    console.print(f"  [yellow]Error: {result.error}[/yellow]")
                progress.advance(task)

        tasks = []
        for url in urls:
            for mode in modes:
                tasks.append(_bench_one(url, mode))
        await asyncio.gather(*tasks)


async def _run_reuse_mode(
    pw, urls, mode, args, real_ua, progress, task, all_runs,
) -> None:
    """Run a reuse-browser mode: one Chrome instance for all URLs."""
    channel, headless = config.launch_params(mode)
    browser = None
    context = None
    page = None

    for attempt in range(3):
        try:
            browser = await pw.chromium.launch(
                headless=headless,
                channel=channel,
                args=config.BROWSER_ARGS,
                timeout=30_000,
            )
            break
        except Exception as e:
            if attempt < 2:
                console.print(f"  [yellow]Chrome launch attempt {attempt + 1} for {mode} failed: {e} — retrying[/yellow]")
                await asyncio.sleep(1)
            else:
                console.print(f"  [red]Failed to launch Chrome for {mode} after 3 attempts: {e}[/red]")
                return

    try:
        ctx_opts: dict = {"viewport": config.VIEWPORT}
        if real_ua:
            ctx_opts["user_agent"] = real_ua
        context = await browser.new_context(**ctx_opts)
        page = await context.new_page()
        await page.add_init_script(WEBDRIVER_PATCH)
        chrome_pid = _find_chrome_pid(browser)

        if chrome_pid is None:
            console.print(f"  [yellow]Cannot find Chrome PID for {mode}, skipping[/yellow]")
            return

        run_idx = args.run_index
        for url in urls:
            desc = f"{url[:50]} | {mode} | run {run_idx}"
            progress.update(task, description=desc)

            try:
                result = await asyncio.wait_for(
                    run_benchmark_reuse(
                        page, chrome_pid, url, mode, run_idx,
                        args.sample_interval, args.settle_time,
                        args.page_timeout,
                    ),
                    timeout=args.run_timeout,
                )
            except asyncio.TimeoutError:
                result = BenchmarkRun(
                    url=url, mode=mode, run_index=run_idx,
                    error=f"Run timed out after {args.run_timeout}s",
                )
            all_runs.append(result)

            if result.error:
                console.print(f"  [yellow]Error: {result.error}[/yellow]")

            progress.advance(task)
    finally:
        if context is not None:
            try:
                await asyncio.wait_for(context.close(), timeout=10)
            except Exception:
                pass
        if browser is not None:
            try:
                await asyncio.wait_for(browser.close(), timeout=10)
            except Exception:
                pass


async def run_mode(args) -> None:
    """Run benchmark for specified modes and save raw results."""
    urls = load_urls(args)
    all_modes = [m.strip() for m in args.modes.split(",")]
    fresh_modes = [m for m in all_modes if not m.endswith("-reuse")]
    reuse_modes = [m for m in all_modes if m.endswith("-reuse")]
    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    # Make world-writable so host user can write report files after container exits
    try:
        output_dir.chmod(0o777)
        output_dir.parent.chmod(0o777)
    except OSError:
        pass

    all_runs: list[BenchmarkRun] = []
    chrome_version = ""
    real_ua = args.user_agent

    async with async_playwright() as pw:
        # Detect which channel to use for version/UA probe
        detect_channel = config.CHANNEL
        if all(m.startswith("headless-shell") for m in all_modes):
            detect_channel = config.HEADLESS_SHELL_CHANNEL

        # Launch browser to detect version/UA — retry up to 3 times (Chrome can SIGSEGV)
        for attempt in range(3):
            try:
                browser = await pw.chromium.launch(
                    headless=True,
                    channel=detect_channel,
                    args=["--no-sandbox"],
                )
                chrome_version = browser.version
                if not real_ua:
                    page = await browser.new_page()
                    real_ua = await page.evaluate("navigator.userAgent")
                    await page.close()
                await browser.close()
                console.print(f"Chrome version: {chrome_version} (channel: {detect_channel})")
                console.print(f"User-Agent: {real_ua}")
                break
            except Exception as e:
                if attempt < 2:
                    console.print(f"[yellow]Chrome launch attempt {attempt + 1} failed: {e} — retrying[/yellow]")
                    await asyncio.sleep(1)
                else:
                    console.print(f"[red]Cannot launch Chrome after 3 attempts: {e}[/red]")
                    sys.exit(1)

        total = len(urls) * len(all_modes)

        console.print(
            f"Benchmarking {len(urls)} URL(s) x {len(all_modes)} mode(s) = {total} iterations (run {args.run_index})"
        )
        console.print(f"  Modes: {', '.join(all_modes)}")

        meta = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "chrome_version": chrome_version,
            "run_index": args.run_index,
            "sample_interval_s": args.sample_interval,
            "settle_time_s": args.settle_time,
            "page_timeout_ms": args.page_timeout,
            "modes": all_modes,
            "urls": urls,
            "workers": getattr(args, 'workers', 1),
        }

        def _save_mode(mode: str) -> None:
            """Save runs for a single mode (atomic write)."""
            mode_runs = [r for r in all_runs if r.mode == mode]
            if mode_runs:
                _save_runs(mode_runs, meta, output_dir / f"runs_{mode}.json")

        try:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                MofNCompleteColumn(),
                console=console,
            ) as progress:
                task = progress.add_task("Benchmarking", total=total)

                # Fresh modes: new browser per URL
                if fresh_modes:
                    await _run_fresh_modes(
                        pw, urls, fresh_modes, args, real_ua, progress, task, all_runs,
                    )
                    # Save fresh mode runs immediately
                    for mode in fresh_modes:
                        _save_mode(mode)

                # Reuse modes: one browser per mode, all URLs on same page
                for mode in reuse_modes:
                    await _run_reuse_mode(
                        pw, urls, mode, args, real_ua, progress, task, all_runs,
                    )
                    # Save after each reuse mode completes
                    _save_mode(mode)
        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted — saving completed runs.[/yellow]")
        except Exception as e:
            console.print(f"\n[red]Benchmark error: {e} — saving completed runs.[/red]")

    # Final save — ensures any runs collected before a crash are persisted
    if all_runs:
        for mode in all_modes:
            mode_runs = [r for r in all_runs if r.mode == mode]
            if mode_runs:
                _save_runs(mode_runs, meta, output_dir / f"runs_{mode}.json")
    else:
        console.print("[red]No completed runs to save.[/red]")


def report_mode(args) -> None:
    """Merge saved run files and generate comparison reports."""
    output_dir: Path = args.output_dir

    run_files = sorted(output_dir.glob("runs_*.json"))
    if not run_files:
        console.print(f"[red]No runs_*.json files found in {output_dir}[/red]")
        sys.exit(1)

    console.print(f"Merging {len(run_files)} run file(s):")
    all_runs: list[BenchmarkRun] = []
    all_metas: list[dict] = []

    for f in run_files:
        console.print(f"  {f.name}")
        meta, runs = _load_runs(f)
        all_metas.append(meta)
        all_runs.extend(runs)

    merged_meta = _merge_meta(all_metas)
    console.print(f"Total runs: {len(all_runs)}")

    generate_all_reports(all_runs, merged_meta, output_dir)


async def main() -> None:
    args = config.build_parser().parse_args()

    if args.report:
        report_mode(args)
    else:
        await run_mode(args)
