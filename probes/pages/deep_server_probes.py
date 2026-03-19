"""Deep server-side behavioral probes.

These probe pages go beyond static fingerprints and test behavioral differences
in how Chrome's network stack operates in headful vs headless mode:

1. Connection concurrency limits and pooling
2. Resource loading prioritization order
3. Speculative connections (link hover, anchor prefetch)
4. Redirect chain behavior and timing
5. Cache validation / conditional request behavior
6. Keep-alive / connection lifecycle
7. Accept-CH (Client Hints) response to server requests
8. Concurrent fetch() from JS vs HTML-initiated loads
9. Beacon API / sendBeacon at page unload
10. Slow server responses (how does the browser handle stalls?)
11. 103 Early Hints processing
12. iframe isolation and connection sharing
"""

import asyncio
import time

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, Response, JSONResponse, RedirectResponse

from core import storage
from probes.tracking import BEACON_BYTES

router = APIRouter()


# ──────────────────────────────────────────────
# 1. Connection concurrency saturation
# ──────────────────────────────────────────────

@router.get("/probe-conn-saturation")
async def conn_saturation_page(s: str = Query(...)):
    """Saturate HTTP/1.1's 6-connection-per-domain limit.

    Serves 60 resources, each delayed 200ms server-side.
    With 6 connections, 60 resources at 200ms each = ~2s total (10 batches).
    If headless uses a different connection pool size, the arrival
    pattern will differ measurably.

    Server records (resource_name, client_port, timestamp) for each request.
    """
    imgs = []
    for i in range(60):
        imgs.append(
            f'<img src="/pages/deep/slow-resource/{i:03d}.png?s={s}&delay=200" width="1" height="1">'
        )

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Connection Saturation</title></head>
<body>
{chr(10).join(imgs)}
<img src="/track/conn-sat-done?s={s}" width="1" height="1">
</body>
</html>"""
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


# ──────────────────────────────────────────────
# 2. Resource priority ordering
# ──────────────────────────────────────────────

@router.get("/probe-priority-order")
async def priority_order_page(s: str = Query(...)):
    """Test Chrome's resource priority scheduling.

    Loads resources of different types simultaneously. Chrome assigns
    internal priorities (Highest for CSS, High for JS in head,
    Low for images below fold, etc.). Server records arrival order.

    If headless doesn't have a real compositor/layout engine running,
    it may not apply the same priority logic.
    """
    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"><title>Priority Order</title>
<!-- 1. Render-blocking CSS (Highest priority) -->
<link rel="stylesheet" href="/pages/deep/priority/critical.css?s={s}">
<!-- 2. Preloaded font (High priority) -->
<link rel="preload" href="/pages/deep/priority/font.woff2?s={s}" as="font" type="font/woff2" crossorigin>
<!-- 3. Sync script in head (High priority) -->
<script src="/pages/deep/priority/head-sync.js?s={s}"></script>
</head>
<body>
<!-- 4. Above-fold image (Medium priority - Chrome boosts visible images) -->
<img src="/pages/deep/priority/above-fold.png?s={s}" width="100" height="100" style="display:block;">

<!-- 5. Deferred script (Low priority) -->
<script src="/pages/deep/priority/deferred.js?s={s}" defer></script>

<!-- 6. Async script (Low priority) -->
<script src="/pages/deep/priority/async-script.js?s={s}" async></script>

<!-- 7. Below-fold images (Lowest priority - not in viewport) -->
<div style="height: 3000px;"></div>
<img src="/pages/deep/priority/below-fold-1.png?s={s}" width="1" height="1" loading="lazy">
<img src="/pages/deep/priority/below-fold-2.png?s={s}" width="1" height="1" loading="lazy">
<img src="/pages/deep/priority/below-fold-3.png?s={s}" width="1" height="1" loading="lazy">

<!-- 8. Fetch with different priorities -->
<script>
fetch('/pages/deep/priority/fetch-high.json?s={s}', {{priority: 'high'}});
fetch('/pages/deep/priority/fetch-low.json?s={s}', {{priority: 'low'}});
fetch('/pages/deep/priority/fetch-auto.json?s={s}');

// 9. Dynamic image injection
var img = new Image();
img.src = '/pages/deep/priority/dynamic-img.png?s={s}';

// 10. Background fetch via requestIdleCallback
if (window.requestIdleCallback) {{
    requestIdleCallback(function() {{
        fetch('/pages/deep/priority/idle-fetch.json?s={s}');
    }});
}} else {{
    setTimeout(function() {{
        fetch('/pages/deep/priority/idle-fetch.json?s={s}');
    }}, 100);
}}
</script>

<img src="/track/priority-done?s={s}" width="1" height="1">
</body>
</html>"""
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


