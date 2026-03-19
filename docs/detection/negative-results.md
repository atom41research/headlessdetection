---
layout: default
title: Negative Results
parent: Detection Methods
nav_order: 5
---

# Negative Results

This page documents detection signals that were tested and found to produce **no measurable difference** between Chrome headful and Chrome headless (`--headless=new`). These negative results are as important as the positive ones -- they define the boundary of what is and is not detectable.

All tests used system Chrome (not Chromium or headless-shell) with `channel="chrome"` and `--disable-blink-features=AutomationControlled`.

## Lazy loading thresholds

Chrome uses identical viewport-based threshold calculations for lazy-loaded images in both headful and headless modes. The `LazyLoadImageObserver` computes its scroll margin based on `navigator.connection` metrics (effectiveType, RTT, downlink), and Chrome headless (`--headless=new`) reports real network metrics identical to headful. Both modes load the same number of lazy images at every viewport size tested (800x600, 1280x720, 1920x1080).

This is in contrast to `chrome-headless-shell`, which reports fake network metrics (RTT=0, downlink=10 Mbps) and does show a different lazy loading threshold. See [Lazy Loading (Headless Shell)](../headless-shell/lazy-loading.md).

## CSS media queries (22 probes)

Twenty-two CSS media feature queries were tested, all producing identical results across headful and headless:

- `prefers-color-scheme` (light/dark)
- `prefers-reduced-motion` (no-preference/reduce)
- `prefers-contrast` (no-preference/more/less/custom)
- `hover` (none/hover)
- `pointer` (none/coarse/fine)
- `any-hover` (none/hover)
- `any-pointer` (none/coarse/fine)
- `color` (bit depth)
- `color-gamut` (srgb/p3/rec2020)
- `display-mode` (browser/standalone/minimal-ui/fullscreen)
- `dynamic-range` (standard/high)
- `forced-colors` (none/active)
- `inverted-colors` (none/inverted)
- `monochrome` (0 or bit depth)
- `orientation` (portrait/landscape)
- `overflow-block` (none/scroll/paged)
- `overflow-inline` (none/scroll)
- `resolution` (dpi/dpcm/dppx)
- `scripting` (none/initial-only/enabled)
- `update` (none/slow/fast)
- `width` (viewport width breakpoints)
- `height` (viewport height breakpoints)

Each query was tested via both CSS `@media` rules (checking which background images load) and JavaScript `window.matchMedia()`. All results were identical in both modes. Chrome headless fully emulates all media features matching headful behavior.

## Font loading

All three `font-display` strategies were tested: `swap`, `block`, and `optional`. In every case, the font loading sequence, timing, and final rendering were identical between headful and headless. Both modes request the same font files in the same order, and the fallback/swap behavior triggers at the same thresholds.

## CSS @import chain timing

Chains of CSS `@import` statements (up to 10 levels deep) were timed by placing beacon images at each chain step. While individual chain steps showed moderate effect sizes (Cohen's d of 0.5--1.4), the high variance across runs meant no chain depth produced a statistically significant difference at n=5. The import chain processing speed is not measurably different between modes.

## Background image chains

CSS background images loaded through multi-level chains (element A triggers image B, which loads stylesheet C, which triggers image D) were tested. Under default conditions, effect sizes were small (d < 0.5) and not significant. Under matched viewport conditions, medium effects appeared (d ~ 0.6) but headful was actually _slower_ (~250 ms vs ~130 ms), likely due to window management overhead. The direction and magnitude of any difference are too unstable for detection.

## Resource request ordering

The sequence of HTTP requests generated during page load was compared between modes. Both headful and headless Chrome issue requests in the same order for the same set of resources. There is no detectable difference in resource prioritization, preload scanning behavior, or speculative parsing between modes.

## Print media detection

CSS `@media print` rules fire identically in both modes. Both headful and headless Chrome apply print stylesheets when instructed via `window.matchMedia('print')` or `page.emulateMedia({ media: 'print' })`. The print rendering path does not differ.

## Lazy iframe loading

Iframes with `loading="lazy"` behave identically in both modes. The same number of iframes load, and the maximum scroll position of loaded iframes is consistent across headful and headless. (Again, this differs for `chrome-headless-shell`, which loads more lazy iframes due to its inflated lazy loading threshold.)

## srcset image selection

`<img srcset="...">` and `<picture><source>` elements select the same image candidate in both modes. Chrome evaluates the `sizes` attribute, viewport width, and device pixel ratio identically regardless of headless mode. There is no difference in image selection logic.

## Canvas fingerprint

Canvas fingerprinting (drawing text and shapes to a `<canvas>` element and hashing the resulting pixel data) produces different hashes between headful and headless -- but the hash also differs between _any two machines_ with different GPU hardware, drivers, or font rendering configurations. Without a pre-computed reference hash for the specific machine, a canvas fingerprint cannot distinguish headful from headless. It is a machine identifier, not a mode identifier.

## Content-visibility: auto

Elements styled with `content-visibility: auto` are rendered identically in both modes. Both headful and headless Chrome process all elements in the DOM regardless of viewport visibility when `content-visibility: auto` is used, loading all associated resources.

## Video/audio preload

`<video>` and `<audio>` elements with various `preload` attributes (`auto`, `metadata`, `none`) generate identical resource request patterns in both modes.

## Resource hints

`<link rel="prefetch">`, `<link rel="preload">`, and `<link rel="modulepreload">` all trigger identical resource fetches in both modes.

## Focus and autofocus CSS

CSS selectors `:focus-visible` and `:focus-within` fire identically when an element has the `autofocus` attribute. Both modes apply focus-related styles consistently.

## Meta refresh timing

`<meta http-equiv="refresh" content="1">` triggers a page refresh after approximately 1010 ms in both modes, with less than 3 ms variance between them.

## CSS env() and viewport units

Dynamic viewport units (`dvh`, `svh`, `lvh`) and `env(safe-area-inset-*)` evaluate to the same values in both modes. There is no difference in how Chrome resolves these CSS values between headful and headless.

## Summary

Chrome's `--headless=new` mode shares the same Blink rendering engine and browser pipeline as headful Chrome. The only detectable differences are at the OS integration layer: scrollbar rendering, window chrome dimensions, and GPU compositing overhead. All content-level signals -- resource loading, CSS evaluation, media queries, font handling, and DOM behavior -- are identical.
