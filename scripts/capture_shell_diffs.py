"""Capture screenshots and HAR files for URLs where headless-shell renders differently."""

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright, TimeoutError as PwTimeout

OUTPUT_DIR = Path("/tmp/shell_rendering_diffs")
VIEWPORT = {"width": 1280, "height": 720}
BROWSER_ARGS = [
    "--no-sandbox",
    "--disable-blink-features=AutomationControlled",
    "--disable-crashpad",
]
WEBDRIVER_PATCH = "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
PAGE_TIMEOUT_MS = 15_000
SETTLE_TIME_S = 3.0

# Mode → (channel, headless)
MODE_PARAMS = {
    "headless": ("chrome", True),
    "headful": ("chrome", False),
    "headless-shell": ("chromium-headless-shell", True),
}

URLS = [
    "https://www.reddit.com/",
    "https://www.amazon.ca/",
    "https://www.amazon.com.au/",
    "https://www.amazon.co.uk/",
    "https://www.amazon.de/",
    "https://www.amazon.fr/",
    "https://www.walmart.com/",
    "https://www.bet365.com/",
    "https://www.sofascore.com/",
    "https://www.flashscore.com/",
    "https://time.com",
    "https://www.ieee.org/",
    "https://kick.com",
]


def slug(url: str) -> str:
    from urllib.parse import urlparse
    host = urlparse(url).hostname or url
    return host.replace(".", "_").replace("www_", "")


async def capture_url(pw, url: str, mode: str, user_agent: str) -> None:
    channel, headless = MODE_PARAMS[mode]
    host = slug(url)
    site_dir = OUTPUT_DIR / host
    site_dir.mkdir(parents=True, exist_ok=True)

    har_path = site_dir / f"{mode}.har"

    try:
        browser = await pw.chromium.launch(
            headless=headless,
            channel=channel,
            args=BROWSER_ARGS,
            timeout=30_000,
        )

        ctx_opts = {
            "viewport": VIEWPORT,
            "user_agent": user_agent,
            "record_har_path": str(har_path),
        }
        context = await browser.new_context(**ctx_opts)
        page = await context.new_page()
        await page.add_init_script(WEBDRIVER_PATCH)

        try:
            response = await page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
        except PwTimeout:
            pass
        except Exception as e:
            print(f"    Navigation error: {str(e)[:100]}")

        await asyncio.sleep(SETTLE_TIME_S)

        # Screenshot
        ss_path = site_dir / f"{mode}.png"
        await page.screenshot(path=str(ss_path), full_page=False)

        # Get content info
        try:
            info = await asyncio.wait_for(page.evaluate("""() => ({
                title: document.title,
                textLen: document.body ? (document.body.innerText || '').length : 0,
                elements: document.querySelectorAll('*').length,
                url: location.href,
            })"""), timeout=5)
            status = response.status if response else 0
            print(f"    {mode:16s} status={status} text={info['textLen']:>6} els={info['elements']:>5} → {info['url'][:70]}")
        except Exception:
            pass

        await context.close()
        await browser.close()

    except Exception as e:
        print(f"    {mode:16s} FAILED: {str(e)[:120]}")


async def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Use Xvfb for headful mode so it doesn't pop up windows
    import subprocess, os, time as _time
    xvfb = subprocess.Popen(
        ["Xvfb", ":99", "-screen", "0", "1280x720x24"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    _time.sleep(1)
    os.environ["DISPLAY"] = ":99"

    async with async_playwright() as pw:
        # Detect headful UA
        browser = await pw.chromium.launch(
            headless=False, channel="chrome", args=["--no-sandbox"]
        )
        page = await browser.new_page()
        user_agent = await page.evaluate("navigator.userAgent")
        await browser.close()
        print(f"User-Agent: {user_agent}\n")

        for url in URLS:
            print(f"\n{'─' * 80}")
            print(f"  {url}")
            print(f"{'─' * 80}")
            for mode in ["headless", "headful", "headless-shell"]:
                await capture_url(pw, url, mode, user_agent)

    xvfb.terminate()

    # Summary
    print(f"\n{'=' * 80}")
    print(f"Output: {OUTPUT_DIR}")
    for d in sorted(OUTPUT_DIR.iterdir()):
        if d.is_dir():
            files = sorted(d.iterdir())
            print(f"  {d.name}/")
            for f in files:
                size = f.stat().st_size
                if size > 1024 * 1024:
                    print(f"    {f.name:30s} {size / 1024 / 1024:.1f} MB")
                else:
                    print(f"    {f.name:30s} {size / 1024:.0f} KB")


if __name__ == "__main__":
    asyncio.run(main())
