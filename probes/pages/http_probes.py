"""HTTP-level probes: capture full request headers, favicon behavior,
meta-refresh timing, and connection patterns."""

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, Response, JSONResponse

router = APIRouter()

# In-memory store for header captures (simple dict keyed by session)
_header_captures: dict[str, list[dict]] = {}


@router.get("/probe-headers")
async def headers_page(s: str = Query(...)):
    """Page that loads many different resource types so we can capture
    their request headers on the server side."""
    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"><title>header probe</title>
<link rel="stylesheet" href="/pages/headers/capture/style.css?s={s}">
<link rel="prefetch" href="/pages/headers/capture/prefetch.dat?s={s}" as="image">
</head>
<body>
<img src="/pages/headers/capture/img.png?s={s}" width="1" height="1">
<video poster="/pages/headers/capture/poster.jpg?s={s}" width="1" height="1" preload="metadata">
  <source src="/pages/headers/capture/video.mp4?s={s}" type="video/mp4">
</video>
<audio preload="metadata">
  <source src="/pages/headers/capture/audio.mp3?s={s}" type="audio/mpeg">
</audio>
<iframe src="/pages/headers/capture/iframe.html?s={s}" width="1" height="1" style="border:none;"></iframe>
<object data="/pages/headers/capture/object.swf?s={s}" width="1" height="1" type="application/x-shockwave-flash"></object>
<script src="/pages/headers/capture/script.js?s={s}" defer></script>
</body>
</html>"""
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


@router.get("/headers/capture/{resource:path}")
async def capture_headers(resource: str, request: Request, s: str = Query(...)):
    """Capture full request headers for analysis."""
    headers_ordered = [(k, v) for k, v in request.headers.raw]
    headers_dict = {k.decode("latin-1"): v.decode("latin-1") for k, v in request.headers.raw}
    if s not in _header_captures:
        _header_captures[s] = []
    _header_captures[s].append({
        "resource": resource,
        "header_names_ordered": [k.decode("latin-1") for k, _ in request.headers.raw],
        "headers": headers_dict,
    })

    # Return appropriate content type
    if resource.endswith(".css"):
        return Response(content="body{}", media_type="text/css", headers={"Cache-Control": "no-store"})
    elif resource.endswith(".js"):
        return Response(content="", media_type="application/javascript", headers={"Cache-Control": "no-store"})
    elif resource.endswith(".html"):
        return HTMLResponse(content="<html><body></body></html>", headers={"Cache-Control": "no-store"})
    else:
        # 1x1 transparent PNG for everything else
        from . import _beacon_bytes
        return Response(content=_beacon_bytes(), media_type="image/png", headers={"Cache-Control": "no-store"})


@router.get("/headers/results/{session_id}")
async def get_header_results(session_id: str):
    """Return captured headers for a session."""
    captures = _header_captures.get(session_id, [])
    return JSONResponse(content=captures)


@router.get("/headers/clear")
async def clear_headers():
    _header_captures.clear()
    return {"status": "cleared"}


@router.get("/probe-favicon")
async def favicon_probe_page(s: str = Query(...)):
    """Minimal page to test if browser automatically requests favicon.ico.
    Also tests shortcut icon and apple-touch-icon."""
    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"><title>favicon probe</title>
<link rel="icon" href="/track/favicon-icon?s={s}" type="image/png">
<link rel="shortcut icon" href="/track/favicon-shortcut?s={s}" type="image/png">
<link rel="apple-touch-icon" href="/track/favicon-apple?s={s}">
</head>
<body>
<img src="/track/favicon-beacon?s={s}" width="1" height="1">
</body>
</html>"""
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


@router.get("/probe-meta-refresh")
async def meta_refresh_page(s: str = Query(...)):
    """Test meta http-equiv refresh timing.
    Page uses meta refresh to redirect after a short delay.
    Server measures time between initial page load and redirect arrival."""
    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"><title>meta refresh probe</title>
<meta http-equiv="refresh" content="1;url=/track/meta-refresh-target?s={s}">
</head>
<body>
<img src="/track/meta-refresh-start?s={s}" width="1" height="1">
</body>
</html>"""
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


@router.get("/probe-srcset-resolution")
async def srcset_resolution_page(s: str = Query(...)):
    """Test which srcset candidate the browser selects.
    Different DPR or viewport may cause different selection."""
    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>srcset resolution probe</title></head>
<body>
<img srcset="/track/srcset-1x?s={s} 1x, /track/srcset-2x?s={s} 2x, /track/srcset-3x?s={s} 3x"
     width="100" height="100">

<img srcset="/track/srcset-320w?s={s} 320w, /track/srcset-640w?s={s} 640w, /track/srcset-1280w?s={s} 1280w, /track/srcset-2560w?s={s} 2560w"
     sizes="(max-width: 600px) 320px, (max-width: 1200px) 640px, 1280px"
     width="100" height="100">

<picture>
  <source media="(min-width: 1280px)" srcset="/track/picture-large?s={s}">
  <source media="(min-width: 800px)" srcset="/track/picture-medium?s={s}">
  <source srcset="/track/picture-small?s={s}">
  <img src="/track/picture-fallback?s={s}" width="100" height="100">
</picture>
</body>
</html>"""
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


