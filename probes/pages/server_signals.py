"""Server-side signal probe pages.

These pages are designed to exercise server-observable HTTP/TLS signals:
- TLS handshake fingerprinting (JA3/JA4)
- HTTP header ordering and values
- Connection reuse patterns
- Prefetch/preconnect behavior over HTTPS
"""

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, Response, JSONResponse

from probes.middleware.header_capture import get_captures, clear_captures
from core.tls.fingerprint import fingerprint_store, compute_ja3, compute_ja3_raw, compute_ja4

router = APIRouter()


@router.get("/probe-tls-fingerprint")
async def tls_fingerprint_page(s: str = Query(...)):
    """Page that loads several sub-resources over HTTPS.

    The TLS handshake for each connection is captured server-side.
    Loads CSS, JS, images, and a font to see if Chrome opens
    multiple TLS connections or reuses one.
    """
    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"><title>TLS Fingerprint Probe</title>
<link rel="stylesheet" href="/pages/server-signals/resource/style.css?s={s}">
</head>
<body>
<h3>TLS Fingerprint Probe</h3>
<p>This page loads resources to capture TLS handshake data.</p>
<img src="/pages/server-signals/resource/img1.png?s={s}" width="1" height="1">
<img src="/pages/server-signals/resource/img2.png?s={s}" width="1" height="1">
<img src="/pages/server-signals/resource/img3.png?s={s}" width="1" height="1">
<script src="/pages/server-signals/resource/script.js?s={s}" defer></script>
<link rel="preload" href="/pages/server-signals/resource/font.woff2?s={s}" as="font" type="font/woff2" crossorigin>
<img src="/track/tls-fp-beacon?s={s}" width="1" height="1">
</body>
</html>"""
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


@router.get("/probe-header-order")
async def header_order_page(s: str = Query(...)):
    """Page that loads multiple resource types to capture header ordering per type.

    Server records the exact header order for: document, stylesheet, script,
    image, font, and fetch requests.
    """
    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"><title>Header Order Probe</title>
<link rel="stylesheet" href="/pages/server-signals/resource/header-style.css?s={s}">
</head>
<body>
<h3>Header Order Probe</h3>
<img src="/pages/server-signals/resource/header-img.png?s={s}" width="1" height="1">
<script src="/pages/server-signals/resource/header-script.js?s={s}" defer></script>
<script>
// Fetch request - different header profile than navigation
fetch('/pages/server-signals/resource/header-fetch.json?s={s}')
  .then(r => r.json()).catch(() => {{}});

// XHR request
var xhr = new XMLHttpRequest();
xhr.open('GET', '/pages/server-signals/resource/header-xhr.json?s={s}');
xhr.send();
</script>
<img src="/track/header-order-beacon?s={s}" width="1" height="1">
</body>
</html>"""
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


@router.get("/probe-connection-reuse")
async def connection_reuse_page(s: str = Query(...)):
    """Load 30 resources simultaneously to test connection reuse patterns.

    Server tracks unique client ports (= unique TCP connections) and timing.
    Over HTTPS this also reveals TLS session resumption behavior.
    """
    imgs = []
    for i in range(30):
        imgs.append(
            f'<img src="/pages/server-signals/resource/conn-{i:02d}.png?s={s}" width="1" height="1">'
        )

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Connection Reuse Probe</title></head>
<body style="margin:0;">
<h3>Connection Reuse Probe</h3>
{chr(10).join(imgs)}
<img src="/track/conn-reuse-beacon?s={s}" width="1" height="1">
</body>
</html>"""
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


@router.get("/probe-prefetch-tls")
async def prefetch_tls_page(s: str = Query(...)):
    """Test preconnect and prefetch hints over HTTPS.

    <link rel="preconnect"> triggers a TLS handshake without an HTTP request.
    <link rel="prefetch"> fetches a resource at low priority.
    These behaviors may differ between headful and headless.
    """
    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"><title>Prefetch TLS Probe</title>
<link rel="preconnect" href="/">
<link rel="prefetch" href="/pages/server-signals/resource/prefetched.dat?s={s}">
<link rel="preload" href="/pages/server-signals/resource/preloaded.css?s={s}" as="style">
<link rel="dns-prefetch" href="//localhost">
</head>
<body>
<h3>Prefetch TLS Probe</h3>
<p>Testing resource hint behavior.</p>
<img src="/pages/server-signals/resource/prefetch-img.png?s={s}" width="1" height="1">
<img src="/track/prefetch-beacon?s={s}" width="1" height="1">
</body>
</html>"""
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


# --- Sub-resource endpoints ---

@router.get("/server-signals/resource/{resource:path}")
async def serve_resource(resource: str, request: Request, s: str = Query(...)):
    """Serve sub-resources for probe pages. Captures headers on each request."""
    from core import storage
    storage.log_request(s, f"ss-{resource}")

    if resource.endswith(".css"):
        return Response(content="body{}", media_type="text/css",
                        headers={"Cache-Control": "no-store"})
    elif resource.endswith(".js"):
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
        from probes.tracking import BEACON_BYTES
        return Response(content=BEACON_BYTES, media_type="image/png",
                        headers={"Cache-Control": "no-store"})


# --- Results endpoints ---

@router.get("/server-signals/headers/{session_id}")
async def get_header_results(session_id: str):
    """Return captured header data for a session."""
    captures = get_captures(session_id)
    return JSONResponse(content=captures)


@router.get("/server-signals/tls/{session_id}")
async def get_tls_results(session_id: str):
    """Return TLS fingerprint data for a session.

    Note: TLS fingerprints are stored by ssl object id, not session id.
    This endpoint returns all currently stored fingerprints for inspection.
    """
    results = []
    for conn_id, info in list(fingerprint_store.items()):
        results.append({
            "conn_id": conn_id,
            "tls_version": hex(info.tls_version),
            "cipher_suites": [hex(c) for c in info.cipher_suites],
            "extensions": [hex(e) for e in info.extensions],
            "supported_groups": [hex(g) for g in info.supported_groups],
            "ec_point_formats": info.ec_point_formats,
            "signature_algorithms": [hex(a) for a in info.signature_algorithms],
            "alpn_protocols": info.alpn_protocols,
            "server_name": info.server_name,
            "ja3_hash": compute_ja3(info),
            "ja3_raw": compute_ja3_raw(info),
            "ja4": compute_ja4(info),
        })
    return JSONResponse(content=results)


@router.get("/server-signals/tls-all")
async def get_all_tls():
    """Return all stored TLS fingerprints."""
    results = []
    for conn_id, info in list(fingerprint_store.items()):
        results.append({
            "conn_id": conn_id,
            "ja3_hash": compute_ja3(info),
            "ja3_raw": compute_ja3_raw(info),
            "ja4": compute_ja4(info),
            "tls_version": hex(info.tls_version),
            "cipher_count": len(info.cipher_suites),
            "extension_count": len(info.extensions),
            "alpn": info.alpn_protocols,
            "sni": info.server_name,
        })
    return JSONResponse(content=results)


@router.get("/server-signals/tls-clear")
async def clear_tls_store():
    """Clear all stored TLS fingerprints."""
    fingerprint_store.clear()
    return {"status": "cleared"}


@router.get("/server-signals/headers-clear")
async def clear_all_headers():
    """Clear all stored header captures."""
    clear_captures()
    return {"status": "cleared"}
