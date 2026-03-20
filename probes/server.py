import uuid

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse

from core import storage
from .tracking import router as tracking_router
from .pages.media_queries import router as media_queries_router
from .pages.lazy_loading import router as lazy_loading_router
from .pages.import_chains import router as import_chains_router
from .pages.background_chains import router as background_chains_router
from .pages.font_loading import router as font_loading_router
from .pages.combined import router as combined_router
from .pages.lazy_loading_fine import router as lazy_fine_router
from .pages.advanced_probes import router as advanced_probes_router
from .pages.http_probes import router as http_probes_router
from .pages.rendering_stress import router as rendering_stress_router
from .pages.compositor_stress import router as compositor_stress_router
from .pages.image_loading import router as image_loading_router
from .pages.ad_cascade import router as ad_cascade_router
from .pages.scrollbar_width import router as scrollbar_width_router
from .pages.outer_inner import router as outer_inner_router
from .pages.server_signals import router as server_signals_router
from .pages.deep_server_probes import router as deep_probes_router
from .middleware.header_capture import HeaderCaptureMiddleware

app = FastAPI(title="Headless Detection Research")
app.add_middleware(HeaderCaptureMiddleware)


@app.on_event("startup")
def startup():
    storage.init_db()


# --- Index page ---

PROBE_PAGES = [
    "scrollbar-width", "outer-inner", "rendering-stress", "stress-compositor",
    "lazy-loading", "lazy-loading-fine", "media-queries", "font-loading",
    "import-chains", "background-chains", "http-probes", "image-loading",
    "ad-cascade", "advanced-probes", "deep-server-probes", "combined",
    "server-signals",
]


@app.get("/", response_class=HTMLResponse)
async def index():
    links = "\n".join(
        f'<li><a href="/pages/{p}?s=demo">{p}</a></li>' for p in PROBE_PAGES
    )
    return f"""<!DOCTYPE html>
<html><head><title>Headless Detection Probe Server</title>
<style>body{{font-family:system-ui;max-width:640px;margin:2rem auto;padding:0 1rem}}
a{{color:#0066cc}}</style></head>
<body><h1>Probe Server</h1>
<p>Available probe pages:</p><ul>{links}</ul>
<p><a href="/docs">API docs (Swagger UI)</a></p>
</body></html>"""


# --- Session management ---

@app.get("/session/new")
async def new_session(
    mode: str = Query(..., description="headful or headless"),
    profile: str = Query("default", description="default or matched"),
    page: str = Query("", description="Which test page"),
):
    session_id = uuid.uuid4().hex[:12]
    storage.create_session(session_id, mode, profile, page)
    return {"session_id": session_id, "mode": mode, "profile": profile, "page": page}


# --- Results API ---

@app.get("/results")
async def all_results():
    sessions = storage.get_all_sessions()
    return JSONResponse(content=sessions)


@app.get("/results/{session_id}")
async def session_results(session_id: str):
    session = storage.get_session(session_id)
    if not session:
        return JSONResponse(content={"error": "Session not found"}, status_code=404)
    requests = storage.get_session_requests(session_id)
    return JSONResponse(content={"session": session, "requests": requests})


@app.get("/results/by-page/{page}")
async def page_results(page: str):
    sessions = storage.get_sessions_by_page(page)
    result = []
    for s in sessions:
        reqs = storage.get_session_requests(s["session_id"])
        result.append({"session": s, "requests": reqs})
    return JSONResponse(content=result)


@app.post("/clear")
async def clear_data():
    storage.clear_all()
    return {"status": "cleared"}


# --- Mount routers ---

app.include_router(tracking_router)
app.include_router(media_queries_router, prefix="/pages")
app.include_router(lazy_loading_router, prefix="/pages")
app.include_router(import_chains_router, prefix="/pages")
app.include_router(background_chains_router, prefix="/pages")
app.include_router(font_loading_router, prefix="/pages")
app.include_router(combined_router, prefix="/pages")
app.include_router(lazy_fine_router, prefix="/pages")
app.include_router(advanced_probes_router, prefix="/pages")
app.include_router(http_probes_router, prefix="/pages")
app.include_router(rendering_stress_router, prefix="/pages")
app.include_router(compositor_stress_router, prefix="/pages")
app.include_router(image_loading_router, prefix="/pages")
app.include_router(ad_cascade_router, prefix="/pages")
app.include_router(scrollbar_width_router, prefix="/pages")
app.include_router(outer_inner_router, prefix="/pages")
app.include_router(server_signals_router, prefix="/pages")
app.include_router(deep_probes_router, prefix="/pages")
