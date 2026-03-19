"""Simulated ad-tech cascade probe for headless detection.

Mimics the prebid.js cookie-sync cascade pattern observed on ad-heavy sites.
A "GTM-like" loader script checks browser APIs, then triggers cascading
redirect chains (simulating prebid partner syncs) whose depth the server
counts per session.

Detection signal: headful fires 30+ cascade beacons; headless fires <10.
"""

import json

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from core import storage
from probes.tracking import BEACON_BYTES

router = APIRouter()

PARTNERS = ["appnexus", "rubicon", "triplelift", "doubleclick", "bidswitch", "openx"]
CASCADE_DEPTH = 5  # redirect hops per partner


@router.get("/ad-cascade")
async def ad_cascade_page(s: str = Query(..., description="Session ID")):
    """Main probe page with simulated GTM/prebid cascade."""
    storage.log_request(s, "page-load")

    partner_entries = ""
    for p in PARTNERS:
        # Each partner gets an image cascade entry point + an iframe
        partner_entries += f"""
        // Partner: {p}
        (function() {{
            var img = new Image();
            img.src = "/pages/ad-cascade/cascade/{p}/0?s={s}";
            var iframe = document.createElement('iframe');
            iframe.src = "/pages/ad-cascade/partner-frame/{p}?s={s}";
            iframe.width = 0; iframe.height = 0;
            iframe.style.display = 'none';
            document.body.appendChild(iframe);
        }})();
"""

    js = f"""
(function() {{
    "use strict";

    // --- Phase 1: API fingerprint probes (what ad scripts check) ---
    var fp = {{}};
    fp.visibilityState = document.visibilityState;
    fp.hidden = document.hidden;
    try {{ fp.hasFocus = document.hasFocus(); }} catch(e) {{ fp.hasFocus = 'error'; }}
    fp.webdriver = navigator.webdriver;
    fp.cookieEnabled = navigator.cookieEnabled;
    fp.windowChrome = typeof window.chrome !== 'undefined';
    fp.chromeRuntime = (typeof window.chrome !== 'undefined' && typeof window.chrome.runtime !== 'undefined');
    fp.pluginsLength = navigator.plugins.length;
    fp.maxTouchPoints = navigator.maxTouchPoints;

    try {{
        var conn = navigator.connection;
        if (conn) {{
            fp.effectiveType = conn.effectiveType;
            fp.downlink = conn.downlink;
            fp.rtt = conn.rtt;
        }}
    }} catch(e) {{}}

    try {{ fp.notificationPermission = Notification.permission; }} catch(e) {{}}

    fp.outerWidth = window.outerWidth;
    fp.outerHeight = window.outerHeight;
    fp.screenWidth = screen.width;
    fp.screenHeight = screen.height;
    fp.colorDepth = screen.colorDepth;

    // --- Phase 2: GTM-like loader ---
    // Real GTM checks visibilityState and environment before loading ad scripts.
    // We simulate this by gating the cascade on common checks.
    new Image().src = "/track/gtm-loaded?s={s}";

    var checksPass = true;
    var failedChecks = [];

    // Check 1: outerWidth/outerHeight vs viewport
    // In headful Chrome, outerWidth > innerWidth (window chrome adds ~8px)
    // and outerHeight > innerHeight (title bar + tabs add ~85px).
    // In headless, outerWidth === innerWidth and outerHeight === innerHeight.
    var widthDelta = window.outerWidth - window.innerWidth;
    var heightDelta = window.outerHeight - window.innerHeight;
    fp.innerWidth = window.innerWidth;
    fp.innerHeight = window.innerHeight;
    fp.widthDelta = widthDelta;
    fp.heightDelta = heightDelta;

    if (widthDelta === 0 && heightDelta === 0) {{
        failedChecks.push('outerSize=innerSize');
    }}
    // Check 2: visibilityState
    if (document.visibilityState !== 'visible') {{
        failedChecks.push('visibilityState=' + document.visibilityState);
    }}
    // Check 3: hasFocus
    if (!document.hasFocus()) {{
        failedChecks.push('hasFocus=false');
    }}
    // Check 4: cookies enabled
    if (!navigator.cookieEnabled) {{
        failedChecks.push('cookieEnabled=false');
    }}

    if (failedChecks.length > 0) {{
        new Image().src = "/track/gtm-checks-failed?s={s}";
        // Still proceed — we want to see if the cascade fires regardless
    }} else {{
        new Image().src = "/track/gtm-checks-passed?s={s}";
    }}

    // --- Phase 3: Prebid-like cascade ---
    new Image().src = "/track/prebid-loaded?s={s}";

    // Gate cascade on environment checks (mimicking real ad-tech behavior).
    // Real ad scripts abort or reduce their cascade when they detect a
    // non-standard environment. The outerSize===innerSize check is the
    // key signal that Chrome headless --headless=new leaks.
    fp.failedChecks = failedChecks;

    // POST fingerprint to server (after all checks have run)
    fetch("/pages/ad-cascade/fingerprint?s={s}", {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify(fp)
    }}).catch(function() {{}});

    if (failedChecks.length === 0) {{
        // Full cascade — all partners fire
{partner_entries}
    }} else {{
        // Reduced cascade — only fire a single direct beacon per partner
        // (mimics ad scripts that bail early in headless)
        new Image().src = "/track/cascade-reduced?s={s}";
    }}

    // --- Phase 4: Cascade timeout beacon ---
    setTimeout(function() {{
        new Image().src = "/track/cascade-timeout?s={s}";
    }}, 8000);

}})();
"""

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Ad Cascade Probe</title>
    <style>body {{ margin: 0; padding: 20px; font-family: sans-serif; }}</style>
