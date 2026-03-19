"""Compare lazy loading behavior across Chromium and Chrome browsers.

Tests both Playwright's bundled Chromium and the system's installed Chrome
in headful and headless modes.

Usage:
    uv run python -m experiments.investigations.browsers
"""

import asyncio

import httpx
from playwright.async_api import async_playwright
from rich.console import Console
from rich.table import Table

from core.config import BASE_URL as BASE
from core.browser import create_session

console = Console()


async def get_loaded_positions(client, sid, prefix="lazyfine-"):
    resp = await client.get(f"{BASE}/results/{sid}")
    resources = [r["resource"] for r in resp.json()["requests"]]
    positions = sorted([int(r.replace(prefix, "")) for r in resources if r.startswith(prefix) and "eager" not in r])
    return positions


async def run_test(pw, client, headless, channel=None, viewport=None, label=""):
    mode = "headless" if headless else "headful"
    launch_args = ["--no-sandbox"]
    launch_kwargs = {"headless": headless, "args": launch_args}
    if channel:
        launch_kwargs["channel"] = channel

    browser_label = channel or "chromium"

    try:
        browser = await pw.chromium.launch(**launch_kwargs)
    except Exception as e:
        console.print(f"  [red]{label:>35s} | FAILED: {e}[/red]")
        return None

    ctx_args = {}
    if viewport:
        ctx_args["viewport"] = viewport
    context = await browser.new_context(**ctx_args)
    page = await context.new_page()

    # Get browser version and network info
    await page.goto("about:blank")
    info = await page.evaluate("""
        (() => {
            const c = navigator.connection || {};
            return {
                ect: c.effectiveType || 'unknown',
                downlink: c.downlink,
                rtt: c.rtt,
                ua: navigator.userAgent,
            };
        })()
    """)

    # Extract Chrome version from UA
    ua = info.get("ua", "")
    version = "?"
    if "Chrome/" in ua:
        version = ua.split("Chrome/")[1].split(" ")[0].split(".")[0]

    sid = await create_session(client, f"{browser_label}-{mode}", "test", "lazy-fine")
    url = f"{BASE}/pages/lazy-fine?s={sid}&step=50&max_pos=5000"
    await page.goto(url, wait_until="networkidle")
    await asyncio.sleep(2)

    await page.close()
    await context.close()
    await browser.close()

    positions = await get_loaded_positions(client, sid)
    max_pos = max(positions) if positions else 0

    vp_label = f"{viewport['width']}x{viewport['height']}" if viewport else "default"
    dl = info.get("downlink", "?")
    rtt = info.get("rtt", "?")
    ect = info.get("ect", "?")

    console.print(
        f"  {label:>35s} | v{version:>4s} | vp={vp_label:>10s} | "
        f"ect={ect:>4s} dl={str(dl):>5s} rtt={str(rtt):>5s} | "
        f"loaded {len(positions):>3d}, max={max_pos}px"
    )
    return {"label": label, "version": version, "max_pos": max_pos, "count": len(positions),
            "ect": ect, "downlink": dl, "rtt": rtt}


async def main():
    console.print("\n[bold]Lazy Loading: Chromium vs Chrome Comparison[/bold]\n")

    async with httpx.AsyncClient() as client:
        await client.post(f"{BASE}/clear")

    # Channels to test: None = bundled Chromium, "chrome" = system Chrome
    browsers = [
        (None, "chromium"),
        ("chrome", "chrome"),
    ]

    viewports = [
        (None, "default"),
        ({"width": 1280, "height": 720}, "1280x720"),
    ]

    results = []

    async with async_playwright() as pw:
        async with httpx.AsyncClient() as client:
            for channel, browser_name in browsers:
                console.rule(f"[bold]{browser_name.upper()}")
                for viewport, vp_name in viewports:
                    for headless in [False, True]:
                        mode = "headless" if headless else "headful"
                        label = f"{browser_name} {mode} vp={vp_name}"
                        result = await run_test(
                            pw, client, headless,
                            channel=channel,
                            viewport=viewport,
                            label=label,
                        )
                        if result:
                            result["browser"] = browser_name
                            result["mode"] = mode
                            result["viewport"] = vp_name
                            results.append(result)

    # Summary table
    console.print()
    table = Table(title="Summary: Lazy Loading Threshold by Browser & Mode", show_lines=True)
    table.add_column("Browser", style="cyan")
    table.add_column("Mode", justify="center")
    table.add_column("Viewport", justify="center")
    table.add_column("Version", justify="center")
    table.add_column("ECT", justify="center")
    table.add_column("Downlink", justify="right")
    table.add_column("RTT", justify="right")
    table.add_column("Max Pos", justify="right", style="bold")
    table.add_column("# Loaded", justify="right")

    for r in results:
        table.add_row(
            r["browser"],
            r["mode"],
            r["viewport"],
            f"v{r['version']}",
            str(r["ect"]),
            str(r["downlink"]),
            str(r["rtt"]),
            f"{r['max_pos']}px",
            str(r["count"]),
        )

    console.print(table)
    console.print()


if __name__ == "__main__":
    asyncio.run(main())
