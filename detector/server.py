"""Detection server that differentiates Chrome new-headless from headful.

Every probe listed here actually differentiates on this machine with stealth
flags active (--disable-blink-features=AutomationControlled, spoofed UA).

Verified probes:
  1. Frame Timing Jitter   — synthetic VSync stddev < 0.3ms vs natural 1-5ms
  2. Window Chrome          — outer == inner means no title bar / borders
  3. Scrollbar Width        — headless renders 0px scrollbars, headful 15px
  4. Canvas Fingerprint     — sub-pixel rendering differs → different image
  5. WebGL Timer Extension  — EXT_disjoint_timer_query missing in headless
  6. WebGL Extension Count  — headless has fewer (GL1: 35 vs 36, GL2: 29 vs 30)
  7. Screen Position        — headless defaults screenX/Y to 10,10

Each test scores +N (headless signal) or -N (headful signal).
Weighted sum > 0 → headless.

Usage:
    uv run uvicorn detector.server:app --port 8099
"""

import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from core.storage import (
    get_all_detections,
    get_detection,
    get_stats,
    init_db,
    save_detection,
)

app = FastAPI(title="Headless Detector")


@app.on_event("startup")
def startup():
    init_db()


class ProbeResults(BaseModel):
    session_id: str
    # 1. Frame timing
    frame_deltas: list[float] = []
    avg_delta: float = 0.0
    delta_stddev: float = 0.0
    # 2. Window chrome
    outer_width: int = 0
    outer_height: int = 0
    inner_width: int = 0
    inner_height: int = 0
    # 3. Scrollbar width
    scrollbar_width: int = -1
    # 4. Canvas fingerprint
    canvas_hash: int = 0
    canvas_pixel: list[int] = []
    # 5. WebGL timer extension
    has_timer_ext: bool = False
    # 6. WebGL extension count
    webgl1_ext_count: int = 0
    webgl2_ext_count: int = 0
    webgl_renderer: str = ""
    # 7. Screen position
    screen_x: int = 0
    screen_y: int = 0
    # Context
    user_agent: str = ""


