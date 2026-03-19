"""Focused investigation into lazy loading behavior differences.

Runs targeted experiments to understand WHY lazy loading differs
between headful and headless modes.

Usage:
    uv run python -m experiments.investigations.lazy
"""

import asyncio

import httpx
from playwright.async_api import async_playwright
from rich.console import Console
from rich.table import Table

from core.config import BASE_URL as BASE
from core.browser import create_session, get_resources as get_results

console = Console()


async def visit(pw, headless: bool, url: str, viewport=None, color_scheme=None, reduced_motion=None):
    browser = await pw.chromium.launch(headless=headless, args=["--no-sandbox"])
    ctx_args = {}
    if viewport:
        ctx_args["viewport"] = viewport
    if color_scheme:
        ctx_args["color_scheme"] = color_scheme
    if reduced_motion:
        ctx_args["reduced_motion"] = reduced_motion
    context = await browser.new_context(**ctx_args)
    page = await context.new_page()
    await page.goto(url, wait_until="networkidle")
    await asyncio.sleep(2)
    await page.close()
    await context.close()
    await browser.close()


async def experiment_fine_threshold(pw, client: httpx.AsyncClient):
    """Experiment 1: Fine-grained threshold detection with 100px steps."""
    console.rule("[bold]Experiment 1: Fine-grained threshold (100px steps)")

    for headless in [False, True]:
        mode = "headless" if headless else "headful"
        sid = await create_session(client, mode, "default", "lazy-fine")
        url = f"{BASE}/pages/lazy-fine?s={sid}&step=100&max_pos=6000"
        await visit(pw, headless, url)
        resources = await get_results(client, sid)
        lazy = sorted([int(r.split("-")[1]) for r in resources if r.startswith("lazyfine-") and r != "lazyfine-eager"])
        max_pos = max(lazy) if lazy else 0
        console.print(f"  {mode:>8s}: loaded {len(lazy)} images, max position = {max_pos}px")
        console.print(f"           positions: {lazy}")


async def experiment_matched_viewport(pw, client: httpx.AsyncClient):
    """Experiment 2: Same viewport size - does the threshold still differ?"""
    console.rule("[bold]Experiment 2: Matched viewport (1280x720)")

    for headless in [False, True]:
        mode = "headless" if headless else "headful"
        sid = await create_session(client, mode, "matched", "lazy-fine")
        url = f"{BASE}/pages/lazy-fine?s={sid}&step=100&max_pos=6000"
        await visit(pw, headless, url, viewport={"width": 1280, "height": 720})
        resources = await get_results(client, sid)
        lazy = sorted([int(r.split("-")[1]) for r in resources if r.startswith("lazyfine-") and r != "lazyfine-eager"])
        max_pos = max(lazy) if lazy else 0
        console.print(f"  {mode:>8s}: loaded {len(lazy)} images, max position = {max_pos}px")


async def experiment_small_viewport(pw, client: httpx.AsyncClient):
    """Experiment 3: Very small viewport in both modes."""
    console.rule("[bold]Experiment 3: Small viewport (400x300)")

    for headless in [False, True]:
        mode = "headless" if headless else "headful"
        sid = await create_session(client, mode, "small", "lazy-fine")
        url = f"{BASE}/pages/lazy-fine?s={sid}&step=100&max_pos=6000"
        await visit(pw, headless, url, viewport={"width": 400, "height": 300})
        resources = await get_results(client, sid)
        lazy = sorted([int(r.split("-")[1]) for r in resources if r.startswith("lazyfine-") and r != "lazyfine-eager"])
        max_pos = max(lazy) if lazy else 0
        console.print(f"  {mode:>8s}: loaded {len(lazy)} images, max position = {max_pos}px")


