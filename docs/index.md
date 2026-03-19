---
layout: default
title: Home
nav_order: 1
---

# headlessdetection

Empirical framework for detecting Chrome headless mode.

{: .note }
> Publication reference placeholder -- paper forthcoming.

## Detection summary

| Signal | Headful | Headless | Reliability |
|---|---|---|---|
| **Scrollbar width** | 15 px | 0 px | 100% |
| **Window chrome gap** | 8/85 px | 0/0 px | 100% |
| **Rendering stress** | ~97 ms | ~87 ms | p=0.001 |
| sec-ch-ua header | Chrome | HeadlessChrome | 100% (trivially spoofable) |
| Lazy loading, media queries, fonts, CSS chains | identical | identical | --- |

Out of 20+ signals tested between Chrome headful and headless, only the first three rows above produce reliable, non-spoofable differences. Everything else -- lazy loading behaviour, media queries, font rendering, CSS feature chains -- is identical across modes.

## Sections

- [Detection Methods](detection/) -- scrollbar width, window chrome gap, rendering stress, and why other signals fail
- [Headless Shell](headless-shell/) -- how `chrome-headless-shell` differs from full Chrome headless
- [Benchmarks](benchmarks/) -- 965-URL Docker benchmark comparing resource usage across modes
- [Raw Data](data/) -- full result tables for Chrome, Chromium, and headless-shell runs

## Source

[View on GitHub](https://github.com/atom41research/headlessdetection){: .btn }