# ──────────────────────────────────────────────
# 3. Speculative connection / link prefetch behavior
# ──────────────────────────────────────────────

@router.get("/probe-speculative")
async def speculative_page(s: str = Query(...)):
    """Test whether Chrome opens speculative connections.

    In headful mode, Chrome may:
    - Preconnect to origins in <a> tags on hover
    - Process <link rel="prefetch"> at idle time
    - Process <link rel="prerender"> (deprecated but some behavior remains)
    - Open speculative connections for forms with action URLs

    In headless, there's no hover, no idle UI, so these may be skipped.
    """
    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"><title>Speculative Connections</title>
<!-- Prefetch - browser should fetch this at low priority -->
<link rel="prefetch" href="/pages/deep/speculative/prefetched-page.html?s={s}">
<!-- Preload - browser MUST fetch this -->
<link rel="preload" href="/pages/deep/speculative/preloaded-data.json?s={s}" as="fetch" crossorigin>
<!-- modulepreload -->
<link rel="modulepreload" href="/pages/deep/speculative/module.mjs?s={s}">
</head>
<body>
<h3>Speculative Connection Probe</h3>

<!-- Links that Chrome may speculatively preconnect to -->
<a href="/pages/deep/speculative/link-target-1.html?s={s}" id="link1">Link 1</a>
<a href="/pages/deep/speculative/link-target-2.html?s={s}" id="link2">Link 2</a>

<!-- Form with action URL -->
<form action="/pages/deep/speculative/form-target?s={s}" method="GET">
    <input type="hidden" name="data" value="test">
</form>

<!-- CSS with url() references that trigger fetches -->
<style>
.bg-probe {{
    width: 1px; height: 1px;
    background-image: url('/pages/deep/speculative/css-bg.png?s={s}');
}}
</style>
<div class="bg-probe"></div>

<script>
// Beacon on load
var img = new Image();
img.src = '/track/speculative-loaded?s={s}';

// Schedule idle work
if (window.requestIdleCallback) {{
    requestIdleCallback(function() {{
        fetch('/pages/deep/speculative/idle-work.json?s={s}');
    }}, {{timeout: 2000}});
}}

// Intersection observer for lazy content
var observer = new IntersectionObserver(function(entries) {{
    entries.forEach(function(e) {{
        if (e.isIntersecting) {{
            fetch('/pages/deep/speculative/intersected.json?s={s}');
        }}
    }});
}});
observer.observe(document.body);
</script>

<img src="/track/speculative-beacon?s={s}" width="1" height="1">
</body>
</html>"""
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


# ──────────────────────────────────────────────
# 4. Redirect chain behavior
# ──────────────────────────────────────────────

@router.get("/probe-redirect-chain")
async def redirect_chain_page(s: str = Query(...)):
    """Test redirect-following behavior.

    Embeds resources that go through 301/302/307/308 redirect chains.
    Server records timing at each hop. Different redirect types may be
    handled differently (cached vs uncached, method-preserving vs not).
    """
    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"><title>Redirect Chain Probe</title>
<!-- CSS through 301 redirect -->
<link rel="stylesheet" href="/pages/deep/redirect/301/style.css?s={s}&hops=3">
</head>
<body>
<!-- Image through 302 redirect -->
<img src="/pages/deep/redirect/302/img.png?s={s}&hops=3" width="1" height="1">

<!-- Script through 307 redirect -->
<script src="/pages/deep/redirect/307/script.js?s={s}&hops=2" defer></script>

<!-- Fetch through 308 redirect -->
<script>
fetch('/pages/deep/redirect/308/data.json?s={s}&hops=4');
</script>

<!-- Meta refresh (server-side redirect at HTML level) -->
<iframe src="/pages/deep/redirect/meta-refresh?s={s}" width="1" height="1" style="border:none;"></iframe>

<img src="/track/redirect-chain-done?s={s}" width="1" height="1">
</body>
</html>"""
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


# ──────────────────────────────────────────────
# 5. Cache validation / conditional requests
# ──────────────────────────────────────────────

@router.get("/probe-cache-behavior")
async def cache_behavior_page(s: str = Query(...)):
    """Test cache validation behavior.

    First visit loads resources with ETag and Last-Modified.
    The page then reloads itself (soft navigation), and we observe
    whether the browser sends If-None-Match / If-Modified-Since.

    Headless might have different caching behavior or skip validation.
    """
    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"><title>Cache Behavior Probe</title>
