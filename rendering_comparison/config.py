"""Configuration and CLI argument parsing."""

import argparse
from pathlib import Path

# Paths
DEFAULT_INPUT = Path("urls.txt")
DEFAULT_OUTPUT_DIR = Path("rendering_comparison/output")

# Browser settings
CHANNEL = "chrome"
HEADLESS_SHELL_CHANNEL = "chromium-headless-shell"
VIEWPORT = {"width": 1280, "height": 720}
BROWSER_ARGS = [
    "--no-sandbox",
    "--disable-blink-features=AutomationControlled",
]

# Mode → (channel, headless flag)
MODE_PARAMS: dict[str, tuple[str, bool]] = {
    "headless": (CHANNEL, True),
    "headful": (CHANNEL, False),
    "headless-shell": (HEADLESS_SHELL_CHANNEL, True),
}

DEFAULT_MODES = "headless,headful"

# Match the real headful Chrome UA so headless doesn't leak "HeadlessChrome"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36"
)

# Timing — cap load at 10s, then collect whatever rendered
PAGE_TIMEOUT_MS = 10_000
SETTLE_TIME_S = 2.0
WAIT_UNTIL = "domcontentloaded"

# Batching
DEFAULT_TOP_N = 50
BATCH_SIZE = 10

# Diff thresholds
SCREENSHOT_DIFF_THRESHOLD = 0.05  # 5% pixel difference
DOM_COUNT_RATIO_THRESHOLD = 0.20  # 20% element count diff
CONTENT_LENGTH_RATIO_THRESHOLD = 0.20


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare rendering across Chrome modes (headless, headful, headless-shell)",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help="Path to the top_diffs_rendering.md file",
    )
    parser.add_argument(
        "--urls-file",
        type=Path,
        default=None,
        help="Plain text file with one URL per line (bypasses --input ranking parser)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Output directory for results and screenshots",
    )
    parser.add_argument(
        "--modes",
        type=str,
        default=DEFAULT_MODES,
        help=f"Comma-separated modes to compare (default: {DEFAULT_MODES}). "
             f"Valid: {', '.join(sorted(MODE_PARAMS))}",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=DEFAULT_TOP_N,
        help="Number of top-ranked URLs to process",
    )
    parser.add_argument(
        "--start-rank",
        type=int,
        default=1,
        help="Start from this rank (for resuming)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=BATCH_SIZE,
        help="URLs per batch",
    )
    parser.add_argument(
        "--csv-input",
        type=Path,
        default=None,
        help="Path to a results.csv from a previous run. "
        "When provided, URLs are read from this CSV instead of the markdown ranking file.",
    )
    parser.add_argument(
        "--filter-diff-types",
        type=str,
        nargs="*",
        default=None,
        help="Only re-run URLs with these diff_type values (e.g., missing_content dom_diff). "
        "Only used with --csv-input.",
    )
    parser.add_argument(
        "--min-net-req-diff",
        type=int,
        default=None,
        help="Only re-run URLs where |network_request_diff| >= this value. "
        "Only used with --csv-input.",
    )
    parser.add_argument(
        "--full-better",
        action="store_true",
        default=True,
        help="Only include URLs where full mode rendered more DOM (default)",
    )
    parser.add_argument(
        "--all-urls",
        action="store_true",
        help="Include all URLs regardless of which mode rendered more",
    )
    return parser
