"""Deep investigation to find ANY difference between Chrome headful and headless.

Tries many creative approaches beyond basic lazy loading.

Usage:
    uv run python -m experiments.investigations.chrome_deep
"""

import asyncio
import statistics

import httpx
from playwright.async_api import async_playwright
from rich.console import Console
from rich.table import Table

from core.config import BASE_URL as BASE, CHANNEL
from core.browser import create_session, get_results, get_resources, close_all

console = Console()


async def get_resource_order(client, sid):
    reqs = await get_results(client, sid)
    reqs.sort(key=lambda r: r["timestamp_ns"])
    return [(r["resource"], r["timestamp_ns"]) for r in reqs]


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


async def run_page(pw, client, headless, page_path, page_name, viewport=None, settle=2):
    mode = "headless" if headless else "headful"
    sid = await create_session(client, f"chrome-{mode}", "deep", page_name)
    browser, context, page = await launch(pw, headless, viewport)
    url = f"{BASE}/pages/{page_path}{'&' if '?' in page_path else '?'}s={sid}"
    if '?' not in page_path:
        url = f"{BASE}/pages/{page_path}?s={sid}"
    await page.goto(url, wait_until="networkidle")
    await asyncio.sleep(settle)
    await close_all(browser, context, page)
    return sid


# =============================================================================
async def test_content_visibility(pw, client):
    console.rule("[bold]1. content-visibility: auto")
    console.print("  [dim]Tests if content-visibility defers bg-image loading differently[/dim]")

    for headless in [False, True]:
        mode = "headless" if headless else "headful"
        sid = await run_page(pw, client, headless, "probe-content-visibility", "content-visibility")
        resources = await get_resources(client, sid)

        cv = sorted([int(r.split("-")[1]) for r in resources if r.startswith("cv-")])
        nocv = sorted([int(r.split("-")[1]) for r in resources if r.startswith("nocv-")])
        cv_max = max(cv) if cv else 0
        nocv_max = max(nocv) if nocv else 0
        console.print(f"  {mode:>8s}: content-visibility={len(cv)} (max={cv_max}px), control={len(nocv)} (max={nocv_max}px)")

        # Check if cv loaded fewer than nocv (it should skip offscreen rendering)
        if len(cv) < len(nocv):
            console.print(f"           [yellow]content-visibility deferred {len(nocv)-len(cv)} images[/yellow]")


# =============================================================================
async def test_video_audio(pw, client):
    console.rule("[bold]2. Video/Audio preload behavior")

    for headless in [False, True]:
        mode = "headless" if headless else "headful"
        sid = await run_page(pw, client, headless, "probe-video-audio", "video-audio")
        resources = sorted(await get_resources(client, sid))
        console.print(f"  {mode:>8s}: {resources}")


# =============================================================================
async def test_link_hints(pw, client):
    console.rule("[bold]3. Resource hints (prefetch, preload, modulepreload)")

    for headless in [False, True]:
        mode = "headless" if headless else "headful"
        sid = await run_page(pw, client, headless, "probe-link-hints", "link-hints")
        resources = sorted(await get_resources(client, sid))
        console.print(f"  {mode:>8s}: {resources}")


# =============================================================================
async def test_request_order(pw, client, n_runs=5):
    console.rule(f"[bold]4. Resource request ORDER ({n_runs} runs)")
    console.print("  [dim]Same resources, but does the browser fetch them in different order?[/dim]")

    orders = {"headful": [], "headless": []}

    for run in range(n_runs):
        for headless in [False, True]:
            mode = "headless" if headless else "headful"
            sid = await run_page(pw, client, headless, "probe-request-order", "request-order",
                                viewport={"width": 1280, "height": 720})
            ordered = await get_resource_order(client, sid)
            resource_order = [r[0] for r in ordered]
            orders[mode].append(resource_order)

    # Compare: are the orders consistently different?
    for mode in ("headful", "headless"):
        console.print(f"\n  [cyan]{mode} orders:[/cyan]")
        for i, order in enumerate(orders[mode]):
            console.print(f"    run {i+1}: {order}")

    # Check if any position consistently differs
    if orders["headful"] and orders["headless"]:
        hf_first = [o[0] if o else None for o in orders["headful"]]
        hl_first = [o[0] if o else None for o in orders["headless"]]
        if set(hf_first) != set(hl_first):
            console.print(f"\n  [bold green]FIRST RESOURCE DIFFERS: headful={set(hf_first)}, headless={set(hl_first)}[/bold green]")


