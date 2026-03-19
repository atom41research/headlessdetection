"""Full investigation suite using Chrome (not bundled Chromium).

Re-runs all detection mechanisms against the system-installed Chrome browser
to find what (if anything) differs between Chrome headful and Chrome headless.

Usage:
    uv run python -m experiments.investigations.chrome
"""

import asyncio
import json

import httpx
from playwright.async_api import async_playwright, BrowserType
from rich.console import Console
from rich.table import Table

from core.config import BASE_URL as BASE, CHANNEL
from core.browser import create_session, get_results, get_resources, close_all

console = Console()


async def launch(pw, headless, viewport=None, args=None):
    launch_args = ["--no-sandbox"]
    if args:
        launch_args.extend(args)
    browser = await pw.chromium.launch(headless=headless, channel=CHANNEL, args=launch_args)
    ctx_args = {}
    if viewport:
        ctx_args["viewport"] = viewport
    context = await browser.new_context(**ctx_args)
    page = await context.new_page()
    return browser, context, page


# =============================================================================
# Experiment 1: Browser Environment Fingerprint
# =============================================================================
async def experiment_fingerprint(pw, client):
    console.rule("[bold]1. Browser Environment Fingerprint")

    js = """
    (() => {
        const c = navigator.connection || {};
        return {
            effectiveType: c.effectiveType,
            downlink: c.downlink,
            rtt: c.rtt,
            saveData: c.saveData,
            type: c.type,
            innerWidth: window.innerWidth,
            innerHeight: window.innerHeight,
            outerWidth: window.outerWidth,
            outerHeight: window.outerHeight,
            devicePixelRatio: window.devicePixelRatio,
            screenWidth: screen.width,
            screenHeight: screen.height,
            availWidth: screen.availWidth,
            availHeight: screen.availHeight,
            colorDepth: screen.colorDepth,
            pixelDepth: screen.pixelDepth,
            webdriver: navigator.webdriver,
            hardwareConcurrency: navigator.hardwareConcurrency,
            maxTouchPoints: navigator.maxTouchPoints,
            pdfViewerEnabled: navigator.pdfViewerEnabled,
            userAgent: navigator.userAgent.replace(/.*Chrome\\//, 'Chrome/').split(' ')[0],
        };
    })()
    """

    for headless in [False, True]:
        mode = "headless" if headless else "headful"
        browser, context, page = await launch(pw, headless)
        await page.goto("about:blank")
        info = await page.evaluate(js)
        await close_all(browser, context, page)

        console.print(f"  [cyan]{mode}:[/cyan]")
        for k, v in info.items():
            console.print(f"    {k}: {v}")
        console.print()


# =============================================================================
# Experiment 2: Lazy Loading - Fine-grained threshold
# =============================================================================
async def experiment_lazy_loading(pw, client):
    console.rule("[bold]2. Lazy Loading Threshold (50px steps)")

    configs = [
        ("default", None),
        ("1280x720", {"width": 1280, "height": 720}),
        ("400x300", {"width": 400, "height": 300}),
        ("1920x1080", {"width": 1920, "height": 1080}),
    ]

    table = Table(title="Chrome: Lazy Loading Thresholds", show_lines=True)
    table.add_column("Viewport", style="cyan")
    table.add_column("Mode", justify="center")
    table.add_column("# Loaded", justify="right")
    table.add_column("Max Position", justify="right", style="bold")

    for vp_name, viewport in configs:
        for headless in [False, True]:
            mode = "headless" if headless else "headful"
            sid = await create_session(client, f"chrome-{mode}", vp_name, "lazy-fine")
            browser, context, page = await launch(pw, headless, viewport)
            url = f"{BASE}/pages/lazy-fine?s={sid}&step=50&max_pos=5000"
            await page.goto(url, wait_until="networkidle")
            await asyncio.sleep(2)
            await close_all(browser, context, page)

            resources = await get_resources(client, sid)
            positions = sorted([int(r.replace("lazyfine-", "")) for r in resources
                               if r.startswith("lazyfine-") and "eager" not in r])
            max_pos = max(positions) if positions else 0
            table.add_row(vp_name, mode, str(len(positions)), f"{max_pos}px")

    console.print(table)
    console.print()


