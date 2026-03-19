from pathlib import Path

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse, Response

from core import storage

router = APIRouter()

BEACON_PATH = Path(__file__).parent / "static" / "beacon.png"
FONT_PATH = Path(__file__).parent / "static" / "test-font.woff2"
BEACON_BYTES = BEACON_PATH.read_bytes()


@router.get("/track/{resource_name:path}")
async def track_resource(resource_name: str, s: str = Query(..., description="Session ID")):
    """Log a tracked resource request and serve a 1x1 beacon PNG."""
    storage.log_request(s, resource_name)
    return Response(
        content=BEACON_BYTES,
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/css/chain/{chain_id}/{step:int}")
async def css_chain_step(
    chain_id: str,
    step: int,
    s: str = Query(..., description="Session ID"),
    total: int = Query(10, description="Total chain length"),
    expensive: bool = Query(True, description="Use expensive CSS rules"),
):
    """Serve a CSS chain link. Each link @imports the next and contains CSS rules."""
    storage.log_request(s, f"chain-{chain_id}-step-{step}")

    css_parts = []

    # Import next link in chain (if not the last)
    if step < total - 1:
        next_url = f"/css/chain/{chain_id}/{step + 1}?s={s}&total={total}&expensive={'true' if expensive else 'false'}"
        css_parts.append(f'@import url("{next_url}");')

    if expensive:
        # Generate computationally expensive CSS rules
        # These stress the software rasterizer in headless mode
        for i in range(20):
            css_parts.append(f"""
.chain-{chain_id}-s{step}-el{i} {{
    width: 500px;
    height: 500px;
    filter: blur({10 + i * 2}px) brightness({100 + i * 10}%) contrast({100 + i * 5}%) saturate({100 + i * 20}%);
    box-shadow: {', '.join(f'{j*3}px {j*3}px {j*10}px rgba({j*10},{j*20},{j*30},0.{j})' for j in range(1, 8))};
    background: repeating-conic-gradient(
        from {i * 15}deg,
        hsl({i * 30}, 70%, 50%) 0deg {i + 1}deg,
        hsl({i * 30 + 60}, 80%, 60%) {i + 1}deg {(i + 1) * 2}deg
    );
    mix-blend-mode: overlay;
}}""")
    else:
        # Minimal CSS - control baseline
        for i in range(20):
            css_parts.append(f".chain-{chain_id}-s{step}-el{i} {{ color: black; }}")

    # Last step triggers a beacon
    if step == total - 1:
        css_parts.append(
            f'.chain-{chain_id}-beacon {{ background-image: url("/track/chain-{chain_id}-beacon?s={s}"); }}'
        )

    return Response(
        content="\n".join(css_parts),
        media_type="text/css",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/font/track/{font_name}")
async def track_font(font_name: str, s: str = Query(..., description="Session ID")):
    """Log a font request and serve the test font."""
    storage.log_request(s, f"font-{font_name}")
    return Response(
        content=FONT_PATH.read_bytes(),
        media_type="font/woff2",
        headers={"Cache-Control": "no-store"},
    )
