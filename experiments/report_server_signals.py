"""Report generator for server-side signal analysis.

Usage:
    uv run python -m experiments.report_server_signals
"""

from rich.console import Console
from rich.table import Table

from core.analysis import (
    analyze_tls_fingerprints,
    analyze_header_order,
    analyze_header_values,
    analyze_connection_patterns,
)

console = Console()

_MATCH = lambda m: "[green]YES[/green]" if m else "[red]NO[/red]" if m is not None else "[dim]N/A[/dim]"


def report_tls():
    console.print("\n[bold underline]TLS Fingerprint Analysis[/bold underline]\n")
    result = analyze_tls_fingerprints()

    if "error" in result:
        console.print(f"[yellow]{result['error']}[/yellow]")
        return

    table = Table(title="JA3/JA4 Comparison")
    table.add_column("Metric")
    table.add_column("Headful")
    table.add_column("Headless")
    table.add_column("Headless-Shell")
    table.add_column("HF=HL?")
    table.add_column("HL=Shell?")

    hf_ja3 = ", ".join(result.get("headful_ja3_unique", [])[:3])
    hl_ja3 = ", ".join(result.get("headless_ja3_unique", [])[:3])
    sh_ja3 = ", ".join(result.get("headless_shell_ja3_unique", [])[:3])
    hf_ja4 = ", ".join(result.get("headful_ja4_unique", [])[:3])
    hl_ja4 = ", ".join(result.get("headless_ja4_unique", [])[:3])
    sh_ja4 = ", ".join(result.get("headless_shell_ja4_unique", [])[:3])

    table.add_row(
        "JA3 hash",
        hf_ja3 or "N/A", hl_ja3 or "N/A", sh_ja3 or "N/A",
        _MATCH(result.get("ja3_match")),
        _MATCH(result.get("ja3_match_hl_vs_shell")),
    )
    table.add_row(
        "JA4 string",
        hf_ja4 or "N/A", hl_ja4 or "N/A", sh_ja4 or "N/A",
        _MATCH(result.get("ja4_match")),
        _MATCH(result.get("ja4_match_hl_vs_shell")),
    )
    table.add_row(
        "Sample count",
        str(result.get("headful_count", 0)),
        str(result.get("headless_count", 0)),
        str(result.get("headless_shell_count", 0)),
        "", "",
    )

    console.print(table)


def report_header_order():
    console.print("\n[bold underline]Header Order Analysis[/bold underline]\n")

    for page in ["probe-header-order", "probe-tls-fingerprint"]:
        result = analyze_header_order(page)
        if "error" in result:
            console.print(f"[yellow]{page}: {result['error']}[/yellow]")
            continue

        console.print(f"  [bold]{page}[/bold]:")

        # Headful vs Headless
        match_hf_hl = result.get("exact_match_hf_vs_hl")
        if match_hf_hl is not None:
            match_str = "[green]IDENTICAL[/green]" if match_hf_hl else (
                f"[red]DIFFERENT[/red] (edit distance: {result.get('edit_distance_hf_vs_hl', '?')}, "
                f"normalized: {result.get('normalized_edit_distance_hf_vs_hl', '?')})"
            )
            console.print(f"    Headful vs Headless: {match_str}")

        # Headless vs Headless-Shell
        match_hl_sh = result.get("exact_match_hl_vs_shell")
        if match_hl_sh is not None:
            match_str = "[green]IDENTICAL[/green]" if match_hl_sh else (
                f"[red]DIFFERENT[/red] (edit distance: {result.get('edit_distance_hl_vs_shell', '?')}, "
                f"normalized: {result.get('normalized_edit_distance_hl_vs_shell', '?')})"
            )
            console.print(f"    Headless vs Shell:   {match_str}")

        for mode, prefix in [("Headful", "headful"), ("Headless", "headless"), ("Shell", "headless_shell")]:
            total = result.get(f"{prefix}_total", 0)
            if total:
                unique = result.get(f"{prefix}_unique_orderings", 0)
                console.print(f"    {mode:12s} {unique} unique orderings from {total} samples")

        # Show differing orders
        if not result.get("exact_match_hl_vs_shell", True):
            hl_order = result.get("headless_most_common_order", [])
            sh_order = result.get("headless_shell_most_common_order", [])
            if hl_order:
                console.print(f"    Headless order: {hl_order}")
            if sh_order:
                console.print(f"    Shell order:    {sh_order}")


