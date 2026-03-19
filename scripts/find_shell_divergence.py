"""Find URLs where headless-shell renders differently from headless/headful.

Analyzes content_length, HTTP status, final_url, and error divergence across
the 3 Chrome modes using existing benchmark data.
"""

import csv
import json
import statistics
from pathlib import Path

JOB = Path("bench/results/job_20260308_202325")
RENDERING_CSV = Path("rendering_comparison/output/results.csv")

# Divergence thresholds
CONTENT_RATIO_THRESHOLD = 0.20  # 20% content length difference


def load_runs(path: Path) -> list[dict]:
    with open(path) as f:
        return json.load(f)["runs"]


def avg_by_url(runs_list: list[list[dict]], mode: str) -> dict[str, dict]:
    """Average content_length, status, etc. across multiple run files for one mode."""
    by_url: dict[str, list[dict]] = {}
    for runs in runs_list:
        for r in runs:
            if r["mode"] == mode:
                by_url.setdefault(r["url"], []).append(r)

    result = {}
    for url, entries in by_url.items():
        valid = [e for e in entries if not e.get("error")]
        if not valid:
            result[url] = {
                "content_length": 0,
                "http_status": 0,
                "final_url": "",
                "error": entries[0].get("error", ""),
                "timed_out": any(e.get("timed_out") for e in entries),
            }
            continue

        cls = [e["content_length"] for e in valid if e.get("content_length", -1) >= 0]
        statuses = [e.get("http_status", 0) for e in valid]
        finals = [e.get("final_url", "") for e in valid if e.get("final_url")]

        result[url] = {
            "content_length": statistics.mean(cls) if cls else 0,
            "http_status": statuses[0] if statuses else 0,
            "final_url": finals[0] if finals else "",
            "error": "",
            "timed_out": any(e.get("timed_out") for e in valid),
        }
    return result


def content_divergence(a: float, b: float) -> float:
    """Compute relative divergence between two content lengths."""
    if a <= 0 and b <= 0:
        return 0.0
    mx = max(a, b)
    if mx == 0:
        return 0.0
    return abs(a - b) / mx


def load_rendering_csv() -> dict[str, dict]:
    """Load rendering comparison results keyed by URL."""
    if not RENDERING_CSV.exists():
        return {}
    result = {}
    with open(RENDERING_CSV) as f:
        for row in csv.DictReader(f):
            result[row["url"]] = row
    return result


