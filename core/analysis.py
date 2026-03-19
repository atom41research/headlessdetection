"""Statistical analysis of headless detection data.

Includes probe-level analysis (binary signals, timing signals, CSS @import chain
timing) and server-side signal analysis (TLS fingerprints, header order/values,
connection patterns).  Supports three-way comparison: headful vs headless vs
headless-shell.
"""

import json
from collections import Counter, defaultdict

import numpy as np
from scipy import stats

from core import storage


# ---------------------------------------------------------------------------
# Probe analysis helpers
# ---------------------------------------------------------------------------

def compute_deltas(requests: list[dict]) -> dict[str, float]:
    """Compute inter-request deltas in milliseconds from a session's requests."""
    if len(requests) < 2:
        return {}

    base_ts = requests[0]["timestamp_ns"]
    deltas = {}
    prev_ts = base_ts

    for req in requests[1:]:
        ts = req["timestamp_ns"]
        delta_ms = (ts - prev_ts) / 1_000_000
        deltas[req["resource"]] = delta_ms
        prev_ts = ts

    return deltas


def compute_elapsed(requests: list[dict]) -> dict[str, float]:
    """Compute elapsed time from first request for each resource (ms)."""
    if not requests:
        return {}

    base_ts = requests[0]["timestamp_ns"]
    return {
        req["resource"]: (req["timestamp_ns"] - base_ts) / 1_000_000
        for req in requests
    }


def get_resource_set(requests: list[dict]) -> set[str]:
    """Get the set of resource names requested in a session."""
    return {req["resource"] for req in requests}


# ---------------------------------------------------------------------------
# Probe analysis
# ---------------------------------------------------------------------------

def analyze_binary_signals(page: str) -> dict:
    """Analyze binary signals (which resources were requested) for a page.

    Returns per-resource counts for headful vs headless, plus chi-squared test results.
    """
    sessions = storage.get_sessions_by_page(page)
    if not sessions:
        return {"error": "No data"}

    headful_sets = []
    headless_sets = []

    for s in sessions:
        reqs = storage.get_session_requests(s["session_id"])
        resources = get_resource_set(reqs)
        if s["mode"] == "headful":
            headful_sets.append(resources)
        else:
            headless_sets.append(resources)

    if not headful_sets or not headless_sets:
        return {"error": "Need both headful and headless data"}

    # Get all unique resources across all sessions
    all_resources = set()
    for rs in headful_sets + headless_sets:
        all_resources.update(rs)

    results = {}
    for resource in sorted(all_resources):
        headful_count = sum(1 for rs in headful_sets if resource in rs)
        headless_count = sum(1 for rs in headless_sets if resource in rs)
        headful_total = len(headful_sets)
        headless_total = len(headless_sets)

        headful_rate = headful_count / headful_total if headful_total else 0
        headless_rate = headless_count / headless_total if headless_total else 0

        # Chi-squared test if there's variation
        differs = abs(headful_rate - headless_rate) > 0.01
        chi2_p = None
        if differs and headful_total > 1 and headless_total > 1:
            table = [
                [headful_count, headful_total - headful_count],
                [headless_count, headless_total - headless_count],
            ]
            if all(sum(row) > 0 for row in table) and all(sum(col) > 0 for col in zip(*table)):
                chi2, p, _, _ = stats.chi2_contingency(table)
                chi2_p = p

        results[resource] = {
            "headful_rate": headful_rate,
            "headless_rate": headless_rate,
            "headful_count": f"{headful_count}/{headful_total}",
            "headless_count": f"{headless_count}/{headless_total}",
            "differs": differs,
            "chi2_p": chi2_p,
        }

    return results


