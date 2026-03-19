from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse, Response

router = APIRouter()


@router.get("/probe-content-visibility")
async def content_visibility_page(s: str = Query(...)):
    """content-visibility: auto skips rendering for offscreen elements.
    The browser may defer loading sub-resources for elements with this property.
    Test if behavior differs between headful and headless.
    """
    css_rules = []
    elements = []

    # Elements with content-visibility: auto at various positions
    for pos in range(0, 8001, 200):
        cls = f"cv-{pos}"
        css_rules.append(f"""
.{cls} {{
    content-visibility: auto;
    contain-intrinsic-size: 100px 100px;
    position: absolute;
    top: {pos}px;
    left: 0;
    width: 100px;
    height: 100px;
    background-image: url("/track/cv-{pos}?s={s}");
    background-size: 1px 1px;
    background-repeat: no-repeat;
}}""")
        elements.append(f'<div class="{cls}"></div>')

    # Control: same elements WITHOUT content-visibility
    for pos in range(0, 8001, 200):
        cls = f"nocv-{pos}"
        css_rules.append(f"""
.{cls} {{
    position: absolute;
    top: {pos}px;
    left: 120px;
    width: 100px;
    height: 100px;
    background-image: url("/track/nocv-{pos}?s={s}");
    background-size: 1px 1px;
    background-repeat: no-repeat;
}}""")
        elements.append(f'<div class="{cls}"></div>')

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>content-visibility probe</title>
<style>body {{ margin:0; height:9000px; position:relative; }}
{chr(10).join(css_rules)}
</style></head>
<body>{chr(10).join(elements)}</body>
</html>"""
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


@router.get("/probe-video-audio")
async def video_audio_page(s: str = Query(...)):
    """Test video/audio preload behavior differences.
    poster images, preload attributes, and source elements.
    """
    elements = []

    # Video with poster at various positions
    for i, preload in enumerate(["none", "metadata", "auto"]):
        elements.append(
            f'<video preload="{preload}" width="100" height="100" '
            f'poster="/track/vidposter-{preload}?s={s}" '
            f'style="position:absolute;top:{i*120}px;left:0;">'
            f'<source src="/track/vidsrc-{preload}?s={s}" type="video/mp4">'
            f'</video>'
        )

    # Audio with preload
    for i, preload in enumerate(["none", "metadata", "auto"]):
        elements.append(
            f'<audio preload="{preload}" '
            f'style="position:absolute;top:{(i+3)*120}px;left:0;">'
            f'<source src="/track/audsrc-{preload}?s={s}" type="audio/mpeg">'
            f'</audio>'
        )

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>video/audio probe</title></head>
<body style="margin:0;height:2000px;position:relative;">
{chr(10).join(elements)}
</body>
</html>"""
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


@router.get("/probe-link-hints")
async def link_hints_page(s: str = Query(...)):
    """Test resource hint behavior: prefetch, preload, preconnect, dns-prefetch, modulepreload.
    These may be handled differently in headless mode.
    """
    links = [
        ("prefetch", f"/track/hint-prefetch?s={s}", "image"),
        ("preload", f"/track/hint-preload?s={s}", "image"),
        ("preload", f"/track/hint-preload-style?s={s}", "style"),
        ("preload", f"/track/hint-preload-font?s={s}", "font"),
        ("modulepreload", f"/track/hint-modulepreload?s={s}", None),
    ]

    link_tags = []
    for rel, href, as_type in links:
        as_attr = f' as="{as_type}"' if as_type else ''
        crossorigin = ' crossorigin' if as_type == 'font' else ''
        link_tags.append(f'<link rel="{rel}" href="{href}"{as_attr}{crossorigin}>')

    # Also test with <link> in body (non-standard but some browsers handle it)
    body_links = [
        f'<link rel="prefetch" href="/track/hint-body-prefetch?s={s}" as="image">',
    ]

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"><title>resource hints probe</title>
{chr(10).join(link_tags)}
</head>
<body>
{chr(10).join(body_links)}
<img src="/track/hint-regular-img?s={s}" width="1" height="1">
</body>
</html>"""
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


@router.get("/probe-request-order")
async def request_order_page(s: str = Query(...)):
    """Test the ORDER in which resources are requested.
    Mix different resource types: CSS, images, fonts, iframes.
    The priority/scheduling may differ between modes.
    """
    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"><title>request order probe</title>
<link rel="stylesheet" href="/track/order-css-1?s={s}">
<link rel="stylesheet" href="/track/order-css-2?s={s}">
<style>
@font-face {{ font-family: 'OrderFont'; src: url('/font/track/order-font-1?s={s}') format('woff2'); font-display: swap; }}
.use-font {{ font-family: 'OrderFont', serif; }}
.bg1 {{ background-image: url("/track/order-bg-1?s={s}"); width:10px; height:10px; }}
.bg2 {{ background-image: url("/track/order-bg-2?s={s}"); width:10px; height:10px; }}
.bg3 {{ background-image: url("/track/order-bg-3?s={s}"); width:10px; height:10px; }}
</style>
</head>
<body>
<img src="/track/order-img-1?s={s}" width="10" height="10">
<img src="/track/order-img-2?s={s}" width="10" height="10">
<img src="/track/order-img-3?s={s}" width="10" height="10">
<div class="bg1"></div>
<div class="bg2"></div>
<div class="bg3"></div>
<p class="use-font">font test</p>
<iframe src="/track/order-iframe-1?s={s}" width="10" height="10" style="border:none;"></iframe>
<img src="/track/order-img-4?s={s}" width="10" height="10" loading="lazy">
<img src="/track/order-img-5?s={s}" width="10" height="10" loading="lazy">
</body>
</html>"""
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


