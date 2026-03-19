"""Compositor stress probes.

The insight: headful Chrome's extra resource consumption comes from the
compositing/display pipeline - GPU process, vsync, frame production.
Static CSS triggers requests during LAYOUT (before compositing).
To detect headless, we need to stress the COMPOSITOR by forcing continuous
animation/repainting while simultaneously loading resources.

Approach:
1. CSS animations that force continuous repainting at 60fps
2. Animations use properties that trigger compositing (transform, opacity)
3. Combine with expensive per-frame work (animated blur, backdrop-filter)
4. Load resources DURING the animation period using animation-delay
5. Measure how compositor contention affects resource arrival timing
"""

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/stress-compositor")
async def compositor_stress_page(
    s: str = Query(...),
    n_layers: int = Query(200, description="Number of animated layers"),
    duration: int = Query(3, description="Animation duration in seconds"),
):
    """Create many animated layers that force compositor work every frame.
    Background-image beacons are triggered at animation keyframe points
    via animation-delay, so their arrival depends on frame processing speed."""
    css_rules = []
    elements = []

    # Start beacon (fires immediately)
    css_rules.append(f'.b-start {{ width:1px;height:1px;background-image:url("/track/comp-start?s={s}"); position:fixed; top:0; left:0; }}')
    elements.append('<div class="b-start"></div>')

    # Create many animated layers with GPU-heavy properties
    for i in range(n_layers):
        cls = f"layer-{i}"
        # will-change: transform promotes to own compositing layer
        # Animate transform + filter simultaneously = heavy compositor work per frame
        css_rules.append(f"""
@keyframes spin-{i} {{
    0% {{ transform: rotate(0deg) scale(1.0); filter: blur({2 + i % 10}px) hue-rotate(0deg); opacity: 0.8; }}
    25% {{ transform: rotate(90deg) scale(1.2); filter: blur({5 + i % 15}px) hue-rotate(90deg); opacity: 0.6; }}
    50% {{ transform: rotate(180deg) scale(0.8); filter: blur({3 + i % 12}px) hue-rotate(180deg); opacity: 0.9; }}
    75% {{ transform: rotate(270deg) scale(1.1); filter: blur({4 + i % 8}px) hue-rotate(270deg); opacity: 0.7; }}
    100% {{ transform: rotate(360deg) scale(1.0); filter: blur({2 + i % 10}px) hue-rotate(360deg); opacity: 0.8; }}
}}
.{cls} {{
    width: 150px; height: 150px;
    position: absolute;
    top: {(i // 20) * 160}px;
    left: {(i % 20) * 160}px;
    will-change: transform, filter, opacity;
    animation: spin-{i} {duration}s linear infinite;
    background: conic-gradient(from {i * 18}deg, hsl({i * 7 % 360}, 70%, 50%), hsl({(i * 7 + 120) % 360}, 80%, 60%), hsl({(i * 7 + 240) % 360}, 60%, 40%));
    mix-blend-mode: {'overlay' if i % 3 == 0 else 'multiply' if i % 3 == 1 else 'screen'};
    border-radius: {20 + i % 30}%;
    backdrop-filter: blur({1 + i % 5}px);
}}""")
        elements.append(f'<div class="{cls}"></div>')

    # Beacon elements triggered by animation-delay
    # These become visible (and load their background) at specific times
    # The compositor's frame production speed affects when these actually fire
    for delay_ms in range(0, duration * 1000 + 1, 200):
        bcls = f"comp-beacon-{delay_ms}"
        css_rules.append(f"""
@keyframes reveal-{delay_ms} {{
    from {{ width: 0; height: 0; }}
    to {{ width: 10px; height: 10px; }}
}}
.{bcls} {{
    width: 0; height: 0; overflow: hidden;
    animation: reveal-{delay_ms} 0.001s forwards;
    animation-delay: {delay_ms}ms;
    background-image: url("/track/comp-t{delay_ms}?s={s}");
    background-size: 1px 1px;
    background-repeat: no-repeat;
    position: fixed;
    bottom: 0;
    right: {delay_ms // 10}px;
}}""")
        elements.append(f'<div class="{bcls}"></div>')

    total_height = ((n_layers // 20) + 1) * 160
    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>compositor stress</title>
<style>
body {{ margin:0; height:{max(total_height, 2000)}px; position:relative; overflow: hidden; }}
{chr(10).join(css_rules)}
</style></head>
<body>
{chr(10).join(elements)}
</body>
</html>"""
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


@router.get("/stress-repaint")
async def repaint_stress_page(
    s: str = Query(...),
    n_elements: int = Query(500, description="Number of elements"),
):
    """Force continuous repainting using CSS animations on paint-triggering
    properties (not just compositing properties like transform).

    Properties that trigger REPAINT: color, background-color, box-shadow,
    border-color, outline, visibility, text-decoration.

    Properties that trigger REFLOW+REPAINT: width, height, padding, margin,
    font-size, line-height.

    We animate paint-triggering properties to force the render pipeline to
    do actual pixel work every frame, not just compositor work."""
    css_rules = []
    elements = []

    css_rules.append(f'.b-start {{ width:1px;height:1px;background-image:url("/track/repaint-start?s={s}"); position:fixed; top:0; left:0; }}')
    elements.append('<div class="b-start"></div>')

    for i in range(n_elements):
        cls = f"rp-{i}"
        # Animate properties that force REPAINT (not just composite)
        css_rules.append(f"""
@keyframes repaint-{i} {{
    0% {{
        box-shadow: 0 0 {10+i%20}px rgba({i*7%255},{i*11%255},{i*13%255},0.8);
        background-color: hsl({i*7%360}, 70%, 50%);
        border-color: hsl({i*13%360}, 80%, 40%);
        outline: {2+i%5}px solid hsl({i*17%360}, 60%, 60%);
    }}
    50% {{
        box-shadow: 0 0 {30+i%40}px rgba({(i*7+128)%255},{(i*11+128)%255},{(i*13+128)%255},0.5);
        background-color: hsl({(i*7+180)%360}, 70%, 50%);
        border-color: hsl({(i*13+180)%360}, 80%, 40%);
        outline: {5+i%8}px solid hsl({(i*17+180)%360}, 60%, 60%);
    }}
    100% {{
        box-shadow: 0 0 {10+i%20}px rgba({i*7%255},{i*11%255},{i*13%255},0.8);
        background-color: hsl({i*7%360}, 70%, 50%);
        border-color: hsl({i*13%360}, 80%, 40%);
        outline: {2+i%5}px solid hsl({i*17%360}, 60%, 60%);
    }}
}}
.{cls} {{
    width: 100px; height: 100px;
    position: absolute;
    top: {(i // 15) * 110}px;
    left: {(i % 15) * 110}px;
    animation: repaint-{i} 0.5s linear infinite;
    border: 3px solid black;
    border-radius: 50%;
}}""")
        elements.append(f'<div class="{cls}"></div>')

    # Timed beacons
    for delay_ms in range(0, 3001, 100):
        bcls = f"rpb-{delay_ms}"
        css_rules.append(f"""
@keyframes rpreveal-{delay_ms} {{
    from {{ width: 0; height: 0; }}
    to {{ width: 10px; height: 10px; }}
}}
.{bcls} {{
    width: 0; height: 0; overflow: hidden;
    animation: rpreveal-{delay_ms} 0.001s forwards;
    animation-delay: {delay_ms}ms;
    background-image: url("/track/repaint-t{delay_ms}?s={s}");
    background-size: 1px 1px; background-repeat: no-repeat;
    position: fixed; bottom: 0; right: {delay_ms // 5}px;
}}""")
        elements.append(f'<div class="{bcls}"></div>')

    total_height = ((n_elements // 15) + 1) * 110
    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>repaint stress</title>
<style>
body {{ margin:0; height:{max(total_height, 2000)}px; position:relative; overflow:hidden; }}
{chr(10).join(css_rules)}
</style></head>
<body>
{chr(10).join(elements)}
</body>
</html>"""
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


@router.get("/stress-reflow")
async def reflow_stress_page(
    s: str = Query(...),
    n_elements: int = Query(300, description="Number of reflowing elements"),
):
    """Animate properties that trigger REFLOW (layout recalculation).
    Reflow is expensive and blocks the main thread.
    Animating width/height forces layout recalculation every frame.

    In headful, reflow + repaint + composite all happen.
    In headless, reflow + repaint happen but composite-to-display is cheaper."""
    css_rules = []
    elements = []

    css_rules.append(f'.b-start {{ width:1px;height:1px;background-image:url("/track/reflow-start?s={s}"); position:fixed; top:0; left:0; }}')
    elements.append('<div class="b-start"></div>')

    for i in range(n_elements):
        cls = f"rf-{i}"
        # Animate width/height = reflow trigger
        # Also add text content so font metrics must be recalculated
        css_rules.append(f"""
@keyframes reflow-{i} {{
    0% {{ width: 80px; height: 80px; padding: 5px; font-size: 12px; }}
    50% {{ width: 120px; height: 120px; padding: 15px; font-size: 18px; }}
    100% {{ width: 80px; height: 80px; padding: 5px; font-size: 12px; }}
}}
.{cls} {{
    position: absolute;
    top: {(i // 10) * 140}px;
    left: {(i % 10) * 140}px;
    animation: reflow-{i} 0.3s linear infinite;
    background-color: hsl({i*12%360}, 60%, 70%);
    border: 2px solid hsl({i*12%360}, 60%, 40%);
    overflow: hidden;
    contain: layout style;
}}""")
        elements.append(f'<div class="{cls}">Text {i} reflow test content</div>')

    # Timed beacons
    for delay_ms in range(0, 3001, 100):
        bcls = f"rfb-{delay_ms}"
        css_rules.append(f"""
@keyframes rfreveal-{delay_ms} {{
    from {{ width: 0; height: 0; }}
    to {{ width: 10px; height: 10px; }}
}}
.{bcls} {{
    width: 0; height: 0; overflow: hidden;
    animation: rfreveal-{delay_ms} 0.001s forwards;
    animation-delay: {delay_ms}ms;
    background-image: url("/track/reflow-t{delay_ms}?s={s}");
    background-size: 1px 1px; background-repeat: no-repeat;
    position: fixed; bottom: 0; right: {delay_ms // 5}px;
}}""")
        elements.append(f'<div class="{bcls}"></div>')

    total_height = ((n_elements // 10) + 1) * 140
    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>reflow stress</title>
<style>
body {{ margin:0; height:{max(total_height, 2000)}px; position:relative; overflow:hidden; }}
{chr(10).join(css_rules)}
</style></head>
<body>
{chr(10).join(elements)}
</body>
</html>"""
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})