def analyze_timing_signals(page: str, profile: str | None = None) -> dict:
    """Analyze timing signals (inter-request deltas) for a page.

    Returns per-resource timing statistics + Mann-Whitney U test + Cohen's d.
    """
    sessions = storage.get_sessions_by_page(page)
    if not sessions:
        return {"error": "No data"}

    if profile:
        sessions = [s for s in sessions if s["profile"] == profile]

    headful_timings: dict[str, list[float]] = {}
    headless_timings: dict[str, list[float]] = {}

    for s in sessions:
        reqs = storage.get_session_requests(s["session_id"])
        elapsed = compute_elapsed(reqs)
        target = headful_timings if s["mode"] == "headful" else headless_timings

        for resource, ms in elapsed.items():
            target.setdefault(resource, []).append(ms)

    # Compute statistics for resources present in both modes
    all_resources = set(headful_timings.keys()) & set(headless_timings.keys())
    results = {}

    for resource in sorted(all_resources):
        hf = np.array(headful_timings[resource])
        hl = np.array(headless_timings[resource])

        # Mann-Whitney U test
        u_stat, u_p = stats.mannwhitneyu(hf, hl, alternative="two-sided") if len(hf) > 1 and len(hl) > 1 else (None, None)

        # Cohen's d effect size
        pooled_std = np.sqrt((np.std(hf, ddof=1)**2 + np.std(hl, ddof=1)**2) / 2)
        cohens_d = (np.mean(hl) - np.mean(hf)) / pooled_std if pooled_std > 0 else 0.0

        results[resource] = {
            "headful_mean_ms": float(np.mean(hf)),
            "headful_median_ms": float(np.median(hf)),
            "headful_std_ms": float(np.std(hf, ddof=1)) if len(hf) > 1 else 0.0,
            "headful_n": len(hf),
            "headless_mean_ms": float(np.mean(hl)),
            "headless_median_ms": float(np.median(hl)),
            "headless_std_ms": float(np.std(hl, ddof=1)) if len(hl) > 1 else 0.0,
            "headless_n": len(hl),
            "mann_whitney_p": float(u_p) if u_p is not None else None,
            "cohens_d": float(cohens_d),
            "significant": u_p is not None and u_p < 0.05,
            "effect_size": (
                "large" if abs(cohens_d) >= 0.8
                else "medium" if abs(cohens_d) >= 0.5
                else "small" if abs(cohens_d) >= 0.2
                else "negligible"
            ),
        }

    return results


def analyze_chain_timing(page: str, profile: str | None = None) -> dict:
    """Analyze CSS @import chain timing specifically.

    Computes inter-step deltas for the chain and compares expensive vs control chains.
    """
    sessions = storage.get_sessions_by_page(page)
    if not sessions:
        return {"error": "No data"}

    if profile:
        sessions = [s for s in sessions if s["profile"] == profile]

    results = {"expensive": {"headful": [], "headless": []}, "control": {"headful": [], "headless": []}}

    for s in sessions:
        reqs = storage.get_session_requests(s["session_id"])

        for chain_id in ("expensive", "control"):
            # Extract chain steps in order
            chain_reqs = [
                r for r in reqs
                if r["resource"].startswith(f"chain-{chain_id}-step-")
            ]
            chain_reqs.sort(key=lambda r: int(r["resource"].split("-")[-1]))

            if len(chain_reqs) < 2:
                continue

            # Compute inter-step deltas
            deltas = []
            for i in range(1, len(chain_reqs)):
                delta_ms = (chain_reqs[i]["timestamp_ns"] - chain_reqs[i - 1]["timestamp_ns"]) / 1_000_000
                deltas.append(delta_ms)

            total_ms = (chain_reqs[-1]["timestamp_ns"] - chain_reqs[0]["timestamp_ns"]) / 1_000_000

            results[chain_id][s["mode"]].append({
                "step_deltas_ms": deltas,
                "total_ms": total_ms,
                "steps": len(chain_reqs),
            })

    # Compute summary statistics
    summary = {}
    for chain_id in ("expensive", "control"):
        for mode in ("headful", "headless"):
            runs = results[chain_id][mode]
            if not runs:
                continue
            totals = [r["total_ms"] for r in runs]
            key = f"{chain_id}_{mode}"
            summary[key] = {
                "mean_total_ms": float(np.mean(totals)),
                "median_total_ms": float(np.median(totals)),
                "std_total_ms": float(np.std(totals, ddof=1)) if len(totals) > 1 else 0.0,
                "n": len(runs),
            }

    # Compare expensive headful vs headless
    for chain_id in ("expensive", "control"):
        hf_totals = [r["total_ms"] for r in results[chain_id]["headful"]]
        hl_totals = [r["total_ms"] for r in results[chain_id]["headless"]]
        if len(hf_totals) > 1 and len(hl_totals) > 1:
            u_stat, u_p = stats.mannwhitneyu(hf_totals, hl_totals, alternative="two-sided")
            pooled_std = np.sqrt((np.std(hf_totals, ddof=1)**2 + np.std(hl_totals, ddof=1)**2) / 2)
            d = (np.mean(hl_totals) - np.mean(hf_totals)) / pooled_std if pooled_std > 0 else 0
            summary[f"{chain_id}_comparison"] = {
                "mann_whitney_p": float(u_p),
                "cohens_d": float(d),
                "significant": u_p < 0.05,
            }

    return summary


