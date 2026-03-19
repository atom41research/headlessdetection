"""Investigate compositor/animation-based detection.

The key insight: headful's extra resource consumption comes from the
compositing/display pipeline (GPU, vsync, frame production).
Our previous tests measured during LAYOUT phase (before compositing).

This test forces continuous ANIMATION which requires per-frame compositor work:
1. stress-compositor: Animated layers with transform+filter (compositor heavy)
2. stress-repaint: Animated paint properties (box-shadow, colors)
3. stress-reflow: Animated layout properties (width, height, padding)

Beacons are triggered by animation-delay at fixed intervals (100-200ms).
If the compositor is saturated in headful, beacon delivery may be delayed.

Usage:
    uv run python -m experiments.investigations.compositor
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


async def launch(pw, headless):
    browser = await pw.chromium.launch(
        headless=headless, channel=CHANNEL, args=["--no-sandbox"]
    )
    ctx = await browser.new_context(viewport=VIEWPORT)
    page = await ctx.new_page()
    return browser, page


def analyze_beacon_timing(timing, prefix):
    """Extract timed beacons and compute inter-arrival deltas."""
    # Find beacons matching pattern like "comp-t200", "repaint-t500", etc.
    timed = []
    for r, t in timing:
        if f"{prefix}-t" in r:
            try:
                delay_str = r.split(f"{prefix}-t")[1]
                delay_ms = int(delay_str)
                timed.append((delay_ms, t))
            except (ValueError, IndexError):
                continue

    timed.sort(key=lambda x: x[0])  # Sort by intended delay

    if len(timed) < 2:
        return None

    # Find start beacon
    start_t = None
    for r, t in timing:
        if r == f"{prefix}-start":
            start_t = t
            break

    if start_t is None and timed:
        start_t = timed[0][1]

    # Compute actual arrival times relative to start
    actual_arrivals = [(d, (t - start_t) / 1_000_000) for d, t in timed]

    # Compute jitter: actual - expected timing
    jitters = [(d, actual - d) for d, actual in actual_arrivals]

    # Total span
    total_span = (timed[-1][1] - timed[0][1]) / 1_000_000

    # Inter-arrival intervals
    intervals = [(timed[i][1] - timed[i-1][1]) / 1_000_000 for i in range(1, len(timed))]

    return {
        "n_beacons": len(timed),
        "total_span": total_span,
        "mean_jitter": statistics.mean([j for _, j in jitters]) if jitters else 0,
        "stdev_jitter": statistics.stdev([j for _, j in jitters]) if len(jitters) > 1 else 0,
        "mean_interval": statistics.mean(intervals) if intervals else 0,
        "stdev_interval": statistics.stdev(intervals) if len(intervals) > 1 else 0,
        "max_jitter": max(j for _, j in jitters) if jitters else 0,
        "arrivals": actual_arrivals[:5],  # First 5 for display
    }


async def test_compositor(pw, client, n_runs=10):
    """Test 1: Animated compositing layers."""
    console.rule("[bold]1. Compositor stress (200 animated layers, 3s)")
    console.print("  Layers animate transform+filter+opacity continuously")
    console.print("  Beacons at 200ms intervals during animation\n")

    headful_data = []
    headless_data = []

    for run in range(n_runs):
        for mode, headless in [("headful", False), ("headless", True)]:
            sid = await create_session(client, mode, "matched", "compositor")
            browser, page = await launch(pw, headless)
            url = f"{BASE}/pages/stress-compositor?s={sid}&n_layers=200&duration=3"
            await page.goto(url, wait_until="networkidle")
            # Wait for animation to run and beacons to fire
            await page.wait_for_timeout(5000)
            await browser.close()

            timing = await get_resource_timing(client, sid)
            result = analyze_beacon_timing(timing, "comp")
            if result:
                target = headful_data if mode == "headful" else headless_data
                target.append(result)
                console.print(f"  run {run+1:2d} {mode:>8}: {result['n_beacons']} beacons, "
                             f"span={result['total_span']:.1f}ms, "
                             f"mean_jitter={result['mean_jitter']:.1f}ms, "
                             f"stdev_jitter={result['stdev_jitter']:.1f}ms")

    _compare(headful_data, headless_data, "compositor")


async def test_repaint(pw, client, n_runs=10):
    """Test 2: Animated repaint properties."""
    console.rule("\n[bold]2. Repaint stress (500 elements, animated colors/shadows)")
    console.print("  Beacons at 100ms intervals\n")

    headful_data = []
    headless_data = []

    for run in range(n_runs):
        for mode, headless in [("headful", False), ("headless", True)]:
            sid = await create_session(client, mode, "matched", "repaint")
            browser, page = await launch(pw, headless)
            url = f"{BASE}/pages/stress-repaint?s={sid}&n_elements=500"
            await page.goto(url, wait_until="networkidle")
            await page.wait_for_timeout(5000)
            await browser.close()

            timing = await get_resource_timing(client, sid)
            result = analyze_beacon_timing(timing, "repaint")
            if result:
                target = headful_data if mode == "headful" else headless_data
                target.append(result)
                console.print(f"  run {run+1:2d} {mode:>8}: {result['n_beacons']} beacons, "
                             f"span={result['total_span']:.1f}ms, "
                             f"mean_jitter={result['mean_jitter']:.1f}ms, "
                             f"stdev_jitter={result['stdev_jitter']:.1f}ms")

    _compare(headful_data, headless_data, "repaint")


async def test_reflow(pw, client, n_runs=10):
    """Test 3: Animated reflow properties."""
    console.rule("\n[bold]3. Reflow stress (300 elements, animated width/height)")
    console.print("  Beacons at 100ms intervals\n")

    headful_data = []
    headless_data = []

    for run in range(n_runs):
        for mode, headless in [("headful", False), ("headless", True)]:
            sid = await create_session(client, mode, "matched", "reflow")
            browser, page = await launch(pw, headless)
            url = f"{BASE}/pages/stress-reflow?s={sid}&n_elements=300"
            await page.goto(url, wait_until="networkidle")
            await page.wait_for_timeout(5000)
            await browser.close()

            timing = await get_resource_timing(client, sid)
            result = analyze_beacon_timing(timing, "reflow")
            if result:
                target = headful_data if mode == "headful" else headless_data
                target.append(result)
                console.print(f"  run {run+1:2d} {mode:>8}: {result['n_beacons']} beacons, "
                             f"span={result['total_span']:.1f}ms, "
                             f"mean_jitter={result['mean_jitter']:.1f}ms, "
                             f"stdev_jitter={result['stdev_jitter']:.1f}ms")

    _compare(headful_data, headless_data, "reflow")


async def test_compositor_heavy(pw, client, n_runs=10):
    """Test 4: Maximum compositor stress - 500 layers."""
    console.rule("\n[bold]4. EXTREME compositor stress (500 animated layers)")

    headful_data = []
    headless_data = []

    for run in range(n_runs):
        for mode, headless in [("headful", False), ("headless", True)]:
            sid = await create_session(client, mode, "matched", "compositor-heavy")
            browser, page = await launch(pw, headless)
            url = f"{BASE}/pages/stress-compositor?s={sid}&n_layers=500&duration=3"
            await page.goto(url, wait_until="networkidle")
            await page.wait_for_timeout(6000)
            await browser.close()

            timing = await get_resource_timing(client, sid)
            result = analyze_beacon_timing(timing, "comp")
            if result:
                target = headful_data if mode == "headful" else headless_data
                target.append(result)
                console.print(f"  run {run+1:2d} {mode:>8}: {result['n_beacons']} beacons, "
                             f"span={result['total_span']:.1f}ms, "
                             f"mean_jitter={result['mean_jitter']:.1f}ms, "
                             f"stdev_jitter={result['stdev_jitter']:.1f}ms")

    _compare(headful_data, headless_data, "compositor-heavy")


def _compare(headful_data, headless_data, label):
    """Statistical comparison."""
    if not headful_data or not headless_data:
        console.print(f"  [red]Insufficient data for {label}[/red]")
        return

    metrics = ["total_span", "mean_jitter", "stdev_jitter", "mean_interval", "stdev_interval"]

    console.print(f"\n  [bold]Summary for {label}:[/bold]")
    for metric in metrics:
        hf_vals = [d[metric] for d in headful_data]
        hl_vals = [d[metric] for d in headless_data]

        if not hf_vals or not hl_vals:
            continue

        hf_mean = statistics.mean(hf_vals)
        hl_mean = statistics.mean(hl_vals)

        line = f"    {metric:>20}: headful={hf_mean:.2f}  headless={hl_mean:.2f}  delta={hf_mean-hl_mean:.2f}"

        if len(hf_vals) >= 3 and len(hl_vals) >= 3:
            try:
                stat, p = mannwhitneyu(hf_vals, hl_vals, alternative='two-sided')
                pooled = statistics.stdev(hf_vals + hl_vals)
                d = (hf_mean - hl_mean) / pooled if pooled > 0 else 0
                sig = " ***" if p < 0.05 else " *" if p < 0.10 else ""
                line += f"  p={p:.4f} d={d:.2f}{sig}"
            except Exception:
                pass

        console.print(line)


async def main():
    console.print("[bold]===== Compositor Stress Investigation =====[/bold]\n")

    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, channel=CHANNEL, args=["--no-sandbox"])
        console.print(f"Chrome version: {b.version}\n")
        await b.close()

    async with httpx.AsyncClient(timeout=120) as client:
        await client.post(f"{BASE}/clear")

        async with async_playwright() as pw:
            await test_compositor(pw, client, n_runs=10)
            await test_repaint(pw, client, n_runs=10)
            await test_reflow(pw, client, n_runs=10)
            await test_compositor_heavy(pw, client, n_runs=10)

    console.print("\n[bold]===== Investigation Complete =====[/bold]")


if __name__ == "__main__":
    asyncio.run(main())
