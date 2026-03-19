#!/usr/bin/env python3
"""Orchestrate headless + headful benchmark containers.

Usage:
    uv run python bench/run.py --url https://example.com
    uv run python bench/run.py --urls-file bench/urls.txt --runs 3
    uv run python bench/run.py --urls-file bench/urls.txt --parallel
    uv run python bench/run.py --no-build --urls-file bench/urls.txt
    uv run python bench/run.py --report-only
    uv run python bench/run.py --modes headless-shell --urls-file urls.txt --job-dir bench/results/job_xxx
"""

import argparse
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BENCH_DIR.parent
COMPOSE_FILE = BENCH_DIR / "docker-compose.yml"
RESULTS_DIR = BENCH_DIR / "results"

# Map mode name → docker-compose service name
SERVICE_MAP = {
    "headless": "headless",
    "headful": "headful",
    "headless-reuse": "headless",
    "headful-reuse": "headful",
    "headless-shell": "headless-shell",
    "headless-shell-reuse": "headless-shell",
}


def run_cmd(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(cmd)}")
    return subprocess.run(cmd, check=check)


def build_images(services: list[str] | None = None) -> None:
    """Build Docker images. If services specified, build only those."""
    cmd = ["docker", "compose", "-f", str(COMPOSE_FILE), "build", "--no-cache"]
    if services:
        unique = sorted(set(services))
        cmd += unique
        print(f"==> Building Docker images (no cache): {', '.join(unique)}")
    else:
        print("==> Building Docker images (no cache)")
    run_cmd(cmd)


_DETECT_UA_SCRIPT = """\
import subprocess, time, os
subprocess.Popen(['Xvfb', ':99', '-screen', '0', '1280x720x24'],
                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(1)
os.environ['DISPLAY'] = ':99'
from playwright.sync_api import sync_playwright
pw = sync_playwright().start()
b = pw.chromium.launch(headless=False, channel='chrome', args=['--no-sandbox'])
p = b.new_page()
print(p.evaluate('navigator.userAgent'))
b.close()
pw.stop()
"""