# ---------------------------------------------------------------------------
# Server-signal helpers
# ---------------------------------------------------------------------------

def _get_captures(session_id: str) -> list[dict]:
    """Get header captures from DB, parsing JSON fields."""
    rows = storage.get_header_captures(session_id)
    captures = []
    for r in rows:
        cap = dict(r)
        # Parse JSON-encoded fields
        for field in ("header_names_ordered", "header_values"):
            val = cap.get(field)
            if isinstance(val, str):
                try:
                    cap[field] = json.loads(val)
                except (json.JSONDecodeError, TypeError):
                    pass
        cap["path"] = cap.get("resource", cap.get("path", ""))
        captures.append(cap)
    return captures


def _levenshtein(s1: list, s2: list) -> int:
    """Compute Levenshtein edit distance between two sequences."""
    if len(s1) < len(s2):
        return _levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)

    prev_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (c1 != c2)
            curr_row.append(min(insertions, deletions, substitutions))
        prev_row = curr_row

    return prev_row[-1]


# ---------------------------------------------------------------------------
# Server-signal analysis
# ---------------------------------------------------------------------------

def analyze_tls_fingerprints() -> dict:
    """Compare TLS fingerprints across modes.

    Returns whether JA3/JA4 differ between headful, headless, and headless-shell.
    """
    all_fps = storage.get_tls_fingerprints()
    if not all_fps:
        return {"error": "No TLS fingerprint data"}

    sessions_map = {s["session_id"]: s for s in storage.get_all_sessions()}

    mode_ja3: dict[str, list[str]] = defaultdict(list)
    mode_ja4: dict[str, list[str]] = defaultdict(list)

    for fp in all_fps:
        sid = fp.get("session_id")
        session = sessions_map.get(sid) if sid else None
        if not session:
            continue
        mode = session["mode"]
        mode_ja3[mode].append(fp["ja3_hash"])
        mode_ja4[mode].append(fp["ja4_string"])

    def _match(a: list, b: list) -> bool | None:
        if a and b:
            return set(a) == set(b)
        return None

    result = {}
    for mode in ("headful", "headless", "headless-shell"):
        prefix = mode.replace("-", "_")
        result[f"{prefix}_ja3_unique"] = list(set(mode_ja3.get(mode, [])))
        result[f"{prefix}_ja4_unique"] = list(set(mode_ja4.get(mode, [])))
        result[f"{prefix}_count"] = len(mode_ja3.get(mode, []))

    # Pairwise matches
    result["ja3_match"] = _match(mode_ja3.get("headful", []), mode_ja3.get("headless", []))
    result["ja4_match"] = _match(mode_ja4.get("headful", []), mode_ja4.get("headless", []))
    result["ja3_match_hl_vs_shell"] = _match(mode_ja3.get("headless", []), mode_ja3.get("headless-shell", []))
    result["ja4_match_hl_vs_shell"] = _match(mode_ja4.get("headless", []), mode_ja4.get("headless-shell", []))

    # Backward compat
    result["headful_ja3_unique"] = result["headful_ja3_unique"]
    result["headless_ja3_unique"] = result["headless_ja3_unique"]
    result["headful_ja4_unique"] = result["headful_ja4_unique"]
    result["headless_ja4_unique"] = result["headless_ja4_unique"]
    result["headful_count"] = result["headful_count"]
    result["headless_count"] = result["headless_count"]

    return result