def report_header_values():
    console.print("\n[bold underline]Header Value Analysis[/bold underline]\n")
    result = analyze_header_values()

    table = Table(title="Header Value Comparison")
    table.add_column("Header")
    table.add_column("Headful")
    table.add_column("Headless")
    table.add_column("Headless-Shell")
    table.add_column("HF=HL?")
    table.add_column("HL=Shell?")

    for header, data in sorted(result.items()):
        hf = ", ".join(data["headful_values"][:2]) or "absent"
        hl = ", ".join(data["headless_values"][:2]) or "absent"
        sh = ", ".join(data.get("headless_shell_values", [])[:2]) or "absent"

        def _trunc(v, n=50):
            return v[:n-3] + "..." if len(v) > n else v

        table.add_row(
            header,
            _trunc(hf), _trunc(hl), _trunc(sh),
            _MATCH(data.get("match")),
            _MATCH(data.get("match_hl_vs_shell")),
        )

    console.print(table)


def report_connections():
    console.print("\n[bold underline]Connection Pattern Analysis[/bold underline]\n")

    for page in ["probe-connection-reuse", "probe-tls-fingerprint"]:
        result = analyze_connection_patterns(page)
        if "error" in result:
            console.print(f"[yellow]{page}: {result['error']}[/yellow]")
            continue

        console.print(f"  [bold]{page}[/bold]:")
        for mode, prefix in [("Headful", "headful"), ("Headless", "headless"), ("Shell", "headless_shell")]:
            n = result.get(f"{prefix}_n", 0)
            if n:
                mean = result.get(f"{prefix}_mean_connections", 0)
                std = result.get(f"{prefix}_std", 0)
                console.print(f"    {mode:12s} unique connections: {mean:.1f} +/- {std:.1f} (n={n})")

        # Headful vs Headless
        p_hf_hl = result.get("mann_whitney_p_hf_vs_hl")
        if p_hf_hl is not None:
            sig = "[red]SIGNIFICANT[/red]" if result.get("significant_hf_vs_hl") else "[green]not significant[/green]"
            d = result.get("cohens_d_hf_vs_hl", 0)
            console.print(f"    HF vs HL:    p={p_hf_hl:.4f}, d={d:.2f} — {sig}")

        # Headless vs Shell
        p_hl_sh = result.get("mann_whitney_p_hl_vs_shell")
        if p_hl_sh is not None:
            sig = "[red]SIGNIFICANT[/red]" if result.get("significant_hl_vs_shell") else "[green]not significant[/green]"
            d = result.get("cohens_d_hl_vs_shell", 0)
            console.print(f"    HL vs Shell: p={p_hl_sh:.4f}, d={d:.2f} — {sig}")


def report_summary():
    """Focused summary of Chrome vs chrome-headless-shell differences."""
    console.print("\n[bold underline]Chrome vs chrome-headless-shell Summary[/bold underline]\n")

    diffs = []

    tls = analyze_tls_fingerprints()
    if "error" not in tls:
        ja3_match = tls.get("ja3_match_hl_vs_shell")
        ja4_match = tls.get("ja4_match_hl_vs_shell")
        if ja3_match is False:
            diffs.append(f"  JA3 hash differs: Chrome={tls.get('headless_ja3_unique', ['?'])} vs Shell={tls.get('headless_shell_ja3_unique', ['?'])}")
        if ja4_match is False:
            diffs.append(f"  JA4 string differs: Chrome={tls.get('headless_ja4_unique', ['?'])} vs Shell={tls.get('headless_shell_ja4_unique', ['?'])}")
        if ja3_match is True and ja4_match is True:
            console.print("  [green]TLS fingerprints (JA3/JA4): IDENTICAL[/green]")

    headers = analyze_header_values()
    for h, data in sorted(headers.items()):
        m = data.get("match_hl_vs_shell")
        if m is False:
            hl_v = data.get("headless_values", [])
            sh_v = data.get("headless_shell_values", [])
            diffs.append(f"  Header '{h}' differs: Chrome={hl_v[:2]} vs Shell={sh_v[:2]}")

    for page in ["probe-header-order", "probe-tls-fingerprint"]:
        order = analyze_header_order(page)
        if order.get("exact_match_hl_vs_shell") is False:
            diffs.append(f"  Header order differs on {page} (edit distance: {order.get('edit_distance_hl_vs_shell', '?')})")

    if diffs:
        console.print("[red]Detectable differences found:[/red]")
        for d in diffs:
            console.print(d)
    else:
        console.print("  [green]No server-side differences detected between Chrome headless and chrome-headless-shell[/green]")


def main():
    console.print("[bold]Server-Side Signal Analysis Report[/bold]")
    console.print("=" * 60)

    report_tls()
    report_header_order()
    report_header_values()
    report_connections()
    report_summary()

    console.print("\n" + "=" * 60)
    console.print("[bold]Report complete.[/bold]\n")


if __name__ == "__main__":
    main()
