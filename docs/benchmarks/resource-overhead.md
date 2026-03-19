---
layout: default
title: Resource Overhead
parent: Benchmarks
nav_order: 1
---

# Resource Overhead

A three-way comparison of Chrome execution modes measuring memory, CPU, process count, and page load timing across 965 real-world websites.

## Fresh browser mode

In fresh mode, a new Chrome instance is launched for each URL, measured, and terminated. This isolates per-page resource usage without cumulative state.

### Memory

| Metric | Headless | Headful | Shell | HL vs HF | Shell vs HF |
|---|---|---|---|---|---|
| Container active memory | 563 MB | 591 MB | 436 MB | -4.7% | **-26.2%** |
| Container total memory | 645 MB | 754 MB | 502 MB | -14.4% | **-33.4%** |
| Chrome USS | 440 MB | 440 MB | 354 MB | -0.1% | **-19.5%** |
| Chrome RSS | 1,268 MB | 1,314 MB | 772 MB | -3.5% | **-41.3%** |

Headless and headful full Chrome are nearly identical in memory usage. Both run the same binary; the `--headless` flag suppresses window creation but does not remove the rendering code or GPU process. The USS difference of -0.1% (0.6 MB) is within noise.

Headless-shell saves 26.2% of container active memory (155 MB) by removing the compositing pipeline, GPU process, and shared library overhead. The RSS savings appear even larger (-41.3%) because RSS double-counts shared library pages across Chrome's process tree -- the shell runs 3.3 fewer processes on average.

### CPU

| Metric | Headless | Headful | Shell | HL vs HF | Shell vs HF |
|---|---|---|---|---|---|
| Container CPU% | 79.5% | 85.4% | 63.3% | -6.9% | **-25.9%** |
| Chrome CPU% (avg) | 57.3% | 59.6% | 47.0% | -3.9% | **-21.1%** |
| Chrome CPU% (peak) | 156.2% | 159.3% | 136.5% | -2.0% | **-14.3%** |

### Processes

| Metric | Headless | Headful | Shell |
|---|---|---|---|
| Process count (peak, mean) | 10.5 | 10.5 | 7.2 |

Headless-shell runs **31.4% fewer processes** than full Chrome. The missing processes are primarily the GPU process (~80--120 MB RSS) and utility processes related to display compositing.

### Timing

| Metric | Headless | Headful | Shell | HL vs HF | Shell vs HF |
|---|---|---|---|---|---|
| Wall-clock load | 3,387 ms | 3,450 ms | 3,484 ms | -1.8% | +1.0% |
| TTFB | 559 ms | 574 ms | 626 ms | -2.5% | **+9.2%** |
| Connect | 118 ms | 118 ms | 150 ms | -0.1% | **+27.2%** |
| DOM Content Loaded | 1,265 ms | 1,282 ms | 1,327 ms | -1.3% | +3.5% |
| Load Event | 1,685 ms | 1,731 ms | 1,788 ms | -2.7% | +3.3% |

Headless-shell is slower on network metrics: +9.2% higher TTFB and +27.2% higher connect time. The connect time median is 102.6 ms (shell) vs 20.7 ms (headful), suggesting differences in TLS session resumption or HTTP/2 connection management in the stripped binary. Despite this, wall-clock page load time differs by only +1.0% because the 2.0s settle time dominates.

## Reuse browser mode

In reuse mode, a single Chrome instance navigates all 965 URLs sequentially on the same tab, measuring cumulative resource growth.

### Memory accumulation

| Metric | Fresh (mean) | Reuse (mean) | Growth factor |
|---|---|---|---|
| Headless active memory | 563 MB | 3,650 MB | 6.5x |
| Headful active memory | 591 MB | 4,034 MB | 6.8x |
| Shell active memory | 436 MB | 3,809 MB | 8.7x |

All three modes accumulate significant memory over 965 navigations. The shell's growth factor (8.7x) is the highest because renderer process memory leaks accumulate similarly across all binaries, while the shell's initial savings (from fewer processes) become proportionally smaller.

### Reuse overhead relative to headful

| Metric | HL-Reuse vs HF-Reuse | Shell-Reuse vs HF-Reuse |
|---|---|---|
| Container active memory | -9.5% (-384 MB) | -5.6% (-225 MB) |
| Chrome USS | -10.1% (-387 MB) | -5.1% (-195 MB) |
| Chrome RSS | -9.3% (-1,165 MB) | -21.9% (-2,734 MB) |
| Wall-clock load | +0.5% (+17 ms) | -0.4% (-15 ms) |

In reuse mode, headless full Chrome saves 9.5% active memory vs headful -- a larger gap than fresh mode (-4.7%) because GUI rendering pipeline state (composited layer trees, texture caches) accumulates over 965 navigations in headful mode but is discarded in headless.

## Errors and compatibility

| Category | Headless | Headful | Shell |
|---|---|---|---|
| Total errors | 33 | 33 | **59** |
| ERR_HTTP2_PROTOCOL_ERROR | 0 | 0 | **36** |
| HTTP 403 responses | 30 | 31 | **95** |
| Content divergence (>50%) | 0.9% | -- | **6.3%** |

Headless-shell has **36 exclusive HTTP/2 protocol errors** on sites that work fine in full Chrome. It receives **3.2x more HTTP 403 responses**, indicating that servers fingerprint protocol-level signals (TLS ClientHello, HTTP/2 settings frames) that differ in the stripped binary.

Content divergence between headless and headful full Chrome is only 0.9% (8 of 940 URLs). Between headless and headless-shell, it rises to 6.3% (58 of 920 URLs), confirming that the shell is substantially easier for servers to detect and block.