def analyze_header_order(page: str | None = None) -> dict:
    """Compare header name ordering across modes.

    Uses normalized edit distance to quantify ordering differences.
    """
    sessions = storage.get_all_sessions()
    if page:
        sessions = [s for s in sessions if page in s.get("page", "")]

    mode_orders: dict[str, list[tuple]] = defaultdict(list)

    for s in sessions:
        captures = _get_captures(s["session_id"])
        for cap in captures:
            names = cap.get("header_names_ordered", [])
            if not names:
                continue
            path = cap.get("path", "")
            if "/probe-" in path or path.endswith((".html", "/")):
                mode_orders[s["mode"]].append(tuple(names))

    modes_present = [m for m in ("headful", "headless", "headless-shell") if mode_orders.get(m)]
    if len(modes_present) < 2:
        return {"error": "Need at least two modes with header data"}

    result = {}

    for mode in ("headful", "headless", "headless-shell"):
        prefix = mode.replace("-", "_")
        orders = mode_orders.get(mode, [])
        if orders:
            common = Counter(orders).most_common(1)[0]
            result[f"{prefix}_most_common_order"] = list(common[0])
            result[f"{prefix}_order_count"] = common[1]
            result[f"{prefix}_total"] = len(orders)
            result[f"{prefix}_unique_orderings"] = len(set(orders))
        else:
            result[f"{prefix}_total"] = 0

    # Pairwise comparisons
    def _compare_orders(mode_a: str, mode_b: str, label: str):
        a_orders = mode_orders.get(mode_a, [])
        b_orders = mode_orders.get(mode_b, [])
        if not a_orders or not b_orders:
            result[f"exact_match_{label}"] = None
            return
        a_common = Counter(a_orders).most_common(1)[0][0]
        b_common = Counter(b_orders).most_common(1)[0][0]
        exact = a_common == b_common
        edit_dist = _levenshtein(list(a_common), list(b_common))
        max_len = max(len(a_common), len(b_common))
        result[f"exact_match_{label}"] = exact
        result[f"edit_distance_{label}"] = edit_dist
        result[f"normalized_edit_distance_{label}"] = round(edit_dist / max_len, 4) if max_len else 0

    _compare_orders("headful", "headless", "hf_vs_hl")
    _compare_orders("headless", "headless-shell", "hl_vs_shell")

    # Backward compat
    result["exact_match"] = result.get("exact_match_hf_vs_hl")
    result["edit_distance"] = result.get("edit_distance_hf_vs_hl", 0)
    result["normalized_edit_distance"] = result.get("normalized_edit_distance_hf_vs_hl", 0)
    result["headful_most_common_order"] = result.get("headful_most_common_order", [])
    result["headful_order_count"] = result.get("headful_order_count", 0)
    result["headful_total"] = result.get("headful_total", 0)
    result["headless_most_common_order"] = result.get("headless_most_common_order", [])
    result["headless_order_count"] = result.get("headless_order_count", 0)
    result["headless_total"] = result.get("headless_total", 0)
    result["headful_unique_orderings"] = result.get("headful_unique_orderings", 0)
    result["headless_unique_orderings"] = result.get("headless_unique_orderings", 0)

    return result


