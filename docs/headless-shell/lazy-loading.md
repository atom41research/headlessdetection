---
layout: default
title: Lazy Loading
parent: Headless Shell
nav_order: 1
---

# Lazy Loading Detection (Headless Shell)

`chrome-headless-shell` reports fabricated network connection metrics through the Network Information API. This causes Chrome's lazy loading threshold calculator to compute an inflated scroll margin, loading images far below the visible viewport.

This is a **100% reliable binary signal** for detecting `chrome-headless-shell`, with zero overlap across all test runs.

## Root cause

Chrome's `LazyLoadImageObserver` determines how far below the viewport to begin loading lazy images based on the perceived network quality. Faster connections get larger margins (pre-fetch more aggressively), slower connections get smaller margins.

| Metric | Headful (real) | Headless Shell (fake) |
|---|---|---|
| `navigator.connection.rtt` | 100 ms | **0 ms** |
| `navigator.connection.downlink` | ~1.5 Mbps | **10 Mbps** |
| `navigator.connection.effectiveType` | 4g | 4g |

The shell reports RTT=0 and downlink=10 Mbps -- values that indicate an unrealistically fast connection. Chrome's threshold formula interprets this as "very fast network, pre-fetch aggressively" and computes a scroll margin roughly 2x larger than normal.

## Measurement results

### Default viewport (headful = system window, headless = 1280x720)

| Mode | Loaded images | Max loaded position | Threshold margin |
|---|---|---|---|
| Headful | 40 | 1950 px | ~1230 px |
| Headless Shell | 75 | 3700 px | ~2980 px |

### Matched viewport 1280x720

| Mode | Loaded images | Max loaded position |
|---|---|---|
| Headful | 31 | 1500 px |
| Headless Shell | 75 | 3700 px |

### Small viewport 400x300

| Mode | Loaded images | Max loaded position |
|---|---|---|
| Headful | 31 | 1500 px |
| Headless Shell | 66 | 3250 px |

## Detection approach

Place `<img loading="lazy">` elements at known scroll offsets down the page. After page load (without scrolling), check which images were loaded by the browser. If images at positions beyond ~2000 px are loaded, the browser is using an inflated lazy loading threshold consistent with headless-shell's fake network metrics.

```javascript
// After page load, check which lazy images were loaded
const images = document.querySelectorAll('img[loading="lazy"]');
let maxLoadedPosition = 0;
images.forEach(img => {
  if (img.complete && img.naturalHeight > 0) {
    maxLoadedPosition = Math.max(maxLoadedPosition, img.offsetTop);
  }
});

// Headful: ~1500-1950px, Headless Shell: ~3250-3700px
if (maxLoadedPosition > 2500) {
  // Likely chrome-headless-shell
}
```

## Consistency

- **Zero overlap** across 5 independent runs per mode
- **Viewport independent**: the threshold difference holds at 400x300, 1280x720, and custom sizes
- **Image size independent**: image dimensions (1x1 through 500x500) do not affect the threshold
- **srcset/picture**: same behavior with responsive image markup
- **Lazy iframes**: same pattern (headful loads to ~3000 px, shell loads to ~4500 px)
- **CSS background images**: not affected (not subject to lazy loading)

## Critical limitation

This detection **does NOT work against Chrome's new headless mode** (`--headless=new`). Full Chrome headless reports real network metrics identical to headful Chrome (RTT=50--100 ms, downlink=1.5--1.75 Mbps). The lazy loading threshold in Chrome headless matches headful exactly.

This signal is specific to `chrome-headless-shell`, which is the binary Playwright bundles as its default Chromium (`chromium-headless-shell` channel). It will not detect automation using system Chrome with `channel="chrome"`.
