"""Unified experiment runner for headless detection investigations.

Usage:
    uv run python -m experiments --list
    uv run python -m experiments --all
    uv run python -m experiments --quick
    uv run python -m experiments --shell
    uv run python -m experiments scrollbar chrome lazy
"""

import argparse
import asyncio
import importlib
import inspect
import sys
import time

from rich.console import Console
from rich.table import Table

from experiments.investigations import ALL, QUICK, REGISTRY, SHELL

console = Console()


def parse_args():
    parser = argparse.ArgumentParser(
        prog="python -m experiments",
        description="Run headless detection investigation scripts.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all available investigations",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run all investigations",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Run only the quick, most reliable investigations",
    )
    parser.add_argument(
        "--shell",
        action="store_true",
        help="Run headless-shell specific investigations",
    )
    parser.add_argument(
        "names",
        nargs="*",
        help="Investigation names to run (e.g. scrollbar chrome lazy)",
    )
    return parser.parse_args()


def print_list():
    table = Table(title="Available Investigations", show_lines=True)
    table.add_column("#", style="dim", justify="right")
    table.add_column("Name", style="cyan bold")
    table.add_column("Description")
    table.add_column("Est. Time", justify="right")
    table.add_column("Modes", justify="center")
    table.add_column("Reliable", justify="center")

    for i, (name, meta) in enumerate(REGISTRY.items(), 1):
        reliable = "[bold green]YES[/bold green]" if meta["reliable"] else "[dim]no[/dim]"
        modes = ", ".join(meta["modes"])
        table.add_row(
            str(i),
            name,
            meta["description"],
            f"{meta['estimated_minutes']} min",
            modes,
            reliable,
        )

    console.print(table)

    total = sum(m["estimated_minutes"] for m in REGISTRY.values())
    console.print(f"\nTotal estimated time for all investigations: [bold]{total} min[/bold]")
    console.print(f"\nPresets:")
    console.print(f"  --quick : {', '.join(QUICK)}")
    console.print(f"  --shell : {', '.join(SHELL)}")
    console.print(f"  --all   : all {len(ALL)} investigations")
    console.print()


def resolve_names(args) -> list[str]:
    if args.all:
        return list(ALL)
    if args.quick:
        return list(QUICK)
    if args.shell:
        return list(SHELL)
    if args.names:
        unknown = [n for n in args.names if n not in REGISTRY]
        if unknown:
            console.print(f"[bold red]Unknown investigation(s): {', '.join(unknown)}[/bold red]")
            console.print(f"Available: {', '.join(REGISTRY.keys())}")
            sys.exit(1)
        return args.names
    return []


def run_investigation(name: str, meta: dict) -> bool:
    """Import and run a single investigation. Returns True on success."""
    module_path = meta["module"]
    try:
        mod = importlib.import_module(module_path)
    except Exception as exc:
        console.print(f"  [bold red]Failed to import {module_path}: {exc}[/bold red]")
        return False

    main_fn = getattr(mod, "main", None)
    if main_fn is None:
        console.print(f"  [bold red]No main() found in {module_path}[/bold red]")
        return False

    try:
        if inspect.iscoroutinefunction(main_fn):
            # ad_cascade.main() takes an args parameter; all others take none
            sig = inspect.signature(main_fn)
            if sig.parameters:
                # Build a minimal namespace with defaults the script expects
                ns = argparse.Namespace(experiment="all")
                asyncio.run(main_fn(ns))
            else:
                asyncio.run(main_fn())
        else:
            main_fn()
    except Exception as exc:
        console.print(f"  [bold red]Error running {name}: {exc}[/bold red]")
        return False

    return True


def main():
    args = parse_args()

    if args.list:
        print_list()
        return

    names = resolve_names(args)
    if not names:
        console.print("[yellow]No investigations specified. Use --list to see options.[/yellow]")
        parse_args.__wrapped__ = None  # unused, just to trigger help
        console.print("Run with --help for usage information.\n")
        return

    total_minutes = sum(REGISTRY[n]["estimated_minutes"] for n in names)
    console.print()
    console.rule("[bold]Headless Detection Investigation Runner")
    console.print(f"\nWill run [bold]{len(names)}[/bold] investigation(s): {', '.join(names)}")
    console.print(f"Estimated total time: [bold]{total_minutes} min[/bold]\n")

    results = {}
    wall_start = time.monotonic()

    for i, name in enumerate(names, 1):
        meta = REGISTRY[name]
        console.rule(f"[bold cyan][{i}/{len(names)}] {name}")
        console.print(f"[dim]{meta['description']}[/dim]")
        console.print(f"[dim]Estimated: {meta['estimated_minutes']} min[/dim]\n")

        t0 = time.monotonic()
        success = run_investigation(name, meta)
        elapsed = time.monotonic() - t0

        results[name] = {
            "success": success,
            "elapsed_seconds": elapsed,
        }

        status = "[bold green]OK[/bold green]" if success else "[bold red]FAILED[/bold red]"
        console.print(f"\n  {status} in {elapsed:.1f}s\n")

    wall_elapsed = time.monotonic() - wall_start

    # Summary
    console.print()
    console.rule("[bold]Summary")

    table = Table(show_lines=True)
    table.add_column("Investigation", style="cyan")
    table.add_column("Status", justify="center")
    table.add_column("Time", justify="right")

    for name, info in results.items():
        status = "[bold green]OK[/bold green]" if info["success"] else "[bold red]FAILED[/bold red]"
        elapsed = info["elapsed_seconds"]
        if elapsed >= 60:
            time_str = f"{elapsed / 60:.1f} min"
        else:
            time_str = f"{elapsed:.1f}s"
        table.add_row(name, status, time_str)

    console.print(table)

    passed = sum(1 for r in results.values() if r["success"])
    failed = len(results) - passed
    console.print(
        f"\n[bold]{passed}[/bold] passed, [bold red]{failed}[/bold red] failed, "
        f"total wall time: {wall_elapsed:.1f}s\n"
    )

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
