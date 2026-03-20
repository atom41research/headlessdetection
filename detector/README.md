# Headless Detector

A detection server that differentiates Chrome's **new headless** mode from headful, even when the client uses stealth flags (`--disable-blink-features=AutomationControlled`, spoofed UA, system Chrome).

## Prerequisites

```bash
uv sync
uv run playwright install chrome
```

## Quick start (local)

```bash
# Start the server
uv run uvicorn detector.server:app --port 8099

# Run the test suite (headful + headless, direct + iframe)
uv run python -m detector.cli --runs 3
```

Visit `http://localhost:8099` in a browser to see the probes run interactively.
Visit `http://localhost:8099/iframe` for the same probes inside an 800x600 iframe.

## Docker

```bash
cd detector

# Run the server (accessible at http://localhost:8099)
docker compose up

# Run the full test suite inside Docker
docker compose run --rm detector test --runs 3

# Build only
docker compose build
```

To deploy on a dedicated server:

```bash
# Run in background, restart on failure
docker compose up -d

# View logs
docker compose logs -f
```

The container includes Xvfb (virtual display) so headful Chrome works inside Docker.

## How it works

The server serves an HTML page with client-side JavaScript probes. The browser runs the probes and POSTs results back. The server scores each probe with a weighted system and returns a verdict.

### Probes

| # | Probe | Headful | Headless | Weight | Survives Docker? |
|---|---|---|---|---|---|
| 1 | **Frame Timing Jitter** | stddev 1-12ms | stddev 0.05ms | 2 | No (Xvfb is also synthetic) |
| 2 | **Window Chrome** | outer > inner | outer == inner | 5 | Yes |
| 3 | **Scrollbar Width** | 15px | 0px | 4 | Yes |
| 4 | **Canvas Fingerprint** | dataURL len 4390 | dataURL len 4534 | info | No (identical in Docker) |
| 5 | **WebGL Timer Extension** | present | missing | 1 | No (missing for both in Docker) |
| 6 | **WebGL Extension Count** | GL1=36, GL2=30 | GL1=35, GL2=29 | info | No |
| 7 | **Screen Position** | (0, 0) | (10, 10) | 1 | No (both 10,10 in Docker) |
| 8 | **sec-ch-ua Brand** | Chrome | HeadlessChrome (shell only) | 3 | Yes (server-side) |
| 9 | **Accept-Language** | present | absent (shell only) | 1 | Yes (server-side) |

Probes 1-7 run client-side in JavaScript. Probes 8-9 run server-side via HTTP header inspection. Window Chrome and Scrollbar Width are the two anchors that work **everywhere** -- bare metal, VM, Docker, any resolution, any page, inside iframes.

### Scoring

Positive score = headless signal, negative = headful. Total > 0 means headless.

| Environment | Headful | Headless (new) | Headless-shell |
|---|---|---|---|
| Bare metal | **-17** | **+9** | **+15** |
| Docker | **-13** | **+9** | **+15** |

### What doesn't work (stealth flags active)

| Signal | Why it fails |
|---|---|
| `navigator.webdriver` | `true` in both modes (identical, not a differentiator) |
| WebGL renderer (SwiftShader) | Both modes use SwiftShader on hosts without a discrete GPU |
| Permission shadows | Both return `query=prompt, notification=default` |
| `navigator.plugins` | Both report 5 plugins with identical names |
| `chrome.csi` / `chrome.loadTimes` | Both present |
| `document.hasFocus()` | Both return `true` |
| `screen.availWidth/Height` | Both match `screen.width/height` |

## Files

| File | Purpose |
|---|---|
| `server.py` | FastAPI server with probe scoring logic and detection HTML |
| `cli.py` | Playwright test harness (both modes, direct + iframe pages) |
| `Dockerfile` | Container with Chrome, Xvfb, and all dependencies |
| `docker-compose.yml` | Run server or tests with one command |
| `entrypoint.sh` | Starts Xvfb, then runs server or test mode |