def compute_verdict(p: ProbeResults, request_headers: dict[str, str] | None = None) -> dict:
    tests = {}

    # ── 1. Frame timing jitter ────────────────────────────────
    # Weight 2: unreliable in VM/Docker (Xvfb also has synthetic VSync)
    if p.frame_deltas:
        avg, stddev = p.avg_delta, p.delta_stddev
        vsync_like = abs(avg - 16.67) < 4.0 or abs(avg - 8.33) < 2.0
        if not vsync_like:
            tests["frame_timing"] = {
                "score": 2,
                "verdict": "headless",
                "reason": f"non-VSync avg={avg:.2f}ms, stddev={stddev:.2f}ms",
            }
        else:
            synthetic = stddev < 0.3
            tests["frame_timing"] = {
                "score": 2 if synthetic else -2,
                "verdict": "headless" if synthetic else "headful",
                "reason": f"avg={avg:.2f}ms, stddev={stddev:.2f}ms"
                          + (" — synthetic VSync" if synthetic else " — natural jitter"),
            }
    else:
        tests["frame_timing"] = {"score": 0, "verdict": "unknown", "reason": "no data"}

    # ── 2. Window chrome ──────────────────────────────────────
    # Weight 5: most reliable — works everywhere including Docker/VM
    if p.outer_width > 0 and p.inner_width > 0:
        no_chrome = p.outer_width == p.inner_width and p.outer_height == p.inner_height
        tests["window_chrome"] = {
            "score": 5 if no_chrome else -5,
            "verdict": "headless" if no_chrome else "headful",
            "reason": f"outer={p.outer_width}x{p.outer_height}, inner={p.inner_width}x{p.inner_height}",
        }
    else:
        tests["window_chrome"] = {"score": 0, "verdict": "unknown", "reason": "no data"}

    # ── 3. Scrollbar width ────────────────────────────────────
    # Weight 4: very reliable — works everywhere including Docker/VM
    if p.scrollbar_width >= 0:
        no_scrollbar = p.scrollbar_width == 0
        tests["scrollbar_width"] = {
            "score": 4 if no_scrollbar else -4,
            "verdict": "headless" if no_scrollbar else "headful",
            "reason": f"scrollbar={p.scrollbar_width}px",
        }
    else:
        tests["scrollbar_width"] = {"score": 0, "verdict": "unknown", "reason": "no data"}

    # ── 4. Canvas fingerprint ─────────────────────────────────
    # We can't set a fixed threshold — but we log the hash for comparison.
    # The fact that the data URL length differs is the signal.
    if p.canvas_hash > 0:
        tests["canvas_fp"] = {
            "score": 0,  # informational: differs, but no reference to compare against
            "verdict": "informational",
            "reason": f"dataURL_len={p.canvas_hash}, pixel={p.canvas_pixel}",
        }
    else:
        tests["canvas_fp"] = {"score": 0, "verdict": "unknown", "reason": "no data"}

    # ── 5. WebGL timer extension ──────────────────────────────
    # Weight 1: unreliable in Docker/VM (missing for both modes under SwiftShader)
    tests["webgl_timer"] = {
        "score": -1 if p.has_timer_ext else 1,
        "verdict": "headful" if p.has_timer_ext else "headless",
        "reason": f"EXT_disjoint_timer_query={'present' if p.has_timer_ext else 'missing'}",
    }

    # ── 6. WebGL extension count ──────────────────────────────
    if p.webgl1_ext_count > 0:
        tests["webgl_ext_count"] = {
            "score": 0,
            "verdict": "informational",
            "reason": f"GL1={p.webgl1_ext_count}, GL2={p.webgl2_ext_count}, renderer={p.webgl_renderer!r}",
        }
    else:
        tests["webgl_ext_count"] = {"score": 0, "verdict": "unknown", "reason": "no data"}

    # ── 7. Screen position ────────────────────────────────────
    # Headless Playwright defaults to screenX=10, screenY=10
    # Headful typically starts at 0,0 (or WM-determined)
    # This is fragile: only use as tiebreaker (low weight)
    if p.screen_x == 10 and p.screen_y == 10:
        tests["screen_position"] = {
            "score": 1,
            "verdict": "headless",
            "reason": f"screenX={p.screen_x}, screenY={p.screen_y} (Playwright default)",
        }
    else:
        tests["screen_position"] = {
            "score": -1,
            "verdict": "headful",
            "reason": f"screenX={p.screen_x}, screenY={p.screen_y}",
        }

    # ── 8. sec-ch-ua brand (server-side) ─────────────────────
    # Weight 3: chrome-headless-shell exposes "HeadlessChrome" in the
    # sec-ch-ua Client Hints header. This is set by the browser engine
    # and cannot be overridden via Playwright's user_agent option.
    if request_headers:
        sec_ch_ua = request_headers.get("sec-ch-ua", "")
        if sec_ch_ua:
            has_headless_brand = "HeadlessChrome" in sec_ch_ua
            tests["sec_ch_ua_brand"] = {
                "score": 3 if has_headless_brand else -3,
                "verdict": "headless" if has_headless_brand else "headful",
                "reason": f"sec-ch-ua={sec_ch_ua!r}" + (" — HeadlessChrome brand detected" if has_headless_brand else ""),
            }
        else:
            tests["sec_ch_ua_brand"] = {"score": 0, "verdict": "unknown", "reason": "sec-ch-ua header absent"}
    else:
        tests["sec_ch_ua_brand"] = {"score": 0, "verdict": "unknown", "reason": "no request headers available"}

    # ── 9. accept-language presence (server-side) ──────────
    # Weight 1: chrome-headless-shell omits accept-language entirely.
    # Low weight because absence could have other explanations.
    if request_headers:
        has_accept_lang = bool(request_headers.get("accept-language", ""))
        tests["accept_language"] = {
            "score": -1 if has_accept_lang else 1,
            "verdict": "headful" if has_accept_lang else "headless",
            "reason": f"accept-language={'present' if has_accept_lang else 'absent'}",
        }
    else:
        tests["accept_language"] = {"score": 0, "verdict": "unknown", "reason": "no request headers available"}

    # ── Weighted verdict ──────────────────────────────────────
    total_score = sum(t["score"] for t in tests.values())
    overall = "headless" if total_score > 0 else "headful"
    headless_count = sum(1 for t in tests.values() if t["verdict"] == "headless")
    headful_count = sum(1 for t in tests.values() if t["verdict"] == "headful")

    return {
        "overall": overall,
        "total_score": total_score,
        "headless_signals": headless_count,
        "headful_signals": headful_count,
        "tests": tests,
    }


