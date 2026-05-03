from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.config import load_config
from app.database import init_db
from app.events import subscribe, unsubscribe
from app.routers import dashboard, projects
from app.routers import topics, ideas
from app.services.scheduler import UploadScheduler


logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)-8s %(name)s - %(message)s",
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = load_config()
    await init_db()
    scheduler = UploadScheduler(cfg.scheduler)
    await scheduler.start()
    yield
    await scheduler.stop()


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


@app.get("/api/events", include_in_schema=False)
async def sse_events(request: Request):
    """Server-Sent Events stream for real-time pipeline feedback."""
    q = subscribe()

    async def generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"data: {payload}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            unsubscribe(q)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
