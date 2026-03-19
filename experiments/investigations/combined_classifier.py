"""Combined classifier: use all discovered signals to detect headless Chrome.

Signals found:
1. Static stress span (5000 heavy elements): headful slower (p=0.001, d=1.35)
2. Repaint stress span (500 animated elements): headful slower (p=0.011, d=0.92)
3. Reflow interval variance: headless higher (p=0.031, d=-0.99)
4. Differential timing (heavy-light): headless higher delta (p=0.003, d=-1.32)

This test collects all signals in a single session and builds a simple classifier.

Usage:
    uv run python -m experiments.investigations.combined_classifier
"""

import asyncio
import statistics
import json

import httpx
from playwright.async_api import async_playwright
from rich.console import Console
from rich.table import Table
from scipy.stats import mannwhitneyu

from core.config import BASE_URL as BASE, DEFAULT_VIEWPORT as VIEWPORT, CHANNEL
from core.browser import create_session

console = Console()
N_RUNS = 20  # More runs for better classification accuracy


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


def beacon_span(timing, prefix):
    beacons = [(r, t) for r, t in timing if prefix in r]
    if len(beacons) < 2:
        return None
    return (beacons[-1][1] - beacons[0][1]) / 1_000_000


def beacon_interval_stdev(timing, prefix):
    beacons = [(r, t) for r, t in timing if prefix in r]
    if len(beacons) < 3:
        return None
    intervals = [(beacons[i][1] - beacons[i-1][1]) / 1_000_000 for i in range(1, len(beacons))]
    return statistics.stdev(intervals)


async def collect_features(pw, client, mode, headless):
    """Collect all feature values for one browser session."""
    features = {}

    # 1. Static stress span (5000 elements)
    sid = await create_session(client, mode, "matched", "clf-static")
    browser, page = await launch(pw, headless)
    await page.goto(f"{BASE}/pages/stress-granular?s={sid}&count=5000&beacon_every=50",
                    wait_until="networkidle")
    await page.wait_for_timeout(8000)
    await browser.close()
    timing = await get_resource_timing(client, sid)
    features["static_span"] = beacon_span(timing, "stress-")

    # 2. Repaint stress span (500 animated elements)
    sid = await create_session(client, mode, "matched", "clf-repaint")
    browser, page = await launch(pw, headless)
    await page.goto(f"{BASE}/pages/stress-repaint?s={sid}&n_elements=500",
                    wait_until="networkidle")
    await page.wait_for_timeout(5000)
    await browser.close()
    timing = await get_resource_timing(client, sid)
    features["repaint_span"] = beacon_span(timing, "repaint-")
    features["repaint_iv_stdev"] = beacon_interval_stdev(timing, "repaint-")

    # 3. Reflow interval variance (300 animated elements)
    sid = await create_session(client, mode, "matched", "clf-reflow")
    browser, page = await launch(pw, headless)
    await page.goto(f"{BASE}/pages/stress-reflow?s={sid}&n_elements=300",
                    wait_until="networkidle")
    await page.wait_for_timeout(5000)
    await browser.close()
    timing = await get_resource_timing(client, sid)
    features["reflow_span"] = beacon_span(timing, "reflow-")
    features["reflow_iv_stdev"] = beacon_interval_stdev(timing, "reflow-")

    # 4. Differential: heavy CSS span
    sid = await create_session(client, mode, "matched", "clf-heavy")
    browser, page = await launch(pw, headless)
    await page.goto(f"{BASE}/pages/stress-css-only?s={sid}&weight=heavy",
                    wait_until="networkidle")
    await page.wait_for_timeout(5000)
    await browser.close()
    timing = await get_resource_timing(client, sid)
    features["heavy_span"] = beacon_span(timing, "cssonly-heavy")

    # 5. Differential: light CSS span
    sid = await create_session(client, mode, "matched", "clf-light")
    browser, page = await launch(pw, headless)
    await page.goto(f"{BASE}/pages/stress-css-only?s={sid}&weight=light",
                    wait_until="networkidle")
    await page.wait_for_timeout(5000)
    await browser.close()
    timing = await get_resource_timing(client, sid)
    features["light_span"] = beacon_span(timing, "cssonly-light")

    # Derived features
    if features["heavy_span"] is not None and features["light_span"] is not None:
        features["heavy_light_delta"] = features["heavy_span"] - features["light_span"]
    else:
        features["heavy_light_delta"] = None

    return features


def simple_threshold_classifier(features, thresholds):
    """Simple threshold-based classifier. Returns votes for headless."""
    votes_headless = 0
    votes_headful = 0

    for feature, (threshold, direction) in thresholds.items():
        val = features.get(feature)
        if val is None:
            continue
        if direction == "above_is_headful":
            if val > threshold:
                votes_headful += 1
            else:
                votes_headless += 1
        elif direction == "above_is_headless":
            if val > threshold:
                votes_headless += 1
            else:
                votes_headful += 1

    return "headless" if votes_headless > votes_headful else "headful"


