"""Playwright test runner for headless detection research.

Visits each test page in both headful and headless modes, collecting
server-side timing data for analysis.

Usage:
    uv run python -m experiments.runner --runs 5 --pages all
    uv run python -m experiments.runner --runs 30 --pages media-queries,import-chains
    uv run python -m experiments.runner --runs 10 --profile matched
"""

import argparse
import asyncio
import sys
import time

import httpx
from playwright.async_api import async_playwright
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn

from . import config

console = Console()


async def create_session(client: httpx.AsyncClient, mode: str, profile: str, page: str) -> str:
    resp = await client.get(
        f"{config.BASE_URL}/session/new",
        params={"mode": mode, "profile": profile, "page": page},
    )
    resp.raise_for_status()
    return resp.json()["session_id"]


async def visit_page(
    browser_type,
    page_name: str,
    session_id: str,
    headless: bool,
    profile: str,
    client: httpx.AsyncClient,
):
    launch_args = {
        "headless": headless,
        "channel": "chrome",
        "args": [
            "--no-sandbox",
            "--disable-blink-features=AutomationControlled",
        ],
    }

    browser = await browser_type.launch(**launch_args)

    context_args = {"ignore_https_errors": True}
    if headless:
        context_args["user_agent"] = config.CHROME_USER_AGENT
    if profile == "matched":
        context_args["viewport"] = config.MATCHED_VIEWPORT
        context_args["color_scheme"] = "light"
        context_args["reduced_motion"] = "no-preference"

    context = await browser.new_context(**context_args)
    page = await context.new_page()

    url = f"{config.BASE_URL}/pages/{page_name}?s={session_id}"
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
    profile: str,
) -> str:
    headless = mode == "headless"
    session_id = await create_session(client, mode, profile, page_name)
    await visit_page(pw.chromium, page_name, session_id, headless, profile, client)
    return session_id


async def main(args: argparse.Namespace):
    pages = config.PAGES if args.pages == "all" else args.pages.split(",")
    profiles = args.profile.split(",")
    modes = ["headful", "headless"]
    total = len(pages) * len(profiles) * len(modes) * args.runs

    console.print(f"\n[bold]Headless Detection Test Runner[/bold]")
    console.print(f"Pages: {', '.join(pages)}")
    console.print(f"Profiles: {', '.join(profiles)}")
    console.print(f"Runs per combination: {args.runs}")
    console.print(f"Total browser launches: {total}\n")

    # Clear previous data if requested
    async with httpx.AsyncClient() as client:
        if args.clear:
            await client.post(f"{config.BASE_URL}/clear")
            console.print("[yellow]Cleared previous data[/yellow]\n")

    async with async_playwright() as pw:
        # Detect real Chrome UA for headless spoofing
        browser = await pw.chromium.launch(
            headless=False, channel="chrome",
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        ctx = await browser.new_context()
        p = await ctx.new_page()
        config.CHROME_USER_AGENT = await p.evaluate("navigator.userAgent")
        await browser.close()
        console.print(f"Chrome UA: [dim]{config.CHROME_USER_AGENT}[/dim]\n")

        async with httpx.AsyncClient() as client:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                MofNCompleteColumn(),
                console=console,
            ) as progress:
                task = progress.add_task("Running tests...", total=total)

                for page_name in pages:
                    for profile in profiles:
                        for run_idx in range(args.runs):
                            for mode in modes:
                                desc = f"{page_name} | {profile} | {mode} | run {run_idx + 1}/{args.runs}"
                                progress.update(task, description=desc)

                                try:
                                    session_id = await run_test(pw, client, page_name, mode, profile)
                                except Exception as e:
                                    console.print(f"[red]Error: {desc}: {e}[/red]")

                                progress.advance(task)

    console.print("\n[bold green]All tests complete.[/bold green]")
    console.print(f"Run analysis: [cyan]uv run python -m experiments.report[/cyan]\n")


def cli():
    parser = argparse.ArgumentParser(description="Headless detection test runner")
    parser.add_argument("--runs", type=int, default=config.DEFAULT_RUNS, help="Number of runs per combination")
    parser.add_argument("--pages", default="all", help="Comma-separated page names or 'all'")
    parser.add_argument("--profile", default="default,matched", help="Comma-separated profiles: default, matched")
    parser.add_argument("--clear", action="store_true", help="Clear previous data before running")
    parser.add_argument("--url", default=config.BASE_URL, help="Base URL of the server")
    args = parser.parse_args()

    if args.url != config.BASE_URL:
        config.BASE_URL = args.url

    asyncio.run(main(args))


if __name__ == "__main__":
    cli()
