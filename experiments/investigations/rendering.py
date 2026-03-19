"""Investigate rendering-dependent timing differences in Chrome.

Hypothesis: headless Chrome may not fully render (or renders differently)
heavy visual content. If so, the pattern/timing of server-side resource
requests should differ between headful and headless modes.

Tests:
1. Granular stress test: 2000 heavy elements with beacons every 50 elements
2. Heavy vs light CSS: same structure, different rendering cost
3. Large SVG images with complex filters
4. Connection burst pattern: 30 simultaneous requests
5. Repeated stress test: statistical comparison over N runs
6. HTTP header comparison

Usage:
    uv run python -m experiments.investigations.rendering
"""

import asyncio
import statistics
import json

import httpx
from playwright.async_api import async_playwright
from rich.console import Console
from rich.table import Table

from core.config import BASE_URL as BASE, CHANNEL
from core.browser import create_session, get_results, get_resources

console = Console()


async def get_resource_timing(client, sid):
    """Return list of (resource, timestamp_ns) sorted by time."""
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
    ctx = await browser.new_context(**ctx_args)
    page = await ctx.new_page()
    return browser, page


async def visit_and_wait(page, url, wait_ms=5000):
    """Visit URL and wait for network idle + extra time."""
    await page.goto(url, wait_until="networkidle")
    await page.wait_for_timeout(wait_ms)


def compute_beacon_deltas(timing_data):
    """From a list of (resource, ts_ns), extract beacon intervals.
    Returns dict: beacon_name -> delta_ms from first beacon."""
    beacons = [(r, t) for r, t in timing_data if "beacon" in r or r.startswith("stress-")]
    if not beacons:
        return {}
    t0 = beacons[0][1]
    return {r: (t - t0) / 1_000_000 for r, t in beacons}


# --- Test 1: Granular stress test ---

async def test_granular_stress(pw, client, n_runs=5):
    console.rule("[bold]1. Granular rendering stress test (2000 heavy elements)")
    console.print("  2000 elements with extreme CSS, beacons every 50 elements")
    console.print(f"  Running {n_runs} iterations per mode...")

    headful_spreads = []
    headless_spreads = []

    for run in range(n_runs):
        for mode, headless in [("headful", False), ("headless", True)]:
            sid = await create_session(client, mode, "matched", "stress-granular")
            browser, page = await launch(pw, headless, viewport={"width": 1280, "height": 720})
            url = f"{BASE}/pages/stress-granular?s={sid}&count=2000&beacon_every=50"
            await visit_and_wait(page, url, wait_ms=8000)
            await browser.close()

            timing = await get_resource_timing(client, sid)
            # Get all stress-b* beacons
            beacons = [(r, t) for r, t in timing if r.startswith("stress-b") or r == "stress-start" or r == "stress-end"]
            if len(beacons) >= 2:
                total_span = (beacons[-1][1] - beacons[0][1]) / 1_000_000
                # Compute inter-beacon intervals
                intervals = []
                for i in range(1, len(beacons)):
                    intervals.append((beacons[i][1] - beacons[i-1][1]) / 1_000_000)

                if mode == "headful":
                    headful_spreads.append(total_span)
                else:
                    headless_spreads.append(total_span)

                console.print(f"  run {run+1:2d} {mode:>8}: {len(beacons)} beacons, "
                             f"total_span={total_span:.1f}ms, "
                             f"mean_interval={statistics.mean(intervals):.1f}ms, "
                             f"stdev_interval={statistics.stdev(intervals) if len(intervals) > 1 else 0:.1f}ms")

    if headful_spreads and headless_spreads:
        console.print(f"\n   headful total_span: mean={statistics.mean(headful_spreads):.1f}ms "
                     f"median={statistics.median(headful_spreads):.1f}ms stdev={statistics.stdev(headful_spreads) if len(headful_spreads) > 1 else 0:.1f}ms")
        console.print(f"  headless total_span: mean={statistics.mean(headless_spreads):.1f}ms "
                     f"median={statistics.median(headless_spreads):.1f}ms stdev={statistics.stdev(headless_spreads) if len(headless_spreads) > 1 else 0:.1f}ms")

        from scipy.stats import mannwhitneyu
        if len(headful_spreads) >= 3 and len(headless_spreads) >= 3:
            try:
                stat, p = mannwhitneyu(headful_spreads, headless_spreads, alternative='two-sided')
                pooled_std = statistics.stdev(headful_spreads + headless_spreads)
                d = (statistics.mean(headful_spreads) - statistics.mean(headless_spreads)) / pooled_std if pooled_std > 0 else 0
                console.print(f"  Mann-Whitney: p={p:.4f} Cohen's d={d:.3f} {'*** SIGNIFICANT ***' if p < 0.05 else ''}")
            except Exception as e:
                console.print(f"  Stats error: {e}")


