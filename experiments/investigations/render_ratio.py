"""Focused investigation: does heavy CSS rendering penalize headful more than headless?

The hypothesis: Chrome headless doesn't perform full GPU compositing,
so heavy CSS (blur, filters, gradients) has less impact on request timing.
The ratio of heavy/light request spans should differ between modes.

Also runs high-iteration stress test for statistical significance.

Usage:
    uv run python -m experiments.investigations.render_ratio
"""

import asyncio
import statistics

import httpx
from playwright.async_api import async_playwright
from rich.console import Console
from scipy.stats import mannwhitneyu

from core.config import BASE_URL as BASE, DEFAULT_VIEWPORT as VIEWPORT, CHANNEL
from core.browser import create_session, get_results

console = Console()
N_RUNS = 15


async def get_resource_timing(client, sid):
    reqs = await get_results(client, sid)
    reqs.sort(key=lambda r: r["timestamp_ns"])
    return [(r["resource"], r["timestamp_ns"]) for r in reqs]


async def launch(pw, headless, viewport=None):
    browser = await pw.chromium.launch(
        headless=headless, channel=CHANNEL, args=["--no-sandbox"]
    )
    ctx = await browser.new_context(viewport=viewport or VIEWPORT)
    page = await ctx.new_page()
    return browser, page


async def visit_and_wait(page, url, wait_ms=5000):
    await page.goto(url, wait_until="networkidle")
    await page.wait_for_timeout(wait_ms)


def extract_span(timing, prefix):
    """Extract total beacon span for resources matching prefix."""
    beacons = [(r, t) for r, t in timing if prefix in r]
    if len(beacons) < 2:
        return None
    return (beacons[-1][1] - beacons[0][1]) / 1_000_000


async def test_heavy_light_ratio(pw, client):
    """Run heavy and light CSS tests many times, compare ratios."""
    console.rule(f"[bold]Heavy vs Light CSS Ratio Test ({N_RUNS} runs per condition)")
    console.print("  3000 elements, beacons every 100. Measuring total beacon span.\n")

    data = {
        "headful_heavy": [], "headful_light": [],
        "headless_heavy": [], "headless_light": [],
    }

    for run in range(N_RUNS):
        for mode, headless in [("headful", False), ("headless", True)]:
            for weight in ["heavy", "light"]:
                sid = await create_session(client, mode, "matched", f"ratio-{weight}")
                browser, page = await launch(pw, headless)
                url = f"{BASE}/pages/stress-css-only?s={sid}&weight={weight}"
                await visit_and_wait(page, url, wait_ms=6000)
                await browser.close()

                timing = await get_resource_timing(client, sid)
                span = extract_span(timing, f"cssonly-{weight}")
                if span is not None:
                    data[f"{mode}_{weight}"].append(span)
                    console.print(f"  run {run+1:2d} {mode:>8} {weight:>5}: span={span:.1f}ms")

    console.print("\n[bold]Summary:[/bold]")
    for key in ["headful_heavy", "headful_light", "headless_heavy", "headless_light"]:
        vals = data[key]
        if vals:
            console.print(f"  {key:>20}: n={len(vals)} mean={statistics.mean(vals):.1f}ms "
                         f"median={statistics.median(vals):.1f}ms stdev={statistics.stdev(vals):.1f}ms")

    # Compute ratios for each run where we have both heavy and light
    headful_ratios = []
    headless_ratios = []
    min_runs = min(len(data["headful_heavy"]), len(data["headful_light"]),
                   len(data["headless_heavy"]), len(data["headless_light"]))

    for i in range(min_runs):
        hf_h = data["headful_heavy"][i]
        hf_l = data["headful_light"][i]
        hl_h = data["headless_heavy"][i]
        hl_l = data["headless_light"][i]
        if hf_l > 0 and hl_l > 0:
            headful_ratios.append(hf_h / hf_l)
            headless_ratios.append(hl_h / hl_l)

    if headful_ratios and headless_ratios:
        console.print(f"\n  [bold]Heavy/Light Ratios:[/bold]")
        console.print(f"   headful: mean={statistics.mean(headful_ratios):.3f}x "
                     f"median={statistics.median(headful_ratios):.3f}x "
                     f"stdev={statistics.stdev(headful_ratios):.3f}")
        console.print(f"  headless: mean={statistics.mean(headless_ratios):.3f}x "
                     f"median={statistics.median(headless_ratios):.3f}x "
                     f"stdev={statistics.stdev(headless_ratios):.3f}")

        if len(headful_ratios) >= 3 and len(headless_ratios) >= 3:
            stat, p = mannwhitneyu(headful_ratios, headless_ratios, alternative='two-sided')
            pooled = statistics.stdev(headful_ratios + headless_ratios)
            d = (statistics.mean(headful_ratios) - statistics.mean(headless_ratios)) / pooled if pooled > 0 else 0
            console.print(f"\n  Mann-Whitney U: p={p:.4f} Cohen's d={d:.3f}")
            if p < 0.05:
                console.print(f"  [bold green]*** STATISTICALLY SIGNIFICANT (p < 0.05) ***[/bold green]")
            elif p < 0.10:
                console.print(f"  [bold yellow]Marginally significant (p < 0.10)[/bold yellow]")
            else:
                console.print(f"  Not significant")


