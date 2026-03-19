from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/import-chains")
async def import_chains_page(
    s: str = Query(..., description="Session ID"),
    chain_length: int = Query(8, description="Number of CSS files in the chain"),
):
    """Page that triggers CSS @import chains.

    Timing signal: the browser must sequentially fetch each CSS file in the chain.
    Each file contains expensive CSS rules that stress the rendering pipeline.
    The server measures inter-request deltas between consecutive chain links.

    Two chains are loaded:
    - 'expensive': Heavy CSS rules (filters, gradients, box-shadows)
    - 'control': Minimal CSS rules (baseline timing)
    """
    # Generate elements that the CSS rules will target
    elements = []
    for chain_id in ("expensive", "control"):
        for step in range(chain_length):
            for el in range(20):
                elements.append(
                    f'<div class="chain-{chain_id}-s{step}-el{el}" '
                    f'style="width:500px;height:500px;position:absolute;top:{step*500+el*25}px;left:0;"></div>'
                )
        # Beacon element for the chain end
        elements.append(f'<div class="chain-{chain_id}-beacon" style="width:1px;height:1px;position:absolute;"></div>')

    expensive_url = f"/css/chain/expensive/0?s={s}&total={chain_length}&expensive=true"
    control_url = f"/css/chain/control/0?s={s}&total={chain_length}&expensive=false"

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>CSS @import Chain Test</title>
    <link rel="stylesheet" href="{expensive_url}">
    <link rel="stylesheet" href="{control_url}">
</head>
<body style="margin:0;position:relative;height:{chain_length * 500 * 20 + 1000}px;">
{chr(10).join(elements)}
</body>
</html>"""

    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})
