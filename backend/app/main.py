"""FastAPI application factory and service lifecycle."""

from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path

from app.config import settings
from app.database.engine import create_tables
from app.api import (
    routes_analysis,
    routes_export,
    routes_features,
    routes_geometry,
    routes_images,
    routes_project,
    routes_upload,
    routes_plots,
    routes_calibration,
)

log = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_tables()
    settings.resolved_upload_dir.mkdir(parents=True, exist_ok=True)
    settings.resolved_output_dir.mkdir(parents=True, exist_ok=True)
    log.info("AI Plot Layout Management v%s", settings.app_version)
    log.info("OCR enabled: %s", settings.enable_ocr)
    log.info("Vision model configured: %s", settings.has_openrouter_key)
    log.info("Survey-specific YOLO enabled: %s", settings.enable_yolo)
    yield


app = FastAPI(
    title=settings.app_title,
    version=settings.app_version,
    description=(
        "AI-assisted survey document understanding, geometry reconstruction, "
        "validation, and interactive plot-layout visualization system."
    ),
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(GZipMiddleware, minimum_size=1000)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["*"],
)

app.include_router(routes_upload.router, prefix="/api", tags=["Upload"])
app.include_router(routes_analysis.router, prefix="/api", tags=["Analysis"])
app.include_router(routes_images.router, prefix="/api", tags=["Images"])
app.include_router(routes_geometry.router, prefix="/api", tags=["Geometry"])
app.include_router(routes_project.router, prefix="/api", tags=["Projects"])
app.include_router(routes_export.router, prefix="/api", tags=["Export"])
app.include_router(routes_features.router, prefix="/api", tags=["Survey features"])
app.include_router(routes_plots.router, prefix="/api", tags=["Plots"])
app.include_router(routes_calibration.router, prefix="/api", tags=["Calibration"])


@app.get("/api/health", tags=["System"])
@app.get("/health", tags=["System"], include_in_schema=False)
async def health_check():
    """Return operational feature state without exposing credentials."""
    return {
        "status": "ok",
        "version": settings.app_version,
        "features": {
            "ocr": settings.enable_ocr,
            "llm": settings.enable_llm and settings.has_openrouter_key,
            "yolo": settings.enable_yolo,
            "llm_model": settings.openrouter_vision_model if settings.enable_llm else None,
        },
    }


# ── Production SPA Static Serving ─────────────────────────────────────────────
# In production, serve the compiled React SPA from frontend/dist if present
frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if frontend_dist.is_dir():
    assets_dir = frontend_dist / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="spa-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        # Do not intercept API, docs, or health endpoints
        if full_path.startswith("api") or full_path in ("docs", "redoc", "openapi.json", "health"):
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Not found")
        target_file = frontend_dist / full_path
        if full_path and target_file.is_file():
            return FileResponse(target_file)
        return FileResponse(frontend_dist / "index.html")
