"""Test the headless detector with headful, headless, and headless-shell Chrome.

All modes use stealth flags to hide obvious automation signals:
  - --disable-blink-features=AutomationControlled  (hides navigator.webdriver)
  - Headful user-agent string (no "HeadlessChrome" in UA)
  - System Chrome for headful/headless (channel="chrome")
  - Playwright's bundled binary for headless-shell (channel="chromium-headless-shell")

The detector must rely on deeper signals (frame timing, window dims, GPU,
HTTP headers) rather than trivially-spoofed ones.

Usage:
    uv run python -m detector.cli
    uv run python -m detector.cli --runs 5
    uv run python -m detector.cli --modes headful,headless-shell
"""

import argparse
import asyncio
import time

import httpx
from playwright.async_api import async_playwright
from rich.console import Console
from rich.table import Table

from core import config
from core.browser import detect_chrome_ua
from core.config import BROWSER_ARGS, DETECTOR_URL, MODE_PARAMS

SERVER_URL = DETECTOR_URL
console = Console()

# Fallback headful UA — used when detect_chrome_ua() hasn't been called yet
HEADFUL_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# Expected verdicts per mode (extends core.config.MODE_PARAMS which only has
# channel + headless flag).
EXPECTED_VERDICTS: dict[str, str] = {
    "headful": "headful",
    "headless": "headless",
    "headless-shell": "headless",
}


async def wait_for_server(url: str, timeout: float = 10.0):
    deadline = time.monotonic() + timeout
    async with httpx.AsyncClient() as client:
        while time.monotonic() < deadline:
            try:
                resp = await client.get(f"{url}/api/session")
                if resp.status_code == 200:
                    return
            except httpx.ConnectError:
                pass
            await asyncio.sleep(0.2)
    raise TimeoutError(f"Server at {url} did not start within {timeout}s")


async def run_detection(pw, mode: str, url: str) -> dict:
    """Visit the detection page and retrieve the server-side verdict."""
    channel, headless = MODE_PARAMS[mode]

    browser = await pw.chromium.launch(
        headless=headless,
        channel=channel,
        args=BROWSER_ARGS,
    )
    ua = config.CHROME_USER_AGENT or HEADFUL_UA
    context = await browser.new_context(
        user_agent=ua,
        viewport={"width": 1280, "height": 720},
    )
    page = await context.new_page()

    await page.goto(url, wait_until="networkidle")
    # Wait for the JS probes to finish and set the data-verdict attribute
    await page.wait_for_function(
        "() => document.getElementById('verdict').getAttribute('data-verdict') !== ''",
        timeout=30000,
    )
    await asyncio.sleep(0.3)

    # Read the clean verdict from the data attribute
    detected = await page.get_attribute("#verdict", "data-verdict")
    verdict_text = await page.inner_text("#verdict")

    await page.close()
    await context.close()
    await browser.close()

    return {"mode": mode, "detected": detected or "unknown", "verdict_text": verdict_text}


async def main(args: argparse.Namespace):
    modes = args.modes.split(",")
    for m in modes:
        if m not in MODE_PARAMS:
            console.print(f"[red]Unknown mode: {m}. Valid: {', '.join(MODE_PARAMS)}[/red]")
            return

    console.print(f"\n[bold]Headless Detector Test[/bold]")
    console.print(f"Server: {SERVER_URL}")
    console.print(f"Modes: {', '.join(modes)}")
    console.print(f"Runs per mode: {args.runs}")
    console.print(f"Stealth flags: {', '.join(BROWSER_ARGS)}")
    console.print(f"UA override: yes (headful UA for all modes)\n")

    await wait_for_server(SERVER_URL)
    console.print("[green]Server is ready[/green]\n")

    # Verify headless-shell is installed if needed
    if "headless-shell" in modes:
        async with async_playwright() as pw:
            try:
                b = await pw.chromium.launch(
                    channel="chromium-headless-shell", headless=True,
                    args=["--no-sandbox"],
                )
                await b.close()
            except Exception as e:
                console.print(
                    f"[red]Cannot launch chromium-headless-shell: {e}\n"
                    f"Install it with: uv run playwright install chromium-headless-shell[/red]"
                )
                return

    results = []
    pages = [("direct", SERVER_URL), ("iframe", f"{SERVER_URL}/iframe")]

    async with async_playwright() as pw:
        for page_label, page_url in pages:
            console.print(f"\n[bold]--- {page_label.upper()} page ---[/bold]")
            for run_idx in range(args.runs):
                for mode in modes:
                    console.print(f"  Run {run_idx + 1}/{args.runs} | {mode}...", end=" ")
                    try:
                        result = await run_detection(pw, mode, page_url)
                        result["page"] = page_label
                        results.append(result)
                        console.print(f"[dim]{result['verdict_text']}[/dim]")
                    except Exception as e:
                        console.print(f"[red]ERROR: {e}[/red]")
                        results.append({"mode": mode, "detected": "error", "verdict_text": str(e), "page": page_label})

    # Fetch all stored results from the server
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{SERVER_URL}/api/all-results")
        all_server_results = resp.json()

    # Summary table
    console.print("\n")
    table = Table(title="Detection Results Summary")
    table.add_column("Run", style="dim")
    table.add_column("Page")
    table.add_column("Actual Mode")
    table.add_column("Detected")
    table.add_column("Correct?")

    correct = 0
    total = 0
    for i, r in enumerate(results):
        if r["detected"] == "error":
            table.add_row(str(i + 1), r.get("page", "?"), r["mode"], "ERROR", "[red]N/A[/red]")
            continue
        total += 1
        expected = EXPECTED_VERDICTS[r["mode"]]
        is_correct = r["detected"] == expected
        if is_correct:
            correct += 1
        table.add_row(
            str(i + 1),
            r.get("page", "?"),
            r["mode"],
            r["detected"],
            "[green]YES[/green]" if is_correct else "[red]NO[/red]",
        )

    console.print(table)
    if total:
        console.print(f"\nAccuracy: {correct}/{total} ({100*correct/total:.0f}%)\n")

    # Detailed probe breakdown from last results
    if all_server_results:
        console.print("[bold]Detailed probe data from server:[/bold]")
        detail_table = Table(title="Per-Test Breakdown (last 6 sessions)")
        detail_table.add_column("Session")
        detail_table.add_column("Test")
        detail_table.add_column("Verdict")
        detail_table.add_column("Reason")

        for sid, data in list(all_server_results.items())[-6:]:
            v = data.get("verdict", {})
            for test_name, test_data in v.get("tests", {}).items():
                detail_table.add_row(
                    sid[:8],
                    test_name,
                    test_data["verdict"],
                    test_data["reason"][:80],
                )
        console.print(detail_table)
        console.print()


def cli():
    global SERVER_URL
    parser = argparse.ArgumentParser(description="Test headless detector")
    parser.add_argument("--runs", type=int, default=3, help="Number of runs per mode")
    parser.add_argument("--modes", default="headful,headless,headless-shell",
                        help="Comma-separated modes (default: headful,headless,headless-shell)")
    parser.add_argument("--url", default=SERVER_URL, help="Server URL")
    args = parser.parse_args()
    if args.url != SERVER_URL:
        SERVER_URL = args.url
    asyncio.run(main(args))


if __name__ == "__main__":
    cli()
