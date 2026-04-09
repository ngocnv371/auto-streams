from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import load_config
from app.database import init_db
from app.routers import dashboard, projects
from app.routers import topics, ideas


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_config()
    await init_db()
    yield


app = FastAPI(title="auto-streams", lifespan=lifespan)

_static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=_static_dir), name="static")

app.include_router(projects.router, prefix="/api/projects", tags=["projects"])
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["dashboard"])
app.include_router(topics.router, prefix="/api/topics", tags=["topics"])
app.include_router(ideas.router, prefix="/api/ideas", tags=["ideas"])


@app.get("/", include_in_schema=False)
async def serve_ui():
    return FileResponse(os.path.join(_static_dir, "index.html"))