async def main():
    console.print("[bold]===== Combined Headless Detection Classifier =====[/bold]\n")

    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, channel=CHANNEL, args=["--no-sandbox"])
        console.print(f"Chrome version: {b.version}")
        await b.close()

    console.print(f"Collecting {N_RUNS} samples per mode (5 pages each)...\n")

    all_features = {"headful": [], "headless": []}

    async with httpx.AsyncClient(timeout=120) as client:
        await client.post(f"{BASE}/clear")

        async with async_playwright() as pw:
            for run in range(N_RUNS):
                for mode, headless in [("headful", False), ("headless", True)]:
                    console.print(f"  Run {run+1:2d}/{N_RUNS} {mode}...", end=" ")
                    features = await collect_features(pw, client, mode, headless)
                    all_features[mode].append(features)

                    # Quick summary
                    ss = features.get("static_span") or 0
                    rs = features.get("repaint_span") or 0
                    hld = features.get("heavy_light_delta") or 0
                    console.print(f"static={ss:.1f}ms repaint={rs:.1f}ms delta={hld:.1f}ms")

    # --- Analysis ---
    console.rule("\n[bold]Feature Analysis")

    feature_names = ["static_span", "repaint_span", "repaint_iv_stdev",
                     "reflow_span", "reflow_iv_stdev", "heavy_light_delta"]

    table = Table(title="Feature Statistics (n={} per mode)".format(N_RUNS))
    table.add_column("Feature", style="bold")
    table.add_column("Headful mean")
    table.add_column("Headless mean")
    table.add_column("Delta")
    table.add_column("p-value")
    table.add_column("Cohen's d")
    table.add_column("Sig?")

    thresholds = {}

    for fname in feature_names:
        hf_vals = [f[fname] for f in all_features["headful"] if f[fname] is not None]
        hl_vals = [f[fname] for f in all_features["headless"] if f[fname] is not None]

        if len(hf_vals) < 3 or len(hl_vals) < 3:
            table.add_row(fname, "N/A", "N/A", "N/A", "N/A", "N/A", "")
            continue

        hf_mean = statistics.mean(hf_vals)
        hl_mean = statistics.mean(hl_vals)
        delta = hf_mean - hl_mean

        stat, p = mannwhitneyu(hf_vals, hl_vals, alternative='two-sided')
        pooled = statistics.stdev(hf_vals + hl_vals)
        d = delta / pooled if pooled > 0 else 0

        sig = "***" if p < 0.01 else "**" if p < 0.05 else "*" if p < 0.10 else ""

        # Set threshold at midpoint between means
        mid = (hf_mean + hl_mean) / 2
        if delta > 0:
            thresholds[fname] = (mid, "above_is_headful")
        else:
            thresholds[fname] = (mid, "above_is_headless")

        table.add_row(
            fname,
            f"{hf_mean:.2f}",
            f"{hl_mean:.2f}",
            f"{delta:.2f}",
            f"{p:.4f}",
            f"{d:.2f}",
            sig
        )

    console.print(table)

    # --- Classifier evaluation ---
    console.rule("\n[bold]Threshold Classifier Evaluation")
    console.print(f"  Thresholds (midpoint between means):")
    for fname, (threshold, direction) in thresholds.items():
        console.print(f"    {fname}: {threshold:.2f} ({direction})")

    correct = 0
    total = 0
    misclassified = []

    for mode in ["headful", "headless"]:
        for i, features in enumerate(all_features[mode]):
            prediction = simple_threshold_classifier(features, thresholds)
            is_correct = prediction == mode
            if is_correct:
                correct += 1
            else:
                misclassified.append((mode, i+1, prediction, features))
            total += 1

    accuracy = correct / total * 100 if total > 0 else 0
    console.print(f"\n  Accuracy: {correct}/{total} = {accuracy:.1f}%")

    if misclassified:
        console.print(f"\n  Misclassified ({len(misclassified)}):")
        for actual, run, predicted, features in misclassified:
            console.print(f"    Run {run} actual={actual} predicted={predicted}")
            for k, v in features.items():
                if v is not None:
                    console.print(f"      {k}={v:.2f}")

    # --- Per-feature classifier accuracy ---
    console.print("\n  Per-feature accuracy:")
    for fname, (threshold, direction) in thresholds.items():
        correct_f = 0
        total_f = 0
        for mode in ["headful", "headless"]:
            for features in all_features[mode]:
                val = features.get(fname)
                if val is None:
                    continue
                if direction == "above_is_headful":
                    pred = "headful" if val > threshold else "headless"
                else:
                    pred = "headless" if val > threshold else "headful"
                if pred == mode:
                    correct_f += 1
                total_f += 1
        acc_f = correct_f / total_f * 100 if total_f > 0 else 0
        console.print(f"    {fname}: {correct_f}/{total_f} = {acc_f:.1f}%")

    # Save raw data
    output = {
        "n_runs": N_RUNS,
        "thresholds": {k: {"value": v[0], "direction": v[1]} for k, v in thresholds.items()},
        "headful": all_features["headful"],
        "headless": all_features["headless"],
        "accuracy": accuracy,
    }
    with open("data/classifier_results.json", "w") as f:
        json.dump(output, f, indent=2)
    console.print(f"\n  Raw data saved to data/classifier_results.json")

    console.print("\n[bold]===== Classifier Complete =====[/bold]")


if __name__ == "__main__":
    asyncio.run(main())
