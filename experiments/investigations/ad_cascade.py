"""Investigation into ad-tech cascade behavior in headless vs headful Chrome.

When visiting ad-heavy sites like w3schools.com, headful Chrome fires ~236 network
requests while headless (with spoofed UA) fires only ~44. The difference is almost
entirely ad/tracking infrastructure: prebid.js cookie-sync cascades fan out across
78+ domains in headful but barely execute in headless.

This script investigates:
1. Whether the signal reproduces reliably with our Chrome setup
2. Whether increased settle time closes the gap (timing cause)
3. Whether overriding visibilityState/hasFocus closes the gap
4. Whether pre-seeding cookies closes the gap
5. Which browser APIs differ between headful and headless

Usage:
    uv run python -m experiments.investigations.ad_cascade
    uv run python -m experiments.investigations.ad_cascade --experiment baseline
    uv run python -m experiments.investigations.ad_cascade --experiment all
"""

import argparse
import asyncio
import json
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright
from rich.console import Console
from rich.table import Table

from core import config
from core.config import BASE_URL as BASE, DEFAULT_VIEWPORT as VIEWPORT, BROWSER_ARGS, CHANNEL
from core.browser import close_all, detect_chrome_ua

console = Console()

TARGET_URL = "https://www.w3schools.com"

# Ad/tracking domain keywords for classification
AD_KEYWORDS = [
    "googletagmanager", "googlesyndication", "doubleclick", "adnxs",
    "casalemedia", "richaudience", "3lift", "omnitagjs", "smartadserver",
    "sharethrough", "bricks-co", "prebid", "google-analytics", "googleads",
    "rubiconproject", "bidswitch", "adsrvr", "criteo", "taboola", "outbrain",
    "pubmatic", "openx", "appnexus", "spotx", "indexexchange", "triplelift",
    "sparteo", "measureadv", "id5-sync", "intentiq", "liveintent",
]
CONSENT_KEYWORDS = ["fastcmp", "consent", "privacy", "cmp", "cookielaw"]

WEBDRIVER_PATCH = (
    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
)

FINGERPRINT_JS = """() => {
    const fp = {};
    fp.visibilityState = document.visibilityState;
    fp.hidden = document.hidden;
    fp.hasFocus = document.hasFocus();
    fp.webdriver = navigator.webdriver;
    fp.cookieEnabled = navigator.cookieEnabled;
    fp.hardwareConcurrency = navigator.hardwareConcurrency;
    fp.deviceMemory = navigator.deviceMemory;
    fp.maxTouchPoints = navigator.maxTouchPoints;
    fp.platform = navigator.platform;
    fp.userAgent = navigator.userAgent;
    fp.languages = navigator.languages;
    fp.windowChrome = typeof window.chrome !== 'undefined';
    fp.chromeRuntime = typeof window.chrome !== 'undefined' && typeof window.chrome.runtime !== 'undefined';
    fp.pluginsLength = navigator.plugins.length;
    fp.mimeTypesLength = navigator.mimeTypes.length;

    // Screen properties
    fp.screenWidth = screen.width;
    fp.screenHeight = screen.height;
    fp.availWidth = screen.availWidth;
    fp.availHeight = screen.availHeight;
    fp.colorDepth = screen.colorDepth;
    fp.pixelDepth = screen.pixelDepth;
    fp.outerWidth = window.outerWidth;
    fp.outerHeight = window.outerHeight;

    // Connection info (ad scripts check this)
    try {
        const conn = navigator.connection;
        if (conn) {
            fp.effectiveType = conn.effectiveType;
            fp.downlink = conn.downlink;
            fp.rtt = conn.rtt;
            fp.saveData = conn.saveData;
        }
    } catch(e) {}

    // Notification permission (ad scripts probe this)
    try {
        fp.notificationPermission = Notification.permission;
    } catch(e) { fp.notificationPermission = 'error'; }

    // WebGL renderer
    try {
        const canvas = document.createElement('canvas');
        const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
        if (gl) {
            const ext = gl.getExtension('WEBGL_debug_renderer_info');
            if (ext) {
                fp.webglVendor = gl.getParameter(ext.UNMASKED_VENDOR_WEBGL);
                fp.webglRenderer = gl.getParameter(ext.UNMASKED_RENDERER_WEBGL);
            }
        }
    } catch(e) {}

    return fp;
}"""

VISIBILITY_OVERRIDE_SCRIPT = """
Object.defineProperty(document, 'visibilityState', {
    get: function() { return 'visible'; }
});
Object.defineProperty(document, 'hidden', {
    get: function() { return false; }
});
Document.prototype.hasFocus = function() { return true; };
"""