def analyze_header_values(page: str | None = None) -> dict:
    """Compare specific header values across modes."""
    sessions = storage.get_all_sessions()
    if page:
        sessions = [s for s in sessions if page in s.get("page", "")]

    interesting_headers = [
        "accept", "accept-language", "accept-encoding",
        "sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform",
        "sec-fetch-dest", "sec-fetch-mode", "sec-fetch-site", "sec-fetch-user",
        "upgrade-insecure-requests", "connection",
    ]

    mode_values: dict[str, dict[str, list[str]]] = {
        mode: {h: [] for h in interesting_headers}
        for mode in ("headful", "headless", "headless-shell")
    }

    for s in sessions:
        mode = s["mode"]
        if mode not in mode_values:
            continue
        captures = _get_captures(s["session_id"])
        for cap in captures:
            vals = cap.get("header_values", {})
            path = cap.get("path", "")
            if "/probe-" not in path:
                continue
            for h in interesting_headers:
                if h in vals:
                    mode_values[mode][h].append(vals[h])

    results = {}
    for h in interesting_headers:
        hf = mode_values["headful"][h]
        hl = mode_values["headless"][h]
        sh = mode_values["headless-shell"][h]

        hf_unique = list(set(hf))
        hl_unique = list(set(hl))
        sh_unique = list(set(sh))

        def _match(a, b):
            if a and b:
                return set(a) == set(b)
            return None

        results[h] = {
            "headful_values": hf_unique,
            "headless_values": hl_unique,
            "headless_shell_values": sh_unique,
            "match": _match(hf, hl),
            "match_hl_vs_shell": _match(hl, sh),
            "headful_count": len(hf),
            "headless_count": len(hl),
            "headless_shell_count": len(sh),
        }

    return results


def analyze_connection_patterns(page: str | None = None) -> dict:
    """Compare connection patterns (unique ports = unique TCP connections)."""
    sessions = storage.get_all_sessions()
    if page:
        sessions = [s for s in sessions if page in s.get("page", "")]

    mode_port_counts: dict[str, list[int]] = defaultdict(list)

    for s in sessions:
        captures = _get_captures(s["session_id"])
        ports = set()
        for cap in captures:
            port = cap.get("client_port")
            if port:
                ports.add(port)
        if ports:
            mode_port_counts[s["mode"]].append(len(ports))

    modes_present = [m for m in ("headful", "headless", "headless-shell") if mode_port_counts.get(m)]
    if len(modes_present) < 2:
        return {"error": "Need at least two modes with connection data"}

    result = {}

    for mode in ("headful", "headless", "headless-shell"):
        prefix = mode.replace("-", "_")
        counts = mode_port_counts.get(mode, [])
        if counts:
            arr = np.array(counts, dtype=float)
            result[f"{prefix}_mean_connections"] = float(np.mean(arr))
            result[f"{prefix}_std"] = float(np.std(arr, ddof=1)) if len(arr) > 1 else 0
            result[f"{prefix}_n"] = len(counts)
        else:
            result[f"{prefix}_n"] = 0

    def _compare_connections(mode_a: str, mode_b: str, label: str):
        a = mode_port_counts.get(mode_a, [])
        b = mode_port_counts.get(mode_b, [])
        if len(a) < 2 or len(b) < 2:
            result[f"mann_whitney_p_{label}"] = None
            result[f"cohens_d_{label}"] = 0.0
            result[f"significant_{label}"] = False
            return
        arr_a = np.array(a, dtype=float)
        arr_b = np.array(b, dtype=float)
        u_stat, u_p = stats.mannwhitneyu(arr_a, arr_b, alternative="two-sided")
        pooled_std = np.sqrt((np.std(arr_a, ddof=1)**2 + np.std(arr_b, ddof=1)**2) / 2)
        cohens_d = float((np.mean(arr_b) - np.mean(arr_a)) / pooled_std) if pooled_std > 0 else 0.0
        result[f"mann_whitney_p_{label}"] = float(u_p)
        result[f"cohens_d_{label}"] = cohens_d
        result[f"significant_{label}"] = u_p < 0.05

    _compare_connections("headful", "headless", "hf_vs_hl")
    _compare_connections("headless", "headless-shell", "hl_vs_shell")

    # Backward compat
    result["headful_mean_connections"] = result.get("headful_mean_connections", 0)
    result["headful_std"] = result.get("headful_std", 0)
    result["headless_mean_connections"] = result.get("headless_mean_connections", 0)
    result["headless_std"] = result.get("headless_std", 0)
    result["mann_whitney_p"] = result.get("mann_whitney_p_hf_vs_hl")
    result["cohens_d"] = result.get("cohens_d_hf_vs_hl", 0)
    result["significant"] = result.get("significant_hf_vs_hl", False)
    result["headful_n"] = result.get("headful_n", 0)
    result["headless_n"] = result.get("headless_n", 0)

    return result
