from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/font-loading")
async def font_loading_page(s: str = Query(..., description="Session ID")):
    """Page with multiple @font-face declarations and varying font-display strategies.

    Timing signal: tracks which fonts are requested and when. font-display: optional
    may cause headless browsers to skip font loading entirely if the initial load
    window is missed.
    """
    font_declarations = []
    elements = []

    variants = [
        ("test-swap", "swap"),
        ("test-block", "block"),
        ("test-fallback", "fallback"),
        ("test-optional", "optional"),
        ("test-auto", "auto"),
    ]

    for font_name, display in variants:
        font_declarations.append(f"""
@font-face {{
    font-family: '{font_name}';
    src: url('/font/track/{font_name}?s={s}') format('woff2');
    font-display: {display};
}}""")
        elements.append(
            f'<p style="font-family: \'{font_name}\', serif; font-size: 16px;">'
            f"Font test: {font_name} (display: {display})</p>"
        )

    # Also test different weights of the same font family
    for weight in (100, 400, 700, 900):
        font_name = f"test-weight-{weight}"
        font_declarations.append(f"""
@font-face {{
    font-family: 'test-weighted';
    src: url('/font/track/{font_name}?s={s}') format('woff2');
    font-weight: {weight};
    font-display: swap;
}}""")
        elements.append(
            f'<p style="font-family: \'test-weighted\', serif; font-weight: {weight}; font-size: 16px;">'
            f"Weight test: {weight}</p>"
        )

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Font Loading Test</title>
    <style>
{chr(10).join(font_declarations)}
    </style>
</head>
<body>
{chr(10).join(elements)}
</body>
</html>"""

    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})