# =============================================================================
# Experiment 3: Lazy Iframes
# =============================================================================
async def experiment_lazy_iframes(pw, client):
    console.rule("[bold]3. Lazy-loaded Iframes")

    for headless in [False, True]:
        mode = "headless" if headless else "headful"
        sid = await create_session(client, f"chrome-{mode}", "default", "lazy-iframe")
        browser, context, page = await launch(pw, headless)
        url = f"{BASE}/pages/lazy-iframe?s={sid}"
        await page.goto(url, wait_until="networkidle")
        await asyncio.sleep(2)
        await close_all(browser, context, page)

        resources = await get_resources(client, sid)
        iframes = sorted([int(r.split("-")[1]) for r in resources
                         if r.startswith("lziframe-") and "eager" not in r])
        max_pos = max(iframes) if iframes else 0
        console.print(f"  {mode:>8s}: {len(iframes)} iframes loaded, max={max_pos}px")
    console.print()


# =============================================================================
# Experiment 4: CSS Background Images
# =============================================================================
async def experiment_css_backgrounds(pw, client):
    console.rule("[bold]4. CSS Background Images (250px steps)")

    for headless in [False, True]:
        mode = "headless" if headless else "headful"
        sid = await create_session(client, f"chrome-{mode}", "default", "lazy-css-bg")
        browser, context, page = await launch(pw, headless)
        url = f"{BASE}/pages/lazy-css-bg?s={sid}"
        await page.goto(url, wait_until="networkidle")
        await asyncio.sleep(2)
        await close_all(browser, context, page)

        resources = await get_resources(client, sid)
        bg = sorted([int(r.split("-")[1]) for r in resources if r.startswith("cssbg-")])
        max_pos = max(bg) if bg else 0
        console.print(f"  {mode:>8s}: {len(bg)} bg images loaded, max={max_pos}px")
    console.print()


# =============================================================================
# Experiment 5: Media Queries
# =============================================================================
async def experiment_media_queries(pw, client):
    console.rule("[bold]5. Media Query Probes")

    headful_probes = set()
    headless_probes = set()

    for headless in [False, True]:
        mode = "headless" if headless else "headful"
        sid = await create_session(client, f"chrome-{mode}", "default", "media-queries")
        browser, context, page = await launch(pw, headless)
        url = f"{BASE}/pages/media-queries?s={sid}"
        await page.goto(url, wait_until="networkidle")
        await asyncio.sleep(2)
        await close_all(browser, context, page)

        resources = set(await get_resources(client, sid))
        if headless:
            headless_probes = resources
        else:
            headful_probes = resources

        console.print(f"  {mode:>8s}: {sorted(resources)}")

    only_headful = headful_probes - headless_probes
    only_headless = headless_probes - headful_probes

    if only_headful or only_headless:
        console.print(f"\n  [bold red]DIFFERENCES FOUND:[/bold red]")
        if only_headful:
            console.print(f"    Only in headful:  {sorted(only_headful)}")
        if only_headless:
            console.print(f"    Only in headless: {sorted(only_headless)}")
    else:
        console.print(f"\n  [dim]No differences - all probes identical[/dim]")
    console.print()


# =============================================================================
# Experiment 6: srcset and picture elements
# =============================================================================
async def experiment_srcset(pw, client):
    console.rule("[bold]6. srcset and picture elements")

    for headless in [False, True]:
        mode = "headless" if headless else "headful"
        sid = await create_session(client, f"chrome-{mode}", "default", "lazy-srcset")
        browser, context, page = await launch(pw, headless)
        url = f"{BASE}/pages/lazy-srcset?s={sid}"
        await page.goto(url, wait_until="networkidle")
        await asyncio.sleep(2)
        await close_all(browser, context, page)

        resources = await get_resources(client, sid)
        img_positions = sorted(set(int(r.split("-")[2]) for r in resources if r.startswith("lzsrcset-img-")))
        srcset_res = [r for r in resources if r.startswith("lzsrcset-srcset-")]
        picture_res = [r for r in resources if r.startswith("lzsrcset-picture-")]

        img_max = max(img_positions) if img_positions else 0
        console.print(f"  {mode:>8s}: img={len(img_positions)} (max={img_max}px), "
                      f"srcset={len(srcset_res)}, picture={len(picture_res)}")
    console.print()