@router.get("/probe-heavy-render")
async def heavy_render_page(s: str = Query(...)):
    """Extremely heavy CSS rendering test.
    Thousands of elements with complex properties to stress the rendering pipeline.
    Measure total time from first to last resource request.
    """
    css_rules = []
    elements = []

    # Start beacon
    css_rules.append(f'.beacon-start {{ width:1px;height:1px;background-image:url("/track/heavy-start?s={s}"); position:absolute; }}')

    # 500 heavy elements with stacked filters
    for i in range(500):
        cls = f"heavy-{i}"
        css_rules.append(f"""
.{cls} {{
    width: 200px; height: 200px;
    filter: blur({3 + (i % 20)}px) brightness({100 + (i % 50)}%) contrast({100 + (i % 30)}%) saturate({200 + (i % 100)}%) hue-rotate({i * 7}deg);
    box-shadow: {', '.join(f'{j}px {j}px {j*3}px rgba({(i*j)%255},{(i*j*2)%255},{(i*j*3)%255},0.5)' for j in range(1, 6))};
    background: repeating-conic-gradient(from {i}deg, hsl({i}, 70%, 50%) 0deg 1deg, hsl({i+60}, 80%, 60%) 1deg 2deg);
    mix-blend-mode: {'overlay' if i % 3 == 0 else 'multiply' if i % 3 == 1 else 'screen'};
    position: absolute;
    top: {(i // 10) * 210}px;
    left: {(i % 10) * 210}px;
}}""")
        elements.append(f'<div class="{cls}"></div>')

    # Mid beacon after heavy elements
    css_rules.append(f'.beacon-mid {{ width:1px;height:1px;background-image:url("/track/heavy-mid?s={s}"); position:absolute; }}')

    # 500 simple elements
    for i in range(500):
        cls = f"simple-{i}"
        css_rules.append(f".{cls} {{ width:200px; height:200px; background-color: hsl({i}, 50%, 50%); position:absolute; top:{(i//10)*210 + 11000}px; left:{(i%10)*210}px; }}")
        elements.append(f'<div class="{cls}"></div>')

    # End beacon
    css_rules.append(f'.beacon-end {{ width:1px;height:1px;background-image:url("/track/heavy-end?s={s}"); position:absolute; }}')

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>heavy render probe</title>
<style>body {{ margin:0; height:25000px; position:relative; }}
{chr(10).join(css_rules)}
</style></head>
<body>
<div class="beacon-start"></div>
{chr(10).join(elements)}
<div class="beacon-mid"></div>
<div class="beacon-end"></div>
</body>
</html>"""
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


@router.get("/probe-scrollbar")
async def scrollbar_page(s: str = Query(...)):
    """Detect scrollbar presence/width via CSS.
    Scrollbar rendering may differ in headless mode.
    Use 100vw vs 100% width difference to detect scrollbar width.
    """
    # The trick: 100vw includes scrollbar, 100% doesn't.
    # An element at exactly 100% width won't overflow, but 100vw will if scrollbar exists.
    # We can use media queries with exact px values around the boundary.

    css_rules = []
    elements = []

    # Probe viewport width at precise boundaries
    for w in range(1260, 1300):
        probe = f"scrollbar-vw-{w}"
        css_rules.append(f'@media (min-width: {w}px) {{ .probe-{probe} {{ background-image: url("/track/{probe}?s={s}"); }} }}')
        elements.append(f'<div class="probe-{probe}" style="width:1px;height:1px;position:absolute;"></div>')

    # Also use an element trick: place a div at 100vw width, and another at 100%
    # The difference in their actual width reveals the scrollbar
    css_rules.append(f"""
