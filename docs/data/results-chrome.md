---
layout: default
title: Chrome Detection Results
parent: Raw Data
nav_order: 1
---

# Chrome (New Headless Mode) Detection Results

System Chrome v144.0.7559.109, launched via Playwright `channel="chrome"`.
Chrome uses `--headless=new` (unified codebase with headful).

## Key Findings

### Working Detection Signals

**1. Rendering Stress Timing (p=0.0013, d=1.35)**
A page with 5000 elements using extreme CSS (blur, filters, gradients,
backdrop-filter, will-change, clip-path) produces measurable server-side
timing differences. Headful takes ~10ms longer for beacons to arrive,
because headful must composite to a real GPU surface / display.

**2. Differential Timing (p=0.0028, d=-1.32)**
Serve the SAME browser both a "heavy CSS" page and a "light CSS" page,
measure the beacon span delta. Headful shows similar timing for both
(constant overhead dominates), while headless shows heavy > light
(rendering cost is visible without the overhead).

**3. User-Agent Header**
Chrome headless announces itself: `HeadlessChrome/144.0.0.0` vs `Chrome/144.0.0.0`.
Trivially detectable server-side, but trivially spoofable.

**4. Window Outer/Inner Dimension Mismatch (100% reliable, zero overlap)**

In headful Chrome, `window.outerWidth > window.innerWidth` and
`window.outerHeight > window.innerHeight` because the browser window
includes chrome (title bar, borders, tabs). In `--headless=new`,
`outer === inner` — there is no window chrome.

| Property                        | Headful | Headless | Signal        |
|---------------------------------|---------|----------|---------------|
| `outerWidth - innerWidth`       | 8px     | **0px**  | Binary        |
| `outerHeight - innerHeight`     | 85px    | **0px**  | Binary        |
| `outerWidth === innerWidth`     | false   | **true** | 100% reliable |

Detection: `if (outerWidth === innerWidth && outerHeight === innerHeight)`
→ headless. Tested across viewport sizes 800×600, 1280×720, 1920×1080.

**Spoofability**: Moderate. Requires patching both `outerWidth` and
`outerHeight` getters to return values larger than the viewport, with
plausible deltas that vary by platform (Linux ~8/85, macOS ~0/28,
Windows ~16/39). An incorrect delta is itself a detection signal.

**Server-side**: Requires minimal client-side JS to relay the measurement.
Cannot be detected via CSS media queries or HTTP headers.
`probes/pages/outer_inner.py` implements full server-side gating: a sync XHR
beacon sends the delta, then the server decides per-request whether to
serve or block resources. Tested: headful gets 3/3 served, headless 0/3.

**5. Scrollbar Width (100% reliable, zero overlap)**

Headful Chrome renders a classic vertical scrollbar (~15px wide) that reduces
the content area width. Headless Chrome uses overlay scrollbars (0px width).
Three independent JS measurement techniques all confirm the same signal:

| Technique                      | Headful | Headless |
|--------------------------------|---------|----------|
| `innerWidth - clientWidth`     | 15px    | **0px**  |
| Offscreen scrollable div       | 15px    | **0px**  |
| `calc(100vw - 100%)` computed  | 15px    | **0px**  |

Detection: `if (window.innerWidth - document.documentElement.clientWidth > 0)`
→ headful. Tested across viewport sizes 800x600, 1280x720, 1920x1080.
n=10 runs per mode, 100% headful rate, 0% headless rate.

**Server-side**: JS measures the delta and fires a labelled beacon
(`/track/sb-js-detected` or `/track/sb-js-not-detected`). The exact pixel
value is also reported (`/track/sb-js-innerWidth-15` vs `-0`). See
`probes/pages/scrollbar_width.py`.

**Spoofability**: Moderate. Requires patching `document.documentElement.clientWidth`
to return `innerWidth - N` with a plausible scrollbar width (15-17px on Linux,
varies by OS/theme). The offscreen-div technique cross-validates.

**CSS-only approaches failed**: Chrome loads `background-image` even for
elements with 0px computed width. Container queries (`@container (min-width: 1px)`)
also evaluate to true on 0-width containers. Pure CSS detection of this signal
is not viable.

**6. Ad-Tech Cascade Timing (investigated, not reliable)**