# =============================================================================
# Experiment 7: Image sizes
# =============================================================================
async def experiment_image_sizes(pw, client):
    console.rule("[bold]7. Image Dimensions vs Threshold")

    for headless in [False, True]:
        mode = "headless" if headless else "headful"
        sid = await create_session(client, f"chrome-{mode}", "default", "lazy-mixed-sizes")
        browser, context, page = await launch(pw, headless)
        url = f"{BASE}/pages/lazy-mixed-sizes?s={sid}"
        await page.goto(url, wait_until="networkidle")
        await asyncio.sleep(2)
        await close_all(browser, context, page)

        resources = await get_resources(client, sid)
        sizes = {}
        for r in resources:
            if r.startswith("lzsize-"):
                parts = r.split("-")
                size_key = parts[1]
                pos = int(parts[2])
                sizes.setdefault(size_key, []).append(pos)

        console.print(f"  [cyan]{mode}:[/cyan]")
        for size_key in sorted(sizes.keys()):
            max_pos = max(sizes[size_key])
            console.print(f"    {size_key:>8s}: {len(sizes[size_key])} loaded, max={max_pos}px")
    console.print()


# =============================================================================
# Experiment 8: Font loading
# =============================================================================
async def experiment_fonts(pw, client):
    console.rule("[bold]8. Font Loading (font-display strategies)")

    for headless in [False, True]:
        mode = "headless" if headless else "headful"
        sid = await create_session(client, f"chrome-{mode}", "default", "font-loading")
        browser, context, page = await launch(pw, headless)
        url = f"{BASE}/pages/font-loading?s={sid}"
        await page.goto(url, wait_until="networkidle")
        await asyncio.sleep(2)
        await close_all(browser, context, page)

        resources = await get_resources(client, sid)
        fonts = sorted([r for r in resources if r.startswith("font-")])
        console.print(f"  {mode:>8s}: {fonts}")
    console.print()


# =============================================================================
# Experiment 9: Import chains timing
# =============================================================================
async def experiment_import_chains(pw, client):
    console.rule("[bold]9. CSS @import Chain Timing")

    table = Table(title="Chrome: Import Chain Timing", show_lines=True)
    table.add_column("Chain", style="cyan")
    table.add_column("Mode", justify="center")
    table.add_column("Steps", justify="right")
    table.add_column("Total (ms)", justify="right", style="bold")

    for headless in [False, True]:
        mode = "headless" if headless else "headful"
        sid = await create_session(client, f"chrome-{mode}", "default", "import-chains")
        browser, context, page = await launch(pw, headless, viewport={"width": 1280, "height": 720})
        url = f"{BASE}/pages/import-chains?s={sid}&chain_length=8"
        await page.goto(url, wait_until="networkidle")
        await asyncio.sleep(2)
        await close_all(browser, context, page)

        reqs = await get_results(client, sid)

        for chain_id in ("expensive", "control"):
            chain_reqs = [r for r in reqs if r["resource"].startswith(f"chain-{chain_id}-step-")]
            chain_reqs.sort(key=lambda r: int(r["resource"].split("-")[-1]))
            if len(chain_reqs) >= 2:
                total_ms = (chain_reqs[-1]["timestamp_ns"] - chain_reqs[0]["timestamp_ns"]) / 1_000_000
                table.add_row(chain_id, mode, str(len(chain_reqs)), f"{total_ms:.1f}")

    console.print(table)
    console.print()


# =============================================================================
# Experiment 10: Background chains timing
# =============================================================================
async def experiment_background_chains(pw, client):
    console.rule("[bold]10. Background Image Chain Timing")

    for headless in [False, True]:
        mode = "headless" if headless else "headful"
        sid = await create_session(client, f"chrome-{mode}", "default", "background-chains")
        browser, context, page = await launch(pw, headless, viewport={"width": 1280, "height": 720})
        url = f"{BASE}/pages/background-chains?s={sid}"
        await page.goto(url, wait_until="networkidle")
        await asyncio.sleep(2)
        await close_all(browser, context, page)

        reqs = await get_results(client, sid)
        if not reqs:
            console.print(f"  {mode:>8s}: no requests")
            continue

        base_ts = reqs[0]["timestamp_ns"]

        heavy = [(r["resource"], (r["timestamp_ns"] - base_ts) / 1_000_000)
                 for r in reqs if r["resource"].startswith("bg-heavy-")]
        light = [(r["resource"], (r["timestamp_ns"] - base_ts) / 1_000_000)
                 for r in reqs if r["resource"].startswith("bg-light-")]

        heavy_avg = sum(t for _, t in heavy) / len(heavy) if heavy else 0
        light_avg = sum(t for _, t in light) / len(light) if light else 0
        total_ms = (reqs[-1]["timestamp_ns"] - base_ts) / 1_000_000

        console.print(
            f"  {mode:>8s}: heavy_avg={heavy_avg:.1f}ms, light_avg={light_avg:.1f}ms, "
            f"total={total_ms:.1f}ms, heavy_n={len(heavy)}, light_n={len(light)}"
        )
    console.print()