<link rel="stylesheet" href="/pages/deep/cached/style.css?s={s}">
</head>
<body>
<img src="/pages/deep/cached/img.png?s={s}" width="1" height="1" id="cached-img">
<script src="/pages/deep/cached/script.js?s={s}"></script>
<script>
// After initial load, re-fetch the same resources to test cache behavior
setTimeout(function() {{
    // Force a conditional request by fetching with cache: 'no-cache'
    fetch('/pages/deep/cached/refetch.json?s={s}', {{cache: 'no-cache'}});

    // Also reload the image (should trigger If-None-Match)
    var img = new Image();
    img.src = '/pages/deep/cached/img.png?s={s}&reload=1';

    // Normal fetch (should use cache)
    fetch('/pages/deep/cached/normal.json?s={s}');

    // Force bypass cache
    fetch('/pages/deep/cached/bypass.json?s={s}', {{cache: 'reload'}});

    var beacon = new Image();
    beacon.src = '/track/cache-done?s={s}';
}}, 500);
</script>
</body>
</html>"""
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


# ──────────────────────────────────────────────
# 6. Accept-CH (Client Hints) negotiation
# ──────────────────────────────────────────────

@router.get("/probe-client-hints")
async def client_hints_page(s: str = Query(...)):
    """Test Client Hints behavior.

    Server responds with Accept-CH header requesting various hints.
    On subsequent requests, Chrome should send the requested hints.
    Headless might not send device-specific hints (Viewport-Width,
    DPR, Device-Memory, etc.) or send different values.
    """
    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"><title>Client Hints Probe</title>
<meta http-equiv="Accept-CH" content="Sec-CH-UA-Full-Version-List, Sec-CH-UA-Arch, Sec-CH-UA-Model, Sec-CH-UA-Bitness, Sec-CH-UA-WoW64, Sec-CH-Prefers-Color-Scheme, Sec-CH-Prefers-Reduced-Motion, Device-Memory, DPR, Viewport-Width, Width">
</head>
<body>
<!-- These sub-resources should include the requested client hints -->
<img src="/pages/deep/hints/after-ch.png?s={s}" width="100" height="100">
<link rel="stylesheet" href="/pages/deep/hints/after-ch.css?s={s}">
<script src="/pages/deep/hints/after-ch.js?s={s}" defer></script>
<script>
// Fetch should also include hints
setTimeout(function() {{
    fetch('/pages/deep/hints/after-ch-fetch.json?s={s}');
    var beacon = new Image();
    beacon.src = '/track/client-hints-done?s={s}';
}}, 300);
</script>
</body>
</html>"""
    # Respond with Accept-CH to request extended hints
    return HTMLResponse(
        content=html,
        headers={
            "Cache-Control": "no-store",
            "Accept-CH": "Sec-CH-UA-Full-Version-List, Sec-CH-UA-Arch, Sec-CH-UA-Model, Sec-CH-UA-Bitness, Sec-CH-UA-WoW64, Sec-CH-Prefers-Color-Scheme, Sec-CH-Prefers-Reduced-Motion, Device-Memory, DPR, Viewport-Width, Width",
        },
    )


# ──────────────────────────────────────────────
# 7. Beacon API / sendBeacon at unload
# ──────────────────────────────────────────────

@router.get("/probe-unload-beacon")
async def unload_beacon_page(s: str = Query(...)):
    """Test sendBeacon / unload behavior.

    Registers visibilitychange and pagehide handlers that send beacons.
    When the browser navigates away or closes the page, these fire.
    Headless might handle page lifecycle events differently.
    """
    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Unload Beacon Probe</title></head>
<body>
<script>
// Track that JS loaded
navigator.sendBeacon('/track/beacon-js-loaded?s={s}', '');

// visibilitychange
document.addEventListener('visibilitychange', function() {{
    if (document.visibilityState === 'hidden') {{
        navigator.sendBeacon('/track/beacon-visibility-hidden?s={s}', '');
    }}
}});

// pagehide
window.addEventListener('pagehide', function() {{
    navigator.sendBeacon('/track/beacon-pagehide?s={s}', '');
}});

// beforeunload
window.addEventListener('beforeunload', function() {{
    navigator.sendBeacon('/track/beacon-beforeunload?s={s}', '');
}});

