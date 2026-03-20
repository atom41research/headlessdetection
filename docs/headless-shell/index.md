---
layout: default
title: Headless Shell
nav_order: 3
has_children: true
---

# Headless Shell

`chrome-headless-shell` is a separate binary from full Chrome. It is a stripped-down build used by automation tools (Puppeteer, Playwright) that removes rendering UI and other components unnecessary for headless operation.

While it shares the same Blink engine, the differences from full Chrome are significant and easily detectable at the network and resource level.

## Key differences from full Chrome

- **Fake network metrics** -- `navigator.connection` reports RTT=0 and downlink=10 Mbps, values that never occur on real connections. This causes a detectable lazy loading threshold shift (images load to 3700 px below the viewport vs 1950 px in headful), providing a 100%-reliable detection signal.
- **Reduced resource footprint** -- the shell strips the GPU process, compositor, and display surface code, resulting in significantly less memory and fewer processes than full Chrome.
- **Higher rates of HTTP/2 errors and server-side blocking** -- servers detect the shell at a higher rate than full Chrome, even with a spoofed User-Agent.

For detailed performance and compatibility analysis, see the companion project [headlessperfbench](https://github.com/atom41research/headlessperfbench).

These differences mean that `chrome-headless-shell` is substantially easier to detect than full Chrome running in headless mode. Any server-side detection system that cannot distinguish full Chrome headless from headful will likely still catch headless-shell through its network behaviour alone.
