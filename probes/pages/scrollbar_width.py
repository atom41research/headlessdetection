"""Scrollbar width detection probe.

In headful Chrome, a classic vertical scrollbar (~15px) makes the content
area narrower than the viewport.  In headless Chrome, overlay scrollbars
(or none at all) take 0px.

Key measurement: ``window.innerWidth - document.documentElement.clientWidth``
gives 15 in headful and 0 in headless.

Detection strategy:
  - JS measures scrollbar width three independent ways
  - Fires labelled beacons (``sb-js-detected`` / ``sb-js-not-detected``)
  - Server reads the beacon names to classify the session

The script is written to look like innocent responsive-layout code that
adapts to scrollbar presence (a common real-world pattern).
"""

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/scrollbar-width")
async def scrollbar_width_page(s: str = Query(..., description="Session ID")):
    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>scrollbar width probe</title>
<style>
body {{
    margin: 0;
    height: 3000px;
    position: relative;
}}

/* Control beacon — always fires */
.sb-control {{
    width: 100%;
    height: 1px;
    background-image: url("/track/sb-control?s={s}");
    background-size: 1px 1px;
    background-repeat: no-repeat;
    position: absolute;
    top: 0;
    left: 0;
    overflow: hidden;
}}
</style></head>
<body>
<div class="sb-control"></div>

<script>
(function() {{
    var sid = "{s}";

    // Technique A: innerWidth vs clientWidth
    var widthA = window.innerWidth - document.documentElement.clientWidth;

    // Technique B: offscreen scrollable div
    var outer = document.createElement("div");
    outer.style.cssText = "position:absolute;top:-9999px;left:-9999px;width:100px;height:100px;overflow:scroll;";
    document.body.appendChild(outer);
    var inner = document.createElement("div");
    inner.style.width = "100%";
    outer.appendChild(inner);
    var widthB = outer.offsetWidth - inner.offsetWidth;
    document.body.removeChild(outer);

    // Technique C: calc(100vw - 100%) computed width
    var probe = document.createElement("div");
    probe.style.cssText = "position:absolute;top:-9999px;width:calc(100vw - 100%);height:1px;";
    document.body.appendChild(probe);
    var widthC = probe.offsetWidth;
    document.body.removeChild(probe);

    // Fire beacons with measured values
    new Image().src = "/track/sb-js-innerWidth-" + widthA + "?s=" + sid;
    new Image().src = "/track/sb-js-offscreen-" + widthB + "?s=" + sid;
    new Image().src = "/track/sb-js-calc-" + widthC + "?s=" + sid;

    // Summary beacon: has-scrollbar or no-scrollbar
    if (widthA > 0) {{
        new Image().src = "/track/sb-js-detected?s=" + sid;
    }} else {{
        new Image().src = "/track/sb-js-not-detected?s=" + sid;
    }}
}})();
</script>
</body>
</html>"""
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})