// Also test keepalive fetch
window.addEventListener('pagehide', function() {{
    fetch('/track/beacon-keepalive-fetch?s={s}', {{
        method: 'POST',
        body: 'unload',
        keepalive: true,
    }});
}});
</script>
<img src="/track/unload-page-loaded?s={s}" width="1" height="1">
</body>
</html>"""
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


# ──────────────────────────────────────────────
# 8. Slow response / stall handling
# ──────────────────────────────────────────────

@router.get("/probe-slow-responses")
async def slow_responses_page(s: str = Query(...)):
    """Test behavior with slow/stalling server responses.

    Some resources respond instantly, others are delayed.
    This tests whether headless has different timeout behavior,
    different retry logic, or handles request queuing differently
    when some connections are stalled.
    """
    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"><title>Slow Response Probe</title>
<link rel="stylesheet" href="/pages/deep/slow-resource/css-fast.css?s={s}&delay=0">
<link rel="stylesheet" href="/pages/deep/slow-resource/css-slow.css?s={s}&delay=1000">
</head>
<body>
<!-- Fast images should load while CSS is stalling -->
<img src="/pages/deep/slow-resource/img-fast.png?s={s}&delay=0" width="1" height="1">
<img src="/pages/deep/slow-resource/img-medium.png?s={s}&delay=500" width="1" height="1">
<img src="/pages/deep/slow-resource/img-slow.png?s={s}&delay=1500" width="1" height="1">

<script>
// JS-initiated fetches while HTML resources are stalling
fetch('/pages/deep/slow-resource/fetch-fast.json?s={s}&delay=0');
fetch('/pages/deep/slow-resource/fetch-slow.json?s={s}&delay=800');

// Track completion
setTimeout(function() {{
    var img = new Image();
    img.src = '/track/slow-responses-done?s={s}';
}}, 3000);
</script>
</body>
</html>"""
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


# ──────────────────────────────────────────────
# 9. iframe isolation / connection sharing
# ──────────────────────────────────────────────

@router.get("/probe-iframe-connections")
async def iframe_connections_page(s: str = Query(...)):
    """Test connection sharing between main frame and iframes.

    Same-origin iframes should share the connection pool.
    Headless might isolate iframe connections differently.
    """
    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Iframe Connection Probe</title></head>
<body>
<!-- Main frame resource -->
<img src="/pages/deep/iframe/main-img.png?s={s}" width="1" height="1">

<!-- Same-origin iframes that also load resources -->
<iframe src="/pages/deep/iframe/child1?s={s}" width="1" height="1" style="border:none;"></iframe>
<iframe src="/pages/deep/iframe/child2?s={s}" width="1" height="1" style="border:none;"></iframe>
<iframe src="/pages/deep/iframe/child3?s={s}" width="1" height="1" style="border:none;"></iframe>

<!-- Nested iframe -->
<iframe src="/pages/deep/iframe/nester?s={s}" width="1" height="1" style="border:none;"></iframe>

<img src="/track/iframe-conn-done?s={s}" width="1" height="1">
</body>
</html>"""
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


@router.get("/deep/iframe/child{n}")
async def iframe_child(n: int, s: str = Query(...)):
    storage.log_request(s, f"iframe-child{n}-doc")
    html = f"""<!DOCTYPE html>
<html><body>
<img src="/pages/deep/iframe/child{n}-img1.png?s={s}" width="1" height="1">
<img src="/pages/deep/iframe/child{n}-img2.png?s={s}" width="1" height="1">
<img src="/pages/deep/iframe/child{n}-img3.png?s={s}" width="1" height="1">
<script>fetch('/pages/deep/iframe/child{n}-fetch.json?s={s}');</script>
</body></html>"""
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


@router.get("/deep/iframe/nester")
async def iframe_nester(s: str = Query(...)):
    storage.log_request(s, "iframe-nester-doc")
    html = f"""<!DOCTYPE html>
<html><body>
<iframe src="/pages/deep/iframe/nested-deep?s={s}" width="1" height="1" style="border:none;"></iframe>
</body></html>"""
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


@router.get("/deep/iframe/nested-deep")
async def iframe_nested_deep(s: str = Query(...)):
    storage.log_request(s, "iframe-nested-deep-doc")
    html = f"""<!DOCTYPE html>
