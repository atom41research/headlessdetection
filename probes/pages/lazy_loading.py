from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

router = APIRouter()

# Positions in pixels from the top of the page
POSITIONS = list(range(0, 10001, 500))  # 0, 500, 1000, ..., 10000


@router.get("/lazy-loading")
async def lazy_loading_page(s: str = Query(..., description="Session ID")):
    """Page with lazy-loaded images at increasing vertical positions.

    Binary signal: which images are requested reveals the browser's viewport
    and lazy loading threshold behavior. Headless browsers with smaller default
    viewports will request fewer images.
    """
    images = []
    for pos in POSITIONS:
        images.append(
            f'<img src="/track/lazy-{pos}?s={s}" loading="lazy" '
            f'width="10" height="10" '
            f'style="position:absolute;top:{pos}px;left:0;">'
        )

    # Also include a few eagerly-loaded images as control
    controls = []
    for i in range(3):
        controls.append(
            f'<img src="/track/eager-{i}?s={s}" loading="eager" '
            f'width="10" height="10" '
            f'style="position:absolute;top:{i * 100}px;left:20px;">'
        )

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Lazy Loading Probes</title>
    <style>
        body {{ margin: 0; padding: 0; height: 11000px; position: relative; }}
    </style>
</head>
<body>
{chr(10).join(controls)}
{chr(10).join(images)}
</body>
</html>"""

    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})
