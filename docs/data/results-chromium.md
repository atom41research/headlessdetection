---
layout: default
title: Chromium Results
parent: Raw Data
nav_order: 4
---

# Chromium (chrome-headless-shell) Detection Results

Playwright bundled Chromium v145 (`chrome-headless-shell` in headless mode).

## Key Finding

Headless Chromium reports **fake network metrics**: RTT=0, downlink=10 Mbps.
Headful Chromium reports **real metrics**: RTT=100ms, downlink=1.5 Mbps.
Both report `effectiveType: "4g"`.

This causes Chromium's `LazyLoadImageObserver` to compute a much larger scroll
margin in headless mode, loading lazy resources far below the viewport.

## Lazy Loading (Binary Signal) - STRONG DETECTOR

### Default viewport (headful=system window, headless=1280x720)

| Mode     | Loaded imgs | Max position | Threshold margin |
|----------|-------------|-------------|-----------------|
| headful  | 40          | 1950px      | ~1230px         |
| headless | 75          | 3700px      | ~2980px         |

### Matched viewport 1280x720

| Mode     | Loaded imgs | Max position |
|----------|-------------|-------------|
| headful  | 31          | 1500px      |
| headless | 75          | 3700px      |

### Small viewport 400x300

| Mode     | Loaded imgs | Max position |
|----------|-------------|-------------|
| headful  | 31          | 1500px      |
| headless | 66          | 3250px      |

### Findings

- Threshold difference is **consistent** regardless of viewport size
- 100% reliable across all 5 runs (zero overlap)
- Image dimensions (1x1 to 500x500) do NOT affect the threshold
- srcset and picture elements show same behavior
- Lazy iframes show same pattern (headful=3000px, headless=4500px)
- CSS background images show NO difference (not affected by lazy loading)

### Network metrics comparison

| Metric         | Headful | Headless |
|----------------|---------|----------|
| effectiveType  | 4g      | 4g       |
| downlink       | ~1.5    | ~10      |
| rtt            | 100     | 0        |
| outerWidth     | 1288    | 1280     |
| outerHeight    | 805     | 720      |

## Media Queries (Binary Signal) - NO DIFFERENCE

All probes fired identically in both modes:
- prefers-color-scheme, prefers-reduced-motion, hover, pointer
- Viewport width/height breakpoints
- display-mode, color depth, contrast preference

## Import Chains (Timing Signal) - WEAK

- Large effect sizes (d=0.5-1.4) but high variance
- Not statistically significant at n=5
- Expensive vs control chains showed similar timing (CSS processing cost
  doesn't differ meaningfully)

## Background Chains (Timing Signal) - WEAK

- Default profile: small effect sizes (d<0.5), not significant
- Matched profile: medium effects (d~0.6), headful was SLOWER (~250ms vs ~130ms)
  but high variance prevented significance
- Headful being slower is counterintuitive - likely due to window management overhead

## Root Cause

Playwright's bundled Chromium uses `chrome-headless-shell` for headless mode.
This binary does not have proper network metric estimation - it reports RTT=0
and inflated downlink. Chromium's lazy loading margin is network-dependent
(larger margin for faster perceived connections), so the fake metrics cause
a ~2x larger margin.

## Limitation

This detection does NOT work against Chrome's new headless mode (`--headless=new`),
which reports proper network metrics identical to headful mode.