async def experiment_css_background(pw, client: httpx.AsyncClient):
    """Experiment 4: CSS background images - do they show similar threshold behavior?"""
    console.rule("[bold]Experiment 4: CSS background images (250px steps)")

    for headless in [False, True]:
        mode = "headless" if headless else "headful"
        sid = await create_session(client, mode, "default", "lazy-css-bg")
        url = f"{BASE}/pages/lazy-css-bg?s={sid}"
        await visit(pw, headless, url)
        resources = await get_results(client, sid)
        bg = sorted([int(r.split("-")[1]) for r in resources if r.startswith("cssbg-")])
        max_pos = max(bg) if bg else 0
        console.print(f"  {mode:>8s}: loaded {len(bg)} bg images, max position = {max_pos}px")


async def experiment_iframes(pw, client: httpx.AsyncClient):
    """Experiment 5: Lazy iframes - same threshold difference?"""
    console.rule("[bold]Experiment 5: Lazy-loaded iframes")

    for headless in [False, True]:
        mode = "headless" if headless else "headful"
        sid = await create_session(client, mode, "default", "lazy-iframe")
        url = f"{BASE}/pages/lazy-iframe?s={sid}"
        await visit(pw, headless, url)
        resources = await get_results(client, sid)
        iframes = sorted([int(r.split("-")[1]) for r in resources if r.startswith("lziframe-") and "eager" not in r])
        max_pos = max(iframes) if iframes else 0
        console.print(f"  {mode:>8s}: loaded {len(iframes)} iframes, max position = {max_pos}px")


async def experiment_srcset(pw, client: httpx.AsyncClient):
    """Experiment 6: srcset and picture elements."""
    console.rule("[bold]Experiment 6: srcset and picture elements")

    for headless in [False, True]:
        mode = "headless" if headless else "headful"
        sid = await create_session(client, mode, "default", "lazy-srcset")
        url = f"{BASE}/pages/lazy-srcset?s={sid}"
        await visit(pw, headless, url)
        resources = await get_results(client, sid)

        # Group by type
        img_positions = sorted(set(int(r.split("-")[2]) for r in resources if r.startswith("lzsrcset-img-")))
        srcset_resources = [r for r in resources if r.startswith("lzsrcset-srcset-")]
        picture_resources = [r for r in resources if r.startswith("lzsrcset-picture-")]

        img_max = max(img_positions) if img_positions else 0
        console.print(f"  {mode:>8s}:")
        console.print(f"    img:     {len(img_positions)} loaded, max={img_max}px")
        console.print(f"    srcset:  {len(srcset_resources)} resources loaded")
        console.print(f"    picture: {len(picture_resources)} resources loaded")


async def experiment_image_sizes(pw, client: httpx.AsyncClient):
    """Experiment 7: Does image size affect the lazy loading threshold?"""
    console.rule("[bold]Experiment 7: Image dimensions affect threshold?")

    for headless in [False, True]:
        mode = "headless" if headless else "headful"
        sid = await create_session(client, mode, "default", "lazy-mixed-sizes")
        url = f"{BASE}/pages/lazy-mixed-sizes?s={sid}"
        await visit(pw, headless, url)
        resources = await get_results(client, sid)

        # Group by size
        sizes = {}
        for r in resources:
            if r.startswith("lzsize-"):
                parts = r.split("-")
                size_key = parts[1]  # e.g. "10x10"
                pos = int(parts[2])
                sizes.setdefault(size_key, []).append(pos)

        for size_key in sorted(sizes.keys()):
            positions = sorted(sizes[size_key])
            max_pos = max(positions)
            console.print(f"  {mode:>8s} {size_key:>8s}: loaded {len(positions)}, max={max_pos}px")


async def main():
    console.print("\n[bold]Lazy Loading Deep Investigation[/bold]\n")

    async with httpx.AsyncClient() as client:
        # Clear previous data
        await client.post(f"{BASE}/clear")

    async with async_playwright() as pw:
        async with httpx.AsyncClient() as client:
            await experiment_fine_threshold(pw, client)
            await experiment_matched_viewport(pw, client)
            await experiment_small_viewport(pw, client)
            await experiment_css_background(pw, client)
            await experiment_iframes(pw, client)
            await experiment_srcset(pw, client)
            await experiment_image_sizes(pw, client)

    console.print("\n[bold green]Investigation complete.[/bold green]\n")


if __name__ == "__main__":
    asyncio.run(main())