def detect_ua() -> str:
    """Detect the real headful Chrome User-Agent from the headful container."""
    print("==> Detecting User-Agent from headful Chrome")
    cmd = [
        "docker", "compose", "-f", str(COMPOSE_FILE), "run", "--rm",
        "--entrypoint", "uv",
        "headful", "run", "python", "-c", _DETECT_UA_SCRIPT,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("Warning: UA detection failed, falling back to auto-detect per container")
        print(f"  stderr: {result.stderr.strip()[:200]}")
        return ""
    ua = result.stdout.strip().splitlines()[-1]
    print(f"  User-Agent: {ua}")
    return ua


def run_container(
    mode: str, run_index: int, bench_args: list[str], volumes: list[str],
    container_output_base: str,
) -> bool:
    service = SERVICE_MAP.get(mode)
    if service is None:
        print(f"Error: unknown mode '{mode}' — no service mapping", file=sys.stderr)
        return False
    run_output = f"{container_output_base}/run_{run_index}"
    print(f"==> Running {mode} container (run {run_index})")
    cmd = [
        "docker", "compose", "-f", str(COMPOSE_FILE), "run", "--rm",
        *volumes,
        service,
        "--modes", mode,
        "--run-index", str(run_index),
        "--output-dir", run_output,
        *bench_args,
    ]
    result = run_cmd(cmd, check=False)
    if result.returncode != 0:
        print(f"Error: {mode} run {run_index} container failed (exit {result.returncode})")
        return False
    print(f"==> {mode} run {run_index} complete")
    return True


def generate_reports(job_dir: Path) -> None:
    """Generate a report for each run subdirectory."""
    run_dirs = sorted(job_dir.glob("run_*"))
    if not run_dirs:
        print("Warning: no run_* subdirectories found, trying job dir directly")
        run_cmd([
            "uv", "run", "python", "-m", "bench",
            "--report", "--output-dir", str(job_dir),
        ])
        return

    for run_dir in run_dirs:
        print(f"\n==> Generating report for {run_dir.name}")
        run_cmd([
            "uv", "run", "python", "-m", "bench",
            "--report", "--output-dir", str(run_dir),
        ])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build and run headless + headful Chrome benchmarks in Docker.",
    )
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--url", type=str, help="Single URL to benchmark")
    target.add_argument("--urls-file", type=Path, help="File with one URL per line")
    parser.add_argument("--runs", type=int, default=3, help="Number of separate container runs per mode (default: 3)")
    parser.add_argument("--settle-time", type=float, default=2.0, help="Wait after page load (default: 2.0)")
    parser.add_argument("--sample-interval", type=float, default=0.25, help="Sampling interval (default: 0.25)")
    parser.add_argument("--page-timeout", type=int, default=10000, help="Navigation timeout in ms (default: 10000)")
    parser.add_argument("--run-timeout", type=int, default=60, help="Max seconds per URL before killing (default: 60)")
    parser.add_argument("--limit", type=int, default=0, help="Only use the first N URLs from the file (default: all)")
    parser.add_argument("--reuse-browser", action="store_true", help="Also run reuse-browser variants (4 modes total)")
    parser.add_argument("--modes", type=str, default="",
                        help="Explicit comma-separated modes (overrides defaults). "
                             "E.g.: headless-shell,headless-shell-reuse")
    parser.add_argument("--user-agent", type=str, default="",
                        help="Override User-Agent (skip auto-detection)")
    parser.add_argument("--parallel", action="store_true", help="Run headless and headful containers in parallel")
    parser.add_argument("--no-build", action="store_true", help="Skip Docker image build")
    parser.add_argument("--report-only", action="store_true", help="Only merge existing results and generate report")
    parser.add_argument("--job-dir", type=Path, default=None,
                        help="Job directory (for --report-only or to append results to an existing job)")
    return parser


def load_urls(path: Path, limit: int) -> list[str]:
    """Load URLs from file, deduplicate, and optionally limit."""
    seen: set[str] = set()
    urls: list[str] = []
    for line in path.read_text().splitlines():
        url = line.strip()
        if not url or url.startswith("#") or url in seen:
            continue
        seen.add(url)
        urls.append(url)
    if limit > 0:
        urls = urls[:limit]
    return urls


def _find_latest_job() -> Path | None:
    """Find the most recent job directory under RESULTS_DIR."""
    jobs = sorted(RESULTS_DIR.glob("job_*"), reverse=True)
    return jobs[0] if jobs else None


