"""Server-side headless detection via outerWidth/innerWidth delta.

Chrome headless (--headless=new) sets outerWidth === innerWidth and
outerHeight === innerHeight.  Headful Chrome always has outer > inner
due to window chrome (title bar 85px, borders 8px on Linux).

This probe uses a single-line JS beacon to relay the delta to the server.
The server then decides what to serve: either a real resource or a block.

Detection flow:
  1. Client loads page with a 1-line <script> that fires a beacon:
       new Image().src = "/pages/outer-inner/beacon?s=X&wd=8&hd=85"
  2. Server receives the beacon and logs the deltas
  3. Server checks: if wd==0 AND hd==0 → headless
  4. Future requests for this session are classified

For server-side-only detection (no client gating), the page embeds
resources behind a /gate/ endpoint.  The gate checks whether the
beacon has arrived and what the deltas were before serving the resource.
"""

import json

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from core import storage
from probes.tracking import BEACON_BYTES

router = APIRouter()

# In-memory session classification (survives only during server lifetime).
# In production this could be Redis / DB-backed.
_session_classification: dict[str, dict] = {}


@router.get("/outer-inner")
async def outer_inner_page(s: str = Query(..., description="Session ID")):
    """Detection page.  Contains minimal JS to measure the delta."""
    storage.log_request(s, "page-load")

    # The beacon must arrive at the server BEFORE gated resources.
    # Strategy: use a synchronous XHR for the beacon (blocks parsing),
    # then inline the gated <img> tags after.  Alternatively, use fetch
    # with await.  We use the XHR approach for maximum compatibility.
    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>probe</title>
<style>
body {{ margin: 0; height: 3000px; position: relative; }}
</style>
<link rel="stylesheet" href="/pages/outer-inner/css-beacon?s={s}">
</head>
<body>
<script>
// Synchronous beacon — blocks HTML parsing until the server receives the delta.
// This ensures all subsequent resource loads are gated correctly.
var x=new XMLHttpRequest();
x.open("GET","/pages/outer-inner/beacon?s={s}&wd="+(window.outerWidth-window.innerWidth)+"&hd="+(window.outerHeight-window.innerHeight),false);
x.send();
// Now inject gated resources — server already knows the classification.
["img-1","img-2","img-3"].forEach(function(n){{
    var i=new Image();i.src="/pages/outer-inner/gate/"+n+"?s={s}";
    document.body.appendChild(i);
}});
</script>
</body>
</html>"""

    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


@router.get("/outer-inner/beacon")
async def beacon(
    s: str = Query(..., description="Session ID"),
    wd: int = Query(0, description="outerWidth - innerWidth"),
    hd: int = Query(0, description="outerHeight - innerHeight"),
):
    """Receive the outer-inner delta measurement.

    The server classifies the session here.
    wd=0 AND hd=0 → headless (no window chrome).
    wd>0 OR hd>0 → headful (has window chrome).
    """
    is_headless = (wd == 0 and hd == 0)
    classification = "headless" if is_headless else "headful"

    _session_classification[s] = {
        "width_delta": wd,
        "height_delta": hd,
        "classification": classification,
    }

    storage.log_request(s, f"beacon-wd{wd}-hd{hd}-{classification}")

    return Response(
        content=BEACON_BYTES,
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/outer-inner/css-beacon")
async def css_beacon(s: str = Query(..., description="Session ID")):
    """CSS resource that always loads (control beacon)."""
    storage.log_request(s, "css-beacon")
    return Response(
        content="/* beacon */",
        media_type="text/css",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/outer-inner/gate/{resource}")
async def gated_resource(
    resource: str,
    s: str = Query(..., description="Session ID"),
):
    """Server-gated resource.

    The server checks the session classification before deciding
    what to serve.  This is the server-side detection mechanism:

    - If beacon says headful → serve the real resource
    - If beacon says headless → serve a block/redirect/different content
    - If beacon hasn't arrived yet → serve the resource (race condition
      fallback; the beacon fires before <img> tags in DOM order)
    """
    info = _session_classification.get(s)

    if info and info["classification"] == "headless":
        # Server detected headless — serve a different response
        storage.log_request(s, f"gate-blocked-{resource}")
        return Response(
            content=BEACON_BYTES,
            media_type="image/png",
            headers={
                "Cache-Control": "no-store",
                "X-Detection": "headless",
                "X-Width-Delta": str(info["width_delta"]),
                "X-Height-Delta": str(info["height_delta"]),
            },
        )

    # Headful or unknown — serve normally
    storage.log_request(s, f"gate-served-{resource}")
    return Response(
        content=BEACON_BYTES,
        media_type="image/png",
        headers={
            "Cache-Control": "no-store",
            "X-Detection": info["classification"] if info else "unknown",
        },
    )


@router.get("/outer-inner/results/{session_id}")
async def results(session_id: str):
    """Return detection results for a session."""
    requests = storage.get_session_requests(session_id)
    resources = [r["resource"] for r in requests]
    info = _session_classification.get(session_id, {})

    gated_served = [r for r in resources if r.startswith("gate-served-")]
    gated_blocked = [r for r in resources if r.startswith("gate-blocked-")]

    return JSONResponse({
        "classification": info.get("classification", "unknown"),
        "width_delta": info.get("width_delta"),
        "height_delta": info.get("height_delta"),
        "total_requests": len(resources),
        "gated_served": len(gated_served),
        "gated_blocked": len(gated_blocked),
        "all_resources": resources,
    })