Initial analysis of w3schools.com HAR files showed headful producing 236
requests vs headless 44. Investigation revealed this was a timing artifact:
with sufficient settle time (5-20s), both modes fire equivalent ad/tracking
cascades. The ad-tech infrastructure (GTM → prebid.js → cookie syncs) does
execute in headless, just with different startup timing.

| Settle Time | Headful Requests | Headless Requests | Gap    |
|-------------|-----------------|-------------------|--------|
| 2s          | 100             | 221               | -121   |
| 5s          | 363             | 292               | +71    |
| 10s         | 1066            | 1253              | -187   |
| 20s         | 1090            | 1146              | ~equal |

Not usable as a detection signal — the direction and magnitude are unstable.

### Non-working Detection Mechanisms

All binary (which resources load) and most timing signals show no difference.

## Rendering Stress Test Details

### Element Count vs Effect Size

| Count | Headful mean | Headless mean | Delta  | p-value  | Cohen's d |
|-------|-------------|--------------|--------|----------|-----------|
| 1000  | 19.7ms      | 22.1ms       | -2.3ms | 0.089    | -0.67     |
| 2000  | 41.5ms      | 36.8ms       | +4.7ms | 0.089    | 0.75      |
| 3000  | 62.3ms      | 61.3ms       | +0.9ms | 0.970    | 0.06      |
| 5000  | 97.2ms      | 86.6ms       | +10.6ms| **0.001**| **1.35**  |

The effect scales with element count. At 5000 elements with extreme CSS
filters/compositing, headful is consistently ~10ms slower. Each element
uses: `filter: blur() brightness() contrast() saturate() hue-rotate()`,
`box-shadow` (7 layers), `repeating-conic-gradient`, `mix-blend-mode`,
`clip-path`, `will-change: transform`, `transform`, `backdrop-filter`.

Beacons placed every 50 elements (102 beacons total).
n=10 runs per condition. Mann-Whitney U test.

### Differential Approach (Heavy - Light)

| Mode     | Heavy span | Light span | Delta (H-L) |
|----------|-----------|-----------|-------------|
| headful  | ~43ms     | ~45ms     | -1.8ms      |
| headless | ~36ms     | ~27ms     | +10.3ms     |

In headful mode, window management and display overhead creates a constant
baseline cost that dominates over CSS complexity. Heavy ≈ Light.

In headless mode, without display/GPU overhead, the actual rendering cost
difference between heavy and light CSS is visible. Heavy > Light.

p=0.0028, Cohen's d=-1.324, n=10 per condition.

### Inter-beacon Interval Variance

| Mode     | Mean stdev | p-value | Cohen's d |
|----------|-----------|---------|-----------|
| headful  | 0.52ms    | 0.054   | 0.78      |
| headless | 0.41ms    |         |           |

Headful shows marginally higher variance in inter-beacon intervals,
possibly due to GPU frame scheduling jitter (vsync, compositor scheduling).

## Browser Environment Fingerprint

| Property          | Headful       | Headless      | Differs? |
|-------------------|---------------|---------------|----------|
| effectiveType     | 4g            | 4g            | No       |
| downlink          | 1.75          | 1.65          | Minor    |
| rtt               | 50            | 100           | Yes*     |
| innerWidth        | 1280          | 1280          | No       |
| innerHeight       | 720           | 720           | No       |
| outerWidth        | 1288          | 1280          | Yes**    |
| outerHeight       | 805           | 720           | Yes**    |
| devicePixelRatio  | 1             | 1             | No       |
| colorDepth        | 24            | 24            | No       |
| webdriver         | true          | true          | No       |
| hardwareConcurrency | 16          | 16            | No       |
| maxTouchPoints    | 0             | 0             | No       |
| pdfViewerEnabled  | true          | true          | No       |
| scrollbar width   | 15            | 0             | **Yes*** |

*RTT varies between runs (50-100ms range), not a reliable differentiator.
**outerWidth/outerHeight differs because headful has window chrome (title bar, borders).
***scrollbar width = innerWidth - clientWidth; headful has classic scrollbar, headless has overlay/none.

## HTTP Header Comparison

