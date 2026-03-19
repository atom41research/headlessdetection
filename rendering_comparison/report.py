"""Generate summary report from comparison results."""

import csv
import json
from dataclasses import asdict
from pathlib import Path

from rich.console import Console
from rich.table import Table

from .comparator import ComparisonResult

console = Console()


def _format_tag_diffs(diffs: dict[str, tuple[int, int]], limit: int = 10) -> str:
    """Format tag count diffs as 'tag: A→B' strings, sorted by abs diff."""
    if not diffs:
        return "-"
    sorted_diffs = sorted(diffs.items(), key=lambda x: abs(x[1][1] - x[1][0]), reverse=True)
    parts = [f"{tag}: {a}→{b}" for tag, (a, b) in sorted_diffs[:limit]]
    return ", ".join(parts)


def _format_req_diffs(diffs: dict[str, tuple[int, int]]) -> str:
    """Format request type diffs as 'type: A→B' strings."""
    if not diffs:
        return "-"
    sorted_diffs = sorted(diffs.items(), key=lambda x: abs(x[1][1] - x[1][0]), reverse=True)
    parts = [f"{rtype}: {a}→{b}" for rtype, (a, b) in sorted_diffs]
    return ", ".join(parts)


def generate_markdown_report(
    results: list[ComparisonResult],
    output_dir: Path,
) -> Path:
    """Write a markdown report sorted by severity, grouped by pair."""
    report_path = output_dir / "report.md"
    lines: list[str] = []
    lines.append("# Rendering Comparison Report\n")
    lines.append(f"**Total comparisons**: {len(results)}\n")

    # Group by pair_label
    pairs: dict[str, list[ComparisonResult]] = {}
    for r in results:
        pairs.setdefault(r.pair_label, []).append(r)

    sig_count = sum(1 for r in results if r.severity > 10)
    lines.append(f"**Significant differences (severity > 10)**: {sig_count}\n")

    # Overall category breakdown
    categories: dict[str, int] = {}
    for r in results:
        key = f"{r.pair_label}:{r.diff_type}"
        categories[key] = categories.get(key, 0) + 1
    lines.append("## Diff Categories\n")
    lines.append("| Pair | Category | Count |")
    lines.append("| --- | --- | --- |")
    for key, count in sorted(categories.items(), key=lambda x: -x[1]):
        pair, cat = key.split(":", 1)
        lines.append(f"| {pair} | {cat} | {count} |")
    lines.append("")

    # Per-pair sections
    for pair_label, pair_results in pairs.items():
        results_sorted = sorted(pair_results, key=lambda r: r.severity, reverse=True)
        a_name = results_sorted[0].mode_a_name if results_sorted else "mode_a"
        b_name = results_sorted[0].mode_b_name if results_sorted else "mode_b"

        lines.append(f"## {a_name} vs {b_name}\n")
        lines.append(f"**URLs compared**: {len(pair_results)}\n")

        sig = sum(1 for r in pair_results if r.severity > 10)
        lines.append(f"**Significant differences**: {sig}\n")

        # Results table
        lines.append(
            f"| Rank | Host | Severity | Type | Screenshot Diff | "
            f"DOM Ratio | Content Ratio | Net Req Diff | Structural | Title | Redirect |"
        )
        lines.append(
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"
        )

        for r in results_sorted:
            struct = ", ".join(r.elements_only_mode_b) if r.elements_only_mode_b else "-"
            lines.append(
                f"| {r.rank} | {r.host} | {r.severity:.1f} | {r.diff_type} | "
                f"{r.screenshot_diff_pct:.1%} | {r.dom_count_ratio:+.2f} | "
                f"{r.content_length_ratio:+.2f} | {r.network_request_diff:+d} | "
                f"{struct} | "
                f"{'Y' if r.has_title_diff else '-'} | "
                f"{'Y' if r.has_redirect_diff else '-'} |"
            )
        lines.append("")

        # Detailed sections for high-severity diffs
        sig_results = [r for r in results_sorted if r.severity > 10]
        if sig_results:
            lines.append(f"### Detailed Diffs ({a_name} vs {b_name})\n")
            for r in sig_results:
                lines.append(f"#### {r.host} (rank {r.rank}, severity {r.severity:.1f})\n")
                lines.append(f"- **Type**: {r.diff_type}")
                lines.append(f"- **Screenshot diff**: {r.screenshot_diff_pct:.1%}")
                lines.append(f"- **DOM ratio** (log2 {b_name}/{a_name}): {r.dom_count_ratio:+.2f}")
                lines.append(
                    f"- **Content ratio** (log2 {b_name}/{a_name}): "
                    f"{r.content_length_ratio:+.2f}"
                )
                lines.append(f"- **Network requests**: {r.network_request_diff:+d}")
                if r.elements_only_mode_b:
                    lines.append(
                        f"- **Elements only in {b_name}**: {', '.join(r.elements_only_mode_b)}"
                    )
                if r.elements_only_mode_a:
                    lines.append(
                        f"- **Elements only in {a_name}**: {', '.join(r.elements_only_mode_a)}"
                    )
                if r.tag_count_diffs:
                    lines.append(
                        f"- **Top tag diffs** ({a_name}→{b_name}): "
                        f"{_format_tag_diffs(r.tag_count_diffs)}"
                    )
                if r.request_type_diffs:
                    lines.append(
                        f"- **Request type diffs** ({a_name}→{b_name}): "
                        f"{_format_req_diffs(r.request_type_diffs)}"
                    )
                if r.has_title_diff:
                    lines.append("- **Title differs**")
                if r.has_redirect_diff:
                    lines.append("- **Redirect differs**")
                if r.mode_a_error:
                    lines.append(f"- **{a_name} error**: {r.mode_a_error}")
                if r.mode_b_error:
                    lines.append(f"- **{b_name} error**: {r.mode_b_error}")
                lines.append("")

    report_path.write_text("\n".join(lines))
    return report_path


