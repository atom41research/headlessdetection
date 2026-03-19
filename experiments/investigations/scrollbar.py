"""Investigate scrollbar-based headless Chrome detection.

Phase 1: Client-side JS measurement (innerWidth vs clientWidth)
Phase 2: Server-side CSS beacon (calc(100vw - 100%) trick)

Usage:
    uv run python -m experiments.investigations.scrollbar
"""

import asyncio

import httpx
from playwright.async_api import async_playwright
from rich.console import Console
from rich.table import Table

from core.config import BASE_URL as BASE, DEFAULT_VIEWPORT as VIEWPORT, BROWSER_ARGS, CHANNEL, CHROME_USER_AGENT as USER_AGENT
from core.browser import create_session, get_results, get_resources, close_all

console = Console()


async def launch(pw, headless, viewport=None):
    browser = await pw.chromium.launch(
        headless=headless, channel=CHANNEL, args=BROWSER_ARGS
    )
    ctx_args = {}
    if viewport:
        ctx_args["viewport"] = viewport
    if headless:
        ctx_args["user_agent"] = USER_AGENT
    context = await browser.new_context(**ctx_args)
    page = await context.new_page()
    return browser, context, page


# =============================================================================
# Experiment 1: JS scrollbar width measurement
# =============================================================================
async def experiment_js_measurement(pw):
    console.rule("[bold]1. JavaScript Scrollbar Width Measurement")

    js = """
    (() => {
        // Make body tall to trigger scrollbar
        document.body.style.height = '3000px';

        // Technique A: innerWidth vs clientWidth
        const widthA = window.innerWidth - document.documentElement.clientWidth;

        // Technique B: offscreen scrollable div
        const outer = document.createElement('div');
        outer.style.cssText = 'position:absolute;top:-9999px;left:-9999px;width:100px;height:100px;overflow:scroll;';
        document.body.appendChild(outer);
        const inner = document.createElement('div');
        inner.style.width = '100%';
        outer.appendChild(inner);
        const widthB = outer.offsetWidth - inner.offsetWidth;
        document.body.removeChild(outer);

        // Technique C: calc(100vw - 100%)
        const probe = document.createElement('div');
        probe.style.cssText = 'position:absolute;top:-9999px;width:calc(100vw - 100%);height:1px;';
        document.body.appendChild(probe);
        const widthC = probe.offsetWidth;
        document.body.removeChild(probe);

        return {
            innerWidth: window.innerWidth,
            clientWidth: document.documentElement.clientWidth,
            techniqueA_innerVsClient: widthA,
            techniqueB_offscreenDiv: widthB,
            techniqueC_calcVw: widthC,
        };
    })()
    """

    table = Table(title="JS Scrollbar Width Measurement", show_lines=True)
    table.add_column("Property", style="cyan")
    table.add_column("Headful", justify="right")
    table.add_column("Headless", justify="right")
    table.add_column("Differs?", justify="center")

    results = {}
    for headless in [False, True]:
        mode = "headless" if headless else "headful"
        browser, context, page = await launch(pw, headless, viewport=VIEWPORT)
        await page.goto("about:blank")
        info = await page.evaluate(js)
        await close_all(browser, context, page)
        results[mode] = info

    for key in results["headful"]:
        hf = results["headful"][key]
        hl = results["headless"][key]
        differs = "[bold red]YES[/bold red]" if hf != hl else "[dim]no[/dim]"
        table.add_row(key, str(hf), str(hl), differs)

    console.print(table)
    console.print()
    return results


# =============================================================================
# Experiment 2: CSS beacon probe (single run)
# =============================================================================
async def experiment_css_beacon(pw, client):
    console.rule("[bold]2. CSS Beacon Probe (calc(100vw - 100%) trick)")

    table = Table(title="CSS Beacon Results", show_lines=True)
    table.add_column("Resource", style="cyan")
    table.add_column("Headful", justify="center")
    table.add_column("Headless", justify="center")
    table.add_column("Differs?", justify="center")

    all_resources = set()
    mode_resources = {}

    for headless in [False, True]:
        mode = "headless" if headless else "headful"
        sid = await create_session(client, mode, "default", "scrollbar-width")
        browser, context, page = await launch(pw, headless, viewport=VIEWPORT)
        url = f"{BASE}/pages/scrollbar-width?s={sid}"
        await page.goto(url, wait_until="networkidle")
        await asyncio.sleep(2)
        await close_all(browser, context, page)

        resources = set(await get_resources(client, sid))
        mode_resources[mode] = resources
        all_resources |= resources

        console.print(f"  {mode:>8s}: {sorted(resources)}")

    console.print()

    for resource in sorted(all_resources):
        hf = "[green]loaded[/green]" if resource in mode_resources["headful"] else "[dim]—[/dim]"
        hl = "[green]loaded[/green]" if resource in mode_resources["headless"] else "[dim]—[/dim]"
        in_hf = resource in mode_resources["headful"]
        in_hl = resource in mode_resources["headless"]
        differs = "[bold red]YES[/bold red]" if in_hf != in_hl else "[dim]no[/dim]"
        table.add_row(resource, hf, hl, differs)

    console.print(table)

    only_headful = mode_resources["headful"] - mode_resources["headless"]
    only_headless = mode_resources["headless"] - mode_resources["headful"]

    if only_headful or only_headless:
        console.print(f"\n  [bold green]DIFFERENCES FOUND:[/bold green]")
        if only_headful:
            console.print(f"    Only in headful:  {sorted(only_headful)}")
        if only_headless:
            console.print(f"    Only in headless: {sorted(only_headless)}")
    else:
        console.print(f"\n  [bold yellow]No differences — all beacons identical[/bold yellow]")
    console.print()