<html><body>
<img src="/pages/deep/iframe/nested-deep-img.png?s={s}" width="1" height="1">
</body></html>"""
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


# ──────────────────────────────────────────────
# 10. Concurrent JS fetch() saturation
# ──────────────────────────────────────────────

@router.get("/probe-fetch-saturation")
async def fetch_saturation_page(s: str = Query(...)):
    """Fire 50 concurrent fetch() calls from JavaScript.

    Unlike HTML-initiated loads (which Chrome prioritizes), JS fetch()
    calls are all medium priority. Server records arrival order and
    timing to see if the concurrency patterns differ.
    """
    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Fetch Saturation</title></head>
<body>
<script>
var promises = [];
for (var i = 0; i < 50; i++) {{
    promises.push(
        fetch('/pages/deep/slow-resource/jsfetch-' + String(i).padStart(3, '0') + '.json?s={s}&delay=100')
    );
}}
Promise.all(promises).then(function() {{
    var img = new Image();
    img.src = '/track/fetch-sat-done?s={s}';
}});
</script>
</body>
</html>"""
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


# ──────────────────────────────────────────────
# Sub-resource endpoints for deep probes
# ──────────────────────────────────────────────

@router.get("/deep/slow-resource/{resource:path}")
async def slow_resource(resource: str, request: Request, s: str = Query(...), delay: int = Query(0)):
    """Serve a resource with configurable server-side delay.

    Records (resource, client_port, timestamp) for behavioral analysis.
    """
    client = request.scope.get("client", (None, None))
    storage.log_request(s, f"deep-slow-{resource}")

    # Store client port for connection tracking
    if client[1]:
        storage.log_request(s, f"port-{client[1]}-{resource}")

    if delay > 0:
        await asyncio.sleep(delay / 1000.0)

    if resource.endswith(".css"):
        return Response(content="body{}", media_type="text/css",
                        headers={"Cache-Control": "no-store"})
    elif resource.endswith(".js"):
        return Response(content="void 0;", media_type="application/javascript",
                        headers={"Cache-Control": "no-store"})
    elif resource.endswith(".json"):
        return Response(content='{"ok":true}', media_type="application/json",
                        headers={"Cache-Control": "no-store"})
    else:
        return Response(content=BEACON_BYTES, media_type="image/png",
                        headers={"Cache-Control": "no-store"})


@router.get("/deep/priority/{resource:path}")
async def priority_resource(resource: str, request: Request, s: str = Query(...)):
    """Serve a priority-probe resource. Records arrival order."""
    storage.log_request(s, f"priority-{resource}")

    if resource.endswith(".css"):
        return Response(content="body{}", media_type="text/css",
                        headers={"Cache-Control": "no-store"})
    elif resource.endswith(".js") or resource.endswith(".mjs"):
        return Response(content="void 0;", media_type="application/javascript",
                        headers={"Cache-Control": "no-store"})
    elif resource.endswith(".json"):
        return Response(content='{"ok":true}', media_type="application/json",
                        headers={"Cache-Control": "no-store"})
    elif resource.endswith(".woff2"):
        from probes.tracking import FONT_PATH
        return Response(content=FONT_PATH.read_bytes(), media_type="font/woff2",
                        headers={"Cache-Control": "no-store"})
    else:
        return Response(content=BEACON_BYTES, media_type="image/png",
                        headers={"Cache-Control": "no-store"})


@router.get("/deep/speculative/{resource:path}")
async def speculative_resource(resource: str, request: Request, s: str = Query(...)):
    """Serve a speculative-probe resource."""
    storage.log_request(s, f"speculative-{resource}")

    if resource.endswith(".css"):
        return Response(content="body{}", media_type="text/css",
                        headers={"Cache-Control": "no-store"})
    elif resource.endswith(".js") or resource.endswith(".mjs"):
        content = "export default {};" if resource.endswith(".mjs") else "void 0;"
        return Response(content=content, media_type="application/javascript",
                        headers={"Cache-Control": "no-store"})
    elif resource.endswith(".json"):
        return Response(content='{"ok":true}', media_type="application/json",
                        headers={"Cache-Control": "no-store"})
    elif resource.endswith(".html"):
        return HTMLResponse(content="<html><body>target</body></html>",
                            headers={"Cache-Control": "no-store"})
    else:
        return Response(content=BEACON_BYTES, media_type="image/png",
                        headers={"Cache-Control": "no-store"})


