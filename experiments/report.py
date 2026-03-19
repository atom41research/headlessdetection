"""Generate analysis reports from collected data.

Usage:
    uv run python -m experiments.report
    uv run python -m experiments.report --page media-queries
    uv run python -m experiments.report --csv results.csv
"""

import argparse
import csv

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

from core import storage
from core.analysis import (
    analyze_binary_signals,
    analyze_timing_signals,
    analyze_chain_timing,
)
from . import config

console = Console()


def report_binary(page: str):
    """Report binary signal analysis (media queries, lazy loading)."""
    results = analyze_binary_signals(page)
    if "error" in results:
        console.print(f"[red]{results['error']}[/red]")
        return

    table = Table(title=f"Binary Signals: {page}", show_lines=True)
    table.add_column("Resource", style="cyan")
    table.add_column("Headful Rate", justify="right")
    table.add_column("Headless Rate", justify="right")
    table.add_column("Differs", justify="center")
    table.add_column("Chi2 p-value", justify="right")

    # Sort: differing probes first
    sorted_resources = sorted(results.items(), key=lambda x: (not x[1]["differs"], x[0]))

    for resource, data in sorted_resources:
        differs_style = "[bold red]YES[/bold red]" if data["differs"] else "[dim]no[/dim]"
        p_str = f"{data['chi2_p']:.4f}" if data["chi2_p"] is not None else "-"
        p_style = f"[bold]{p_str}[/bold]" if data["chi2_p"] is not None and data["chi2_p"] < 0.05 else p_str

        table.add_row(
            resource,
            f"{data['headful_rate']:.0%} ({data['headful_count']})",
            f"{data['headless_rate']:.0%} ({data['headless_count']})",
            differs_style,
            p_style,
        )

    console.print(table)
    console.print()


def report_timing(page: str, profile: str | None = None):
    """Report timing signal analysis."""
    results = analyze_timing_signals(page, profile)
    if "error" in results:
        console.print(f"[red]{results['error']}[/red]")
        return

    title = f"Timing Signals: {page}"
    if profile:
        title += f" (profile: {profile})"

    table = Table(title=title, show_lines=True)
    table.add_column("Resource", style="cyan", max_width=35)
    table.add_column("Headful (ms)", justify="right")
    table.add_column("Headless (ms)", justify="right")
    table.add_column("Diff (ms)", justify="right")
    table.add_column("Cohen's d", justify="right")
    table.add_column("Effect", justify="center")
    table.add_column("p-value", justify="right")
    table.add_column("Sig", justify="center")

    # Sort by absolute Cohen's d descending
    sorted_resources = sorted(results.items(), key=lambda x: abs(x[1]["cohens_d"]), reverse=True)

    for resource, data in sorted_resources:
        diff_ms = data["headless_mean_ms"] - data["headful_mean_ms"]
        sig = "[bold green]***[/bold green]" if data["significant"] else "[dim]-[/dim]"

        effect_style = {
            "large": "[bold red]",
            "medium": "[yellow]",
            "small": "[dim]",
            "negligible": "[dim]",
        }[data["effect_size"]]

        p_str = f"{data['mann_whitney_p']:.4f}" if data["mann_whitney_p"] is not None else "-"

        table.add_row(
            resource,
            f"{data['headful_mean_ms']:.2f} +/- {data['headful_std_ms']:.2f} (n={data['headful_n']})",
            f"{data['headless_mean_ms']:.2f} +/- {data['headless_std_ms']:.2f} (n={data['headless_n']})",
            f"{diff_ms:+.2f}",
            f"{data['cohens_d']:.3f}",
            f"{effect_style}{data['effect_size']}[/]",
            p_str,
            sig,
        )

    console.print(table)
    console.print()


def report_chains(page: str, profile: str | None = None):
    """Report CSS @import chain analysis."""
    results = analyze_chain_timing(page, profile)
    if "error" in results:
        console.print(f"[red]{results['error']}[/red]")
        return

    title = f"Chain Timing: {page}"
    if profile:
        title += f" (profile: {profile})"

    table = Table(title=title, show_lines=True)
    table.add_column("Chain", style="cyan")
    table.add_column("Mode", justify="center")
    table.add_column("Mean Total (ms)", justify="right")
    table.add_column("Median (ms)", justify="right")
    table.add_column("Std (ms)", justify="right")
    table.add_column("N", justify="right")

    for key in ("expensive_headful", "expensive_headless", "control_headful", "control_headless"):
        if key not in results:
            continue
        data = results[key]
        chain, mode = key.rsplit("_", 1)
        table.add_row(
            chain,
            mode,
            f"{data['mean_total_ms']:.2f}",
            f"{data['median_total_ms']:.2f}",
            f"{data['std_total_ms']:.2f}",
            str(data["n"]),
        )

    console.print(table)

    # Print comparison results
    for chain_id in ("expensive", "control"):
        comp_key = f"{chain_id}_comparison"
        if comp_key in results:
            comp = results[comp_key]
            sig = "SIGNIFICANT" if comp["significant"] else "not significant"
            console.print(
                f"  {chain_id} chain: p={comp['mann_whitney_p']:.4f}, "
                f"Cohen's d={comp['cohens_d']:.3f} [{sig}]"
            )
    console.print()


def export_csv(output_path: str):
    """Export all session data to CSV."""
    sessions = storage.get_all_sessions()

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["session_id", "mode", "profile", "page", "resource", "timestamp_ns", "elapsed_ms"])

        for s in sessions:
            reqs = storage.get_session_requests(s["session_id"])
            base_ts = reqs[0]["timestamp_ns"] if reqs else 0
            for req in reqs:
                elapsed = (req["timestamp_ns"] - base_ts) / 1_000_000
                writer.writerow([
                    s["session_id"],
                    s["mode"],
                    s["profile"],
                    s["page"],
                    req["resource"],
                    req["timestamp_ns"],
                    f"{elapsed:.3f}",
                ])

    console.print(f"[green]Exported to {output_path}[/green]")


def main():
    storage.init_db()

    parser = argparse.ArgumentParser(description="Headless detection analysis report")
    parser.add_argument("--page", default=None, help="Analyze a specific page (default: all)")
    parser.add_argument("--profile", default=None, help="Filter by profile (default/matched)")
    parser.add_argument("--csv", default=None, help="Export raw data to CSV")
    args = parser.parse_args()

    if args.csv:
        export_csv(args.csv)
        return

    pages = [args.page] if args.page else config.PAGES

    console.print(Panel("[bold]Headless Browser Detection - Analysis Report[/bold]", style="blue"))
    console.print()

    for page in pages:
        sessions = storage.get_sessions_by_page(page)
        if not sessions:
            console.print(f"[dim]No data for page: {page}[/dim]")
            continue

        console.print(f"[bold underline]{page}[/bold underline] ({len(sessions)} sessions)")
        console.print()

        # Binary analysis for media-queries and lazy-loading
        if page in ("media-queries", "lazy-loading", "combined", "scrollbar-width"):
            report_binary(page)

        # Timing analysis
        if page in ("import-chains", "background-chains", "font-loading", "combined"):
            for profile in ([args.profile] if args.profile else ["default", "matched"]):
                report_timing(page, profile)

        # Chain-specific analysis
        if page in ("import-chains", "combined"):
            for profile in ([args.profile] if args.profile else ["default", "matched"]):
                report_chains(page, profile)

        console.rule()


if __name__ == "__main__":
    main()