# --- Test 2: Heavy vs Light CSS comparison ---

async def test_heavy_vs_light(pw, client, n_runs=5):
    console.rule("[bold]2. Heavy vs Light CSS (same structure, different rendering cost)")
    console.print("  3000 elements, beacons every 100")

    results = {"headful_heavy": [], "headful_light": [], "headless_heavy": [], "headless_light": []}

    for run in range(n_runs):
        for mode, headless in [("headful", False), ("headless", True)]:
            for weight in ["heavy", "light"]:
                sid = await create_session(client, mode, "matched", f"cssonly-{weight}")
                browser, page = await launch(pw, headless, viewport={"width": 1280, "height": 720})
                url = f"{BASE}/pages/stress-css-only?s={sid}&weight={weight}"
                await visit_and_wait(page, url, wait_ms=6000)
                await browser.close()

                timing = await get_resource_timing(client, sid)
                beacons = [(r, t) for r, t in timing if f"cssonly-{weight}" in r]
                if len(beacons) >= 2:
                    total_span = (beacons[-1][1] - beacons[0][1]) / 1_000_000
                    results[f"{mode}_{weight}"].append(total_span)
                    console.print(f"  run {run+1} {mode:>8} {weight:>5}: {len(beacons)} beacons, span={total_span:.1f}ms")

    console.print("\n  Summary:")
    for key, vals in results.items():
        if vals:
            console.print(f"  {key:>20}: mean={statistics.mean(vals):.1f}ms median={statistics.median(vals):.1f}ms")

    # Key comparison: does heavy CSS penalize headful more than headless?
    hf_heavy = results["headful_heavy"]
    hf_light = results["headful_light"]
    hl_heavy = results["headless_heavy"]
    hl_light = results["headless_light"]

    if hf_heavy and hf_light and hl_heavy and hl_light:
        hf_ratio = statistics.mean(hf_heavy) / statistics.mean(hf_light) if statistics.mean(hf_light) > 0 else 0
        hl_ratio = statistics.mean(hl_heavy) / statistics.mean(hl_light) if statistics.mean(hl_light) > 0 else 0
        console.print(f"\n  headful  heavy/light ratio: {hf_ratio:.2f}x")
        console.print(f"  headless heavy/light ratio: {hl_ratio:.2f}x")
        console.print(f"  If headless skips rendering, its ratio should be closer to 1.0")


# --- Test 3: SVG rendering stress ---

async def test_svg_rendering(pw, client, n_runs=3):
    console.rule("[bold]3. Complex SVG rendering")
    console.print("  20 complex SVGs with filter chains (blur, turbulence, displacement)")

    headful_spans = []
    headless_spans = []

    for run in range(n_runs):
        for mode, headless in [("headful", False), ("headless", True)]:
            sid = await create_session(client, mode, "matched", "large-images")
            browser, page = await launch(pw, headless, viewport={"width": 1280, "height": 720})
            url = f"{BASE}/pages/stress-large-images?s={sid}"
            await visit_and_wait(page, url, wait_ms=8000)
            await browser.close()

            timing = await get_resource_timing(client, sid)
            beacons = [(r, t) for r, t in timing if r.startswith("lgimg-")]
            svg_renders = [(r, t) for r, t in timing if r.startswith("svg-render-")]

            if beacons:
                total_span = (beacons[-1][1] - beacons[0][1]) / 1_000_000
                if mode == "headful":
                    headful_spans.append(total_span)
                else:
                    headless_spans.append(total_span)
                console.print(f"  run {run+1} {mode:>8}: {len(beacons)} beacons, {len(svg_renders)} SVGs, span={total_span:.1f}ms")

    if headful_spans and headless_spans:
        console.print(f"\n   headful: mean={statistics.mean(headful_spans):.1f}ms")
        console.print(f"  headless: mean={statistics.mean(headless_spans):.1f}ms")


# --- Test 4: Connection burst pattern ---