def classify_url(url: str) -> str:
    """Classify a URL as 'first-party', 'ad-tracking', 'consent', or 'other'."""
    lower = url.lower()
    if "w3schools.com" in lower:
        return "first-party"
    if any(kw in lower for kw in CONSENT_KEYWORDS):
        return "consent"
    if any(kw in lower for kw in AD_KEYWORDS):
        return "ad-tracking"
    return "other-3p"


def analyze_har(har_path: Path) -> dict:
    """Parse a HAR file and return classified request counts."""
    with open(har_path) as f:
        har = json.load(f)

    entries = har["log"]["entries"]
    categories = Counter()
    domains = set()
    domain_counts = Counter()

    for entry in entries:
        url = entry["request"]["url"]
        cat = classify_url(url)
        categories[cat] += 1
        domain = urlparse(url).netloc
        domains.add(domain)
        domain_counts[domain] += 1

    return {
        "total": len(entries),
        "categories": dict(categories),
        "unique_domains": len(domains),
        "domain_counts": dict(domain_counts.most_common(20)),
    }


async def launch(pw, headless: bool, *, extra_init_scripts: list[str] | None = None):
    """Launch Chrome with standard config."""
    browser = await pw.chromium.launch(
        headless=headless,
        channel=CHANNEL,
        args=BROWSER_ARGS,
    )
    ctx_args: dict = {"viewport": VIEWPORT}
    if headless:
        ctx_args["user_agent"] = config.CHROME_USER_AGENT
    context = await browser.new_context(**ctx_args)
    page = await context.new_page()
    await page.add_init_script(WEBDRIVER_PATCH)
    for script in extra_init_scripts or []:
        await page.add_init_script(script)
    return browser, context, page


async def visit_with_har(
    pw,
    url: str,
    headless: bool,
    settle: float = 5.0,
    extra_init_scripts: list[str] | None = None,
    cookies: list[dict] | None = None,
) -> dict:
    """Visit a URL, capture HAR, return analysis."""
    with tempfile.TemporaryDirectory() as tmpdir:
        har_path = Path(tmpdir) / "capture.har"

        browser = await pw.chromium.launch(
            headless=headless,
            channel=CHANNEL,
            args=BROWSER_ARGS,
        )
        ctx_args: dict = {
            "viewport": VIEWPORT,
            "record_har_path": str(har_path),
        }
        if headless:
            ctx_args["user_agent"] = config.CHROME_USER_AGENT
        context = await browser.new_context(**ctx_args)

        if cookies:
            await context.add_cookies(cookies)

        page = await context.new_page()
        await page.add_init_script(WEBDRIVER_PATCH)
        for script in extra_init_scripts or []:
            await page.add_init_script(script)

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        except Exception:
            pass  # partial load is fine

        await asyncio.sleep(settle)

        # Collect fingerprint before closing
        fingerprint = {}
        try:
            fingerprint = await page.evaluate(FINGERPRINT_JS)
        except Exception:
            pass

        await page.close()
        await context.close()
        await browser.close()

        result = analyze_har(har_path)
        result["fingerprint"] = fingerprint
        return result


def print_comparison_table(headful: dict, headless: dict, title: str):
    """Print a comparison table of HAR analysis results."""
    table = Table(title=title, show_lines=True)
    table.add_column("Metric", style="bold")
    table.add_column("Headful", justify="right")
    table.add_column("Headless", justify="right")
    table.add_column("Delta", justify="right")

    table.add_row(
        "Total requests",
        str(headful["total"]),
        str(headless["total"]),
        f"[red]+{headful['total'] - headless['total']}[/]",
    )
    table.add_row(
        "Unique domains",
        str(headful["unique_domains"]),
        str(headless["unique_domains"]),
        f"+{headful['unique_domains'] - headless['unique_domains']}",
    )

    all_cats = sorted(
        set(headful["categories"].keys()) | set(headless["categories"].keys())
    )
    for cat in all_cats:
        fc = headful["categories"].get(cat, 0)
        hc = headless["categories"].get(cat, 0)
        delta = fc - hc
        style = "[red]" if delta > 5 else "[green]" if delta < -5 else ""
        end = "[/]" if style else ""
        table.add_row(
            f"  {cat}",
            str(fc),
            str(hc),
            f"{style}{delta:+d}{end}",
        )

    console.print(table)