# ── Routes ───────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def detection_page():
    return HTMLResponse(content=DETECTION_HTML, headers={"Cache-Control": "no-store"})


@app.get("/iframe", response_class=HTMLResponse)
async def iframe_page():
    """Identical detection probes but served inside a fixed-size iframe.
    Window chrome (outer==inner) holds even inside iframes because the
    iframe's contentWindow still reflects the top-level browser window."""
    return HTMLResponse(
        content=IFRAME_HOST_HTML,
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/session")
async def new_session():
    return {"session_id": uuid.uuid4().hex[:12]}


@app.post("/api/results")
async def submit_results(probe: ProbeResults, request: Request):
    headers = dict(request.headers)
    verdict = compute_verdict(probe, request_headers=headers)
    client_ip = request.client.host if request.client else None
    save_detection(
        session_id=probe.session_id,
        probe=probe.model_dump(),
        verdict=verdict,
        client_ip=client_ip,
        request_headers=headers,
    )
    return JSONResponse(content={"session_id": probe.session_id, "verdict": verdict})


@app.get("/api/results/{session_id}")
async def get_results(session_id: str):
    result = get_detection(session_id)
    if not result:
        return JSONResponse(content={"error": "not found"}, status_code=404)
    return JSONResponse(content=result)


@app.get("/api/all-results")
async def list_results():
    results = get_all_detections()
    # Return as dict keyed by session_id for backwards compatibility
    return JSONResponse(content={r["session_id"]: r for r in results})


@app.get("/api/stats")
async def detection_stats():
    return JSONResponse(content=get_stats())


# ── Shared JS probes (used by both direct page and iframe) ───────────

PROBE_JS = r"""
async function runProbes(session_id) {
  const r = { session_id };

  // 1. Frame timing
  const deltas = await new Promise(resolve => {
    const d = [];
    let last = null, count = 0;
    function tick(ts) {
      if (last !== null) d.push(ts - last);
      last = ts;
      if (++count < 100) requestAnimationFrame(tick);
      else resolve(d);
    }
    requestAnimationFrame(tick);
  });
  r.frame_deltas = deltas;
  const avg = deltas.reduce((a,b) => a+b, 0) / deltas.length;
  const stddev = Math.sqrt(deltas.reduce((a,d) => a + (d - avg) ** 2, 0) / deltas.length);
  r.avg_delta = avg;
  r.delta_stddev = stddev;

  // 2. Window chrome — always reads from the TOP window
  const top = window.top || window;
  r.outer_width = top.outerWidth;
  r.outer_height = top.outerHeight;
  r.inner_width = top.innerWidth;
  r.inner_height = top.innerHeight;

  // 3. Scrollbar width
  const outer = document.createElement('div');
  outer.style.cssText = 'width:100px;height:100px;overflow:scroll;position:absolute;top:-9999px;visibility:hidden;';
  document.body.appendChild(outer);
  const inner = document.createElement('div');
  inner.style.cssText = 'width:100%;height:200px;';
  outer.appendChild(inner);
  r.scrollbar_width = outer.offsetWidth - outer.clientWidth;
  document.body.removeChild(outer);

  // 4. Canvas fingerprint
  try {
    const c = document.createElement('canvas');
    c.width = 200; c.height = 50;
    const ctx = c.getContext('2d');
    ctx.textBaseline = 'top';
    ctx.font = '14px Arial';
    ctx.fillStyle = '#f60';
    ctx.fillRect(50, 0, 100, 50);
    ctx.fillStyle = '#069';
    ctx.fillText('Cwm fjord veg', 2, 15);
    ctx.fillStyle = 'rgba(102, 204, 0, 0.7)';
    ctx.fillText('quiz, blank', 4, 30);
    r.canvas_hash = c.toDataURL().length;
    const px = ctx.getImageData(75, 25, 1, 1).data;
    r.canvas_pixel = Array.from(px);
  } catch(e) { r.canvas_hash = 0; r.canvas_pixel = []; }

  // 5. WebGL timer extension
  try {
    const c = document.createElement('canvas');
    const gl = c.getContext('webgl');
    if (gl) {
      r.has_timer_ext = !!gl.getExtension('EXT_disjoint_timer_query');
      const exts = gl.getSupportedExtensions() || [];
      r.webgl1_ext_count = exts.length;
      const dbg = gl.getExtension('WEBGL_debug_renderer_info');
      r.webgl_renderer = dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER);
    }
  } catch(e) {}

  // 6. WebGL2 extension count
  try {
    const c2 = document.createElement('canvas');
    const gl2 = c2.getContext('webgl2');
    if (gl2) {
      r.webgl2_ext_count = (gl2.getSupportedExtensions() || []).length;
    }
  } catch(e) {}

  // 7. Screen position
  r.screen_x = window.top.screenX;
  r.screen_y = window.top.screenY;
  r.user_agent = navigator.userAgent;

  return r;
}
"""

# ── Detection page HTML ──────────────────────────────────────────────

DETECTION_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Headless Detection</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: system-ui, sans-serif; background: #0f0f0f; color: #e0e0e0; padding: 2rem; }
  h1 { margin-bottom: 1rem; font-size: 1.4rem; }
  .test { margin: 0.8rem 0; padding: 0.8rem 1rem; border: 1px solid #333; border-radius: 6px; }
  .test h2 { font-size: 0.95rem; margin-bottom: 0.3rem; }
  .status { font-size: 0.85rem; color: #888; }
  .pass { color: #4caf50; }
  .fail { color: #f44336; }
  .info { color: #42a5f5; }
  #verdict { margin-top: 1.5rem; padding: 1rem; border-radius: 6px; font-size: 1.2rem; font-weight: bold; }
  .verdict-headful { background: #1b5e20; color: #a5d6a7; }
  .verdict-headless { background: #b71c1c; color: #ef9a9a; }
  pre { font-size: 0.78rem; background: #1a1a1a; padding: 0.4rem; border-radius: 4px; overflow-x: auto; margin-top: 0.3rem; white-space: pre-wrap; }
</style>
</head>
<body>
<h1>Headless Detection</h1>

<div class="test"><h2>1. Frame Timing Jitter</h2>
  <div class="status" id="s1">Running...</div><pre id="d1"></pre></div>
<div class="test"><h2>2. Window Chrome</h2>
  <div class="status" id="s2">Checking...</div><pre id="d2"></pre></div>
<div class="test"><h2>3. Scrollbar Width</h2>
  <div class="status" id="s3">Checking...</div><pre id="d3"></pre></div>
<div class="test"><h2>4. Canvas Fingerprint</h2>
  <div class="status" id="s4">Checking...</div><pre id="d4"></pre></div>
<div class="test"><h2>5. WebGL Timer Extension</h2>
  <div class="status" id="s5">Checking...</div><pre id="d5"></pre></div>
<div class="test"><h2>6. WebGL Extension Count</h2>
  <div class="status" id="s6">Checking...</div><pre id="d6"></pre></div>
<div class="test"><h2>7. Screen Position</h2>
  <div class="status" id="s7">Checking...</div><pre id="d7"></pre></div>
<div class="test"><h2>8. sec-ch-ua Header (server-side)</h2>
  <div class="status" id="s8">Server-side...</div><pre id="d8"></pre></div>
<div class="test"><h2>9. Accept-Language (server-side)</h2>
  <div class="status" id="s9">Server-side...</div><pre id="d9"></pre></div>

<div id="verdict" data-verdict="">Analyzing...</div>

<script>
""" + PROBE_JS + r"""

function setStatus(id, text, cls) {
  document.getElementById(id).textContent = text;
  document.getElementById(id).className = 'status ' + cls;
}

(async function() {
  const { session_id } = await (await fetch('/api/session')).json();
  const r = await runProbes(session_id);

  // Display results
  const avg = r.avg_delta, stddev = r.delta_stddev;
  document.getElementById('d1').textContent =
    `Avg: ${avg.toFixed(2)}ms  Stddev: ${stddev.toFixed(2)}ms  Frames: ${r.frame_deltas.length}\nFirst 10: [${r.frame_deltas.slice(0,10).map(d=>d.toFixed(2)).join(', ')}]`;
  const synthetic = stddev < 0.3 && Math.abs(avg - 16.67) < 4;
  const nonVsync = Math.abs(avg - 16.67) >= 4 && Math.abs(avg - 8.33) >= 2;
  setStatus('s1', nonVsync ? `HEADLESS — non-VSync (avg=${avg.toFixed(1)}ms)` :
    synthetic ? `HEADLESS — synthetic VSync (stddev=${stddev.toFixed(3)}ms)` :
    `HEADFUL — natural jitter (stddev=${stddev.toFixed(2)}ms)`,
    (nonVsync || synthetic) ? 'fail' : 'pass');

  const noChrome = r.outer_width === r.inner_width && r.outer_height === r.inner_height;
  document.getElementById('d2').textContent =
    `outer: ${r.outer_width}x${r.outer_height}  inner: ${r.inner_width}x${r.inner_height}`;
  setStatus('s2', noChrome ? 'HEADLESS — no window decorations' :
    `HEADFUL — decorations (+${r.outer_width - r.inner_width}w, +${r.outer_height - r.inner_height}h)`,
    noChrome ? 'fail' : 'pass');

  document.getElementById('d3').textContent = `Scrollbar width: ${r.scrollbar_width}px`;
  setStatus('s3', r.scrollbar_width === 0
    ? 'HEADLESS — zero-width scrollbars'
    : `HEADFUL — ${r.scrollbar_width}px scrollbars`,
    r.scrollbar_width === 0 ? 'fail' : 'pass');

  document.getElementById('d4').textContent =
    `dataURL length: ${r.canvas_hash}  pixel@(75,25): [${r.canvas_pixel.join(',')}]`;
  setStatus('s4', `Canvas fingerprint (hash=${r.canvas_hash})`, 'info');

  document.getElementById('d5').textContent =
    `EXT_disjoint_timer_query: ${r.has_timer_ext ? 'present' : 'missing'}`;
  setStatus('s5', r.has_timer_ext
    ? 'HEADFUL — timer extension present'
    : 'HEADLESS — timer extension missing',
    r.has_timer_ext ? 'pass' : 'fail');

  document.getElementById('d6').textContent =
    `WebGL1: ${r.webgl1_ext_count}  WebGL2: ${r.webgl2_ext_count}\nRenderer: ${r.webgl_renderer || 'N/A'}`;
  setStatus('s6', `GL1=${r.webgl1_ext_count} GL2=${r.webgl2_ext_count}`, 'info');

  document.getElementById('d7').textContent = `screenX=${r.screen_x}  screenY=${r.screen_y}`;
  setStatus('s7', r.screen_x === 10 && r.screen_y === 10
    ? 'HEADLESS — default position (10,10)'
    : `HEADFUL — position (${r.screen_x},${r.screen_y})`,
    (r.screen_x === 10 && r.screen_y === 10) ? 'fail' : 'pass');

  // Submit
  const resp = await fetch('/api/results', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(r),
  });
  const { verdict } = await resp.json();

  // Server-side probes (analyzed from request headers)
  const t = verdict.tests;
  if (t.sec_ch_ua_brand) {
    setStatus('s8', t.sec_ch_ua_brand.verdict.toUpperCase() + ' — ' + t.sec_ch_ua_brand.reason,
      t.sec_ch_ua_brand.verdict === 'headless' ? 'fail' : t.sec_ch_ua_brand.verdict === 'headful' ? 'pass' : 'info');
    document.getElementById('d8').textContent = t.sec_ch_ua_brand.reason;
  }
  if (t.accept_language) {
    setStatus('s9', t.accept_language.verdict.toUpperCase() + ' — ' + t.accept_language.reason,
      t.accept_language.verdict === 'headless' ? 'fail' : t.accept_language.verdict === 'headful' ? 'pass' : 'info');
    document.getElementById('d9').textContent = t.accept_language.reason;
  }

  const vDiv = document.getElementById('verdict');
  vDiv.setAttribute('data-verdict', verdict.overall);
  vDiv.textContent = `Verdict: ${verdict.overall.toUpperCase()} (score: ${verdict.total_score}, ${verdict.headless_signals} headless / ${verdict.headful_signals} headful)`;
  vDiv.className = verdict.overall === 'headless' ? 'verdict-headless' : 'verdict-headful';
})();
</script>
</body>
</html>
"""


# ── Iframe host page ─────────────────────────────────────────────────

IFRAME_HOST_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Headless Detection (iframe)</title>
<style>
  body { font-family: system-ui, sans-serif; background: #0f0f0f; color: #e0e0e0; padding: 2rem; }
  h1 { margin-bottom: 1rem; font-size: 1.4rem; }
  iframe { border: 2px solid #333; border-radius: 6px; }
  #verdict { margin-top: 1rem; padding: 1rem; border-radius: 6px; font-size: 1.2rem; font-weight: bold; }
  .verdict-headful { background: #1b5e20; color: #a5d6a7; }
  .verdict-headless { background: #b71c1c; color: #ef9a9a; }
  pre { font-size: 0.78rem; background: #1a1a1a; padding: 0.5rem; border-radius: 4px; margin-top: 0.5rem; white-space: pre-wrap; }
</style>
</head>
<body>
<h1>Headless Detection — via iframe (800x600)</h1>
<iframe id="probe-frame" src="/" width="800" height="600"></iframe>
<div id="verdict" data-verdict="">Waiting for iframe probes...</div>
<pre id="detail"></pre>
<script>
const iframe = document.getElementById('probe-frame');
// Poll the iframe's verdict
const poll = setInterval(async () => {
  try {
    const iframeVerdict = iframe.contentDocument.getElementById('verdict');
    if (iframeVerdict && iframeVerdict.getAttribute('data-verdict')) {
      clearInterval(poll);
      const v = iframeVerdict.getAttribute('data-verdict');
      const vDiv = document.getElementById('verdict');
      vDiv.setAttribute('data-verdict', v);
      vDiv.textContent = 'Iframe ' + iframeVerdict.textContent;
      vDiv.className = v === 'headless' ? 'verdict-headless' : 'verdict-headful';
      // Show the outer/inner from the host page perspective
      document.getElementById('detail').textContent =
        `Host window: outer=${window.outerWidth}x${window.outerHeight}, inner=${window.innerWidth}x${window.innerHeight}\n` +
        `Iframe contentWindow: outer=${iframe.contentWindow.outerWidth}x${iframe.contentWindow.outerHeight}, inner=${iframe.contentWindow.innerWidth}x${iframe.contentWindow.innerHeight}`;
    }
  } catch(e) {}
}, 200);
</script>
</body>
</html>
"""