async def test_connection_burst(pw, client, n_runs=5):
    console.rule("[bold]4. Connection burst pattern (30 simultaneous requests)")
    console.print("  Measures how browser schedules 30 concurrent image requests")

    headful_data = []
    headless_data = []

    for run in range(n_runs):
        for mode, headless in [("headful", False), ("headless", True)]:
            sid = await create_session(client, mode, "matched", "conn-pattern")
            browser, page = await launch(pw, headless, viewport={"width": 1280, "height": 720})
            url = f"{BASE}/pages/probe-connection-pattern?s={sid}"
            await visit_and_wait(page, url, wait_ms=3000)
            await browser.close()

            timing = await get_resource_timing(client, sid)
            conn_reqs = [(r, t) for r, t in timing if r.startswith("conn-")]

            if len(conn_reqs) >= 2:
                total_span = (conn_reqs[-1][1] - conn_reqs[0][1]) / 1_000_000
                # Compute inter-request intervals
                intervals = [(conn_reqs[i][1] - conn_reqs[i-1][1]) / 1_000_000 for i in range(1, len(conn_reqs))]
                # Clustering: how many arrive within first 10% of total span
                if total_span > 0:
                    early_cutoff = conn_reqs[0][1] + (total_span * 0.1 * 1_000_000)
                    early_count = sum(1 for _, t in conn_reqs if t <= early_cutoff)
                else:
                    early_count = len(conn_reqs)

                data = {
                    "total_span": total_span,
                    "mean_interval": statistics.mean(intervals),
                    "stdev_interval": statistics.stdev(intervals) if len(intervals) > 1 else 0,
                    "early_pct": early_count / len(conn_reqs) * 100,
                }
                if mode == "headful":
                    headful_data.append(data)
                else:
                    headless_data.append(data)

                console.print(f"  run {run+1} {mode:>8}: {len(conn_reqs)} reqs, "
                             f"span={total_span:.1f}ms, early_pct={data['early_pct']:.0f}%, "
                             f"stdev={data['stdev_interval']:.2f}ms")

    if headful_data and headless_data:
        console.print(f"\n   headful: mean_span={statistics.mean([d['total_span'] for d in headful_data]):.1f}ms "
                     f"mean_early_pct={statistics.mean([d['early_pct'] for d in headful_data]):.0f}%")
        console.print(f"  headless: mean_span={statistics.mean([d['total_span'] for d in headless_data]):.1f}ms "
                     f"mean_early_pct={statistics.mean([d['early_pct'] for d in headless_data]):.0f}%")


# --- Test 5: HTTP header comparison ---

async def test_http_headers(pw, client):
    console.rule("[bold]5. HTTP header comparison")
    console.print("  Comparing request headers between headful and headless")

    # Clear previous captures
    await client.get(f"{BASE}/pages/headers/clear")

    for mode, headless in [("headful", False), ("headless", True)]:
        sid = f"headers-{mode}"
        await create_session(client, mode, "matched", "headers")
        browser, page = await launch(pw, headless, viewport={"width": 1280, "height": 720})
        url = f"{BASE}/pages/probe-headers?s={sid}"
        await visit_and_wait(page, url, wait_ms=3000)
        await browser.close()

        # Get captured headers
        resp = await client.get(f"{BASE}/pages/headers/results/{sid}")
        captures = resp.json()

        console.print(f"\n  {mode} ({len(captures)} resources captured):")
        for cap in captures:
            console.print(f"    {cap['resource']}:")
            for k, v in sorted(cap['headers'].items()):
                # Skip host and non-interesting headers
                if k in ('host', 'connection', 'content-length'):
                    continue
                console.print(f"      {k}: {v[:100]}")

    # Now compare specific headers
    headful_resp = await client.get(f"{BASE}/pages/headers/results/headers-headful")
    headless_resp = await client.get(f"{BASE}/pages/headers/results/headers-headless")
    hf_caps = headful_resp.json()
    hl_caps = headless_resp.json()

    # Find matching resources and compare headers
    hf_by_resource = {c['resource']: c['headers'] for c in hf_caps}
    hl_by_resource = {c['resource']: c['headers'] for c in hl_caps}

    common = set(hf_by_resource.keys()) & set(hl_by_resource.keys())
    diffs_found = False
    for resource in sorted(common):
        hf_h = hf_by_resource[resource]
        hl_h = hl_by_resource[resource]
        all_keys = set(hf_h.keys()) | set(hl_h.keys())
        for k in sorted(all_keys):
            hf_v = hf_h.get(k, '<missing>')
            hl_v = hl_h.get(k, '<missing>')
            if hf_v != hl_v and k not in ('host', 'connection', 'content-length'):
                if not diffs_found:
                    console.print("\n  [bold red]HEADER DIFFERENCES FOUND:[/bold red]")
                    diffs_found = True
                console.print(f"    {resource} -> {k}:")
                console.print(f"       headful: {hf_v[:100]}")
                console.print(f"      headless: {hl_v[:100]}")

    if not diffs_found:
        console.print("\n  No header differences found between modes")


