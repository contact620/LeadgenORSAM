"""
ORSAM API Server
Run with: uvicorn api.server:app --reload --host 0.0.0.0 --port 8000
"""
import os
import sys

# Add project root to sys.path so pipeline modules resolve
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.routes.pipeline import router as pipeline_router
from api.routes.health import router as health_router

app = FastAPI(title="ORSAM Lead Gen API", version="1.0.0")

# ── CORS (allow Vite dev server) ───────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── API routes ─────────────────────────────────────────────────────────────────
app.include_router(health_router, prefix="/api")
app.include_router(pipeline_router, prefix="/api")

# ── Serve built frontend (production) ─────────────────────────────────────────
_dist = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.isdir(_dist):
    app.mount("/", StaticFiles(directory=_dist, html=True), name="frontend")
