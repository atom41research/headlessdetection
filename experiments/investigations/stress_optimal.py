"""Find optimal parameters for the rendering stress detection signal.

We know 2000 heavy elements gives p=0.028 with d=0.87.
Try to maximize the effect by varying:
1. Element count (1000, 3000, 5000)
2. CSS complexity (extreme: massive blur, backdrop-filter, will-change)
3. Beacon density (every 25 vs 50 vs 100)

Also tries a differential approach: serve both heavy and light pages in the same
session and compute the SERVER-SIDE difference.

Usage:
    uv run python -m experiments.investigations.stress_optimal
"""

import asyncio
import statistics

import httpx
from playwright.async_api import async_playwright
from rich.console import Console
from scipy.stats import mannwhitneyu

from core.config import BASE_URL as BASE, DEFAULT_VIEWPORT as VIEWPORT, CHANNEL
from core.browser import create_session

console = Console()


async def get_resource_timing(client, sid):
    resp = await client.get(f"{BASE}/results/{sid}")
    reqs = resp.json()["requests"]
    reqs.sort(key=lambda r: r["timestamp_ns"])
    return [(r["resource"], r["timestamp_ns"]) for r in reqs]


async def launch(pw, headless, viewport=None):
    browser = await pw.chromium.launch(
        headless=headless, channel=CHANNEL, args=["--no-sandbox"]
    )
    ctx = await browser.new_context(viewport=viewport or VIEWPORT)
    page = await ctx.new_page()
    return browser, page


async def visit_and_wait(page, url, wait_ms=8000):
    await page.goto(url, wait_until="networkidle")
    await page.wait_for_timeout(wait_ms)


def compute_span(timing, prefix="stress-"):
    beacons = [(r, t) for r, t in timing if prefix in r]
    if len(beacons) < 2:
        return None, 0, 0
    span = (beacons[-1][1] - beacons[0][1]) / 1_000_000
    intervals = [(beacons[i][1] - beacons[i-1][1]) / 1_000_000 for i in range(1, len(beacons))]
    stdev = statistics.stdev(intervals) if len(intervals) > 1 else 0
    return span, len(beacons), stdev


async def test_element_counts(pw, client):
    """Test different element counts to find the sweet spot."""
    console.rule("[bold]1. Effect of element count on detection")
    N_RUNS = 10

    for count in [1000, 2000, 3000, 5000]:
        console.print(f"\n  --- {count} elements, beacon every 50 ---")
        headful_spans = []
        headless_spans = []

        for run in range(N_RUNS):
            for mode, headless in [("headful", False), ("headless", True)]:
                sid = await create_session(client, mode, "matched", f"count-{count}")
                browser, page = await launch(pw, headless)
                url = f"{BASE}/pages/stress-granular?s={sid}&count={count}&beacon_every=50"
                await visit_and_wait(page, url, wait_ms=max(5000, count * 3))
                await browser.close()

                timing = await get_resource_timing(client, sid)
                span, n_beacons, _ = compute_span(timing)
                if span is not None:
                    if mode == "headful":
                        headful_spans.append(span)
                    else:
                        headless_spans.append(span)
                    console.print(f"    run {run+1:2d} {mode:>8}: {n_beacons} beacons, span={span:.1f}ms")

        if len(headful_spans) >= 3 and len(headless_spans) >= 3:
            hf_mean = statistics.mean(headful_spans)
            hl_mean = statistics.mean(headless_spans)
            stat, p = mannwhitneyu(headful_spans, headless_spans, alternative='two-sided')
            pooled = statistics.stdev(headful_spans + headless_spans)
            d = (hf_mean - hl_mean) / pooled if pooled > 0 else 0
            console.print(f"\n    headful:  mean={hf_mean:.1f}ms stdev={statistics.stdev(headful_spans):.1f}")
            console.print(f"    headless: mean={hl_mean:.1f}ms stdev={statistics.stdev(headless_spans):.1f}")
            console.print(f"    p={p:.4f} d={d:.3f} delta={hf_mean-hl_mean:.1f}ms {'***' if p < 0.05 else ''}")


