from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/background-chains")
async def background_chains_page(s: str = Query(..., description="Session ID")):
    """Page with elements that have CSS background-image loads + varying render complexity.

    Timing signal: elements with heavy CSS filters/effects may delay when the browser
    fetches their background images compared to simple elements. The server compares
    request timing of heavy vs lightweight elements.
    """
    elements = []
    css_rules = []

    # Heavy elements: expensive CSS that stresses software rasterizer
    for i in range(15):
        cls = f"bg-heavy-{i}"
        css_rules.append(f"""
.{cls} {{
    width: 600px;
    height: 600px;
    background-image: url("/track/bg-heavy-{i}?s={s}");
    background-size: 1px 1px;
    background-repeat: no-repeat;
    filter: blur({5 + i * 3}px) saturate({200 + i * 50}%);
    box-shadow: {', '.join(f'{j*2}px {j*2}px {j*8}px rgba(0,0,0,0.{min(j,9)})' for j in range(1, 10))};
    backdrop-filter: blur({3 + i}px);
    background-color: hsl({i * 24}, 70%, 50%);
}}""")
        elements.append(f'<div class="{cls}"></div>')

    # Light elements: minimal CSS, same background-image pattern
    for i in range(15):
        cls = f"bg-light-{i}"
        css_rules.append(f"""
.{cls} {{
    width: 600px;
    height: 600px;
    background-image: url("/track/bg-light-{i}?s={s}");
    background-size: 1px 1px;
    background-repeat: no-repeat;
    background-color: #eee;
}}""")
        elements.append(f'<div class="{cls}"></div>')

    # A start beacon to mark page render beginning
    css_rules.append(f"""
.bg-start-beacon {{
    width: 1px;
    height: 1px;
    background-image: url("/track/bg-start?s={s}");
    position: absolute;
    top: 0;
    left: 0;
}}""")

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Background Chain Test</title>
    <style>
        body {{ margin: 0; }}
{chr(10).join(css_rules)}
    </style>
</head>
<body>
<div class="bg-start-beacon"></div>
{chr(10).join(elements)}
</body>
</html>"""

    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})
