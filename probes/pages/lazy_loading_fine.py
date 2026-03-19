from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/lazy-fine")
async def lazy_fine_page(
    s: str = Query(..., description="Session ID"),
    step: int = Query(100, description="Position step in pixels"),
    max_pos: int = Query(6000, description="Maximum position"),
):
    """Fine-grained lazy loading test with configurable step size.

    Used to precisely determine the lazy loading threshold in different modes.
    """
    positions = list(range(0, max_pos + 1, step))

    images = []
    for pos in positions:
        images.append(
            f'<img src="/track/lazyfine-{pos}?s={s}" loading="lazy" '
            f'width="10" height="10" '
            f'style="position:absolute;top:{pos}px;left:0;">'
        )

    # Eager control
    images.append(
        f'<img src="/track/lazyfine-eager?s={s}" loading="eager" '
        f'width="10" height="10" style="position:absolute;top:0;left:20px;">'
    )

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Fine-grained Lazy Loading</title>
    <style>
        body {{ margin: 0; padding: 0; height: {max_pos + 100}px; position: relative; }}
    </style>
</head>
<body>
{chr(10).join(images)}
</body>
</html>"""

    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


@router.get("/lazy-srcset")
async def lazy_srcset_page(s: str = Query(..., description="Session ID")):
    """Test lazy loading with srcset and picture elements.

    Explores whether srcset/picture interact differently with lazy loading
    in headful vs headless modes.
    """
    elements = []

    # Regular img with loading=lazy at various positions
    for pos in range(0, 5001, 500):
        elements.append(
            f'<img src="/track/lzsrcset-img-{pos}?s={s}" loading="lazy" '
            f'width="100" height="100" '
            f'style="position:absolute;top:{pos}px;left:0;">'
        )

    # img with srcset - does lazy loading respect srcset differently?
    for pos in range(0, 5001, 500):
        elements.append(
            f'<img src="/track/lzsrcset-srcset-{pos}-1x?s={s}" '
            f'srcset="/track/lzsrcset-srcset-{pos}-2x?s={s} 2x, /track/lzsrcset-srcset-{pos}-3x?s={s} 3x" '
            f'loading="lazy" width="100" height="100" '
            f'style="position:absolute;top:{pos}px;left:120px;">'
        )

    # picture element with lazy loading
    for pos in range(0, 5001, 500):
        elements.append(f"""<picture style="position:absolute;top:{pos}px;left:240px;">
    <source srcset="/track/lzsrcset-picture-{pos}-webp?s={s}" type="image/webp">
    <source srcset="/track/lzsrcset-picture-{pos}-png?s={s}" type="image/png">
    <img src="/track/lzsrcset-picture-{pos}-fallback?s={s}" loading="lazy" width="100" height="100">
</picture>""")

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Lazy Loading with srcset/picture</title>
    <style>
        body {{ margin: 0; padding: 0; height: 6000px; position: relative; }}
    </style>
</head>
<body>
{chr(10).join(elements)}
</body>
</html>"""

    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


@router.get("/lazy-css-bg")
async def lazy_css_background_page(s: str = Query(..., description="Session ID")):
    """Test if CSS background images show similar lazy-like behavior.

    CSS background images aren't affected by loading="lazy", but browsers
    may still defer loading for off-screen elements. Test if this behavior
    differs between headful and headless.
    """
    css_rules = []
    elements = []

    for pos in range(0, 8001, 250):
        cls = f"bgpos-{pos}"
        css_rules.append(
            f'.{cls} {{ '
            f'width: 100px; height: 100px; '
            f'background-image: url("/track/cssbg-{pos}?s={s}"); '
            f'background-size: 1px 1px; background-repeat: no-repeat; '
            f'}}'
        )
        elements.append(
            f'<div class="{cls}" style="position:absolute;top:{pos}px;left:0;"></div>'
        )

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>CSS Background Loading Behavior</title>
    <style>
        body {{ margin: 0; padding: 0; height: 9000px; position: relative; }}
{chr(10).join(css_rules)}
    </style>
</head>
<body>
{chr(10).join(elements)}
</body>
</html>"""

    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


@router.get("/lazy-iframe")
async def lazy_iframe_page(s: str = Query(..., description="Session ID")):
    """Test lazy loading on iframes.

    iframes also support loading="lazy". Test if the threshold differs
    between headful and headless, similar to images.
    """
    iframes = []
    for pos in range(0, 6001, 500):
        iframes.append(
            f'<iframe src="/track/lziframe-{pos}?s={s}" loading="lazy" '
            f'width="100" height="100" '
            f'style="position:absolute;top:{pos}px;left:0;border:none;"></iframe>'
        )

    # Eager control
    iframes.append(
        f'<iframe src="/track/lziframe-eager?s={s}" loading="eager" '
        f'width="100" height="100" style="position:absolute;top:0;left:120px;border:none;"></iframe>'
    )

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Lazy Loading iframes</title>
    <style>
        body {{ margin: 0; padding: 0; height: 7000px; position: relative; }}
    </style>
</head>
<body>
{chr(10).join(iframes)}
</body>
</html>"""

    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


@router.get("/lazy-mixed-sizes")
async def lazy_mixed_sizes_page(s: str = Query(..., description="Session ID")):
    """Test if image dimensions affect the lazy loading threshold.

    Browsers may use the image's layout size to adjust the loading threshold.
    """
    elements = []

    sizes = [(10, 10), (100, 100), (500, 500), (1, 1), (100, 1000)]

    for idx, (w, h) in enumerate(sizes):
        for pos in range(0, 5001, 500):
            tag = f"lzsize-{w}x{h}-{pos}"
            elements.append(
                f'<img src="/track/{tag}?s={s}" loading="lazy" '
                f'width="{w}" height="{h}" '
                f'style="position:absolute;top:{pos}px;left:{idx * (w + 20)}px;">'
            )

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Lazy Loading Mixed Sizes</title>
    <style>
        body {{ margin: 0; padding: 0; height: 6000px; position: relative; }}
    </style>
</head>
<body>
{chr(10).join(elements)}
</body>
</html>"""

    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})
