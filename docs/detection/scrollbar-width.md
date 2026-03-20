---
layout: default
title: Scrollbar Width
parent: Detection Methods
nav_order: 1
---

# Scrollbar Width Detection

Chrome headful renders classic native scrollbars that occupy approximately 15 pixels of horizontal space, reducing the content area width. Chrome headless uses overlay scrollbars with 0 pixels of width -- the content area extends to the full viewport.

This is a **100% reliable binary signal** with zero overlap between modes.

## How it works

When a page has a vertical scrollbar (content taller than the viewport), the scrollbar consumes horizontal space in headful mode. Three independent JavaScript measurement techniques all confirm the same signal.

### Technique 1: innerWidth minus clientWidth

`window.innerWidth` reports the full viewport width including the scrollbar area. `document.documentElement.clientWidth` reports only the content area width, excluding the scrollbar. Their difference is the scrollbar width.

### Technique 2: Offscreen scrollable div

Create a div with `overflow: scroll` positioned offscreen. The difference between its `offsetWidth` (outer box) and `clientWidth` (inner content area) is the scrollbar width. This technique works even if the page itself has no scrollbar.

### Technique 3: CSS calc computed value

The expression `calc(100vw - 100%)` evaluates to the scrollbar width because `100vw` includes the scrollbar area while `100%` of the body does not. Reading the computed value via `getComputedStyle` yields the scrollbar width in pixels.

## Measurement results

| Technique | Headful | Headless |
|---|---|---|
| `innerWidth - clientWidth` | 15 px | **0 px** |
| Offscreen scrollable div (`offsetWidth - clientWidth`) | 15 px | **0 px** |
| `calc(100vw - 100%)` computed value | 15 px | **0 px** |

All three techniques agree in both modes, providing cross-validation against spoofing attempts that patch only one API surface.

### Statistical confidence

- n=10 runs per mode
- 100% detection rate (headful always 15 px, headless always 0 px)
- Zero overlap between distributions
- Tested at viewport sizes 800x600, 1280x720, and 1920x1080 -- signal holds at all sizes

## Detection code

```javascript
function detectScrollbarWidth() {
  // Technique 1: viewport vs content width
  const t1 = window.innerWidth - document.documentElement.clientWidth;

  // Technique 2: offscreen scrollable div
  const outer = document.createElement('div');
  outer.style.cssText = 'position:absolute;top:-9999px;width:100px;height:100px;overflow:scroll';
  document.body.appendChild(outer);
  const t2 = outer.offsetWidth - outer.clientWidth;
  document.body.removeChild(outer);

  // Technique 3: CSS calc
  const probe = document.createElement('div');
  probe.style.cssText = 'position:absolute;top:-9999px;width:calc(100vw - 100%)';
  document.body.appendChild(probe);
  const t3 = parseFloat(getComputedStyle(probe).width);
  document.body.removeChild(probe);

  // Cross-validate: all three should agree
  const isHeadful = t1 > 0 && t2 > 0 && t3 > 0;
  return { t1, t2, t3, isHeadful };
}
```

If any of the three techniques returns a value greater than 0, the browser is rendering classic scrollbars (headful). If all three return 0, the browser uses overlay scrollbars (headless).

## Server-side integration

The client-side JS measures the scrollbar width and fires a labelled beacon back to the server (`/track/sb-js-detected` or `/track/sb-js-not-detected`). The exact pixel value is also reported (e.g., `/track/sb-js-innerWidth-15` vs `/track/sb-js-innerWidth-0`). See `probes/pages/scrollbar_width.py` for the implementation.

## Spoofability

**Moderate.** An attacker must patch `document.documentElement.clientWidth` to return `innerWidth - N` where N is a plausible scrollbar width for the target OS:

- Linux: 15--17 px (GTK/Qt theme dependent)
- macOS: 15 px (classic scrollbar) or 0 px (overlay, system default)
- Windows: 17 px (default), varies with DPI scaling

The offscreen div technique cross-validates because it uses a different DOM element and different properties (`offsetWidth` and `clientWidth` on a child div). An attacker must patch both code paths consistently.

Additionally, the CSS `calc(100vw - 100%)` approach reads the computed style through a third code path. Intercepting all three requires thorough knowledge of the detection page's structure.

## CSS-only approaches: why they fail

Two CSS-only strategies were tested and found to be non-viable:

1. **Background image on zero-width element.** Chrome loads `background-image` resources even for elements with a computed width of 0 px. A container set to `width: calc(100vw - 100%)` with a background image will trigger the image load regardless of the actual width, so the server cannot distinguish modes by whether the image was requested.

2. **Container queries.** `@container (min-width: 1px)` evaluates to true even on containers with 0 px width in Chrome's current implementation. This makes container queries unusable for detecting zero-width scrollbar containers.

Pure CSS detection of the scrollbar width difference is not viable. JavaScript is required.

## Platform notes

The 15 px scrollbar width measured in testing reflects the default GTK theme on Linux. The exact value varies:

| Platform | Typical scrollbar width |
|---|---|
| Linux (GTK default) | 15 px |
| Linux (KDE/Qt) | 15--17 px |
| Windows 10/11 | 17 px |
| macOS (classic) | 15 px |
| macOS (overlay, default) | 0 px |

On macOS with default settings, the scrollbar width is 0 px in both headful and headless modes because macOS uses overlay scrollbars system-wide. Detection via this signal requires the headful browser to be running on a platform with classic (non-overlay) scrollbars. Linux and Windows are reliable; macOS is not.
