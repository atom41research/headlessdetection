---
layout: default
title: Methodology
parent: Benchmarks
nav_order: 2
---

# Benchmark Methodology

This page describes the experimental setup, measurement infrastructure, and analysis methods used in the resource overhead benchmarks.

## Environment

Each Chrome mode runs in an isolated Docker container with fixed resource limits:

| Parameter | Value |
|---|---|
| Container CPU limit | 4 cores |
| Container memory limit | 8 GB RAM |
| Container shared memory | 8 GB |
| Host OS | Linux |
| Headful display | Xvfb (virtual framebuffer) |

Docker containers ensure reproducible isolation. All three modes (headless, headful, headless-shell) run under identical cgroup constraints.

## Browser versions

| Mode | Binary | Chrome version | Playwright channel |
|---|---|---|---|
| Headless | Google Chrome stable | 145.0.7632.159 | `chrome` |
| Headful | Google Chrome stable | 145.0.7632.159 | `chrome` |
| Headless Shell | chrome-headless-shell | 145.0.7632.6 | `chromium-headless-shell` |

Headless and headful modes use the same Chrome binary. The headless-shell binary is a separate stripped build from Chrome for Testing.

## Browser launch flags

All modes are launched with:

```
--no-sandbox --disable-blink-features=AutomationControlled --disable-crashpad
```

A headful Chrome user-agent string is applied to all modes to prevent user-agent-based detection from confounding results.

## URL set

965 URLs derived from the Tranco top-1000 list after deduplication and filtering unreachable domains. The URLs span a representative cross-section of the web: news sites, e-commerce, social media, government, educational institutions, SaaS products, and CDN endpoints.

## Test modes

### Fresh browser mode

A new Chrome instance is launched for each URL. The browser navigates to the URL, waits for `domcontentloaded`, holds for a 2.0-second settle time, collects metrics, and then the browser is terminated. This provides isolated per-URL measurements without state leakage between URLs.

### Reuse browser mode

A single Chrome instance is launched and navigates all 965 URLs sequentially on the same tab. The browser is not restarted between URLs. This measures cumulative resource growth and simulates long-running automation sessions.

## Run structure

- 2 independent runs per mode (independent container launches)
- 1,930 total data points per mode (965 URLs x 2 runs)
- Each run processes URLs in a fixed order

## Measurement infrastructure

Two independent measurement systems operate simultaneously during each page load:

### psutil (process-level)

Monitors the Chrome process tree (parent + all child processes via `proc.children(recursive=True)`). Captures:

- RSS (Resident Set Size) per process, summed across the tree
- USS (Unique Set Size) per process, summed across the tree
- CPU time (user + system) per sample
- Process count

### cgroup v2 (container-level)

Reads kernel accounting files for the container's cgroup:

- `memory.stat` fields: `anon` + `kernel` (active memory), `file` (page cache)
- `memory.current` (total charged memory)
- `cpu.stat` field: `usage_usec` (CPU microseconds)

### Sampling

- Sampling interval: 250 ms
- Settle time after `domcontentloaded`: 2.0 seconds
- Navigation timeout: 10,000 ms
- Per-URL timeout: 60 seconds
- Baseline measurement taken before Chrome launches for each URL (fresh mode only)

### Navigation timing

Collected via JavaScript after page load:

```javascript
performance.getEntriesByType('navigation')[0]
```

Metrics extracted: DNS, Connect, TTFB, Response, DOM Interactive, DOM Content Loaded, DOM Complete, Load Event. All times are milliseconds from navigation start.

## Viewport

All modes use a 1280 x 720 viewport. Headful mode renders to a virtual framebuffer (Xvfb) at the same resolution.

## Analysis methods

- Per-mode aggregate statistics: mean, median, stdev, min, max, P5, P95
- Overhead ratios: mode A mean / mode B mean for each metric
- Per-URL paired differences: (mode A value) - (mode B value) for URLs with valid data in both modes
- Quartile analysis: URLs bucketed by headless Chrome RSS into 4 equal groups to examine scaling behavior
- Content divergence: pairwise comparison of `document.body.innerText.length` across modes, flagging URLs with >20% or >50% relative difference
