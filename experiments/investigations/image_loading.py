"""Investigation into IntersectionObserver-based image loading.

Compares JS-based image loading between Chrome headful and headless modes.
The page uses IntersectionObserver (not native loading="lazy") to set image
src attributes, reproducing the fanbox.cc pattern.

Usage:
    uv run python -m experiments.investigations.image_loading
"""

import asyncio
from collections import defaultdict

import httpx
from playwright.async_api import async_playwright
from rich.console import Console
from rich.table import Table

from core import config
from core.config import BASE_URL as BASE, DEFAULT_VIEWPORT as VIEWPORT, BROWSER_ARGS, CHANNEL
from core.browser import close_all, detect_chrome_ua

console = Console()

GROUPS = [
    "io-ctrl",
    "io-src",
    "io-margin0",
    "io-margin200",
    "io-margin1000",
    "io-newimg",
    "io-decode",
    "io-bgimg",
    "io-fetch",
    "io-react",
]


async def create_session(client: httpx.AsyncClient, mode: str, page: str) -> str:
    resp = await client.get(
        f"{BASE}/session/new",
        params={"mode": mode, "profile": "matched", "page": page},
    )
    return resp.json()["session_id"]


async def get_resources(client: httpx.AsyncClient, sid: str) -> list[str]:
    resp = await client.get(f"{BASE}/results/{sid}")
    return [r["resource"] for r in resp.json()["requests"]]


def parse_resource(resource: str) -> tuple[str, int] | None:
    """Parse 'io-group-123' into ('io-group', 123)."""
    for g in GROUPS:
        if resource.startswith(g + "-"):
            try:
                pos = int(resource[len(g) + 1:])
                return g, pos
            except ValueError:
                pass
    return None


async def launch(pw, headless: bool):
    browser = await pw.chromium.launch(
        headless=headless, channel=CHANNEL, args=BROWSER_ARGS
    )
    ctx_args = {"viewport": VIEWPORT}
    if headless and config.CHROME_USER_AGENT:
        ctx_args["user_agent"] = config.CHROME_USER_AGENT
    context = await browser.new_context(**ctx_args)
    page = await context.new_page()
    return browser, context, page


async def run_once(pw, client, headless: bool, settle: float = 2.0, scroll_to: int | None = None) -> list[str]:
    """Run one visit and return loaded resources."""
    mode = "headless" if headless else "headful"
    sid = await create_session(client, mode, "image-loading")
    browser, context, page = await launch(pw, headless)
    url = f"{BASE}/pages/image-loading?s={sid}"
    await page.goto(url, wait_until="domcontentloaded")
    if scroll_to is not None:
        await page.evaluate(f"window.scrollTo(0, {scroll_to})")
        await asyncio.sleep(1.0)
    await asyncio.sleep(settle)
    await close_all(browser, context, page)
    return await get_resources(client, sid)


def print_comparison(headful_resources: list[str], headless_resources: list[str], title: str):
    """Print a Rich table comparing loaded resources by group and position."""
    headful_set = set(headful_resources)
    headless_set = set(headless_resources)

    # Collect all positions seen
    all_positions = set()
    for r in headful_resources + headless_resources:
        parsed = parse_resource(r)
        if parsed:
            all_positions.add(parsed[1])
    positions = sorted(all_positions)

    table = Table(title=title, show_lines=True)
    table.add_column("Group", style="bold")
    for pos in positions:
        table.add_column(str(pos), justify="center", min_width=3)
    table.add_column("Total", justify="right", style="bold")

    for group in GROUPS:
        row = [group]
        total_f, total_h = 0, 0
        for pos in positions:
            key = f"{group}-{pos}"
            in_f = key in headful_set
            in_h = key in headless_set
            if in_f:
                total_f += 1
            if in_h:
                total_h += 1
            if in_f and in_h:
                row.append("[green]both[/]")
            elif in_f and not in_h:
                row.append("[red]F only[/]")
            elif not in_f and in_h:
                row.append("[yellow]H only[/]")
            else:
                row.append("[dim]none[/]")
        row.append(f"F:{total_f} H:{total_h}")
        table.add_row(*row)

    console.print(table)

    # Summary of differences
    only_headful = headful_set - headless_set
    only_headless = headless_set - headful_set
    if only_headful or only_headless:
        console.print(f"  [red]Only in headful ({len(only_headful)}):[/] {sorted(only_headful)}")
        console.print(f"  [yellow]Only in headless ({len(only_headless)}):[/] {sorted(only_headless)}")
    else:
        console.print("  [green]No differences — identical resource sets[/]")