def print_fingerprint_diff(headful_fp: dict, headless_fp: dict):
    """Print a table of fingerprint differences."""
    table = Table(title="Browser API Fingerprints", show_lines=True)
    table.add_column("Property", style="bold")
    table.add_column("Headful")
    table.add_column("Headless")
    table.add_column("Match?", justify="center")

    all_keys = sorted(set(headful_fp.keys()) | set(headless_fp.keys()))
    for key in all_keys:
        fv = str(headful_fp.get(key, "N/A"))
        hv = str(headless_fp.get(key, "N/A"))
        match = "[green]YES[/]" if fv == hv else "[red]NO[/]"
        table.add_row(key, fv[:60], hv[:60], match)

    console.print(table)


async def experiment_baseline(pw):
    """Experiment 1: Baseline comparison — visit w3schools in both modes."""
    console.rule("[bold]Experiment 1: Baseline Comparison")
    console.print(f"  URL: {TARGET_URL}")
    console.print("  Settle: 5s\n")

    console.print("  Running headful...", end=" ")
    headful = await visit_with_har(pw, TARGET_URL, headless=False, settle=5.0)
    console.print("[green]done[/]")

    console.print("  Running headless...", end=" ")
    headless = await visit_with_har(pw, TARGET_URL, headless=True, settle=5.0)
    console.print("[green]done[/]")

    print_comparison_table(headful, headless, "Baseline: w3schools.com")

    # Show top domains only in headful
    headful_domains = set(headful["domain_counts"].keys())
    headless_domains = set(headless["domain_counts"].keys())
    only_headful = headful_domains - headless_domains
    if only_headful:
        console.print(
            f"\n  [red]Domains only in headful ({len(only_headful)}):[/]"
        )
        for d in sorted(only_headful)[:15]:
            console.print(f"    {d}")
        if len(only_headful) > 15:
            console.print(f"    ... and {len(only_headful) - 15} more")

    return headful, headless


async def experiment_settle_time(pw):
    """Experiment 2: Does increasing settle time close the gap?"""
    console.rule("[bold]Experiment 2: Settle Time Sweep")

    for settle in [2.0, 5.0, 10.0, 20.0]:
        console.print(f"\n  Settle time: {settle}s")
        console.print("    Headful...", end=" ")
        headful = await visit_with_har(pw, TARGET_URL, headless=False, settle=settle)
        console.print("[green]done[/]", end="  ")
        console.print("Headless...", end=" ")
        headless = await visit_with_har(pw, TARGET_URL, headless=True, settle=settle)
        console.print("[green]done[/]")
        print_comparison_table(headful, headless, f"Settle = {settle}s")


async def experiment_visibility_override(pw):
    """Experiment 3: Override visibilityState and hasFocus in headless."""
    console.rule("[bold]Experiment 3: Visibility/Focus Override")
    console.print("  Patching: document.visibilityState='visible', hasFocus()=true\n")

    console.print("  Headful (no patch, control)...", end=" ")
    headful = await visit_with_har(pw, TARGET_URL, headless=False, settle=5.0)
    console.print("[green]done[/]")

    console.print("  Headless (no patch)...", end=" ")
    headless_no_patch = await visit_with_har(
        pw, TARGET_URL, headless=True, settle=5.0
    )
    console.print("[green]done[/]")

    console.print("  Headless (with visibility patch)...", end=" ")
    headless_patched = await visit_with_har(
        pw,
        TARGET_URL,
        headless=True,
        settle=5.0,
        extra_init_scripts=[VISIBILITY_OVERRIDE_SCRIPT],
    )
    console.print("[green]done[/]")

    print_comparison_table(headful, headless_no_patch, "Headful vs Headless (no patch)")
    print_comparison_table(
        headful, headless_patched, "Headful vs Headless (visibility patched)"
    )

    # Did the patch help?
    no_patch_total = headless_no_patch["total"]
    patched_total = headless_patched["total"]
    console.print(
        f"\n  Headless no-patch: {no_patch_total} requests, "
        f"patched: {patched_total} requests "
        f"(delta: {patched_total - no_patch_total:+d})"
    )
    if patched_total > no_patch_total + 10:
        console.print("  [green]Visibility patch recovered requests![/]")
    else:
        console.print("  [yellow]Visibility patch had little effect[/]")


