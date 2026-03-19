"""Test runner for server-side signal probes.

Visits probe pages over both HTTP and HTTPS in headful, headless, and
headless-shell Chrome, capturing TLS fingerprints, header ordering,
and connection patterns.

Usage:
    uv run python -m experiments.runner_server_signals --runs 5
    uv run python -m experiments.runner_server_signals --runs 5 --modes headless,headless-shell
    uv run python -m experiments.runner_server_signals --runs 10 --pages probe-tls-fingerprint,probe-header-order
"""

import argparse
import asyncio
import json

import httpx
from playwright.async_api import async_playwright
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn

from . import config

console = Console()


async def detect_chrome_ua(browser_type) -> str:
    """Launch headful Chrome once to get the real user agent string."""
    browser = await browser_type.launch(
        headless=False,
        channel="chrome",
        args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
    )
    context = await browser.new_context()
    page = await context.new_page()
    ua = await page.evaluate("navigator.userAgent")
    await browser.close()
    return ua


async def create_session(client: httpx.AsyncClient, mode: str, profile: str, page: str, scheme: str) -> str:
    resp = await client.get(
        f"{config.BASE_URL}/session/new",
        params={"mode": mode, "profile": profile, "page": f"{scheme}-{page}"},
    )
    resp.raise_for_status()
    return resp.json()["session_id"]


async def visit_page(
    browser_type,
    page_name: str,
    session_id: str,
    channel: str,
    headless: bool,
    base_url: str,
):
    launch_args = {
        "headless": headless,
        "channel": channel,
        "args": [
            "--no-sandbox",
            "--disable-blink-features=AutomationControlled",
        ],
    }

    browser = await browser_type.launch(**launch_args)

    context_args = {
        "ignore_https_errors": True,
        "viewport": config.MATCHED_VIEWPORT,
    }
    if headless:
        context_args["user_agent"] = config.CHROME_USER_AGENT

    context = await browser.new_context(**context_args)
    page = await context.new_page()

    url = f"{base_url}/pages/{page_name}?s={session_id}"
    await page.goto(url, wait_until="networkidle")
    await asyncio.sleep(config.SETTLE_TIME)

    await page.close()
    await context.close()
    await browser.close()


async def run_test(
    pw,
    client: httpx.AsyncClient,
    page_name: str,
    mode: str,
    scheme: str,
) -> str:
    channel, headless = config.MODE_PARAMS[mode]
    base_url = config.HTTPS_BASE_URL if scheme == "https" else config.BASE_URL
    session_id = await create_session(client, mode, "matched", page_name, scheme)
    await visit_page(pw.chromium, page_name, session_id, channel, headless, base_url)
    return session_id


async def collect_tls_fingerprints(client: httpx.AsyncClient, mode: str):
    """Fetch TLS fingerprints from server and persist to DB with mode info.

    Creates a synthetic session for each mode's TLS data so the analysis
    can group fingerprints by mode.
    """
    resp = await client.get(f"{config.BASE_URL}/pages/server-signals/tls-all")
    fps = resp.json()
    if not fps:
        return

    # Create a session to hold this mode's TLS fingerprints
    session_resp = await client.get(
        f"{config.BASE_URL}/session/new",
        params={"mode": mode, "profile": "tls", "page": "tls-fingerprint"},
    )
    tls_session_id = session_resp.json()["session_id"]

    # Persist each unique fingerprint
    seen_ja3 = set()
    from core import storage
    for fp in fps:
        ja3 = fp.get("ja3_hash", "")
        if ja3 in seen_ja3:
            continue
        seen_ja3.add(ja3)
        storage.log_tls_fingerprint(
            session_id=tls_session_id,
            client_port=0,
            tls_version=fp.get("tls_version", ""),
            cipher_suites=json.dumps(fp.get("cipher_suites", [])) if isinstance(fp.get("cipher_suites"), list) else str(fp.get("cipher_count", "")),
            extensions=json.dumps(fp.get("extensions", [])) if isinstance(fp.get("extensions"), list) else "",
            supported_groups="",
            ec_point_formats="",
            signature_algorithms="",
            alpn_protocols=json.dumps(fp.get("alpn", [])),
            server_name=fp.get("sni", ""),
            ja3_hash=ja3,
            ja4_string=fp.get("ja4", ""),
        )

    console.print(f"  Collected {len(seen_ja3)} unique TLS fingerprint(s) for [bold]{mode}[/bold]")


