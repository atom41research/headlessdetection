---
layout: default
title: Benchmarks
nav_order: 4
has_children: true
---

# Benchmarks

A 965-URL Docker benchmark comparing Chrome across three modes: headless, headful (via Xvfb), and headless-shell.

## Setup

| Parameter | Value |
|---|---|
| Chrome version | v145 |
| Runs per mode | 2 |
| Sampling interval | 250 ms |
| Settle time | 2.0 s |
| Viewport | 1280 x 720 |
| URL set | 965 URLs from Tranco top-1000 (after filtering unreachable) |

Headful mode runs inside Docker with Xvfb providing a virtual display, ensuring identical container isolation across all three modes.

## Resource overhead

| Metric | Headless | Headful | Shell |
|---|---|---|---|
| Container active memory | 563 MB | 591 MB | 436 MB |
| Chrome USS | 440 MB | 440 MB | 354 MB |
| Process count | 10.5 | 10.5 | 7.2 |

Headful and headless full Chrome are nearly identical in resource usage. The only meaningful difference is Xvfb overhead (~28 MB). Headless-shell is substantially lighter owing to its stripped-down architecture.
