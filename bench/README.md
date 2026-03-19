# bench — Chrome Headful vs Headless Resource Overhead

Measures CPU and RAM cost of headful Chrome (with Xvfb) vs headless Chrome when loading real websites. Each mode runs in its own Docker container with per-run isolation — every run gets a fresh container, so DNS/HTTP/page caches don't contaminate repeated measurements.

## Architecture

```
bench/run.py (host orchestrator)
  ├── Builds Docker images (Dockerfile.headless, Dockerfile.headful)
  ├── Detects headful Chrome User-Agent (shared across all containers)
  ├── Launches N containers per mode (1 container = 1 run = 1 pass over all URLs)
  │     └── docker compose run headless --modes headless --run-index 0
  │     └── docker compose run headful  --modes headful  --run-index 0
  │     └── docker compose run headless --modes headless --run-index 1
  │     └── ...
  └── Generates reports from collected JSON results

bench/__main__.py (inside container)
  └── benchmark.py → runner.py + monitor.py
      ├── Launches Chrome via Playwright (headless or headful)
      ├── Navigates to each URL, captures HTTP status, content, load events
      ├── Monitors Chrome process tree (psutil: USS, RSS, CPU)
      ├── Reads container cgroup v2 metrics (memory.current, memory.stat, cpu.stat)
      └── Saves raw results as runs_<mode>.json
```

- **`Dockerfile.headless`** — Chrome + Python, no Xvfb, no GTK, no X11
- **`Dockerfile.headful`** — Chrome + Python + Xvfb + GTK + X11 (virtual display)
- Each container runs one mode with one `--run-index`, iterating all URLs once
- Results are merged locally with `--report` to generate comparison tables

## Quick Start

The easiest way is via the orchestrator:

```bash
# Single URL, 3 runs per mode
uv run python bench/run.py --url https://example.com

# URL list, 2 runs, with reuse-browser variants
uv run python bench/run.py --urls-file top1000trancourls.txt --limit 10 --runs 2 --reuse-browser

# Parallel headless + headful containers
uv run python bench/run.py --urls-file bench/urls.txt --runs 3 --parallel

# Skip Docker build (reuse existing images)
uv run python bench/run.py --url https://example.com --no-build

# Re-generate reports from existing results
uv run python bench/run.py --report-only
uv run python bench/run.py --report-only --job-dir bench/results/job_20260308_201351
```

### Manual container usage

```bash
# Build images
docker compose -f bench/docker-compose.yml build

# Run a single mode
docker compose -f bench/docker-compose.yml run --rm headless \
  --url https://example.com --modes headless --run-index 0 \
  --output-dir /app/bench/results/job_manual/run_0

# Generate report from collected results
uv run python -m bench --report --output-dir bench/results/job_manual/run_0
```

## Orchestrator Options (`bench/run.py`)

| Flag | Default | Description |
|------|---------|-------------|
| `--url` | — | Single URL to benchmark |
| `--urls-file` | — | File with one URL per line |
| `--runs` | 3 | Number of separate container runs per mode |
| `--limit` | 0 (all) | Only use the first N URLs from the file |
| `--reuse-browser` | off | Also run reuse-browser variants (4 modes total) |
| `--parallel` | off | Run headless and headful containers in parallel |
| `--no-build` | off | Skip Docker image build |
| `--report-only` | off | Only merge existing results and generate report |
| `--job-dir` | latest | Job directory for `--report-only` |
| `--settle-time` | 2.0 | Seconds to wait after page load |
| `--sample-interval` | 0.25 | psutil sampling interval (seconds) |
| `--page-timeout` | 10000 | Navigation timeout (ms) |
| `--run-timeout` | 60 | Max seconds per URL before killing |

## Container Options (`python -m bench`)

