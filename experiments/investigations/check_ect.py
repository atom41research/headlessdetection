"""Check what effective connection type (ECT) browsers report.

Chromium uses ECT to determine lazy loading thresholds:
- 4G: 1250px threshold
- 3G or slower: 2500px threshold

Hypothesis: headless reports a different ECT than headful, causing
different lazy loading thresholds.
"""

import asyncio
import sys

from playwright.async_api import async_playwright
from rich.console import Console

console = Console()

JS_CHECK = """
(() => {
    const conn = navigator.connection || {};
    return {
        effectiveType: conn.effectiveType || 'unknown',
        downlink: conn.downlink || 'unknown',
        rtt: conn.rtt || 'unknown',
        saveData: conn.saveData || false,
        type: conn.type || 'unknown',
        // Also check viewport
        innerWidth: window.innerWidth,
        innerHeight: window.innerHeight,
        outerWidth: window.outerWidth,
        outerHeight: window.outerHeight,
        devicePixelRatio: window.devicePixelRatio,
        // Screen info
        screenWidth: screen.width,
        screenHeight: screen.height,
        availWidth: screen.availWidth,
        availHeight: screen.availHeight,
    };
})()
"""


async def main():
    console.print("\n[bold]Network & Viewport Info: Headful vs Headless[/bold]\n")

    async with async_playwright() as pw:
        for headless in [False, True]:
            mode = "headless" if headless else "headful"
            browser = await pw.chromium.launch(headless=headless, args=["--no-sandbox"])
            context = await browser.new_context()
            page = await context.new_page()
            await page.goto("about:blank")
            info = await page.evaluate(JS_CHECK)
            await browser.close()

            console.print(f"[cyan]{mode}:[/cyan]")
            for key, val in info.items():
                console.print(f"  {key}: {val}")
            console.print()

        # Also test with matched viewport
        console.print("[bold]With matched viewport (1280x720):[/bold]\n")
        for headless in [False, True]:
            mode = "headless" if headless else "headful"
            browser = await pw.chromium.launch(headless=headless, args=["--no-sandbox"])
            context = await browser.new_context(viewport={"width": 1280, "height": 720})
            page = await context.new_page()
            await page.goto("about:blank")
            info = await page.evaluate(JS_CHECK)
            await browser.close()

            console.print(f"[cyan]{mode}:[/cyan]")
            for key, val in info.items():
                console.print(f"  {key}: {val}")
            console.print()


if __name__ == "__main__":
    asyncio.run(main())
