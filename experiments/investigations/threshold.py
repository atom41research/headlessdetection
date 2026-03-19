"""Investigate the exact lazy loading threshold mechanism.

Tests:
1. Does the threshold change if we spoof the connection type?
2. Does the outerWidth/outerHeight difference matter? (headful has window chrome)
3. Does the screen size (vs viewport) affect the threshold?
4. What's the exact pixel boundary?
"""

import asyncio

import httpx
from playwright.async_api import async_playwright
from rich.console import Console

from core.config import BASE_URL as BASE
from core.browser import create_session

console = Console()


async def get_loaded_positions(client, sid, prefix="lazyfine-"):
    resp = await client.get(f"{BASE}/results/{sid}")
    resources = [r["resource"] for r in resp.json()["requests"]]
    positions = sorted([int(r.replace(prefix, "")) for r in resources if r.startswith(prefix) and "eager" not in r])
    return positions


async def run_test(pw, client, headless, viewport=None, args=None, label="", emulate_media=None):
    mode = "headless" if headless else "headful"
    launch_args = ["--no-sandbox"]
    if args:
        launch_args.extend(args)

    browser = await pw.chromium.launch(headless=headless, args=launch_args)
    ctx_args = {}
    if viewport:
        ctx_args["viewport"] = viewport
    context = await browser.new_context(**ctx_args)
    page = await context.new_page()

    # Check effective connection type
    await page.goto("about:blank")
    net_info = await page.evaluate("""
        (() => {
            const c = navigator.connection || {};
            return { ect: c.effectiveType, downlink: c.downlink, rtt: c.rtt };
        })()
    """)

    sid = await create_session(client, mode, "test", "lazy-fine")
    url = f"{BASE}/pages/lazy-fine?s={sid}&step=50&max_pos=5000"
    await page.goto(url, wait_until="networkidle")
    await asyncio.sleep(2)
    await page.close()
    await context.close()
    await browser.close()

    positions = await get_loaded_positions(client, sid)
    max_pos = max(positions) if positions else 0
    vp_label = f"{viewport['width']}x{viewport['height']}" if viewport else "default"
    console.print(
        f"  {label or mode:>25s} | vp={vp_label:>10s} | "
        f"ect={net_info.get('ect','?'):>4s} dl={str(net_info.get('downlink','?')):>5s} rtt={str(net_info.get('rtt','?')):>5s} | "
        f"loaded {len(positions):>3d}, max={max_pos}px"
    )
    return max_pos


async def main():
    console.print("\n[bold]Lazy Loading Threshold Investigation[/bold]\n")

    async with httpx.AsyncClient() as client:
        await client.post(f"{BASE}/clear")

    async with async_playwright() as pw:
        async with httpx.AsyncClient() as client:
            # Experiment 1: Default settings
            console.rule("[bold]1. Default settings (50px step)")
            await run_test(pw, client, False, label="headful-default")
            await run_test(pw, client, True, label="headless-default")

            # Experiment 2: Matched viewport
            console.rule("[bold]2. Matched viewport 1280x720")
            await run_test(pw, client, False, viewport={"width": 1280, "height": 720}, label="headful-1280x720")
            await run_test(pw, client, True, viewport={"width": 1280, "height": 720}, label="headless-1280x720")

            # Experiment 3: Very small viewport
            console.rule("[bold]3. Small viewport 400x300")
            await run_test(pw, client, False, viewport={"width": 400, "height": 300}, label="headful-400x300")
            await run_test(pw, client, True, viewport={"width": 400, "height": 300}, label="headless-400x300")

            # Experiment 4: Force slow connection via CDP
            console.rule("[bold]4. Headless with throttled network (simulating 3G)")
            browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
            context = await browser.new_context(viewport={"width": 1280, "height": 720})
            page = await context.new_page()

            # Emulate slow 3G via CDP
            cdp = await context.new_cdp_session(page)
            await cdp.send("Network.emulateNetworkConditions", {
                "offline": False,
                "downloadThroughput": 400 * 1024 / 8,  # 400 kbps
                "uploadThroughput": 400 * 1024 / 8,
                "latency": 400,
                "connectionType": "cellular3g",
            })

            sid = await create_session(client, "headless", "throttled-3g", "lazy-fine")
            url = f"{BASE}/pages/lazy-fine?s={sid}&step=50&max_pos=5000"
            await page.goto(url, wait_until="networkidle", timeout=60000)
            await asyncio.sleep(3)

            net_info = await page.evaluate("""
                (() => {
                    const c = navigator.connection || {};
                    return { ect: c.effectiveType, downlink: c.downlink, rtt: c.rtt };
                })()
            """)

            await page.close()
            await context.close()
            await browser.close()

            positions = await get_loaded_positions(client, sid)
            max_pos = max(positions) if positions else 0
            console.print(
                f"  {'headless-3G-throttled':>25s} | vp={'1280x720':>10s} | "
                f"ect={net_info.get('ect','?'):>4s} dl={str(net_info.get('downlink','?')):>5s} rtt={str(net_info.get('rtt','?')):>5s} | "
                f"loaded {len(positions):>3d}, max={max_pos}px"
            )

            # Experiment 5: Headful with screen size override
            console.rule("[bold]5. Different screen sizes")
            for screen in [{"width": 800, "height": 600}, {"width": 1920, "height": 1080}, {"width": 3840, "height": 2160}]:
                browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
                context = await browser.new_context(
                    viewport={"width": 1280, "height": 720},
                    screen=screen,
                )
                page = await context.new_page()
                sid = await create_session(client, "headless", f"screen-{screen['width']}x{screen['height']}", "lazy-fine")
                url = f"{BASE}/pages/lazy-fine?s={sid}&step=50&max_pos=5000"
                await page.goto(url, wait_until="networkidle")
                await asyncio.sleep(2)
                await page.close()
                await context.close()
                await browser.close()

                positions = await get_loaded_positions(client, sid)
                max_pos = max(positions) if positions else 0
                console.print(
                    f"  headless screen={screen['width']}x{screen['height']:>4d} | vp={'1280x720':>10s} | "
                    f"loaded {len(positions):>3d}, max={max_pos}px"
                )

    console.print("\n[bold green]Investigation complete.[/bold green]\n")


if __name__ == "__main__":
    asyncio.run(main())