@router.get("/deep/redirect/{status_code}/{resource:path}")
async def redirect_resource(
    status_code: int,
    resource: str,
    request: Request,
    s: str = Query(...),
    hops: int = Query(1),
):
    """Multi-hop redirect endpoint. Each hop decrements the counter."""
    storage.log_request(s, f"redirect-{status_code}-hop{hops}-{resource}")

    if hops > 1:
        next_url = f"/pages/deep/redirect/{status_code}/{resource}?s={s}&hops={hops - 1}"
        return RedirectResponse(url=next_url, status_code=status_code)

    # Final destination
    if resource.endswith(".css"):
        return Response(content="body{}", media_type="text/css",
                        headers={"Cache-Control": "no-store"})
    elif resource.endswith(".js"):
        return Response(content="void 0;", media_type="application/javascript",
                        headers={"Cache-Control": "no-store"})
    elif resource.endswith(".json"):
        return Response(content='{"ok":true}', media_type="application/json",
                        headers={"Cache-Control": "no-store"})
    else:
        return Response(content=BEACON_BYTES, media_type="image/png",
                        headers={"Cache-Control": "no-store"})


@router.get("/deep/redirect/meta-refresh")
async def meta_refresh_redirect(s: str = Query(...)):
    """HTML-level redirect via meta http-equiv refresh."""
    storage.log_request(s, "redirect-meta-refresh-start")
    html = f"""<!DOCTYPE html>
<html><head>
<meta http-equiv="refresh" content="0;url=/track/redirect-meta-refresh-target?s={s}">
</head><body></body></html>"""
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


@router.get("/deep/cached/{resource:path}")
async def cached_resource(resource: str, request: Request, s: str = Query(...)):
    """Serve cacheable resources with ETag and Last-Modified.

    Records whether the request included conditional headers.
    """
    # Check for conditional request headers
    if_none_match = request.headers.get("if-none-match", "")
    if_modified = request.headers.get("if-modified-since", "")

    has_conditional = bool(if_none_match or if_modified)
    storage.log_request(s, f"cached-{resource}-conditional={has_conditional}")

    if if_none_match == '"static-etag-v1"':
        return Response(status_code=304, headers={"ETag": '"static-etag-v1"'})

    headers = {
        "ETag": '"static-etag-v1"',
        "Last-Modified": "Mon, 01 Jan 2024 00:00:00 GMT",
        "Cache-Control": "max-age=3600",
    }

    if resource.endswith(".css"):
        return Response(content="body{color:black;}", media_type="text/css", headers=headers)
    elif resource.endswith(".js"):
        return Response(content="void 0;", media_type="application/javascript", headers=headers)
    elif resource.endswith(".json"):
        return Response(content='{"cached":true}', media_type="application/json", headers=headers)
    else:
        return Response(content=BEACON_BYTES, media_type="image/png", headers=headers)


@router.get("/deep/hints/{resource:path}")
async def hints_resource(resource: str, request: Request, s: str = Query(...)):
    """Serve resources and capture any Client Hints headers sent."""
    # Capture all sec-ch-* and device headers
    hint_headers = {}
    for name, value in request.headers.raw:
        name_str = name.decode("latin-1").lower()
        if name_str.startswith("sec-ch-") or name_str in ("dpr", "viewport-width", "width", "device-memory"):
            hint_headers[name_str] = value.decode("latin-1")

    storage.log_request(s, f"hints-{resource}-hints={len(hint_headers)}")

    # Also log the individual hints for analysis
    for hint_name, hint_value in hint_headers.items():
        storage.log_request(s, f"hint-{hint_name}={hint_value}")

    if resource.endswith(".css"):
        return Response(content="body{}", media_type="text/css",
                        headers={"Cache-Control": "no-store"})
    elif resource.endswith(".js"):
        return Response(content="void 0;", media_type="application/javascript",
                        headers={"Cache-Control": "no-store"})
    elif resource.endswith(".json"):
        return Response(content='{"ok":true}', media_type="application/json",
                        headers={"Cache-Control": "no-store"})
    else:
        return Response(content=BEACON_BYTES, media_type="image/png",
                        headers={"Cache-Control": "no-store"})


@router.get("/deep/iframe/{resource:path}")
async def iframe_resource(resource: str, request: Request, s: str = Query(...)):
    """Serve iframe sub-resources."""
    client = request.scope.get("client", (None, None))
    storage.log_request(s, f"iframe-{resource}")
    if client[1]:
        storage.log_request(s, f"iframe-port-{client[1]}-{resource}")

    if resource.endswith(".json"):
        return Response(content='{"ok":true}', media_type="application/json",
                        headers={"Cache-Control": "no-store"})
    else:
        return Response(content=BEACON_BYTES, media_type="image/png",
                        headers={"Cache-Control": "no-store"})