# =============================================================================
# Experiment 3: Repeated runs for statistical confidence
# =============================================================================
async def experiment_repeated(pw, client, n_runs=10):
    console.rule(f"[bold]3. Repeated Beacon Probe ({n_runs} runs per mode)")

    key_probe = "sb-js-detected"
    counts = {"headful": 0, "headless": 0}

    for run in range(n_runs):
        for headless in [False, True]:
            mode = "headless" if headless else "headful"
            sid = await create_session(client, mode, "repeated", "scrollbar-width")
            browser, context, page = await launch(pw, headless, viewport=VIEWPORT)
            url = f"{BASE}/pages/scrollbar-width?s={sid}"
            await page.goto(url, wait_until="networkidle")
            await asyncio.sleep(2)
            await close_all(browser, context, page)

            resources = set(await get_resources(client, sid))
            fired = key_probe in resources
            if fired:
                counts[mode] += 1
            console.print(
                f"  run {run+1:>2d}/{n_runs}  {mode:>8s}  "
                f"{key_probe}: {'[green]FIRED[/green]' if fired else '[dim]—[/dim]'}"
            )

    console.print()
    hf_rate = counts["headful"] / n_runs
    hl_rate = counts["headless"] / n_runs
    console.print(f"  [bold]Results:[/bold]")
    console.print(f"    headful  rate: {hf_rate:.0%} ({counts['headful']}/{n_runs})")
    console.print(f"    headless rate: {hl_rate:.0%} ({counts['headless']}/{n_runs})")

    if hf_rate == 1.0 and hl_rate == 0.0:
        console.print(f"\n  [bold green]PERFECT BINARY SIGNAL: 100% headful, 0% headless[/bold green]")
    elif hf_rate > hl_rate:
        console.print(f"\n  [bold yellow]PARTIAL SIGNAL: headful > headless but not clean[/bold yellow]")
    else:
        console.print(f"\n  [bold red]NO SIGNAL: rates are similar or inverted[/bold red]")
    console.print()


# =============================================================================
# Experiment 4: Viewport size robustness
# =============================================================================
async def experiment_viewport_robustness(pw, client):
    console.rule("[bold]4. Viewport Size Robustness")

    viewports = [
        ("800x600", {"width": 800, "height": 600}),
        ("1280x720", {"width": 1280, "height": 720}),
        ("1920x1080", {"width": 1920, "height": 1080}),
    ]

    js = """
    (() => {
        return {
            innerWidth: window.innerWidth,
            clientWidth: document.documentElement.clientWidth,
            scrollbarWidth: window.innerWidth - document.documentElement.clientWidth,
        };
    })()
    """

    table = Table(title="Scrollbar Width Across Viewports", show_lines=True)
    table.add_column("Viewport", style="cyan")
    table.add_column("Mode", justify="center")
    table.add_column("innerWidth", justify="right")
    table.add_column("clientWidth", justify="right")
    table.add_column("Scrollbar", justify="right", style="bold")
    table.add_column("sb-js-detected", justify="center")

    for vp_name, viewport in viewports:
        for headless in [False, True]:
            mode = "headless" if headless else "headful"

            # JS measurement
            browser, context, page = await launch(pw, headless, viewport=viewport)
            await page.goto("about:blank")
            await page.evaluate("document.body.style.height = '3000px'")
            info = await page.evaluate(js)
            await close_all(browser, context, page)

            # CSS beacon
            sid = await create_session(client, mode, vp_name, "scrollbar-width")
            browser, context, page = await launch(pw, headless, viewport=viewport)
            url = f"{BASE}/pages/scrollbar-width?s={sid}"
            await page.goto(url, wait_until="networkidle")
            await asyncio.sleep(2)
            await close_all(browser, context, page)

            resources = set(await get_resources(client, sid))
            beacon_fired = "sb-js-detected" in resources

            table.add_row(
                vp_name,
                mode,
                str(info["innerWidth"]),
                str(info["clientWidth"]),
                f"{info['scrollbarWidth']}px",
                "[green]FIRED[/green]" if beacon_fired else "[dim]—[/dim]",
            )

    console.print(table)
    console.print()


# =============================================================================
# Main
# =============================================================================
async def main():
    console.print("\n[bold]===== Scrollbar Width Detection Investigation =====[/bold]")
    console.print(f"[dim]Using channel='{CHANNEL}' (system Chrome)[/dim]\n")

    async with async_playwright() as pw:
        # Verify Chrome is available
        try:
            browser = await pw.chromium.launch(
                headless=True, channel=CHANNEL, args=["--no-sandbox"]
            )
            version = browser.version
            await browser.close()
            console.print(f"[green]Chrome version: {version}[/green]\n")
        except Exception as e:
            console.print(f"[red]Chrome not available: {e}[/red]")
            console.print("Install Chrome or use: npx playwright install chrome")
            return

        # Experiment 1: no server needed
        await experiment_js_measurement(pw)

        # Experiments 2-4: need the FastAPI server
        async with httpx.AsyncClient() as client:
            try:
                await client.get(f"{BASE}/session/new", params={"mode": "test", "profile": "test", "page": "test"})
            except httpx.ConnectError:
                console.print(
                    "[red]Server not running. Start with:[/red]\n"
                    "  uv run uvicorn app.main:app\n"
                )
                return

            await experiment_css_beacon(pw, client)
            await experiment_repeated(pw, client, n_runs=10)
            await experiment_viewport_robustness(pw, client)

    console.print("[bold green]===== Investigation Complete =====[/bold green]\n")


if __name__ == "__main__":
    asyncio.run(main())
