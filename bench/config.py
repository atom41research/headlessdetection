"""Configuration and CLI argument parsing for the bench utility."""

import argparse
from pathlib import Path

# Browser settings (from CLAUDE.md rules)
CHANNEL = "chrome"
HEADLESS_SHELL_CHANNEL = "chromium-headless-shell"
BROWSER_ARGS = [
    "--no-sandbox",
    "--disable-blink-features=AutomationControlled",
    "--disable-crashpad",
]
VIEWPORT = {"width": 1280, "height": 720}


def launch_params(mode: str) -> tuple[str, bool]:
    """Return (channel, headless) for a given benchmark mode."""
    if mode.startswith("headless-shell"):
        return HEADLESS_SHELL_CHANNEL, True
    if mode.startswith("headful"):
        return CHANNEL, False
    return CHANNEL, True

# Benchmark defaults
DEFAULT_RUNS = 3
DEFAULT_SETTLE_TIME_S = 2.0
DEFAULT_SAMPLE_INTERVAL_S = 0.25
DEFAULT_PAGE_TIMEOUT_MS = 10_000
DEFAULT_RUN_TIMEOUT_S = 60
DEFAULT_OUTPUT_DIR = Path("bench/results")
WAIT_UNTIL = "domcontentloaded"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Benchmark CPU/RAM overhead of headful vs headless Chrome",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Merge existing runs_*.json files and generate comparison reports (no benchmarking)",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--url",
        type=str,
        help="Single URL to benchmark",
    )
    group.add_argument(
        "--urls-file",
        type=Path,
        help="Path to file with one URL per line",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=DEFAULT_RUNS,
        help=f"Iterations per URL per mode (default {DEFAULT_RUNS})",
    )
    parser.add_argument(
        "--settle-time",
        type=float,
        default=DEFAULT_SETTLE_TIME_S,
        help=f"Seconds to wait after page load (default {DEFAULT_SETTLE_TIME_S})",
    )
    parser.add_argument(
        "--sample-interval",
        type=float,
        default=DEFAULT_SAMPLE_INTERVAL_S,
        help=f"psutil sampling interval in seconds (default {DEFAULT_SAMPLE_INTERVAL_S})",
    )
    parser.add_argument(
        "--page-timeout",
        type=int,
        default=DEFAULT_PAGE_TIMEOUT_MS,
        help=f"Navigation timeout in ms (default {DEFAULT_PAGE_TIMEOUT_MS})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Directory for results (default {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--run-timeout",
        type=int,
        default=DEFAULT_RUN_TIMEOUT_S,
        help=f"Max seconds per URL run before killing (default {DEFAULT_RUN_TIMEOUT_S})",
    )
    parser.add_argument(
        "--user-agent",
        type=str,
        default="",
        help="Override User-Agent (default: auto-detect from Chrome)",
    )
    parser.add_argument(
        "--modes",
        type=str,
        default="headless,headful",
        help="Comma-separated modes to benchmark (default headless,headful)",
    )
    parser.add_argument(
        "--run-index",
        type=int,
        default=0,
        help="Index of this run (set by orchestrator, default 0)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Concurrent browser instances for fresh modes (default 1 = sequential). "
             "Reuse modes always run sequentially.",
    )
    return parser