async def test_stress_span(pw, client):
    """High-iteration granular stress test."""
    console.rule(f"\n[bold]Granular Stress Span Test ({N_RUNS} runs)")
    console.print("  2000 heavy elements, beacons every 50\n")

    headful_spans = []
    headless_spans = []

    for run in range(N_RUNS):
        for mode, headless in [("headful", False), ("headless", True)]:
            sid = await create_session(client, mode, "matched", "stress-span")
            browser, page = await launch(pw, headless)
            url = f"{BASE}/pages/stress-granular?s={sid}&count=2000&beacon_every=50"
            await visit_and_wait(page, url, wait_ms=8000)
            await browser.close()

            timing = await get_resource_timing(client, sid)
            beacons = [(r, t) for r, t in timing if r.startswith("stress-")]
            if len(beacons) >= 2:
                span = (beacons[-1][1] - beacons[0][1]) / 1_000_000
                intervals = [(beacons[i][1] - beacons[i-1][1]) / 1_000_000 for i in range(1, len(beacons))]
                iv_stdev = statistics.stdev(intervals) if len(intervals) > 1 else 0

                if mode == "headful":
                    headful_spans.append(span)
                else:
                    headless_spans.append(span)

                console.print(f"  run {run+1:2d} {mode:>8}: span={span:.1f}ms "
                             f"mean_iv={statistics.mean(intervals):.2f}ms stdev_iv={iv_stdev:.2f}ms")

    if headful_spans and headless_spans:
        console.print(f"\n   headful: n={len(headful_spans)} mean={statistics.mean(headful_spans):.1f}ms "
                     f"median={statistics.median(headful_spans):.1f}ms stdev={statistics.stdev(headful_spans):.1f}ms")
        console.print(f"  headless: n={len(headless_spans)} mean={statistics.mean(headless_spans):.1f}ms "
                     f"median={statistics.median(headless_spans):.1f}ms stdev={statistics.stdev(headless_spans):.1f}ms")

        if len(headful_spans) >= 3 and len(headless_spans) >= 3:
            stat, p = mannwhitneyu(headful_spans, headless_spans, alternative='two-sided')
            pooled = statistics.stdev(headful_spans + headless_spans)
            d = (statistics.mean(headful_spans) - statistics.mean(headless_spans)) / pooled if pooled > 0 else 0
            console.print(f"\n  Mann-Whitney U: p={p:.4f} Cohen's d={d:.3f}")
            if p < 0.05:
                console.print(f"  [bold green]*** STATISTICALLY SIGNIFICANT (p < 0.05) ***[/bold green]")
            elif p < 0.10:
                console.print(f"  [bold yellow]Marginally significant (p < 0.10)[/bold yellow]")


async def test_headers(pw, client):
    """Capture and compare HTTP headers between modes."""
    console.rule("\n[bold]HTTP Header Comparison")

    # Clear previous
    await client.get(f"{BASE}/pages/headers/clear")

    results = {}
    for mode, headless in [("headful", False), ("headless", True)]:
        sid = f"hdr-{mode}"
        await create_session(client, mode, "matched", "headers")
        browser, page = await launch(pw, headless)
        url = f"{BASE}/pages/probe-headers?s={sid}"
        await visit_and_wait(page, url, wait_ms=3000)
        await browser.close()

        resp = await client.get(f"{BASE}/pages/headers/results/{sid}")
        captures = resp.json()
        results[mode] = {c['resource']: c['headers'] for c in captures}
        console.print(f"  {mode}: captured {len(captures)} resources")

    # Compare
    hf = results.get("headful", {})
    hl = results.get("headless", {})
    common = set(hf.keys()) & set(hl.keys())

    diffs = []
    for resource in sorted(common):
        all_keys = set(hf[resource].keys()) | set(hl[resource].keys())
        for k in sorted(all_keys):
            hf_v = hf[resource].get(k, '<missing>')
            hl_v = hl[resource].get(k, '<missing>')
            if hf_v != hl_v and k not in ('host', 'connection', 'content-length'):
                diffs.append((resource, k, hf_v, hl_v))

    if diffs:
        console.print(f"\n  [bold red]DIFFERENCES FOUND ({len(diffs)}):[/bold red]")
        for resource, key, hf_v, hl_v in diffs:
            console.print(f"    {resource} -> {key}:")
            console.print(f"       headful: {hf_v[:120]}")
            console.print(f"      headless: {hl_v[:120]}")
    else:
        console.print("\n  No header differences found")

    # Print full headers for one resource for comparison
    for resource in sorted(common)[:1]:
        console.print(f"\n  Full headers for '{resource}':")
        console.print(f"    headful:")
        for k, v in sorted(hf[resource].items()):
            console.print(f"      {k}: {v[:100]}")
        console.print(f"    headless:")
        for k, v in sorted(hl[resource].items()):
            console.print(f"      {k}: {v[:100]}")


async def main():
    console.print("[bold]===== Focused Rendering Ratio Investigation =====[/bold]\n")

    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, channel=CHANNEL, args=["--no-sandbox"])
        console.print(f"Chrome version: {b.version}\n")
        await b.close()

    async with httpx.AsyncClient(timeout=60) as client:
        await client.post(f"{BASE}/clear")

        async with async_playwright() as pw:
            await test_heavy_light_ratio(pw, client)
            await test_stress_span(pw, client)
            await test_headers(pw, client)

    console.print("\n[bold]===== Investigation Complete =====[/bold]")


if __name__ == "__main__":
    asyncio.run(main())
