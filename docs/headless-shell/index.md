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

- **26% less memory** -- container active memory drops from 563 MB (headless) to 436 MB
- **31% fewer processes** -- average process count drops from 10.5 to 7.2
- **Fake network metrics** -- `navigator.connection` reports RTT=0 and downlink=10 Mbps, values that never occur on real connections
- **36 exclusive HTTP/2 protocol errors** -- across 965 URLs, headless-shell triggers 36 protocol-level errors that never appear in full Chrome headless or headful modes
- **3.2x more HTTP 403 responses** -- servers block headless-shell at a significantly higher rate than full Chrome
- **6.3% content divergence** -- page content differs from full Chrome headless on 6.3% of tested URLs, measured by DOM structure comparison

These differences mean that `chrome-headless-shell` is substantially easier to detect than full Chrome running in headless mode. Any server-side detection system that cannot distinguish full Chrome headless from headful will likely still catch headless-shell through its network behaviour alone.
