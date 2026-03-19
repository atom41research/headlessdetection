"""Extreme rendering stress tests.

The hypothesis: headless Chrome may not fully render (or renders faster because
it doesn't need to composite to screen/GPU upload). If we create pages that are
EXTREMELY expensive to render, the timing pattern of resource requests arriving
at the server should differ.

We interleave heavy rendering elements with beacon requests (background-image
URLs) at regular intervals. If rendering delays request scheduling, the beacons
will arrive more spread out. If headless skips rendering, beacons arrive faster.
"""

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse, Response

router = APIRouter()


@router.get("/stress-granular")
async def stress_granular_page(
    s: str = Query(...),
    count: int = Query(2000, description="Number of heavy elements"),
    beacon_every: int = Query(50, description="Place a beacon every N elements"),
):
    """Interleave heavy CSS elements with beacons at regular intervals.
    Server-side, we measure the arrival times of each beacon to see if
    the rendering load affects request scheduling differently."""
    css_rules = []
    elements = []

    # Start beacon
    css_rules.append(f'.beacon-s {{ width:1px;height:1px;background-image:url("/track/stress-start?s={s}"); position:absolute; top:0; left:0; }}')
    elements.append('<div class="beacon-s"></div>')

    for i in range(count):
        cls = f"h-{i}"
        # Extreme rendering: stacked filters, complex gradients, compositing, box-shadows
        css_rules.append(f"""\
.{cls} {{
    width: 300px; height: 300px;
    filter: blur({5 + (i % 30)}px) brightness({80 + (i % 50)}%) contrast({90 + (i % 40)}%) saturate({150 + (i % 150)}%) hue-rotate({i * 13}deg);
    box-shadow: {', '.join(f'{j*2}px {j*2}px {j*5}px rgba({(i*j*7)%255},{(i*j*11)%255},{(i*j*13)%255},0.6)' for j in range(1, 8))};
    background: repeating-conic-gradient(
        from {i * 7}deg,
        hsl({i % 360}, 70%, 50%) 0deg 2deg,
        hsl({(i * 3) % 360}, 80%, 60%) 2deg 4deg,
        hsl({(i * 7) % 360}, 60%, 40%) 4deg 6deg
    );
    mix-blend-mode: {'overlay' if i % 4 == 0 else 'multiply' if i % 4 == 1 else 'screen' if i % 4 == 2 else 'color-dodge'};
    clip-path: polygon({', '.join(f'{50 + 40 * (1 if (j + i) % 2 else -1) * ((j + i) % 3) / 2}% {50 + 40 * (1 if (j + i + 1) % 2 else -1) * ((j + i + 1) % 3) / 2}%' for j in range(6))});
    position: absolute;
    top: {(i // 10) * 310}px;
    left: {(i % 10) * 310}px;
    will-change: transform;
    transform: rotate({i * 3}deg) scale({0.8 + (i % 5) * 0.1});
    backdrop-filter: blur({2 + i % 10}px);
    opacity: {0.6 + (i % 4) * 0.1};
}}""")
        elements.append(f'<div class="{cls}"></div>')

        # Place beacon at intervals
        if (i + 1) % beacon_every == 0:
            beacon_cls = f"beacon-{i+1}"
            css_rules.append(f'.{beacon_cls} {{ width:1px;height:1px;background-image:url("/track/stress-b{i+1}?s={s}"); position:absolute; top:{(i // 10) * 310}px; left:{(i % 10) * 310 + 305}px; }}')
            elements.append(f'<div class="{beacon_cls}"></div>')

    # End beacon
    css_rules.append(f'.beacon-e {{ width:1px;height:1px;background-image:url("/track/stress-end?s={s}"); position:absolute; bottom:0; left:0; }}')
    elements.append('<div class="beacon-e"></div>')

    total_height = ((count // 10) + 1) * 310
    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>rendering stress test</title>
<style>body {{ margin:0; height:{total_height}px; position:relative; }}
{chr(10).join(css_rules)}
</style></head>
<body>{chr(10).join(elements)}</body>
</html>"""
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


@router.get("/stress-large-images")
async def stress_large_images_page(s: str = Query(...)):
    """Test with actual large images that require significant decode time.
    Uses SVG images with complex filter chains served inline."""
    elements = []

    # Start beacon
    elements.append(f'<img src="/track/lgimg-start?s={s}" width="1" height="1">')

    # Generate multiple complex SVGs as data URIs embedded in background-image
    for i in range(20):
        # Each "image" is served by the server and is a complex SVG
        elements.append(
            f'<div style="width:500px;height:500px;position:absolute;top:{i*510}px;left:0;'
            f'background-image:url(/serve-heavy-svg/{i}?s={s});background-size:cover;"></div>'
        )
        # Beacon after each heavy image
        elements.append(
            f'<img src="/track/lgimg-b{i}?s={s}" width="1" height="1" '
            f'style="position:absolute;top:{i*510+505}px;left:0;">'
        )

    # End beacon
    elements.append(f'<img src="/track/lgimg-end?s={s}" width="1" height="1" style="position:absolute;bottom:0;">')

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>large images stress</title></head>
<body style="margin:0;height:{20*510+100}px;position:relative;">
{chr(10).join(elements)}
</body>
</html>"""
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


@router.get("/serve-heavy-svg/{idx}")
async def serve_heavy_svg(idx: int, s: str = Query(...)):
    """Serve a complex SVG that's expensive to render.
    Uses SVG filters (feGaussianBlur, feTurbulence, feDisplacementMap, etc.)
    which require actual pixel processing."""
    from . import _log_track
    _log_track(s, f"svg-render-{idx}")

    # Generate a complex SVG with expensive filter chains
    filters = []
    for j in range(5):
        filters.append(f"""
    <filter id="f{j}" x="-50%" y="-50%" width="200%" height="200%">
        <feTurbulence type="fractalNoise" baseFrequency="0.{idx+j+1:02d}" numOctaves="5" seed="{idx*10+j}" result="turb"/>
        <feDisplacementMap in="SourceGraphic" in2="turb" scale="{20+j*5}" xChannelSelector="R" yChannelSelector="G" result="disp"/>
        <feGaussianBlur in="disp" stdDeviation="{3+j}" result="blur"/>
        <feColorMatrix in="blur" type="hueRotate" values="{idx*30+j*60}" result="color"/>
        <feMorphology in="color" operator="dilate" radius="{1+j}" result="morph"/>
        <feComposite in="morph" in2="SourceGraphic" operator="over"/>
    </filter>""")

    shapes = []
    for j in range(50):
        shapes.append(
            f'<circle cx="{50 + (j*37)%400}" cy="{50 + (j*53)%400}" r="{20 + j%30}" '
            f'fill="hsl({(idx*50+j*20)%360}, 70%, 50%)" filter="url(#f{j%5})" opacity="0.7"/>'
        )

    svg = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="500" height="500" viewBox="0 0 500 500">
<defs>
{chr(10).join(filters)}
</defs>
<rect width="500" height="500" fill="hsl({idx*20}, 60%, 90%)"/>
{chr(10).join(shapes)}
</svg>"""

    return Response(
        content=svg.encode(),
        media_type="image/svg+xml",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/stress-css-only")
async def stress_css_only_page(
    s: str = Query(...),
    weight: str = Query("heavy", description="'heavy' or 'light' - CSS complexity"),
):
    """Pure CSS stress test - no images except beacons.
    Creates a huge number of elements with either heavy or light CSS.
    Compare beacon arrival patterns between heavy and light versions."""
    N = 3000
    css_rules = []
    elements = []

    css_rules.append(f'.beacon-s {{ width:1px;height:1px;background-image:url("/track/cssonly-{weight}-start?s={s}"); position:absolute; }}')
    elements.append('<div class="beacon-s"></div>')

    for i in range(N):
        cls = f"e-{i}"
        if weight == "heavy":
            css_rules.append(f"""\
.{cls} {{
    width:200px; height:200px;
    filter: blur({3+i%20}px) saturate({200+i%200}%);
    box-shadow: {', '.join(f'{j}px {j}px {j*4}px rgba({(i+j)*7%255},{(i+j)*11%255},{(i+j)*13%255},0.5)' for j in range(1,6))};
    background: conic-gradient(from {i}deg, hsl({i%360},70%,50%) 0deg, hsl({(i+120)%360},80%,60%) 120deg, hsl({(i+240)%360},60%,40%) 240deg);
    mix-blend-mode: overlay;
    position:absolute; top:{(i//15)*210}px; left:{(i%15)*210}px;
}}""")
        else:
            css_rules.append(f"""\
.{cls} {{
    width:200px; height:200px;
    background-color: hsl({i%360},50%,50%);
    position:absolute; top:{(i//15)*210}px; left:{(i%15)*210}px;
}}""")
        elements.append(f'<div class="{cls}"></div>')

        if (i + 1) % 100 == 0:
            bcls = f"beacon-{i+1}"
            css_rules.append(f'.{bcls} {{ width:1px;height:1px;background-image:url("/track/cssonly-{weight}-b{i+1}?s={s}"); position:absolute; top:{(i//15)*210+205}px; left:0; }}')
            elements.append(f'<div class="{bcls}"></div>')

    css_rules.append(f'.beacon-e {{ width:1px;height:1px;background-image:url("/track/cssonly-{weight}-end?s={s}"); position:absolute; bottom:0; }}')
    elements.append('<div class="beacon-e"></div>')

    total_height = ((N // 15) + 1) * 210
    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>CSS-only stress ({weight})</title>
<style>body {{ margin:0; height:{total_height}px; position:relative; }}
{chr(10).join(css_rules)}
</style></head>
<body>{chr(10).join(elements)}</body>
</html>"""
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})
