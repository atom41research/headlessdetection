# headlessdetection

Empirical framework for detecting Chrome headless mode -- which signals work, which don't, and why.

> Supporting material for [publication placeholder -- will be updated].

---

## Detection signals: Chrome headful vs headless

Chrome's `--headless=new` mode shares the same binary and rendering pipeline as headful Chrome. Most detection strategies people assume would work simply do not. The table below separates the signals that survived testing from the ones that didn't.

| Signal | Headful | Headless | Reliability | Spoofability |
|---|---|---|---|---|
| **Scrollbar width** | 15 px | 0 px | 100 % | Moderate |
| **Window chrome** (outer - inner) | 8 / 85 px | 0 / 0 px | 100 % | Moderate |
| **Rendering stress timing** | ~97 ms | ~87 ms | p = 0.001, d = 1.35 | Low |
| **Differential timing** | similar H/L | heavy > light | p = 0.003, d = -1.32 | Low |
| sec-ch-ua header | Chrome/... | HeadlessChrome/... | 100 % | Trivial |
| Lazy loading thresholds | identical | identical | -- | -- |
| CSS media queries (22 probes) | identical | identical | -- | -- |
| Font loading behavior | identical | identical | -- | -- |
| CSS @import chain timing | identical | identical | -- | -- |
| Background image chains | identical | identical | -- | -- |
| Resource request ordering | identical | identical | -- | -- |

The "identical" rows are not padding. They document negative results -- hypotheses we tested and rejected. Every row cost investigation time, and knowing what does not work is as valuable as knowing what does.

### Detection code

The two strongest signals require only trivial JS:

```javascript
// Scrollbar width: 15 in headful, 0 in headless
const scrollbarWidth = window.innerWidth - document.documentElement.clientWidth;

// Window chrome: headful has outer > inner, headless has outer === inner
if (window.outerWidth === window.innerWidth &&
    window.outerHeight === window.innerHeight) {
  // headless
}
```

Scrollbar width is measured three independent ways (innerWidth - clientWidth, offscreen scrollable div, `calc(100vw - 100%)` computed style). All three agree: 15 px headful, 0 px headless, across every viewport size tested. The window chrome signal exploits the fact that headless Chrome has no title bar, borders, or tab strip -- `outerWidth === innerWidth` is a binary indicator with zero overlap across 10 runs at three viewport sizes.

Both signals are spoofable by patching DOM property getters, but cross-validation between techniques raises the bar. An attacker who patches `clientWidth` but not the offscreen-div method is caught.

---

## Detection signals: Chrome vs chrome-headless-shell

`chrome-headless-shell` is a stripped binary distributed by Chrome for Testing (what Playwright bundles as its default "chromium"). It is a fundamentally different target than Chrome's `--headless=new`.

Key detection-relevant findings:

- **Fake network metrics** (RTT = 0, downlink = 10 Mbps) cause a detectable lazy loading threshold shift: images load to 3700 px below the viewport vs 1950 px in headful. This is a 100%-reliable binary signal across all viewport sizes.
- **Significant resource and compatibility differences** -- the shell strips the GPU process, compositor, and display surface code, and exhibits higher rates of HTTP/2 errors and server-side blocking. Detailed performance analysis is available in the companion project [headlessperfbench](https://github.com/atom41research/headlessperfbench).

The shell binary is easier to detect and harder to disguise. If your automation uses Playwright's default Chromium channel, you are running a different browser than your users.

---

## Quick start

```bash
# Install
git clone https://github.com/atom41research/headlessdetection.git
cd headlessdetection
uv sync
uv run playwright install chrome

# Run the detection server (visit http://localhost:8099 in Chrome)
uv run uvicorn detector.server:app --port 8099

# Run quick experiments (~5 min, reliable signals)
uv run python -m experiments --quick

# Run all experiments (~60 min, all signals)
uv run python -m experiments --all

# List available experiments
uv run python -m experiments --list

# Start the probe server (individual detection pages)
uv run python scripts/run_server.py
```

---

## Project structure

```
core/                  Shared config, browser helpers, storage, analysis, TLS
detector/              Standalone detection server with weighted scoring
probes/                Research probe server -- 18 detection test pages
experiments/           Investigation scripts and experiment runner
rendering_comparison/  Side-by-side headful vs headless rendering
docs/                  Results data and GitHub Pages site
data/                  Raw experimental data
scripts/               Utility scripts (server runner, data processing)
```

---

## How it works

The probe server (`probes/`) serves HTML pages, each testing one detection hypothesis. Pages contain JS probes that fire tracking beacons back to the server. The server records all requests per session. Investigation scripts then launch Chrome in different modes (headful, headless, headless-shell), visit the pages, and the analysis module computes statistical significance using Mann-Whitney U tests and Cohen's d effect sizes.

The detector (`detector/`) is the operational version -- a single server that runs all viable detection probes with a weighted scoring system. Visit it in any browser and it immediately tells you whether you are headful or headless. No client-side libraries, no fingerprinting SDKs. Just the signals that survived empirical testing.

---

## Requirements

- Python 3.12+
- System Chrome (not Chromium)
- Playwright (`uv run playwright install chrome`)

---

## Citation

If you use this framework or data in your research, please cite:

```
[Citation will be added upon publication]
```

---

## License

AGPL-3.0-or-later