# --- Test 6: Favicon behavior ---

async def test_favicon(pw, client):
    console.rule("[bold]6. Favicon request behavior")
    console.print("  Does headless request favicons the same way?")

    for mode, headless in [("headful", False), ("headless", True)]:
        sid = await create_session(client, mode, "matched", "favicon")
        browser, page = await launch(pw, headless, viewport={"width": 1280, "height": 720})
        url = f"{BASE}/pages/probe-favicon?s={sid}"
        await visit_and_wait(page, url, wait_ms=3000)
        await browser.close()

        resources = await get_resources(client, sid)
        console.print(f"  {mode:>8}: {sorted(resources)}")


# --- Test 7: Meta refresh timing ---

async def test_meta_refresh(pw, client, n_runs=3):
    console.rule("[bold]7. Meta http-equiv=refresh timing")
    console.print("  Does meta refresh fire at the same time in both modes?")

    headful_deltas = []
    headless_deltas = []

    for run in range(n_runs):
        for mode, headless in [("headful", False), ("headless", True)]:
            sid = await create_session(client, mode, "matched", "meta-refresh")
            browser, page = await launch(pw, headless, viewport={"width": 1280, "height": 720})
            url = f"{BASE}/pages/probe-meta-refresh?s={sid}"
            await visit_and_wait(page, url, wait_ms=5000)
            await browser.close()

            timing = await get_resource_timing(client, sid)
            start_t = None
            target_t = None
            for r, t in timing:
                if r == "meta-refresh-start":
                    start_t = t
                if r == "meta-refresh-target":
                    target_t = t

            if start_t and target_t:
                delta_ms = (target_t - start_t) / 1_000_000
                if mode == "headful":
                    headful_deltas.append(delta_ms)
                else:
                    headless_deltas.append(delta_ms)
                console.print(f"  run {run+1} {mode:>8}: refresh delta={delta_ms:.1f}ms")
            else:
                console.print(f"  run {run+1} {mode:>8}: start={'yes' if start_t else 'NO'} target={'yes' if target_t else 'NO'}")

    if headful_deltas and headless_deltas:
        console.print(f"\n   headful: mean={statistics.mean(headful_deltas):.1f}ms")
        console.print(f"  headless: mean={statistics.mean(headless_deltas):.1f}ms")


# --- Test 8: CSS environment/viewport probes ---

async def test_css_env(pw, client):
    console.rule("[bold]8. CSS environment variables and dynamic viewport units")

    for mode, headless in [("headful", False), ("headless", True)]:
        sid = await create_session(client, mode, "matched", "css-env")
        browser, page = await launch(pw, headless, viewport={"width": 1280, "height": 720})
        url = f"{BASE}/pages/probe-css-vars-env?s={sid}"
        await visit_and_wait(page, url, wait_ms=3000)
        await browser.close()

        resources = await get_resources(client, sid)
        console.print(f"  {mode:>8}: {sorted(resources)}")


# --- Test 9: Overflow/scrollbar behavior ---

async def test_overflow(pw, client):
    console.rule("[bold]9. Overflow/scrollbar behavior")

    for mode, headless in [("headful", False), ("headless", True)]:
        sid = await create_session(client, mode, "matched", "overflow")
        browser, page = await launch(pw, headless, viewport={"width": 1280, "height": 720})
        url = f"{BASE}/pages/probe-overflow-behavior?s={sid}"
        await visit_and_wait(page, url, wait_ms=3000)
        await browser.close()

        resources = await get_resources(client, sid)
        console.print(f"  {mode:>8}: {sorted(resources)}")


async def main():
    console.print("[bold]===== Chrome Rendering Stress Investigation =====[/bold]\n")

    # Show Chrome version
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, channel=CHANNEL, args=["--no-sandbox"])
        ver = b.version
        await b.close()
    console.print(f"Chrome version: {ver}\n")

    async with httpx.AsyncClient(timeout=60) as client:
        # Clear old data
        await client.post(f"{BASE}/clear")

        async with async_playwright() as pw:
            await test_granular_stress(pw, client, n_runs=5)
            await test_heavy_vs_light(pw, client, n_runs=5)
            await test_svg_rendering(pw, client, n_runs=3)
            await test_connection_burst(pw, client, n_runs=5)
            await test_http_headers(pw, client)
            await test_favicon(pw, client)
            await test_meta_refresh(pw, client, n_runs=3)
            await test_css_env(pw, client)
            await test_overflow(pw, client)

    console.print("\n[bold]===== Rendering Stress Investigation Complete =====[/bold]")


if __name__ == "__main__":
    asyncio.run(main())