</head>
<body>
    <h1>Ad Cascade Detection Probe</h1>
    <p>This page simulates an ad-tech cascade (GTM + prebid + cookie syncs).</p>
    <p>Session: <code>{s}</code></p>
    <script>
{js}
    </script>
</body>
</html>"""

    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


@router.get("/ad-cascade/partner-frame/{partner}")
async def partner_frame(
    partner: str,
    s: str = Query(..., description="Session ID"),
):
    """Simulated SSP partner iframe — fires a cascade of sync pixels."""
    storage.log_request(s, f"partner-frame-{partner}")

    # Build image tags that point to the cascade chain
    imgs = ""
    for i in range(CASCADE_DEPTH):
        imgs += f'<img src="/pages/ad-cascade/cascade/{partner}/{i}?s={s}" width="1" height="1">\n'

    # Also fire dynamic images (matching real prebid behavior)
    dynamic_js = ""
    for i in range(CASCADE_DEPTH):
        dynamic_js += f'new Image().src = "/pages/ad-cascade/cascade/{partner}/{i}?s={s}&via=js";\n'

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body>
{imgs}
<script>
{dynamic_js}
</script>
</body></html>"""

    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


@router.get("/ad-cascade/cascade/{partner}/{step}")
async def cascade_step(
    partner: str,
    step: int,
    s: str = Query(..., description="Session ID"),
    via: str = Query("img", description="How this was triggered"),
):
    """Simulated cookie-sync redirect chain step.

    Steps 0 to CASCADE_DEPTH-2 redirect to the next step (302).
    The final step returns a 1x1 beacon PNG.
    """
    storage.log_request(s, f"cascade-{partner}-{step}")

    if step < CASCADE_DEPTH - 1:
        next_url = f"/pages/ad-cascade/cascade/{partner}/{step + 1}?s={s}&via=redir"
        return RedirectResponse(url=next_url, status_code=302)

    # Final step: return beacon
    return Response(
        content=BEACON_BYTES,
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/ad-cascade/fingerprint")
async def receive_fingerprint(
    request: Request,
    s: str = Query(..., description="Session ID"),
):
    """Receive client-side API fingerprint probe results."""
    body = await request.json()
    storage.log_request(s, f"fingerprint:{json.dumps(body, separators=(',', ':'))}")
    return JSONResponse({"status": "ok"})


@router.get("/ad-cascade/results/{session_id}")
async def cascade_results(session_id: str):
    """Return cascade metrics for a session."""
    requests = storage.get_session_requests(session_id)
    resources = [r["resource"] for r in requests]

    # Count cascade beacons per partner
    partner_depths = {}
    for p in PARTNERS:
        depths = [
            int(r.split("-")[-1])
            for r in resources
            if r.startswith(f"cascade-{p}-")
        ]
        partner_depths[p] = max(depths) + 1 if depths else 0

    # Extract fingerprint
    fingerprint = {}
    for r in resources:
        if r.startswith("fingerprint:"):
            try:
                fingerprint = json.loads(r[len("fingerprint:"):])
            except json.JSONDecodeError:
                pass

    return JSONResponse({
        "total_beacons": len(resources),
        "partner_depths": partner_depths,
        "gtm_loaded": "gtm-loaded" in resources,
        "prebid_loaded": "prebid-loaded" in resources,
        "checks_passed": "gtm-checks-passed" in resources,
        "checks_failed": "gtm-checks-failed" in resources,
        "cascade_timeout": "cascade-timeout" in resources,
        "fingerprint": fingerprint,
        "all_resources": resources,
    })