def main() -> None:
    args = build_parser().parse_args()

    if args.report_only:
        job_dir = args.job_dir or _find_latest_job()
        if not job_dir or not job_dir.exists():
            print("Error: no job directory found. Use --job-dir to specify one.", file=sys.stderr)
            sys.exit(1)
        print(f"==> Reporting on: {job_dir}")
        generate_reports(job_dir)
        return

    if not args.url and not args.urls_file:
        print("Error: --url or --urls-file is required (unless --report-only)", file=sys.stderr)
        sys.exit(1)

    # Determine modes to run
    if args.modes:
        all_modes = [m.strip() for m in args.modes.split(",")]
        # Validate all modes have a service mapping
        for m in all_modes:
            if m not in SERVICE_MAP:
                print(f"Error: unknown mode '{m}'. Valid: {', '.join(sorted(SERVICE_MAP))}", file=sys.stderr)
                sys.exit(1)
    else:
        fresh_modes = ["headless", "headful"]
        reuse_modes = ["headless-reuse", "headful-reuse"] if args.reuse_browser else []
        all_modes = fresh_modes + reuse_modes

    fresh_modes = [m for m in all_modes if not m.endswith("-reuse")]
    reuse_modes = [m for m in all_modes if m.endswith("-reuse")]

    # Job directory: reuse existing or create new
    if args.job_dir:
        job_dir = args.job_dir
        job_dir.mkdir(parents=True, exist_ok=True)
        # Derive the job name from the path for container output mapping
        job_name = job_dir.name
        print(f"==> Appending to job directory: {job_dir}")
    else:
        job_name = "job_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        job_dir = RESULTS_DIR / job_name
        job_dir.mkdir(parents=True, exist_ok=True)
        print(f"==> Job directory: {job_dir}")

    # Container output dir is relative to the mount point
    container_output = f"/app/bench/results/{job_name}"

    # Build container bench args (each container does one pass; --run-index and --output-dir set per launch)
    bench_args = [
        "--settle-time", str(args.settle_time),
        "--sample-interval", str(args.sample_interval),
        "--page-timeout", str(args.page_timeout),
        "--run-timeout", str(args.run_timeout),
    ]

    volumes: list[str] = []
    tmp_file = None

    if args.url:
        bench_args += ["--url", args.url]
    else:
        urls_path = args.urls_file.resolve()
        if not urls_path.is_file():
            print(f"Error: URLs file not found: {urls_path}", file=sys.stderr)
            sys.exit(1)

        urls = load_urls(urls_path, args.limit)
        if not urls:
            print("Error: no URLs found in file", file=sys.stderr)
            sys.exit(1)
        print(f"==> {len(urls)} URLs loaded (deduped{f', limited to {args.limit}' if args.limit else ''})")

        # Write cleaned URL list to a temp file for mounting
        tmp_file = tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", prefix="bench_urls_", delete=False
        )
        tmp_file.write("\n".join(urls) + "\n")
        tmp_file.flush()

        volumes += ["-v", f"{tmp_file.name}:/app/bench/urls.txt:ro"]
        bench_args += ["--urls-file", "/app/bench/urls.txt"]

    try:
        if not args.no_build:
            # Only build services needed for the requested modes
            services_needed = list({SERVICE_MAP[m] for m in all_modes})
            # UA detection needs headful — build it too if not already included
            needs_ua_detection = not args.user_agent and "headful" not in services_needed
            if needs_ua_detection:
                services_needed.append("headful")
            build_images(services_needed)

        # User-Agent: use provided, or detect from headful Chrome
        if args.user_agent:
            ua = args.user_agent
            print(f"==> User-Agent (provided): {ua}")
        else:
            ua = detect_ua()
        if ua:
            bench_args += ["--user-agent", ua]

        total_containers = len(all_modes) * args.runs
        print(f"==> {total_containers} containers to launch ({len(all_modes)} modes x {args.runs} runs)")

        for run_idx in range(args.runs):
            print(f"\n==> Run {run_idx + 1}/{args.runs}")

            if args.parallel:
                # Run fresh modes in parallel
                if fresh_modes:
                    with ThreadPoolExecutor(max_workers=len(fresh_modes)) as pool:
                        futures = {
                            pool.submit(run_container, mode, run_idx, bench_args, volumes, container_output): mode
                            for mode in fresh_modes
                        }
                        failed = []
                        for future in as_completed(futures):
                            mode = futures[future]
                            if not future.result():
                                failed.append(mode)
                        if failed:
                            print(f"Warning: {', '.join(failed)} run {run_idx} failed.")

                # Run reuse modes in parallel
                if reuse_modes:
                    with ThreadPoolExecutor(max_workers=len(reuse_modes)) as pool:
                        futures = {
                            pool.submit(run_container, mode, run_idx, bench_args, volumes, container_output): mode
                            for mode in reuse_modes
                        }
                        for future in as_completed(futures):
                            mode = futures[future]
                            if not future.result():
                                print(f"Warning: {mode} run {run_idx} failed.")
            else:
                for mode in all_modes:
                    run_container(mode, run_idx, bench_args, volumes, container_output)

        generate_reports(job_dir)
    finally:
        if tmp_file is not None:
            Path(tmp_file.name).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