async def main(args: argparse.Namespace):
    pages = config.SERVER_SIGNAL_PAGES if args.pages == "all" else args.pages.split(",")
    modes = args.modes.split(",")

    # Validate modes
    for m in modes:
        if m not in config.MODE_PARAMS:
            console.print(f"[red]Unknown mode: {m}. Valid: {', '.join(config.MODE_PARAMS)}[/red]")
            return

    schemes = ["http", "https"]
    total = len(pages) * len(modes) * len(schemes) * args.runs

    console.print(f"\n[bold]Server Signal Test Runner[/bold]")
    console.print(f"Pages: {', '.join(pages)}")
    console.print(f"Modes: {', '.join(modes)}")
    console.print(f"Schemes: http, https")
    console.print(f"Runs per combination: {args.runs}")
    console.print(f"Total browser launches: {total}\n")

    async with httpx.AsyncClient() as client:
        if args.clear:
            await client.post(f"{config.BASE_URL}/clear")
            await client.get(f"{config.BASE_URL}/pages/server-signals/headers-clear")
            await client.get(f"{config.BASE_URL}/pages/server-signals/tls-clear")
            console.print("[yellow]Cleared previous data[/yellow]\n")

    async with async_playwright() as pw:
        # Detect real Chrome UA for headless spoofing
        real_ua = await detect_chrome_ua(pw.chromium)
        config.CHROME_USER_AGENT = real_ua.replace("HeadlessChrome", "Chrome")
        console.print(f"Detected Chrome UA: [dim]{config.CHROME_USER_AGENT}[/dim]\n")

        # Verify headless-shell is installed if needed
        if "headless-shell" in modes:
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

        async with httpx.AsyncClient() as client:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                MofNCompleteColumn(),
                console=console,
            ) as progress:
                task = progress.add_task("Running tests...", total=total)

                # Run modes sequentially so we can collect TLS per-mode
                for mode in modes:
                    # Clear TLS store before this mode's HTTPS runs
                    await client.get(f"{config.BASE_URL}/pages/server-signals/tls-clear")

                    for page_name in pages:
                        for run_idx in range(args.runs):
                            for scheme in schemes:
                                desc = f"{page_name} | {scheme} | {mode} | run {run_idx + 1}/{args.runs}"
                                progress.update(task, description=desc)

                                try:
                                    await run_test(pw, client, page_name, mode, scheme)
                                except Exception as e:
                                    console.print(f"[red]Error: {desc}: {e}[/red]")

                                progress.advance(task)

                    # Collect TLS fingerprints for this mode
                    await collect_tls_fingerprints(client, mode)

    console.print("\n[bold green]All tests complete.[/bold green]")
    console.print(f"View TLS data:    [cyan]curl http://127.0.0.1:8000/pages/server-signals/tls-all[/cyan]")
    console.print(f"View header data: [cyan]curl http://127.0.0.1:8000/pages/server-signals/headers/<session_id>[/cyan]")
    console.print(f"Run analysis:     [cyan]uv run python -m experiments.report_server_signals[/cyan]\n")


def cli():
    parser = argparse.ArgumentParser(description="Server signal test runner")
    parser.add_argument("--runs", type=int, default=5, help="Number of runs per combination")
    parser.add_argument("--pages", default="all", help="Comma-separated page names or 'all'")
    parser.add_argument("--modes", default="headful,headless,headless-shell",
                        help="Comma-separated modes (default: headful,headless,headless-shell)")
    parser.add_argument("--clear", action="store_true", help="Clear previous data before running")
    args = parser.parse_args()
    asyncio.run(main(args))


if __name__ == "__main__":
    cli()