| Header            | Headful                    | Headless                        | Differs? |
|-------------------|----------------------------|---------------------------------|----------|
| user-agent        | Chrome/144.0.0.0           | HeadlessChrome/144.0.0.0        | **YES**  |
| sec-ch-ua         | "Google Chrome";v="144"    | "Google Chrome";v="144"         | No       |
| sec-ch-ua-mobile  | ?0                         | ?0                              | No       |
| sec-ch-ua-platform| "Linux"                    | "Linux"                         | No       |
| sec-fetch-dest    | (varies by resource type)  | (identical)                     | No       |
| sec-fetch-mode    | (varies by resource type)  | (identical)                     | No       |
| accept            | (varies by resource type)  | (identical)                     | No       |

Only user-agent differs. All Sec-CH-* client hints are identical.

## Binary Signal Tests - NO DIFFERENCE

All of the following show identical behavior between headful and headless:

- **Lazy loading**: Same thresholds at all viewport sizes
- **Lazy iframes**: Same load count and max position
- **CSS background images**: All loaded identically
- **Media queries**: All probes identical
- **srcset/picture**: Same selections
- **Font loading**: All strategies identical
- **content-visibility: auto**: Both loaded all elements
- **Video/audio preload**: Identical resource sets
- **Resource hints** (prefetch/preload/modulepreload): Identical
- **Resource request order**: Consistent between modes
- **Scrollbar CSS media queries**: Same viewport width probes (but JS scrollbar width detection WORKS — see finding #5)
- **Print media**: Identical @media behavior
- **Focus/autofocus CSS**: :focus-visible and :focus-within both fire
- **Favicon requests**: Both request declared favicons
- **Meta refresh timing**: Both ~1010ms (within 3ms of each other)
- **CSS env() / viewport units**: dvh/svh/lvh all identical
- **Overflow/scrollbar behavior**: Identical
- **Container queries**: Identical

## Conclusion

Chrome's `--headless=new` shares the same rendering pipeline as headful.
CSS-only binary signals (which resources load) are completely identical.
However, **JS-measured window/scrollbar properties and timing signals
from rendering-intensive pages reveal measurable differences**:

1. Scrollbar width is 15px in headful, 0px in headless (100% binary signal)
2. `outerWidth/outerHeight` match `innerWidth/innerHeight` in headless only
3. Headful has constant GPU/display overhead that masks CSS complexity
4. With 5000+ heavy CSS elements, the timing gap is statistically significant

### Practical Limitations

**Timing signals:**
- Requires very heavy pages (5000+ elements with extreme CSS)
- Single-measurement accuracy is poor; multiple samples needed
- Network latency in production would overwhelm millisecond-scale differences
- Adversary can add artificial delays to match headful timing
- Effect may vary across hardware (GPU vs no GPU)

**JS property signals (scrollbar width, outer/inner gap):**
- Require client-side JS execution (not pure server-side)
- Spoofable by patching DOM property getters, but cross-validation
  with multiple techniques (offscreen div, calc probe) raises the bar

### Detection Hierarchy

| Signal                     | Reliability | Spoofability | Server-side? |
|----------------------------|------------|-------------|-------------|
| Scrollbar width (JS)       | High       | Moderate    | JS→beacon   |
| outer/inner dimension gap  | High       | Moderate    | JS→beacon   |
| User-Agent header          | High       | Trivial     | Yes         |
| Rendering stress span      | Medium     | Moderate    | Yes         |
| Differential timing        | Medium     | Moderate    | Yes         |
| Interval variance          | Low        | Low         | Yes         |
| Ad-tech cascade timing     | None       | N/A         | N/A         |

## Comparison: Chromium (chrome-headless-shell) vs Chrome (new headless)

| Signal              | Chromium headless | Chrome headless |
|---------------------|------------------|-----------------|
| Lazy loading margin | ~3700px (BROKEN) | ~1950px (normal)|
| Network RTT         | 0 (fake)         | 50-100 (real)   |
| Network downlink    | 10 (fake)        | 1.5-1.75 (real) |
| User-Agent          | "Chrome"         | "HeadlessChrome" |
| Rendering timing    | not tested       | p=0.001 @ 5000  |
| Media queries       | identical        | identical       |
| Font loading        | identical        | identical       |
| CSS bg images       | identical        | identical       |

The lazy loading detection ONLY works against `chrome-headless-shell`,
which is what Playwright bundles as its default Chromium.