# =============================================================================
# Experiment 11: Multiple runs for statistical comparison
# =============================================================================
async def experiment_repeated_lazy(pw, client, n_runs=5):
    console.rule(f"[bold]11. Repeated Lazy Loading ({n_runs} runs, 1280x720)")

    results = {"headful": [], "headless": []}

    for run in range(n_runs):
        for headless in [False, True]:
            mode = "headless" if headless else "headful"
            sid = await create_session(client, f"chrome-{mode}", "repeated", "lazy-fine")
            browser, context, page = await launch(pw, headless, viewport={"width": 1280, "height": 720})
            url = f"{BASE}/pages/lazy-fine?s={sid}&step=50&max_pos=5000"
            await page.goto(url, wait_until="networkidle")
            await asyncio.sleep(2)
            await close_all(browser, context, page)

            resources = await get_resources(client, sid)
            positions = sorted([int(r.replace("lazyfine-", "")) for r in resources
                               if r.startswith("lazyfine-") and "eager" not in r])
            max_pos = max(positions) if positions else 0
            results[mode].append(max_pos)
            console.print(f"  run {run+1}/{n_runs} {mode:>8s}: max={max_pos}px ({len(positions)} imgs)")

    console.print(f"\n  [bold]Summary:[/bold]")
    for mode in ("headful", "headless"):
        vals = results[mode]
        console.print(f"    {mode}: max positions = {vals}")
        if len(set(vals)) == 1:
            console.print(f"    → Perfectly consistent: always {vals[0]}px")
        else:
            console.print(f"    → Varies: min={min(vals)}, max={max(vals)}")

    if results["headful"] and results["headless"]:
        hf_max = max(results["headful"])
        hl_min = min(results["headless"])
        if hf_max < hl_min:
            console.print(f"\n  [bold green]SEPARABLE: headful always < {hf_max}px, headless always >= {hl_min}px[/bold green]")
        elif hf_max == hl_min or set(results["headful"]) == set(results["headless"]):
            console.print(f"\n  [bold yellow]IDENTICAL: no difference between modes[/bold yellow]")
        else:
            console.print(f"\n  [bold red]OVERLAPPING: ranges overlap, not a clean separator[/bold red]")
    console.print()


# =============================================================================
# Main
# =============================================================================
async def main():
    console.print("\n[bold]===== Full Chrome Investigation Suite =====[/bold]")
    console.print(f"[dim]Using channel='{CHANNEL}' (system Chrome)[/dim]\n")

    async with httpx.AsyncClient() as client:
        await client.post(f"{BASE}/clear")

    async with async_playwright() as pw:
        # Verify Chrome is available
        try:
            browser = await pw.chromium.launch(headless=True, channel=CHANNEL, args=["--no-sandbox"])
            version = browser.version
            await browser.close()
            console.print(f"[green]Chrome version: {version}[/green]\n")
        except Exception as e:
            console.print(f"[red]Chrome not available: {e}[/red]")
            console.print("Install Chrome or use: npx playwright install chrome")
            return

        async with httpx.AsyncClient() as client:
            await experiment_fingerprint(pw, client)
            await experiment_lazy_loading(pw, client)
            await experiment_lazy_iframes(pw, client)
            await experiment_css_backgrounds(pw, client)
            await experiment_media_queries(pw, client)
            await experiment_srcset(pw, client)
            await experiment_image_sizes(pw, client)
            await experiment_fonts(pw, client)
            await experiment_import_chains(pw, client)
            await experiment_background_chains(pw, client)
            await experiment_repeated_lazy(pw, client, n_runs=5)

    console.print("[bold green]===== Chrome Investigation Complete =====[/bold green]\n")


if __name__ == "__main__":
    asyncio.run(main())