.vw-probe {{
    width: 100vw;
    height: 1px;
    overflow: hidden;
    background-image: url("/track/scrollbar-vw-full?s={s}");
    background-size: 1px 1px;
    background-repeat: no-repeat;
}}
.pct-probe {{
    width: 100%;
    height: 1px;
    overflow: hidden;
    background-image: url("/track/scrollbar-pct-full?s={s}");
    background-size: 1px 1px;
    background-repeat: no-repeat;
}}
""")

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>scrollbar probe</title>
<style>body {{ margin:0; height:3000px; position:relative; }}
{chr(10).join(css_rules)}
</style></head>
<body>
<div class="vw-probe"></div>
<div class="pct-probe"></div>
{chr(10).join(elements)}
</body>
</html>"""
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


@router.get("/probe-animation-timing")
async def animation_timing_page(s: str = Query(...)):
    """Use CSS animations with delays to trigger resource loads at specific times.
    animation-delay + animation-fill-mode:forwards can change element visibility
    after a delay, potentially triggering background-image loads.

    If the animation timer runs differently in headless vs headful, the server
    will see resources requested at different times.
    """
    css_rules = []
    elements = []

    # Beacon at load time
    css_rules.append(f'.anim-start {{ background-image: url("/track/anim-start?s={s}"); width:1px;height:1px;position:absolute; }}')

    # Elements that become visible after CSS animation delays
    for delay_ms in [0, 50, 100, 200, 500, 1000, 2000]:
        cls = f"anim-{delay_ms}"
        css_rules.append(f"""
@keyframes reveal-{delay_ms} {{
    from {{ width: 0; height: 0; }}
    to {{ width: 100px; height: 100px; }}
}}
.{cls} {{
    width: 0;
    height: 0;
    overflow: hidden;
    animation: reveal-{delay_ms} 0.001s forwards;
    animation-delay: {delay_ms}ms;
    background-image: url("/track/anim-{delay_ms}?s={s}");
    background-size: 1px 1px;
    background-repeat: no-repeat;
    position: absolute;
    top: 0;
    left: {delay_ms // 10}px;
}}""")
        elements.append(f'<div class="{cls}"></div>')

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>animation timing probe</title>
<style>
{chr(10).join(css_rules)}
</style></head>
<body>
<div class="anim-start"></div>
{chr(10).join(elements)}
</body>
</html>"""
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


@router.get("/probe-print-media")
async def print_media_page(s: str = Query(...)):
    """Test @media print behavior. Headless may handle print stylesheets differently."""
    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>print media probe</title>
<style>
.screen-only {{ background-image: url("/track/print-screen?s={s}"); width:1px;height:1px; }}
@media print {{
    .print-only {{ background-image: url("/track/print-print?s={s}"); width:1px;height:1px; }}
}}
@media screen {{
    .media-screen {{ background-image: url("/track/print-mediascreen?s={s}"); width:1px;height:1px; }}
}}
@media not print {{
    .not-print {{ background-image: url("/track/print-notprint?s={s}"); width:1px;height:1px; }}
}}
</style></head>
<body>
<div class="screen-only"></div>
<div class="print-only"></div>
<div class="media-screen"></div>
<div class="not-print"></div>
</body>
</html>"""
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


@router.get("/probe-focus-visibility")
async def focus_visibility_page(s: str = Query(...)):
    """Test page visibility and focus-related CSS.
    :focus-visible, :focus-within, autofocus behavior.
    """
    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>focus/visibility probe</title>
<style>
/* Test if autofocused element triggers :focus styles */
input:focus {{ background-image: url("/track/focus-input-focus?s={s}"); }}
input:focus-visible {{ background-image: url("/track/focus-input-focus-visible?s={s}"); }}
.wrapper:focus-within {{ background-image: url("/track/focus-wrapper-focus-within?s={s}"); }}

/* Always-on probes */
.always {{ background-image: url("/track/focus-always?s={s}"); width:1px;height:1px; }}
</style></head>
<body>
<div class="always"></div>
<div class="wrapper">
    <input type="text" autofocus style="width:100px;">
</div>
</body>
</html>"""
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})
