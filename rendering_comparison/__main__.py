"""Entry point: uv run python -m rendering_comparison

Pipeline: parse URLs → visit in each mode → compare pairwise → report.
"""

import asyncio
import json
from dataclasses import asdict
from itertools import combinations
from pathlib import Path

from playwright.async_api import async_playwright
from rich.console import Console
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    MofNCompleteColumn,
)

from . import config
from .parser import parse_ranking_file, parse_csv_results, RankedURL
from .collector import collect_page_data, PageMetrics
from .comparator import compare, ComparisonResult
from .report import (
    generate_markdown_report,
    generate_csv,
    save_raw_metrics,
    print_summary,
)

console = Console()


def _load_urls_file(path: Path) -> list[RankedURL]:
    """Load URLs from a plain text file (one per line)."""
    urls: list[RankedURL] = []
    for i, line in enumerate(path.read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Extract host from URL
        from urllib.parse import urlparse
        host = urlparse(line).hostname or line
        urls.append(RankedURL(
            rank=i, host=host, score=0.0,
            tech_diff=0, dom_ratio=0.0, h_dom_size=0, f_dom_size=0,
            req_diff=0, other_diff=0, cluster="",
        ))
        # Override the url property by storing the full URL
        urls[-1]._full_url = line  # type: ignore[attr-defined]
    return urls


PER_MODE_TIMEOUT_S = 30  # max seconds per mode per URL (navigation + settle + metrics)


async def process_url(
    pw, url: str, modes: list[str], output_dir: Path, host_slug: str,
) -> dict[str, PageMetrics]:
    """Collect page data for a URL in each mode. Returns {mode: PageMetrics}."""
    results = {}
    for mode in modes:
        try:
            results[mode] = await asyncio.wait_for(
                collect_page_data(pw, url, mode, output_dir, host_slug),
                timeout=PER_MODE_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            console.print(f"  [yellow]Timeout: {mode} on {url[:50]}[/yellow]")
            results[mode] = PageMetrics(url=url, mode=mode, error=f"Timeout after {PER_MODE_TIMEOUT_S}s")
        except Exception as e:
            results[mode] = PageMetrics(url=url, mode=mode, error=str(e)[:200])
    return results


async def main():
    args = config.build_parser().parse_args()

    # Parse modes
    modes = [m.strip() for m in args.modes.split(",")]
    for m in modes:
        if m not in config.MODE_PARAMS:
            console.print(f"[red]Unknown mode '{m}'. Valid: {', '.join(sorted(config.MODE_PARAMS))}[/red]")
            return

    output_dir: Path = args.output
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "screenshots").mkdir(exist_ok=True)
    (output_dir / "har").mkdir(exist_ok=True)

    # Load URLs from one of three sources
    if args.urls_file:
        urls = _load_urls_file(args.urls_file)
        filter_label = f"urls-file ({len(urls)} URLs)"
    elif args.csv_input:
        urls = parse_csv_results(
            args.csv_input,
            diff_types=args.filter_diff_types,
            min_net_req_diff=args.min_net_req_diff,
        )
        filter_label = f"csv-input ({len(urls)} filtered URLs)"
    else:
        full_better = args.full_better and not args.all_urls
        urls = parse_ranking_file(
            args.input,
            top_n=args.top_n,
            start_rank=args.start_rank,
            full_better_only=full_better,
        )
        filter_label = "full-better only" if full_better else "all"

    console.print("\n[bold]Rendering Comparison[/bold]")
    console.print(f"Input: {args.urls_file or args.csv_input or args.input}")
    console.print(f"Modes: {', '.join(modes)}")
    console.print(f"Filter: {filter_label}")
    console.print(f"URLs to process: {len(urls)}")
    console.print(f"Output: {output_dir}\n")

    # Determine comparison pairs
    pairs = list(combinations(modes, 2))
    console.print(f"Comparison pairs: {', '.join(f'{a} vs {b}' for a, b in pairs)}\n")

    all_comparisons: list[ComparisonResult] = []
    all_raw_metrics: list[dict] = []

    async with async_playwright() as pw:
        # Verify Chrome is available
        try:
            browser = await pw.chromium.launch(
                headless=True, channel=config.CHANNEL, args=["--no-sandbox"]
            )
            version = browser.version
            await browser.close()
            console.print(f"[green]Chrome version: {version}[/green]\n")
        except Exception as e:
            console.print(f"[red]Chrome not available: {e}[/red]")
            return

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Comparing URLs...", total=len(urls))

            for i in range(0, len(urls), args.batch_size):
                batch = urls[i : i + args.batch_size]

                for ranked_url in batch:
                    progress.update(
                        task,
                        description=f"[{ranked_url.rank}] {ranked_url.host}",
                    )

                    # Get the URL — support both RankedURL.url property and _full_url override
                    url = getattr(ranked_url, "_full_url", None) or ranked_url.url
                    host_slug = ranked_url.host.replace(".", "_")

                    try:
                        mode_metrics = await process_url(
                            pw, url, modes, output_dir, host_slug,
                        )

                        # Save raw metrics
                        raw_entry = {
                            "host": ranked_url.host,
                            "rank": ranked_url.rank,
                        }
                        for mode, metrics in mode_metrics.items():
                            raw_entry[mode] = asdict(metrics)
                        all_raw_metrics.append(raw_entry)

                        # Pairwise comparisons
                        for mode_a, mode_b in pairs:
                            if mode_a in mode_metrics and mode_b in mode_metrics:
                                comparison = compare(
                                    mode_metrics[mode_a],
                                    mode_metrics[mode_b],
                                    host=ranked_url.host,
                                    rank=ranked_url.rank,
                                    screenshots_dir=output_dir / "screenshots",
                                    mode_a_name=mode_a,
                                    mode_b_name=mode_b,
                                )
                                all_comparisons.append(comparison)

                    except Exception as e:
                        console.print(
                            f"[red]Error processing {ranked_url.host}: {e}[/red]"
                        )

                    progress.advance(task)

                # Flush intermediate results after each batch
                save_raw_metrics(all_raw_metrics, output_dir)

    console.print("\n[bold]Generating reports...[/bold]")
    md_path = generate_markdown_report(all_comparisons, output_dir)
    csv_path = generate_csv(all_comparisons, output_dir)
    console.print(f"  Markdown: {md_path}")
    console.print(f"  CSV: {csv_path}")

    print_summary(all_comparisons)
    console.print("\n[bold green]Done.[/bold green]\n")


if __name__ == "__main__":
    asyncio.run(main())