# =============================================================================
async def test_heavy_render_timing(pw, client, n_runs=10):
    console.rule(f"[bold]5. Heavy render timing ({n_runs} runs)")
    console.print("  [dim]500 elements with extreme CSS vs 500 simple elements[/dim]")

    timings = {"headful": [], "headless": []}

    for run in range(n_runs):
        for headless in [False, True]:
            mode = "headless" if headless else "headful"
            sid = await run_page(pw, client, headless, "probe-heavy-render", "heavy-render",
                                viewport={"width": 1280, "height": 720}, settle=3)
            reqs = await get_results(client, sid)

            start = next((r for r in reqs if r["resource"] == "heavy-start"), None)
            mid = next((r for r in reqs if r["resource"] == "heavy-mid"), None)
            end = next((r for r in reqs if r["resource"] == "heavy-end"), None)

            if start and mid and end:
                t_heavy = (mid["timestamp_ns"] - start["timestamp_ns"]) / 1_000_000
                t_simple = (end["timestamp_ns"] - mid["timestamp_ns"]) / 1_000_000
                t_total = (end["timestamp_ns"] - start["timestamp_ns"]) / 1_000_000
                timings[mode].append({"heavy": t_heavy, "simple": t_simple, "total": t_total})
                console.print(f"  run {run+1:>2d} {mode:>8s}: heavy={t_heavy:.1f}ms simple={t_simple:.1f}ms total={t_total:.1f}ms")

    # Statistics
    console.print()
    for mode in ("headful", "headless"):
        if timings[mode]:
            totals = [t["total"] for t in timings[mode]]
            heavys = [t["heavy"] for t in timings[mode]]
            console.print(
                f"  {mode:>8s} total: mean={statistics.mean(totals):.1f}ms "
                f"median={statistics.median(totals):.1f}ms stdev={statistics.stdev(totals):.1f}ms"
            )
            console.print(
                f"  {mode:>8s} heavy: mean={statistics.mean(heavys):.1f}ms "
                f"median={statistics.median(heavys):.1f}ms stdev={statistics.stdev(heavys):.1f}ms"
            )

    # Mann-Whitney U test
    if len(timings["headful"]) >= 3 and len(timings["headless"]) >= 3:
        from scipy import stats
        import numpy as np
        hf_totals = [t["total"] for t in timings["headful"]]
        hl_totals = [t["total"] for t in timings["headless"]]
        u, p = stats.mannwhitneyu(hf_totals, hl_totals, alternative="two-sided")
        pooled_std = np.sqrt((np.std(hf_totals, ddof=1)**2 + np.std(hl_totals, ddof=1)**2) / 2)
        d = (np.mean(hl_totals) - np.mean(hf_totals)) / pooled_std if pooled_std > 0 else 0
        sig = "***" if p < 0.05 else "ns"
        console.print(f"\n  Mann-Whitney: p={p:.4f} Cohen's d={d:.3f} [{sig}]")

        hf_heavys = [t["heavy"] for t in timings["headful"]]
        hl_heavys = [t["heavy"] for t in timings["headless"]]
        u2, p2 = stats.mannwhitneyu(hf_heavys, hl_heavys, alternative="two-sided")
        pooled_std2 = np.sqrt((np.std(hf_heavys, ddof=1)**2 + np.std(hl_heavys, ddof=1)**2) / 2)
        d2 = (np.mean(hl_heavys) - np.mean(hf_heavys)) / pooled_std2 if pooled_std2 > 0 else 0
        console.print(f"  Heavy phase: p={p2:.4f} Cohen's d={d2:.3f} [{('***' if p2 < 0.05 else 'ns')}]")


# =============================================================================
async def test_scrollbar(pw, client):
    console.rule("[bold]6. Scrollbar detection via CSS")
    console.print("  [dim]Probing viewport width at 1px resolution around 1280px[/dim]")

    for headless in [False, True]:
        mode = "headless" if headless else "headful"
        sid = await run_page(pw, client, headless, "probe-scrollbar", "scrollbar",
                            viewport={"width": 1280, "height": 720})
        resources = await get_resources(client, sid)

        vw_probes = sorted([int(r.split("-")[-1]) for r in resources if r.startswith("scrollbar-vw-") and "full" not in r])
        max_vw = max(vw_probes) if vw_probes else 0
        min_vw = min(vw_probes) if vw_probes else 0
        console.print(f"  {mode:>8s}: viewport matched {len(vw_probes)} probes, range={min_vw}-{max_vw}px")

    console.print("  [dim]If headless lacks scrollbar, it has wider effective viewport[/dim]")


# =============================================================================
async def test_animation_timing(pw, client, n_runs=5):
    console.rule(f"[bold]7. CSS animation timing ({n_runs} runs)")
    console.print("  [dim]Do CSS animations fire their delayed resource loads at the same time?[/dim]")

    for headless in [False, True]:
        mode = "headless" if headless else "headful"
        for run in range(n_runs):
            sid = await run_page(pw, client, headless, "probe-animation-timing", "animation-timing",
                                viewport={"width": 1280, "height": 720}, settle=3)
            reqs = await get_results(client, sid)

            start = next((r for r in reqs if r["resource"] == "anim-start"), None)
            if not start:
                continue

            base = start["timestamp_ns"]
            delays = {}
            for r in reqs:
                if r["resource"].startswith("anim-") and r["resource"] != "anim-start":
                    delay_label = r["resource"].replace("anim-", "")
                    elapsed_ms = (r["timestamp_ns"] - base) / 1_000_000
                    delays[delay_label] = elapsed_ms

            delay_str = ", ".join(f"{k}={v:.1f}ms" for k, v in sorted(delays.items(), key=lambda x: int(x[0])))
            console.print(f"  run {run+1} {mode:>8s}: {delay_str}")


