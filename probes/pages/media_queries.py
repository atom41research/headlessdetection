from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/media-queries")
async def media_queries_page(s: str = Query(..., description="Session ID")):
    """Page that uses CSS media queries to conditionally load tracked resources.

    Binary signal: which probes fire reveals the browser's environment.
    """
    probes = [
        # Color scheme
        ("prefers-color-scheme: dark", "mq-dark-scheme"),
        ("prefers-color-scheme: light", "mq-light-scheme"),
        # Motion preferences
        ("prefers-reduced-motion: reduce", "mq-reduced-motion"),
        ("prefers-reduced-motion: no-preference", "mq-no-reduced-motion"),
        # Pointer/hover capabilities
        ("hover: hover", "mq-hover"),
        ("hover: none", "mq-no-hover"),
        ("pointer: fine", "mq-pointer-fine"),
        ("pointer: coarse", "mq-pointer-coarse"),
        ("pointer: none", "mq-pointer-none"),
        # Viewport width breakpoints
        ("max-width: 799px", "mq-vw-lt800"),
        ("min-width: 800px) and (max-width: 1023px", "mq-vw-800-1023"),
        ("min-width: 1024px) and (max-width: 1279px", "mq-vw-1024-1279"),
        ("min-width: 1280px) and (max-width: 1919px", "mq-vw-1280-1919"),
        ("min-width: 1920px", "mq-vw-gte1920"),
        # Viewport height breakpoints
        ("max-height: 599px", "mq-vh-lt600"),
        ("min-height: 600px) and (max-height: 719px", "mq-vh-600-719"),
        ("min-height: 720px) and (max-height: 1079px", "mq-vh-720-1079"),
        ("min-height: 1080px", "mq-vh-gte1080"),
        # Display mode
        ("display-mode: browser", "mq-display-browser"),
        # Color depth
        ("min-color: 8", "mq-color-8bit"),
        # Contrast preference
        ("prefers-contrast: more", "mq-high-contrast"),
        ("prefers-contrast: no-preference", "mq-no-contrast-pref"),
    ]

    css_rules = []
    html_elements = []
    for media_query, probe_name in probes:
        css_rules.append(
            f"@media ({media_query}) {{\n"
            f'  .probe-{probe_name} {{ background-image: url("/track/{probe_name}?s={s}"); }}\n'
            f"}}"
        )
        html_elements.append(f'<div class="probe-{probe_name}" style="width:1px;height:1px;position:absolute;"></div>')

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Media Query Probes</title>
    <style>
{chr(10).join(css_rules)}
    </style>
</head>
<body>
{chr(10).join(html_elements)}
</body>
</html>"""

    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})