async def test_differential(pw, client):
    """Differential approach: same browser visits heavy page then light page.
    Compute the DIFFERENCE in span per session. This controls for
    machine load variance between runs."""
    console.rule("[bold]\n2. Differential approach (heavy - light in same session)")
    N_RUNS = 10

    headful_deltas = []
    headless_deltas = []

    for run in range(N_RUNS):
        for mode, headless in [("headful", False), ("headless", True)]:
            browser, page = await launch(pw, headless)

            # Heavy first
            sid_h = await create_session(client, mode, "matched", "diff-heavy")
            url_h = f"{BASE}/pages/stress-granular?s={sid_h}&count=2000&beacon_every=50"
            await visit_and_wait(page, url_h, wait_ms=6000)

            # Light: navigate to light page in same browser
            sid_l = await create_session(client, mode, "matched", "diff-light")
            url_l = f"{BASE}/pages/stress-css-only?s={sid_l}&weight=light"
            await visit_and_wait(page, url_l, wait_ms=5000)

            await browser.close()

            timing_h = await get_resource_timing(client, sid_h)
            timing_l = await get_resource_timing(client, sid_l)

            span_h, _, _ = compute_span(timing_h, "stress-")
            span_l, _, _ = compute_span(timing_l, "cssonly-light")

            if span_h is not None and span_l is not None:
                delta = span_h - span_l
                if mode == "headful":
                    headful_deltas.append(delta)
                else:
                    headless_deltas.append(delta)
                console.print(f"  run {run+1:2d} {mode:>8}: heavy={span_h:.1f}ms light={span_l:.1f}ms delta={delta:.1f}ms")

    if len(headful_deltas) >= 3 and len(headless_deltas) >= 3:
        console.print(f"\n   headful deltas: mean={statistics.mean(headful_deltas):.1f}ms stdev={statistics.stdev(headful_deltas):.1f}")
        console.print(f"  headless deltas: mean={statistics.mean(headless_deltas):.1f}ms stdev={statistics.stdev(headless_deltas):.1f}")
        stat, p = mannwhitneyu(headful_deltas, headless_deltas, alternative='two-sided')
        pooled = statistics.stdev(headful_deltas + headless_deltas)
        d = (statistics.mean(headful_deltas) - statistics.mean(headless_deltas)) / pooled if pooled > 0 else 0
        console.print(f"  p={p:.4f} d={d:.3f} {'***' if p < 0.05 else ''}")


async def test_interval_variance(pw, client):
    """Test whether the VARIANCE of inter-beacon intervals differs.
    GPU compositing may cause more variable timing due to frame scheduling."""
    console.rule("[bold]\n3. Inter-beacon interval variance")
    N_RUNS = 10

    headful_stdevs = []
    headless_stdevs = []

    for run in range(N_RUNS):
        for mode, headless in [("headful", False), ("headless", True)]:
            sid = await create_session(client, mode, "matched", "variance-test")
            browser, page = await launch(pw, headless)
            url = f"{BASE}/pages/stress-granular?s={sid}&count=2000&beacon_every=25"
            await visit_and_wait(page, url, wait_ms=8000)
            await browser.close()

            timing = await get_resource_timing(client, sid)
            beacons = [(r, t) for r, t in timing if "stress-" in r]
            if len(beacons) >= 3:
                intervals = [(beacons[i][1] - beacons[i-1][1]) / 1_000_000 for i in range(1, len(beacons))]
                iv_stdev = statistics.stdev(intervals)
                iv_mean = statistics.mean(intervals)

                if mode == "headful":
                    headful_stdevs.append(iv_stdev)
                else:
                    headless_stdevs.append(iv_stdev)
                console.print(f"  run {run+1:2d} {mode:>8}: {len(beacons)} beacons, "
                             f"mean_iv={iv_mean:.2f}ms stdev_iv={iv_stdev:.2f}ms")

    if len(headful_stdevs) >= 3 and len(headless_stdevs) >= 3:
        console.print(f"\n   headful interval stdev: mean={statistics.mean(headful_stdevs):.2f}ms")
        console.print(f"  headless interval stdev: mean={statistics.mean(headless_stdevs):.2f}ms")
        stat, p = mannwhitneyu(headful_stdevs, headless_stdevs, alternative='two-sided')
        pooled = statistics.stdev(headful_stdevs + headless_stdevs)
        d = (statistics.mean(headful_stdevs) - statistics.mean(headless_stdevs)) / pooled if pooled > 0 else 0
        console.print(f"  p={p:.4f} d={d:.3f} {'***' if p < 0.05 else ''}")
        console.print(f"  Higher variance in headful would indicate GPU frame scheduling jitter")


async def main():
    console.print("[bold]===== Stress Test Parameter Optimization =====[/bold]\n")

    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, channel=CHANNEL, args=["--no-sandbox"])
        console.print(f"Chrome version: {b.version}\n")
        await b.close()

    async with httpx.AsyncClient(timeout=120) as client:
        await client.post(f"{BASE}/clear")

        async with async_playwright() as pw:
            await test_element_counts(pw, client)
            await test_differential(pw, client)
            await test_interval_variance(pw, client)

    console.print("\n[bold]===== Optimization Complete =====[/bold]")


if __name__ == "__main__":
    asyncio.run(main())