| Flag | Default | Description |
|------|---------|-------------|
| `--url` | — | Single URL to benchmark |
| `--urls-file` | — | File with one URL per line |
| `--modes` | headless,headful | Which mode(s) to run in this container |
| `--run-index` | 0 | Index of this run (set by orchestrator) |
| `--output-dir` | bench/results | Results directory |
| `--report` | — | Merge existing `runs_*.json` and generate reports |
| `--settle-time` | 2.0 | Seconds to wait after page load |
| `--sample-interval` | 0.25 | psutil sampling interval (seconds) |
| `--page-timeout` | 10000 | Navigation timeout (ms) |
| `--run-timeout` | 60 | Max seconds per URL before killing |
| `--user-agent` | auto-detect | Override User-Agent string |

## Modes

| Mode | Chrome | Browser lifecycle |
|------|--------|-------------------|
| `headless` | `--headless` | New browser per URL |
| `headful` | Xvfb display | New browser per URL |
| `headless-reuse` | `--headless` | Single browser, all URLs on one page |
| `headful-reuse` | Xvfb display | Single browser, all URLs on one page |

Fresh modes (`headless`, `headful`) launch and close Chrome for each URL — this measures the full startup + page load cost. Reuse modes keep one Chrome instance alive and navigate the same tab, measuring the incremental cost of each page.

## Output Files

Results are organized as `bench/results/job_<timestamp>/run_<N>/`:

| File | Description |
|------|-------------|
| `runs_<mode>.json` | Raw per-URL data from container (monitor samples, load events, HTTP status) |
| `fresh_summary.csv` | Per-URL comparison: headless vs headful (new browser) |
| `fresh_summary.json` | Structured JSON with metadata and overhead calculations |
| `reuse_summary.csv` | Per-URL comparison: headless-reuse vs headful-reuse |
| `reuse_summary.json` | Structured JSON for reuse mode |
| `samples.csv` | Every raw psutil + cgroup sample for time-series analysis |
| `load_events.csv` | Per-run Navigation Timing milestones, HTTP status, content length |

## Metrics

Metrics are reported at two levels, ordered by importance:

### Container level (cgroup v2)

The real cost to the machine. Read from `/sys/fs/cgroup/` inside the container.

| Metric | Source | Description |
|--------|--------|-------------|
| **Container Active (MB)** | `memory.stat` anon + kernel | Non-reclaimable memory (the best single metric) |
| **Container Total (MB)** | `memory.current` | Includes page cache (reclaimable under pressure) |
| **Container CPU%** | `cpu.stat` usage_usec / duration | CPU as % of one core |

### Chrome process level (psutil)

Chrome-specific detail from the process tree (parent + renderers + GPU + utility).

| Metric | Description |
|--------|-------------|
| **Chrome USS (MB)** | Unique Set Size — Chrome's private memory (no shared lib double-counting) |
| **Chrome RSS (MB)** | Resident Set Size — sum across processes (inflated by shared pages) |
| **Chrome CPU%** | Sum of per-process CPU utilization |

### Page load validation

Each run captures:
- HTTP status code
- Final URL (redirect detection)
- `document.body.innerText.length` (content verification)
- Navigation Timing Level 2 milestones (DNS, TTFB, DOM interactive, load event)
- Timeout and error tracking

The report flags: timeouts, HTTP errors, empty pages, content divergence >50% between headless/headful, and different redirect destinations across modes.

## Why Separate Containers?

Running both modes in a single container would have Xvfb running during headless measurements, polluting the results. Separate containers ensure:
- The headless image has no Xvfb, GTK, or X11 utilities installed
- No background Xvfb process consuming memory during headless runs
- Each environment matches its real-world deployment scenario

## Why Per-Run Container Isolation?

Each `--run-index` gets its own container because:
- **No DNS/HTTP caching**: Run 2 of a URL doesn't benefit from run 1's cached responses
- **Clean cgroup state**: Container cgroup memory grows monotonically — restarting gives a clean baseline
- **Reproducibility**: Each run is independent, so results can be compared or discarded individually
