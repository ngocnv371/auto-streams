from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from typing import Optional

from app.database import get_session
from app.models import Project, PROJECT_STATUSES
from app.schemas import DashboardOut

router = APIRouter()

Session = Annotated[AsyncSession, Depends(get_session)]

# Maps each queue to the project status that feeds it
_QUEUE_STATUS_MAP: dict[str, list[str]] = {
    "text_queue":   ["approved"],
    "tts_queue":    ["scenes_ready"],
    "music_queue":  ["scenes_ready"],
    "image_queue":  ["audio_ready"],
    "render_queue": ["images_ready", "clips_ready"],
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
