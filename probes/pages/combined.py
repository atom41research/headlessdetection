from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/combined")
async def combined_page(
    s: str = Query(..., description="Session ID"),
    chain_length: int = Query(6, description="CSS chain length"),
):
    """Combined page incorporating all detection mechanisms.

    Includes media query probes, lazy loading images, CSS import chains,
    background image chains, and font loading - all on a single page.
    """
    # --- Media query probes ---
    mq_probes = [
        ("prefers-color-scheme: dark", "mq-dark-scheme"),
        ("prefers-color-scheme: light", "mq-light-scheme"),
        ("prefers-reduced-motion: reduce", "mq-reduced-motion"),
        ("prefers-reduced-motion: no-preference", "mq-no-reduced-motion"),
        ("hover: hover", "mq-hover"),
        ("hover: none", "mq-no-hover"),
        ("pointer: fine", "mq-pointer-fine"),
        ("pointer: coarse", "mq-pointer-coarse"),
        ("max-width: 799px", "mq-vw-lt800"),
        ("min-width: 800px) and (max-width: 1023px", "mq-vw-800-1023"),
        ("min-width: 1024px) and (max-width: 1279px", "mq-vw-1024-1279"),
        ("min-width: 1280px", "mq-vw-gte1280"),
        ("max-height: 599px", "mq-vh-lt600"),
        ("min-height: 600px) and (max-height: 719px", "mq-vh-600-719"),
        ("min-height: 720px", "mq-vh-gte720"),
    ]

    mq_css = []
    mq_html = []
    for query, name in mq_probes:
        mq_css.append(f'@media ({query}) {{ .probe-{name} {{ background-image: url("/track/{name}?s={s}"); }} }}')
        mq_html.append(f'<div class="probe-{name}" style="width:1px;height:1px;position:absolute;"></div>')

    # --- Lazy loading images ---
    lazy_positions = list(range(0, 6001, 500))
    lazy_html = []
    for pos in lazy_positions:
        lazy_html.append(
            f'<img src="/track/lazy-{pos}?s={s}" loading="lazy" '
            f'width="10" height="10" style="position:absolute;top:{pos}px;left:50px;">'
        )

    # --- Background image elements ---
    bg_css = []
    bg_html = []
    bg_css.append(f'.bg-start {{ width:1px;height:1px;background-image:url("/track/bg-start?s={s}");position:absolute; }}')
    for i in range(8):
        bg_css.append(f"""
.bg-heavy-{i} {{
    width:400px; height:400px;
    background-image: url("/track/bg-heavy-{i}?s={s}");
    background-size: 1px 1px; background-repeat: no-repeat;
    filter: blur({5+i*3}px) saturate({200+i*50}%);
    box-shadow: {', '.join(f'{j*2}px {j*2}px {j*6}px rgba(0,0,0,0.3)' for j in range(1,6))};
    background-color: hsl({i*45}, 70%, 50%);
}}""")
        bg_html.append(f'<div class="bg-heavy-{i}" style="position:absolute;top:{6500+i*420}px;"></div>')

    for i in range(8):
        bg_css.append(f"""
.bg-light-{i} {{
    width:400px; height:400px;
    background-image: url("/track/bg-light-{i}?s={s}");
    background-size: 1px 1px; background-repeat: no-repeat;
    background-color: #eee;
}}""")
        bg_html.append(f'<div class="bg-light-{i}" style="position:absolute;top:{10000+i*420}px;"></div>')

    # --- Font loading ---
    font_css = []
    font_html = []
    for display in ("swap", "block", "optional"):
        name = f"test-{display}"
        font_css.append(f"""
@font-face {{
    font-family: '{name}';
    src: url('/font/track/{name}?s={s}') format('woff2');
    font-display: {display};
}}""")
        font_html.append(f'<p style="font-family:\'{name}\',serif;position:absolute;top:{14000}px;">Font: {name}</p>')

    # --- CSS import chain links ---
    expensive_url = f"/css/chain/expensive/0?s={s}&total={chain_length}&expensive=true"
    control_url = f"/css/chain/control/0?s={s}&total={chain_length}&expensive=false"

    chain_html = []
    for chain_id in ("expensive", "control"):
        for step in range(chain_length):
            for el in range(10):
                chain_html.append(
                    f'<div class="chain-{chain_id}-s{step}-el{el}" '
                    f'style="width:400px;height:400px;position:absolute;top:{15000+step*400+el*40}px;"></div>'
                )
        chain_html.append(f'<div class="chain-{chain_id}-beacon" style="width:1px;height:1px;position:absolute;"></div>')

    total_height = 15000 + chain_length * 400 * 10 + 2000

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Combined Detection Test</title>
    <link rel="stylesheet" href="{expensive_url}">
    <link rel="stylesheet" href="{control_url}">
    <style>
{chr(10).join(mq_css)}
{chr(10).join(bg_css)}
{chr(10).join(font_css)}
    </style>
</head>
<body style="margin:0;position:relative;height:{total_height}px;">
<div class="bg-start"></div>
{chr(10).join(mq_html)}
{chr(10).join(lazy_html)}
{chr(10).join(bg_html)}
{chr(10).join(font_html)}
{chr(10).join(chain_html)}
</body>
</html>"""

    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})
