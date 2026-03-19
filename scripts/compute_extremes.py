"""Compute min/max per-mode values and per-URL difference extremes vs headful."""

import json
import statistics
from pathlib import Path

JOB = Path("bench/results/job_20260308_202325")

# Metrics to extract from mode objects
METRICS = {
    "cgroup_active_avg_mb": "Container Active (MB)",
    "cgroup_total_avg_mb": "Container Total (MB)",
    "cgroup_cpu_pct": "Container CPU%",
    "avg_uss_mb": "Chrome USS (MB)",
    "avg_rss_mb": "Chrome RSS (MB)",
    "avg_cpu_pct": "Chrome CPU% (avg)",
    "avg_page_load_ms": "Wall-clock load (ms)",
}

NAV_METRICS = {
    "ttfb_ms": "TTFB (ms)",
    "connect_ms": "Connect (ms)",
    "dns_ms": "DNS (ms)",
}


def load_json(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def avg_runs(run0_results: list[dict], run1_results: list[dict], mode_key: str) -> dict[str, dict]:
    """Average metrics across run_0 and run_1 per URL for a given mode key."""
    r0_by_url = {r["url"]: r.get(mode_key) for r in run0_results if r.get(mode_key)}
    r1_by_url = {r["url"]: r.get(mode_key) for r in run1_results if r.get(mode_key)}

    combined = {}
    all_urls = set(r0_by_url) | set(r1_by_url)
    for url in all_urls:
        m0 = r0_by_url.get(url)
        m1 = r1_by_url.get(url)
        if m0 and m1:
            merged = {}
            for k in METRICS:
                v0, v1 = m0.get(k, 0), m1.get(k, 0)
                merged[k] = (v0 + v1) / 2
            # Nav timing from load_events
            le0 = m0.get("load_events", {})
            le1 = m1.get("load_events", {})
            merged["load_events"] = {}
            for k in NAV_METRICS:
                v0, v1 = le0.get(k, 0), le1.get(k, 0)
                if v0 and v1:
                    merged["load_events"][k] = (v0 + v1) / 2
                elif v0:
                    merged["load_events"][k] = v0
                elif v1:
                    merged["load_events"][k] = v1
            # Track errors/timeouts
            merged["errors"] = (m0.get("errors", 0) + m1.get("errors", 0))
            merged["timeouts"] = (m0.get("timeouts", 0) + m1.get("timeouts", 0))
            combined[url] = merged
        elif m0:
            combined[url] = {k: m0.get(k, 0) for k in METRICS}
            combined[url]["load_events"] = {k: m0.get("load_events", {}).get(k, 0) for k in NAV_METRICS}
            combined[url]["errors"] = m0.get("errors", 0)
            combined[url]["timeouts"] = m0.get("timeouts", 0)
        elif m1:
            combined[url] = {k: m1.get(k, 0) for k in METRICS}
            combined[url]["load_events"] = {k: m1.get("load_events", {}).get(k, 0) for k in NAV_METRICS}
            combined[url]["errors"] = m1.get("errors", 0)
            combined[url]["timeouts"] = m1.get("timeouts", 0)
    return combined


def compute_absolute_minmax(mode_data: dict[str, dict], label: str):
    """Print absolute min/max for each metric across all URLs."""
    print(f"\n=== Absolute Min/Max: {label} ===")
    all_metrics = list(METRICS.keys()) + [f"nav_{k}" for k in NAV_METRICS]
    for metric_key in METRICS:
        vals = [d[metric_key] for d in mode_data.values() if d.get(metric_key, 0) > 0]
        if vals:
            print(f"  {METRICS[metric_key]:30s}  min={min(vals):10.1f}  max={max(vals):10.1f}")
    for nav_key in NAV_METRICS:
        vals = [d["load_events"][nav_key] for d in mode_data.values()
                if d.get("load_events", {}).get(nav_key, 0) > 0]
        if vals:
            print(f"  {NAV_METRICS[nav_key]:30s}  min={min(vals):10.1f}  max={max(vals):10.1f}")


def compute_diffs(mode_a: dict[str, dict], mode_b: dict[str, dict],
                  label_a: str, label_b: str):
    """Compute per-URL diffs (mode_a - mode_b) and report extremes."""
    print(f"\n=== Per-URL Differences: {label_a} minus {label_b} ===")
    common = set(mode_a) & set(mode_b)
    # Filter out URLs with errors in either mode
    valid = [url for url in common
             if mode_a[url].get("errors", 0) == 0 and mode_b[url].get("errors", 0) == 0
             and mode_a[url].get("timeouts", 0) == 0 and mode_b[url].get("timeouts", 0) == 0]
    print(f"  URLs compared: {len(valid)} (of {len(common)} common)")

    for metric_key in METRICS:
        diffs = []
        for url in valid:
            va = mode_a[url].get(metric_key, 0)
            vb = mode_b[url].get(metric_key, 0)
            if va > 0 and vb > 0:
                diffs.append((va - vb, url))
        if not diffs:
            continue
        diffs.sort(key=lambda x: x[0])
        mn_val, mn_url = diffs[0]
        mx_val, mx_url = diffs[-1]
        mean_val = statistics.mean(d[0] for d in diffs)
        # Shorten URLs for display
        mn_url_short = mn_url[:60]
        mx_url_short = mx_url[:60]
        print(f"  {METRICS[metric_key]:30s}")
        print(f"    min diff: {mn_val:+10.1f}  ({mn_url_short})")
        print(f"    max diff: {mx_val:+10.1f}  ({mx_url_short})")
        print(f"    mean diff: {mean_val:+10.1f}  n={len(diffs)}")

    for nav_key in NAV_METRICS:
        diffs = []
        for url in valid:
            le_a = mode_a[url].get("load_events", {})
            le_b = mode_b[url].get("load_events", {})
            va = le_a.get(nav_key, 0)
            vb = le_b.get(nav_key, 0)
            if va > 0 and vb > 0:
                diffs.append((va - vb, url))
        if not diffs:
            continue
        diffs.sort(key=lambda x: x[0])
        mn_val, mn_url = diffs[0]
        mx_val, mx_url = diffs[-1]
        mean_val = statistics.mean(d[0] for d in diffs)
        print(f"  {NAV_METRICS[nav_key]:30s}")
        print(f"    min diff: {mn_val:+10.1f}  ({mn_url[:60]})")
        print(f"    max diff: {mx_val:+10.1f}  ({mx_url[:60]})")
        print(f"    mean diff: {mean_val:+10.1f}  n={len(diffs)}")


def analyze_mode(strategy: str, mode_key_baseline: str, mode_key_comparison: str, label: str):
    """Load data for a strategy pair and compute diffs."""
    # Load both runs
    r0 = load_json(JOB / "run_0" / f"{strategy}_summary.json")["results"]
    r1 = load_json(JOB / "run_1" / f"{strategy}_summary.json")["results"]
    baseline = avg_runs(r0, r1, mode_key_baseline)
    comparison = avg_runs(r0, r1, mode_key_comparison)
    return baseline, comparison


def main():
    print("=" * 80)
    print("FRESH MODE ANALYSIS")
    print("=" * 80)

    # Load headless + headful from fresh strategy
    r0_fresh = load_json(JOB / "run_0" / "fresh_summary.json")["results"]
    r1_fresh = load_json(JOB / "run_1" / "fresh_summary.json")["results"]
    headless = avg_runs(r0_fresh, r1_fresh, "headless")
    headful = avg_runs(r0_fresh, r1_fresh, "headful")

    # Load headless-shell from shell_fresh strategy
    r0_shell = load_json(JOB / "run_0" / "shell_fresh_summary.json")["results"]
    r1_shell = load_json(JOB / "run_1" / "shell_fresh_summary.json")["results"]
    shell = avg_runs(r0_shell, r1_shell, "headless-shell")

    # Absolute min/max per mode
    compute_absolute_minmax(headless, "Headless (fresh)")
    compute_absolute_minmax(headful, "Headful (fresh)")
    compute_absolute_minmax(shell, "Headless-Shell (fresh)")

    # Per-URL diffs vs headful
    compute_diffs(headless, headful, "Headless", "Headful")
    compute_diffs(shell, headful, "Headless-Shell", "Headful")

    print("\n" + "=" * 80)
    print("REUSE MODE ANALYSIS")
    print("=" * 80)

    # Load reuse data
    r0_reuse = load_json(JOB / "run_0" / "reuse_summary.json")["results"]
    r1_reuse = load_json(JOB / "run_1" / "reuse_summary.json")["results"]
    hl_reuse = avg_runs(r0_reuse, r1_reuse, "headless-reuse")
    hf_reuse = avg_runs(r0_reuse, r1_reuse, "headful-reuse")

    r0_sr = load_json(JOB / "run_0" / "shell_reuse_summary.json")["results"]
    r1_sr = load_json(JOB / "run_1" / "shell_reuse_summary.json")["results"]
    shell_reuse = avg_runs(r0_sr, r1_sr, "headless-shell-reuse")

    compute_absolute_minmax(hl_reuse, "Headless-Reuse")
    compute_absolute_minmax(hf_reuse, "Headful-Reuse")
    compute_absolute_minmax(shell_reuse, "Shell-Reuse")

    compute_diffs(hl_reuse, hf_reuse, "Headless-Reuse", "Headful-Reuse")
    compute_diffs(shell_reuse, hf_reuse, "Shell-Reuse", "Headful-Reuse")


if __name__ == "__main__":
    main()
