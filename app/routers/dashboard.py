from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from typing import Optional

from app.database import get_session
from app.models import Project, PROJECT_STATUSES
from app.schemas import DashboardOut
from app.services.pipeline import (
    run_text_stage,
    run_tts_stage,
    run_music_stage,
    run_image_stage,
    run_render_stage,
)

router = APIRouter()

Session = Annotated[AsyncSession, Depends(get_session)]

# Maps each queue to the project status that feeds it
_QUEUE_STATUS_MAP: dict[str, list[str]] = {
    "text_queue":   ["approved"],
    "tts_queue":    ["scenes_ready"],
    "music_queue":  ["tts_ready"],
    "image_queue":  ["tts_ready"],
    "render_queue": ["media_ready", "images_ready", "clips_ready"],
}


@router.get("", response_model=DashboardOut)
async def get_dashboard(
    session: Session,
    topic_id: Optional[str] = Query(None),
):
    stmt = select(Project.status, func.count().label("cnt")).group_by(Project.status)
    if topic_id:
        stmt = stmt.where(Project.topic_id == topic_id)
    result = await session.execute(stmt)
    rows = result.all()
    raw: dict[str, int] = {row.status: row.cnt for row in rows}

    status_counts = {s: raw.get(s, 0) for s in PROJECT_STATUSES}
    total = sum(raw.values())

    queue_counts = {
        name: sum(raw.get(s, 0) for s in statuses)
        for name, statuses in _QUEUE_STATUS_MAP.items()
    }

    return DashboardOut(
        status_counts=status_counts,
        queue_counts=queue_counts,
        total=total,
    )


@router.post("/run-queue")
async def run_queue(
    session: Session,
    background_tasks: BackgroundTasks,
    queue: str = Query(..., description="Queue name, e.g. text_queue"),
    topic_id: Optional[str] = Query(None),
) -> dict:
    if queue not in _QUEUE_STATUS_MAP:
        raise HTTPException(400, f"Unknown queue '{queue}'. Valid queues: {list(_QUEUE_STATUS_MAP)}")

    statuses = _QUEUE_STATUS_MAP[queue]
    stmt = select(Project).where(Project.status.in_(statuses))
    if topic_id:
        stmt = stmt.where(Project.topic_id == topic_id)
    result = await session.execute(stmt)
    projects = result.scalars().all()

    for project in projects:
        background_tasks.add_task(_process_pipeline_stub, project.id, queue)

    return {"queued": len(projects), "queue": queue}


# ------------------------------------------------------------------ helpers

_QUEUE_HANDLERS = {
    "text_queue":   run_text_stage,
    "tts_queue":    run_tts_stage,
    "music_queue":  run_music_stage,
    "image_queue":  run_image_stage,
    "render_queue": run_render_stage,
}


async def _process_pipeline_stub(project_id: str, queue: str) -> None:
    handler = _QUEUE_HANDLERS.get(queue)
    if handler:
        await handler(project_id)