async def experiment_default(pw, client):
    """Experiment 1: Single run, matched viewport, default settle time."""
    console.rule("[bold]Experiment 1: Default (matched viewport, 2s settle)")

    headful_res = await run_once(pw, client, headless=False)
    headless_res = await run_once(pw, client, headless=True)
    print_comparison(headful_res, headless_res, "Default Run")


async def experiment_multi_run(pw, client, runs: int = 10):
    """Experiment 2: Multiple runs to compute load rates."""
    console.rule(f"[bold]Experiment 2: {runs} runs per mode (load rates)")

    headful_counts: dict[str, int] = defaultdict(int)
    headless_counts: dict[str, int] = defaultdict(int)

    for i in range(runs):
        console.print(f"  Run {i + 1}/{runs}...", end=" ")
        for headless in [False, True]:
            resources = await run_once(pw, client, headless=headless)
            counts = headful_counts if not headless else headless_counts
            for r in resources:
                counts[r] += 1
        console.print("[green]done[/]")

    # Collect all resource keys
    all_keys = sorted(set(headful_counts.keys()) | set(headless_counts.keys()))

    # Find resources with divergent load rates
    table = Table(title=f"Load Rates ({runs} runs)", show_lines=True)
    table.add_column("Resource", style="bold")
    table.add_column("Headful", justify="right")
    table.add_column("Headless", justify="right")
    table.add_column("Diff?", justify="center")

    divergent = 0
    for key in all_keys:
        f_rate = headful_counts.get(key, 0) / runs
        h_rate = headless_counts.get(key, 0) / runs
        diff = abs(f_rate - h_rate)
        style = "[red]YES[/]" if diff > 0.1 else "[green]no[/]"
        if diff > 0.1:
            divergent += 1
        table.add_row(
            key,
            f"{f_rate:.0%}",
            f"{h_rate:.0%}",
            style,
        )

    console.print(table)
    console.print(f"  Divergent resources (>10% diff): {divergent}/{len(all_keys)}")


async def experiment_settle_time(pw, client):
    """Experiment 3: Extended settle times to see if headless catches up."""
    console.rule("[bold]Experiment 3: Extended settle times")

    for settle in [2.0, 5.0, 10.0]:
        console.print(f"\n  Settle time: {settle}s")
        headful_res = await run_once(pw, client, headless=False, settle=settle)
        headless_res = await run_once(pw, client, headless=True, settle=settle)
        print_comparison(headful_res, headless_res, f"Settle = {settle}s")


async def experiment_scroll(pw, client):
    """Experiment 4: Programmatic scroll after initial load."""
    console.rule("[bold]Experiment 4: Scroll after load")

    for scroll_pos in [2000, 5000, 8000]:
        console.print(f"\n  Scroll to {scroll_pos}px after load")
        headful_res = await run_once(pw, client, headless=False, scroll_to=scroll_pos)
        headless_res = await run_once(pw, client, headless=True, scroll_to=scroll_pos)
        print_comparison(headful_res, headless_res, f"Scroll to {scroll_pos}px")


async def main():
    console.print("\n[bold]IntersectionObserver Image Loading Investigation[/bold]")
    console.print(f"  Chrome channel: {CHANNEL}")
    console.print(f"  Viewport: {VIEWPORT['width']}x{VIEWPORT['height']}")
    console.print(f"  UA spoofed for headless: yes\n")

    async with httpx.AsyncClient() as client:
        await client.post(f"{BASE}/clear")

    async with async_playwright() as pw:
        await detect_chrome_ua(pw)
        async with httpx.AsyncClient() as client:
            await experiment_default(pw, client)
            await experiment_multi_run(pw, client, runs=5)
            await experiment_settle_time(pw, client)
            await experiment_scroll(pw, client)

    console.print("\n[bold green]Investigation complete.[/bold green]\n")


if __name__ == "__main__":
    asyncio.run(main())
