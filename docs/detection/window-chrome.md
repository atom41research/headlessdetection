---
layout: default
title: Window Chrome
parent: Detection Methods
nav_order: 2
---

# Window Chrome Detection

In headful Chrome, the browser window includes non-content UI elements: a title bar, tab strip, toolbar, and window borders. These cause `window.outerWidth` and `window.outerHeight` to be larger than `window.innerWidth` and `window.innerHeight`. In headless mode, there is no window chrome, so `outer === inner`.

This is a **100% reliable binary signal** with zero overlap between modes.

## Measurement results

| Property | Headful | Headless | Signal |
|---|---|---|---|
| `outerWidth - innerWidth` | 8 px | **0 px** | Binary |
| `outerHeight - innerHeight` | 85 px | **0 px** | Binary |
| `outerWidth === innerWidth` | false | **true** | 100% reliable |

The 8 px horizontal delta accounts for the window border on Linux. The 85 px vertical delta accounts for the title bar, tab strip, and toolbar. These values are platform-specific but the key signal -- whether the delta is zero or non-zero -- is universal.

## Viewport independence

Tested across three viewport sizes:

| Viewport | Headful outerWidth - innerWidth | Headful outerHeight - innerHeight | Headless delta |
|---|---|---|---|
| 800 x 600 | 8 px | 85 px | 0 / 0 |
| 1280 x 720 | 8 px | 85 px | 0 / 0 |
| 1920 x 1080 | 8 px | 85 px | 0 / 0 |

The signal holds at all viewport sizes. The headful deltas are constant because window chrome dimensions do not scale with the content viewport.

## Detection code

```javascript
function detectWindowChrome() {
  const widthDelta = window.outerWidth - window.innerWidth;
  const heightDelta = window.outerHeight - window.innerHeight;

  if (widthDelta === 0 && heightDelta === 0) {
    return 'headless';
  }
  return 'headful';
}
```

## Iframe behavior

The signal works inside iframes. `contentWindow.outerWidth` and `contentWindow.outerHeight` read from the top-level window, so the delta is preserved regardless of iframe nesting depth.

## Server-side gating

`probes/pages/outer_inner.py` implements a full server-side gating mechanism:

1. The page loads with a sync XHR beacon that sends the `outerWidth - innerWidth` and `outerHeight - innerHeight` deltas to the server before any other resources are requested.
2. The server examines the deltas. If both are zero, it identifies the client as headless and refuses to serve subsequent resources (images, stylesheets, scripts).
3. If the deltas are non-zero, the server serves all resources normally.

Test results: headful Chrome received 3/3 gated resources. Headless Chrome received 0/3.

This approach is effective because the sync XHR fires before the browser requests any dependent resources, giving the server a classification signal before it commits to serving content.

## Spoofability

**Moderate.** An attacker must patch both `window.outerWidth` and `window.outerHeight` getters to return values larger than `innerWidth` and `innerHeight` by plausible platform-specific deltas:

| Platform | Typical horizontal delta | Typical vertical delta |
|---|---|---|
| Linux (GNOME/KDE) | 8 px | 85 px |
| macOS | 0 px | 28 px |
| Windows | 16 px | 39 px |

Returning the wrong delta for the claimed platform (e.g., reporting macOS deltas while `navigator.platform` says Linux) is itself a detection signal. The attacker must ensure consistency across all exposed platform indicators.

Patching `outerWidth`/`outerHeight` via `Object.defineProperty` on the window object is detectable by checking whether the property descriptor has been modified (e.g., checking `Object.getOwnPropertyDescriptor(window, 'outerWidth').get` identity).

## Limitations

- Requires client-side JavaScript execution. Cannot be detected via CSS media queries or HTTP headers alone.
- On macOS, the horizontal delta is 0 px even in headful mode (no visible window border), so the horizontal check alone is insufficient. The vertical delta (28 px for the title bar) is still non-zero.
- Fullscreen/kiosk mode sets `outerWidth === innerWidth` and `outerHeight === innerHeight` even in headful mode. An attacker could claim kiosk mode to justify zero deltas, but kiosk mode is unusual for normal browsing and is itself a signal.
