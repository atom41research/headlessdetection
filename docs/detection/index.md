---
layout: default
title: Detection Methods
nav_order: 2
has_children: true
---

# Detection Methods

The approach is straightforward: test every observable signal between Chrome headful and Chrome headless, then report which ones actually differ.

Out of 20+ signals tested, only 4 produce measurable differences between the two modes:

1. **Scrollbar width** -- headful Chrome renders native scrollbars at 15 px wide; headless renders overlay scrollbars at 0 px. This is a 100% reliable binary signal.
2. **Window chrome gap** -- headful Chrome reports an 8 px horizontal and 85 px vertical gap between `window.outerWidth/Height` and `window.innerWidth/Height` (accounting for window frame and toolbar); headless reports 0/0. Also 100% reliable.
3. **Rendering stress timing** -- under a sustained CSS animation + layout stress workload, headful averages ~97 ms per frame while headless averages ~87 ms. The difference is statistically significant (p=0.001) but requires multiple samples to distinguish reliably.
4. **sec-ch-ua header** -- the client hint header contains `HeadlessChrome` in headless mode. This is trivially spoofable and should not be relied upon for detection.

Everything else tested -- lazy loading, media queries, installed fonts, CSS `@supports` chains, WebGL renderer strings, plugin lists, permission states, and more -- is identical across headful and headless Chrome.