# =============================================================================
async def test_print_media(pw, client):
    console.rule("[bold]8. @media print behavior")

    for headless in [False, True]:
        mode = "headless" if headless else "headful"
        sid = await run_page(pw, client, headless, "probe-print-media", "print-media")
        resources = sorted(await get_resources(client, sid))
        console.print(f"  {mode:>8s}: {resources}")


# =============================================================================
async def test_focus_visibility(pw, client):
    console.rule("[bold]9. Focus/autofocus CSS behavior")
    console.print("  [dim]Does autofocus trigger :focus/:focus-visible CSS in headless?[/dim]")

    for headless in [False, True]:
        mode = "headless" if headless else "headful"
        sid = await run_page(pw, client, headless, "probe-focus-visibility", "focus-visibility", settle=2)
        resources = sorted(await get_resources(client, sid))
        console.print(f"  {mode:>8s}: {resources}")


# =============================================================================
async def test_outer_dimensions(pw, client):
    console.rule("[bold]10. outerWidth/outerHeight CSS detection")
    console.print("  [dim]Headful has window chrome, headless doesn't. Can CSS detect this?[/dim]")

    # We know outerHeight differs. In headful with 720 viewport, outerHeight=805.
    # The difference means the actual window occupies more screen space.
    # CSS can't read outerHeight directly, but we can detect it indirectly
    # via the 1280x720 lazy loading anomaly.

    # Re-test lazy loading at the exact boundary where headful loads more
    for headless in [False, True]:
        mode = "headless" if headless else "headful"
        sid = await create_session(client, f"chrome-{mode}", "outer-dim", "lazy-fine")
        browser, context, page = await launch(pw, headless, viewport={"width": 1280, "height": 720})

        # Get actual dimensions
        dims = await page.evaluate("({inner: [innerWidth, innerHeight], outer: [outerWidth, outerHeight], screen: [screen.width, screen.height]})")

        url = f"{BASE}/pages/lazy-fine?s={sid}&step=50&max_pos=5000"
        await page.goto(url, wait_until="networkidle")
        await asyncio.sleep(2)
        await close_all(browser, context, page)

        resources = await get_resources(client, sid)
        positions = sorted([int(r.replace("lazyfine-", "")) for r in resources
                           if r.startswith("lazyfine-") and "eager" not in r])
        max_pos = max(positions) if positions else 0
        console.print(f"  {mode:>8s}: inner={dims['inner']} outer={dims['outer']} screen={dims['screen']} → max_lazy={max_pos}px")


# =============================================================================
async def test_gpu_detection(pw, client):
    console.rule("[bold]11. GPU rendering flag effect")
    console.print("  [dim]Testing with --disable-gpu vs default[/dim]")

    for gpu_flag in [[], ["--disable-gpu"]]:
        flag_label = "no-gpu" if gpu_flag else "default"
        for headless in [False, True]:
            mode = "headless" if headless else "headful"
            sid = await run_page(pw, client, headless, "probe-heavy-render", f"gpu-{flag_label}",
                                viewport={"width": 1280, "height": 720}, settle=3)
            reqs = await get_results(client, sid)

            start = next((r for r in reqs if r["resource"] == "heavy-start"), None)
            end = next((r for r in reqs if r["resource"] == "heavy-end"), None)
            if start and end:
                total = (end["timestamp_ns"] - start["timestamp_ns"]) / 1_000_000
                console.print(f"  {flag_label:>7s} {mode:>8s}: total={total:.1f}ms")


# =============================================================================
async def main():
    console.print("\n[bold]===== Deep Chrome Detection Investigation =====[/bold]\n")

    async with httpx.AsyncClient() as client:
        await client.post(f"{BASE}/clear")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, channel=CHANNEL, args=["--no-sandbox"])
        console.print(f"[green]Chrome version: {browser.version}[/green]\n")
        await browser.close()

        async with httpx.AsyncClient() as client:
            await test_content_visibility(pw, client)
            await test_video_audio(pw, client)
            await test_link_hints(pw, client)
            await test_request_order(pw, client, n_runs=5)
            await test_heavy_render_timing(pw, client, n_runs=10)
            await test_scrollbar(pw, client)
            await test_animation_timing(pw, client, n_runs=3)
            await test_print_media(pw, client)
            await test_focus_visibility(pw, client)
            await test_outer_dimensions(pw, client)
            await test_gpu_detection(pw, client)

    console.print("\n[bold green]===== Deep Investigation Complete =====[/bold green]\n")


if __name__ == "__main__":
    asyncio.run(main())