async def experiment_cookies(pw):
    """Experiment 4: Pre-seed common ad-tech cookies."""
    console.rule("[bold]Experiment 4: Cookie Pre-seeding")

    # Common ad-tech cookies that might unblock cascades
    ad_cookies = [
        {"name": "test_cookie", "value": "CheckForPermission", "domain": ".doubleclick.net", "path": "/"},
        {"name": "_ga", "value": "GA1.2.123456789.1234567890", "domain": ".w3schools.com", "path": "/"},
        {"name": "_gid", "value": "GA1.2.987654321.1234567890", "domain": ".w3schools.com", "path": "/"},
        {"name": "euconsent-v2", "value": "VALID_CONSENT_STRING", "domain": ".w3schools.com", "path": "/"},
    ]

    console.print("  Headful (no extra cookies, control)...", end=" ")
    headful = await visit_with_har(pw, TARGET_URL, headless=False, settle=5.0)
    console.print("[green]done[/]")

    console.print("  Headless (no cookies)...", end=" ")
    headless_no_cookies = await visit_with_har(
        pw, TARGET_URL, headless=True, settle=5.0
    )
    console.print("[green]done[/]")

    console.print("  Headless (with pre-seeded cookies)...", end=" ")
    headless_cookies = await visit_with_har(
        pw, TARGET_URL, headless=True, settle=5.0, cookies=ad_cookies
    )
    console.print("[green]done[/]")

    print_comparison_table(
        headful, headless_no_cookies, "Headful vs Headless (no cookies)"
    )
    print_comparison_table(
        headful, headless_cookies, "Headful vs Headless (pre-seeded cookies)"
    )


async def experiment_fingerprint(pw):
    """Experiment 5: Collect and compare browser API fingerprints."""
    console.rule("[bold]Experiment 5: API Fingerprint Comparison")

    console.print("  Headful...", end=" ")
    headful = await visit_with_har(pw, TARGET_URL, headless=False, settle=3.0)
    console.print("[green]done[/]")

    console.print("  Headless...", end=" ")
    headless = await visit_with_har(pw, TARGET_URL, headless=True, settle=3.0)
    console.print("[green]done[/]")

    print_fingerprint_diff(headful["fingerprint"], headless["fingerprint"])


async def experiment_multi_run(pw, runs: int = 5):
    """Experiment 6: Multiple runs for consistency check."""
    console.rule(f"[bold]Experiment 6: Multi-run Consistency ({runs} runs)")

    headful_totals = []
    headless_totals = []
    headful_ad = []
    headless_ad = []

    for i in range(runs):
        console.print(f"  Run {i + 1}/{runs}...", end=" ")

        hf = await visit_with_har(pw, TARGET_URL, headless=False, settle=5.0)
        hl = await visit_with_har(pw, TARGET_URL, headless=True, settle=5.0)

        headful_totals.append(hf["total"])
        headless_totals.append(hl["total"])
        headful_ad.append(hf["categories"].get("ad-tracking", 0))
        headless_ad.append(hl["categories"].get("ad-tracking", 0))

        console.print(
            f"headful={hf['total']} headless={hl['total']} "
            f"(ad: {hf['categories'].get('ad-tracking', 0)} vs "
            f"{hl['categories'].get('ad-tracking', 0)})"
        )

    table = Table(title="Multi-run Summary", show_lines=True)
    table.add_column("Metric", style="bold")
    table.add_column("Headful", justify="right")
    table.add_column("Headless", justify="right")

    def fmt_stats(vals):
        avg = sum(vals) / len(vals)
        mn, mx = min(vals), max(vals)
        return f"{avg:.0f} (range: {mn}-{mx})"

    table.add_row("Total requests", fmt_stats(headful_totals), fmt_stats(headless_totals))
    table.add_row("Ad/tracking requests", fmt_stats(headful_ad), fmt_stats(headless_ad))
    console.print(table)


EXPERIMENTS = {
    "baseline": experiment_baseline,
    "settle": experiment_settle_time,
    "visibility": experiment_visibility_override,
    "cookies": experiment_cookies,
    "fingerprint": experiment_fingerprint,
    "multi-run": experiment_multi_run,
}


async def main(args: argparse.Namespace):
    console.print("\n[bold]Ad-Tech Cascade Investigation[/bold]")
    console.print(f"  Chrome channel: {CHANNEL}")
    console.print(f"  Viewport: {VIEWPORT['width']}x{VIEWPORT['height']}")
    console.print(f"  Target: {TARGET_URL}\n")

    # Detect real headful UA for spoofing
    async with async_playwright() as pw_init:
        await detect_chrome_ua(pw_init)
    console.print(f"  UA spoofed for headless: yes ({config.CHROME_USER_AGENT[:50]}...)\n")

    experiments = (
        list(EXPERIMENTS.values())
        if args.experiment == "all"
        else [EXPERIMENTS[args.experiment]]
    )

    async with async_playwright() as pw:
        for exp in experiments:
            await exp(pw)

    console.print("\n[bold green]Investigation complete.[/bold green]\n")


def cli():
    parser = argparse.ArgumentParser(description="Ad cascade headless investigation")
    parser.add_argument(
        "--experiment",
        default="all",
        choices=["all", *EXPERIMENTS.keys()],
        help="Which experiment to run (default: all)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(main(cli()))
