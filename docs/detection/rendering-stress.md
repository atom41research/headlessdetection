---
layout: default
title: Rendering Stress
parent: Detection Methods
nav_order: 3
---

# Rendering Stress Detection

Headful Chrome must composite rendered content to a real GPU surface and display pipeline. Headless Chrome skips this final compositing step. Under sustained rendering stress, this difference produces a measurable timing gap in server-side beacon arrival.

This is a **statistical signal**, not a binary one. It requires multiple samples and is not practical for single-shot detection.

## Methodology

The test page contains 5000+ HTML elements, each styled with extreme CSS properties designed to maximize rendering pipeline work:

- `filter: blur() brightness() contrast() saturate() hue-rotate()`
- `box-shadow` with 7 layers
- `repeating-conic-gradient` backgrounds
- `mix-blend-mode: overlay`
- `clip-path: polygon()`
- `will-change: transform`
- `transform: rotate() scale()`
- `backdrop-filter: blur()`

Beacons are placed every 50 elements (102 beacons total). The server records the arrival time of each beacon and computes the total span (time from first to last beacon arrival).

## Statistical results

### Element count vs effect size

| Element count | Headful mean | Headless mean | Delta | p-value | Cohen's d |
|---|---|---|---|---|---|
| 1000 | 19.7 ms | 22.1 ms | -2.3 ms | 0.089 | -0.67 |
| 2000 | 41.5 ms | 36.8 ms | +4.7 ms | 0.089 | 0.75 |
| 3000 | 62.3 ms | 61.3 ms | +0.9 ms | 0.970 | 0.06 |
| 5000 | 97.2 ms | 86.6 ms | +10.6 ms | **0.001** | **1.35** |

The effect scales with element count. At 5000 elements, headful is consistently ~10 ms slower than headless. The p-value of 0.0013 and Cohen's d of 1.35 indicate a large, statistically significant effect. n=10 runs per condition, Mann-Whitney U test.

### Differential approach (heavy minus light)

Rather than comparing absolute timing between modes, serve the same browser both a "heavy CSS" page and a "light CSS" page, then compare the delta (heavy - light) across modes.

| Mode | Heavy span | Light span | Delta (heavy - light) |
|---|---|---|---|
| Headful | ~43 ms | ~45 ms | -1.8 ms |
| Headless | ~36 ms | ~27 ms | +10.3 ms |

In headful mode, window management and display compositing overhead creates a constant baseline cost that dominates over CSS complexity differences. Heavy and light pages take approximately the same time.

In headless mode, without display/GPU overhead, the actual rendering cost difference between heavy and light CSS becomes visible. Heavy pages take measurably longer than light pages.

p=0.0028, Cohen's d=-1.324, n=10 per condition.

### Inter-beacon interval variance

| Mode | Mean stdev | p-value | Cohen's d |
|---|---|---|---|
| Headful | 0.52 ms | 0.054 | 0.78 |
| Headless | 0.41 ms | | |

Headful shows marginally higher variance in inter-beacon intervals, possibly due to GPU frame scheduling jitter (vsync, compositor scheduling). This is a weak signal and not statistically significant at the 0.05 level.

## Implementation

The rendering stress test is implemented in `probes/pages/rendering_stress.py`. The server generates the heavy page dynamically, embeds beacon URLs at intervals, and records arrival timestamps.

## Why this works

Headful Chrome initializes the full compositing pipeline even for `--headless=new` mode:

1. The GPU process is spawned (~80--120 MB RSS).
2. The display compositor allocates surfaces and manages layer trees.
3. Every frame must be composited to a surface, even though no display is connected.

This constant overhead masks CSS complexity differences in headful mode. In headless mode, the rendering pipeline skips surface allocation and compositing, making the actual rendering cost of CSS effects visible in beacon timing.

## Practical limitations

- **Requires heavy pages.** The effect is only statistically significant at 5000+ elements with extreme CSS. Lighter pages (1000--3000 elements) do not produce reliable separation.
- **Multiple samples needed.** Single-measurement accuracy is poor due to network jitter and system load variation. At least 5--10 measurements per browser session are needed for reliable classification.
- **Network latency dominates.** In production environments, millisecond-scale rendering differences are dwarfed by variable network latency (50--500 ms). The signal is most useful on fast local networks or when the server and browser are co-located.
- **Artificial delay countermeasure.** An attacker can inject `setTimeout` delays to match headful timing, raising the measured span. The differential approach (heavy - light) is harder to spoof because the attacker must add consistent delays across both page variants.
- **Hardware dependent.** The effect size depends on GPU acceleration availability. Machines with dedicated GPUs may show different deltas than those using software rendering.