def generate_csv(results: list[ComparisonResult], output_dir: Path) -> Path:
    """Write a CSV of all results for further analysis."""
    csv_path = output_dir / "results.csv"
    fieldnames = [
        "pair_label",
        "mode_a_name",
        "mode_b_name",
        "rank",
        "host",
        "url",
        "severity",
        "diff_type",
        "screenshot_diff_pct",
        "dom_count_ratio",
        "content_length_ratio",
        "network_request_diff",
        "has_structural_diff",
        "has_title_diff",
        "has_redirect_diff",
        "elements_only_mode_b",
        "elements_only_mode_a",
        "tag_count_diffs",
        "request_type_diffs",
        "mode_a_console_errors",
        "mode_b_console_errors",
        "mode_a_error",
        "mode_b_error",
    ]
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in sorted(results, key=lambda r: r.severity, reverse=True):
            row = asdict(r)
            row["elements_only_mode_b"] = ";".join(row["elements_only_mode_b"])
            row["elements_only_mode_a"] = ";".join(row["elements_only_mode_a"])
            row["tag_count_diffs"] = json.dumps(row["tag_count_diffs"])
            row["request_type_diffs"] = json.dumps(row["request_type_diffs"])
            writer.writerow({k: row[k] for k in fieldnames})
    return csv_path


def save_raw_metrics(all_metrics: list[dict], output_dir: Path) -> Path:
    """Save the raw per-URL metrics as JSON for later analysis."""
    path = output_dir / "raw_metrics.json"
    path.write_text(json.dumps(all_metrics, indent=2, default=str))
    return path


def print_summary(results: list[ComparisonResult]) -> None:
    """Print a rich table summary to console."""
    # Group by pair
    pairs: dict[str, list[ComparisonResult]] = {}
    for r in results:
        pairs.setdefault(r.pair_label, []).append(r)

    for pair_label, pair_results in pairs.items():
        a_name = pair_results[0].mode_a_name
        b_name = pair_results[0].mode_b_name

        table = Table(title=f"{a_name} vs {b_name}", show_lines=True)
        table.add_column("Rank", style="dim", justify="right")
        table.add_column("Host", style="cyan")
        table.add_column("Severity", justify="right", style="bold")
        table.add_column("Type", justify="center")
        table.add_column("Screenshot %", justify="right")
        table.add_column("DOM Ratio", justify="right")
        table.add_column("Net Req", justify="right")
        table.add_column("Tag Diffs", justify="right")

        for r in sorted(pair_results, key=lambda x: x.severity, reverse=True)[:30]:
            sev_style = (
                "bold red" if r.severity > 20 else ("yellow" if r.severity > 10 else "dim")
            )
            table.add_row(
                str(r.rank),
                r.host,
                f"[{sev_style}]{r.severity:.1f}[/{sev_style}]",
                r.diff_type,
                f"{r.screenshot_diff_pct:.1%}",
                f"{r.dom_count_ratio:+.2f}",
                f"{r.network_request_diff:+d}",
                str(len(r.tag_count_diffs)),
            )
        console.print(table)