@router.get("/probe-connection-pattern")
async def connection_pattern_page(s: str = Query(...)):
    """Load many resources simultaneously to test HTTP/2 multiplexing behavior.
    The server timestamps each request; different connection scheduling
    in headful vs headless might create different arrival patterns."""
    # 30 images requested simultaneously
    imgs = []
    for i in range(30):
        imgs.append(f'<img src="/track/conn-{i:02d}?s={s}" width="1" height="1">')

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>connection pattern probe</title></head>
<body style="margin:0;">
{chr(10).join(imgs)}
</body>
</html>"""
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


@router.get("/probe-css-vars-env")
async def css_vars_env_page(s: str = Query(...)):
    """Test CSS environment variables and viewport units.
    env(safe-area-inset-*), dvh/svh/lvh viewport units might differ."""
    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>CSS env/viewport probe</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<style>
/* Dynamic viewport units - may differ if toolbar exists */
.dvh-test {{ height: 100dvh; width: 1px; background-image: url("/track/env-dvh?s={s}"); background-size:1px 1px; background-repeat:no-repeat; position:absolute; }}
.svh-test {{ height: 100svh; width: 1px; background-image: url("/track/env-svh?s={s}"); background-size:1px 1px; background-repeat:no-repeat; position:absolute; left:2px; }}
.lvh-test {{ height: 100lvh; width: 1px; background-image: url("/track/env-lvh?s={s}"); background-size:1px 1px; background-repeat:no-repeat; position:absolute; left:4px; }}

/* Safe area insets - typically 0 in desktop, but may differ in headless */
.safe-area {{
    padding: env(safe-area-inset-top, 0px) env(safe-area-inset-right, 0px)
             env(safe-area-inset-bottom, 0px) env(safe-area-inset-left, 0px);
    background-image: url("/track/env-safearea?s={s}");
    background-size:1px 1px; background-repeat:no-repeat;
    width: 1px; height: 1px; position:absolute; left:6px;
}}

/* Container query based detection */
.container {{ container-type: inline-size; width: 100%; }}
@container (min-width: 1000px) {{
    .cq-wide {{ background-image: url("/track/env-cq-wide?s={s}"); width:1px; height:1px; }}
}}
@container (max-width: 999px) {{
    .cq-narrow {{ background-image: url("/track/env-cq-narrow?s={s}"); width:1px; height:1px; }}
}}

/* Standard viewport probes */
.always {{ background-image: url("/track/env-always?s={s}"); width:1px; height:1px; position:absolute; }}
</style></head>
<body style="margin:0; height:100vh;">
<div class="always"></div>
<div class="dvh-test"></div>
<div class="svh-test"></div>
<div class="lvh-test"></div>
<div class="safe-area"></div>
<div class="container">
  <div class="cq-wide"></div>
  <div class="cq-narrow"></div>
</div>
</body>
</html>"""
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


@router.get("/probe-overflow-behavior")
async def overflow_behavior_page(s: str = Query(...)):
    """Test overflow scrollbar behavior with overlay vs classic scrollbars.
    Chrome on Linux may use overlay scrollbars differently in headless."""
    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>overflow behavior probe</title>
<style>
/* Container with overflow:auto - will show scrollbar if content overflows */
.scroll-container {{
    width: 200px;
    height: 100px;
    overflow: auto;
    position: absolute;
    top: 0;
    left: 0;
}}
.scroll-content {{
    width: 100%;
    height: 500px;  /* taller than container -> scrollbar */
}}

/* Element inside the scroll container that's exactly 200px wide.
   If classic scrollbar takes space, this overflows horizontally. */
.width-probe {{
    width: 200px;
    height: 1px;
    background-image: url("/track/overflow-width-probe?s={s}");
    background-size: 1px 1px;
    background-repeat: no-repeat;
}}

/* Use resize:both to see if the browser allows manual resize
   (headless might not support this) */
.resizable {{
    width: 100px;
    height: 100px;
    resize: both;
    overflow: auto;
    background-image: url("/track/overflow-resizable?s={s}");
    background-size: 1px 1px;
    background-repeat: no-repeat;
    position: absolute;
    top: 120px;
    left: 0;
    border: 1px solid black;
}}

/* overflow:overlay (non-standard but Chrome supports it) */
.overlay-scroll {{
    width: 200px;
    height: 100px;
    overflow: overlay;
    position: absolute;
    top: 250px;
    left: 0;
}}
.overlay-inner {{
    height: 500px;
    background-image: url("/track/overflow-overlay?s={s}");
    background-size: 1px 1px;
    background-repeat: no-repeat;
}}

.always {{ background-image: url("/track/overflow-always?s={s}"); width:1px; height:1px; position:absolute; top:400px; }}
</style></head>
<body style="margin:0;">
<div class="scroll-container">
    <div class="scroll-content">
        <div class="width-probe"></div>
    </div>
</div>
<div class="resizable">resize me</div>
<div class="overlay-scroll">
    <div class="overlay-inner"></div>
</div>
<div class="always"></div>
</body>
</html>"""
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})