def main():
    # Load fresh mode data from both runs
    run_files = []
    for run_dir in ["run_0", "run_1"]:
        run_files.append({
            "headless": load_runs(JOB / run_dir / "runs_headless.json"),
            "headful": load_runs(JOB / run_dir / "runs_headful.json"),
            "headless-shell": load_runs(JOB / run_dir / "runs_headless-shell.json"),
        })

    # Also load reuse mode
    reuse_files = []
    for run_dir in ["run_0", "run_1"]:
        reuse_files.append({
            "headless-reuse": load_runs(JOB / run_dir / "runs_headless-reuse.json"),
            "headful-reuse": load_runs(JOB / run_dir / "runs_headful-reuse.json"),
            "headless-shell-reuse": load_runs(JOB / run_dir / "runs_headless-shell-reuse.json"),
        })

    # Average across runs per URL per mode (fresh)
    hl = avg_by_url([rf["headless"] for rf in run_files], "headless")
    hf = avg_by_url([rf["headful"] for rf in run_files], "headful")
    shell = avg_by_url([rf["headless-shell"] for rf in run_files], "headless-shell")

    # Average across runs per URL per mode (reuse)
    hl_r = avg_by_url([rf["headless-reuse"] for rf in reuse_files], "headless-reuse")
    hf_r = avg_by_url([rf["headful-reuse"] for rf in reuse_files], "headful-reuse")
    shell_r = avg_by_url([rf["headless-shell-reuse"] for rf in reuse_files], "headless-shell-reuse")

    # Load rendering comparison for cross-reference
    rendering = load_rendering_csv()

    # Analyze fresh mode divergence
    all_urls = set(hl) & set(hf) & set(shell)
    print(f"Fresh mode: {len(all_urls)} URLs with all 3 modes")

    divergent = []
    for url in sorted(all_urls):
        s = shell[url]
        h = hl[url]
        f_ = hf[url]

        # Skip if any mode had errors
        if s["error"] or h["error"] or f_["error"]:
            continue
        if s["timed_out"] or h["timed_out"] or f_["timed_out"]:
            continue

        cl_shell = s["content_length"]
        cl_hl = h["content_length"]
        cl_hf = f_["content_length"]

        div_vs_hl = content_divergence(cl_shell, cl_hl)
        div_vs_hf = content_divergence(cl_shell, cl_hf)
        max_div = max(div_vs_hl, div_vs_hf)

        # Check for redirect divergence
        redirect_diff = (
            s["final_url"] != h["final_url"]
            or s["final_url"] != f_["final_url"]
        ) if s["final_url"] and h["final_url"] and f_["final_url"] else False

        # Check for status divergence
        status_diff = (
            s["http_status"] != h["http_status"]
            or s["http_status"] != f_["http_status"]
        )

        # Cross-reference with rendering comparison
        rend = rendering.get(url, {})
        rend_severity = float(rend.get("severity", 0)) if rend else 0
        rend_type = rend.get("diff_type", "") if rend else ""

        if max_div > 0 or redirect_diff or status_diff:
            divergent.append({
                "url": url,
                "cl_shell": cl_shell,
                "cl_hl": cl_hl,
                "cl_hf": cl_hf,
                "div_vs_hl": div_vs_hl,
                "div_vs_hf": div_vs_hf,
                "max_div": max_div,
                "redirect_diff": redirect_diff,
                "status_diff": status_diff,
                "status_shell": s["http_status"],
                "status_hl": h["http_status"],
                "status_hf": f_["http_status"],
                "final_shell": s["final_url"],
                "final_hl": h["final_url"],
                "final_hf": f_["final_url"],
                "rend_severity": rend_severity,
                "rend_type": rend_type,
            })

    divergent.sort(key=lambda x: x["max_div"], reverse=True)

    # Print report
    print(f"\n{'=' * 100}")
    print("FRESH MODE: Shell Rendering Divergence Report")
    print(f"{'=' * 100}")

    # Summary stats
    n_total = len(divergent)
    n_gt20 = sum(1 for d in divergent if d["max_div"] > 0.20)
    n_gt50 = sum(1 for d in divergent if d["max_div"] > 0.50)
    n_gt80 = sum(1 for d in divergent if d["max_div"] > 0.80)
    n_redirect = sum(1 for d in divergent if d["redirect_diff"])
    n_status = sum(1 for d in divergent if d["status_diff"])
    n_zero = sum(1 for d in divergent if d["max_div"] == 0)
    print(f"\nURLs with any divergence: {n_total}")
    print(f"  >20% content divergence: {n_gt20}")
    print(f"  >50% content divergence: {n_gt50}")
    print(f"  >80% content divergence: {n_gt80}")
    print(f"  Redirect divergence:     {n_redirect}")
    print(f"  Status code divergence:  {n_status}")
    print(f"  Zero content divergence: {n_zero}")

    # Top divergent URLs
    print(f"\n{'─' * 100}")
    print("Top URLs by content divergence (shell vs headless/headful)")
    print(f"{'─' * 100}")
    print(f"{'URL':<65} {'Shell':>7} {'HL':>7} {'HF':>7} {'vsHL':>6} {'vsHF':>6} {'Rend':>6} {'Type':<15}")
    print(f"{'─' * 65} {'─' * 7} {'─' * 7} {'─' * 7} {'─' * 6} {'─' * 6} {'─' * 6} {'─' * 15}")

    for d in divergent[:80]:
        if d["max_div"] < 0.01 and not d["redirect_diff"] and not d["status_diff"]:
            continue
        url_short = d["url"][:64]
        rtype = d["rend_type"][:14] if d["rend_type"] else "-"
        flags = ""
        if d["redirect_diff"]:
            flags += " REDIR"
        if d["status_diff"]:
            flags += f" STATUS({d['status_shell']}/{d['status_hl']}/{d['status_hf']})"

        print(
            f"{url_short:<65} "
            f"{d['cl_shell']:>7.0f} {d['cl_hl']:>7.0f} {d['cl_hf']:>7.0f} "
            f"{d['div_vs_hl']:>5.1%} {d['div_vs_hf']:>5.1%} "
            f"{d['rend_severity']:>5.1f} {rtype:<15}"
            f"{flags}"
        )

    # Redirect divergence details
    redirect_divs = [d for d in divergent if d["redirect_diff"]]
    if redirect_divs:
        print(f"\n{'─' * 100}")
        print("Redirect Divergence Details")
        print(f"{'─' * 100}")
        for d in redirect_divs[:20]:
            print(f"\n  {d['url']}")
            print(f"    Shell:   {d['final_shell'][:90]}")
            print(f"    HL:      {d['final_hl'][:90]}")
            print(f"    HF:      {d['final_hf'][:90]}")

    # Status divergence details
    status_divs = [d for d in divergent if d["status_diff"]]
    if status_divs:
        print(f"\n{'─' * 100}")
        print("HTTP Status Divergence Details")
        print(f"{'─' * 100}")
        for d in status_divs[:20]:
            print(f"  {d['url'][:70]}  Shell={d['status_shell']} HL={d['status_hl']} HF={d['status_hf']}")

    # ── Reuse mode analysis ──
    all_reuse = set(hl_r) & set(hf_r) & set(shell_r)
    print(f"\n\n{'=' * 100}")
    print(f"REUSE MODE: Shell Rendering Divergence Report ({len(all_reuse)} URLs)")
    print(f"{'=' * 100}")

    reuse_div = []
    for url in sorted(all_reuse):
        s = shell_r[url]
        h = hl_r[url]
        f_ = hf_r[url]
        if s["error"] or h["error"] or f_["error"]:
            continue
        if s["timed_out"] or h["timed_out"] or f_["timed_out"]:
            continue

        cl_shell = s["content_length"]
        cl_hl = h["content_length"]
        cl_hf = f_["content_length"]

        div_vs_hl = content_divergence(cl_shell, cl_hl)
        div_vs_hf = content_divergence(cl_shell, cl_hf)
        max_div = max(div_vs_hl, div_vs_hf)

        if max_div > 0.01:
            reuse_div.append({
                "url": url,
                "cl_shell": cl_shell,
                "cl_hl": cl_hl,
                "cl_hf": cl_hf,
                "div_vs_hl": div_vs_hl,
                "div_vs_hf": div_vs_hf,
                "max_div": max_div,
            })

    reuse_div.sort(key=lambda x: x["max_div"], reverse=True)
    n_r20 = sum(1 for d in reuse_div if d["max_div"] > 0.20)
    n_r50 = sum(1 for d in reuse_div if d["max_div"] > 0.50)
    print(f"\nURLs with >1% content divergence: {len(reuse_div)}")
    print(f"  >20% content divergence: {n_r20}")
    print(f"  >50% content divergence: {n_r50}")

    if reuse_div:
        print(f"\n{'URL':<65} {'Shell':>7} {'HL':>7} {'HF':>7} {'vsHL':>6} {'vsHF':>6}")
        print(f"{'─' * 65} {'─' * 7} {'─' * 7} {'─' * 7} {'─' * 6} {'─' * 6}")
        for d in reuse_div[:40]:
            print(
                f"{d['url'][:64]:<65} "
                f"{d['cl_shell']:>7.0f} {d['cl_hl']:>7.0f} {d['cl_hf']:>7.0f} "
                f"{d['div_vs_hl']:>5.1%} {d['div_vs_hf']:>5.1%}"
            )


if __name__ == "__main__":
    main()
