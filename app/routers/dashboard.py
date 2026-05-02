from __future__ import annotations

import asyncio
import json
from typing import Annotated
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import Project, PROJECT_STATUSES
from app.schemas import (
    DashboardOut,
    BestShortsTableOut,
    BestShortsOut,
    BestShortsAnalyzeRequest,
    BestShortsAnalyzeOut,
)
from app.services.generation.service import GenerationService
from app.services.pipeline import (
    fetch_best_shorts,
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
    "image_queue":  ["music_ready"],
    "render_queue": ["images_ready"],
}

_FULL_PIPELINE_ELIGIBLE_STATUSES = [
    "approved",
    "scenes_ready",
    "tts_ready",
    "music_ready",
    "images_ready",
]

_BEST_SHORTS_ANALYSIS_SYSTEM_PROMPT = (
    "You are a YouTube Shorts strategist. Analyze top shorts using only the "
    "provided title + views data and return concise, actionable guidance."
)


def _build_best_shorts_analysis_prompt(shorts: list[dict[str, object]]) -> str:
    return (
        "Analyze this ranked list of YouTube Shorts (title + views).\n"
        "Return plain text with this structure:\n"
        "1) Key patterns (3 bullets)\n"
        "2) Content angles to test next (5 bullets)\n"
        "3) Title formula recommendations (3 bullets)\n\n"
        "Shorts JSON:\n"
        f"{json.dumps(shorts, ensure_ascii=True)}"
    )


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
    queue: str = Query(..., description="Queue name (text_queue..render_queue) or 'all'"),
    topic_id: Optional[str] = Query(None),
) -> dict:
    if queue == "all":
        stmt = select(Project).where(Project.status.in_(_FULL_PIPELINE_ELIGIBLE_STATUSES))
        if topic_id:
            stmt = stmt.where(Project.topic_id == topic_id)
        result = await session.execute(stmt)
        projects = result.scalars().all()

        project_ids = [project.id for project in projects]
        background_tasks.add_task(_process_full_pipeline_batch, project_ids)

        return {"queued": len(projects), "queue": queue}

    if queue not in _QUEUE_STATUS_MAP:
        valid = [*list(_QUEUE_STATUS_MAP), "all"]
        raise HTTPException(400, f"Unknown queue '{queue}'. Valid queues: {valid}")

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


async def _process_full_pipeline_batch(project_ids: list[str]) -> None:
    # Run handlers in global stage order across all projects.
    # Each stage handler no-ops when the current status is not eligible.
    for handler in (
        run_text_stage,
        run_tts_stage,
        run_music_stage,
        run_image_stage,
        run_render_stage,
    ):
        for project_id in project_ids:
            await handler(project_id)


@router.get("/best-shorts", response_model=BestShortsTableOut)
async def get_best_shorts(
    session: Session,
    max_results: int = Query(50, ge=1, le=50),
    topic_id: Optional[str] = Query(None),
):
    rows = await asyncio.to_thread(fetch_best_shorts, max_results)

    stmt = select(Project).where(Project.status == "uploaded")
    if topic_id:
        stmt = stmt.where(Project.topic_id == topic_id)
    result = await session.execute(stmt)
    projects = result.scalars().all()
    url_to_project: dict[str, Project] = {}
    for project in projects:
        meta = project.get_metadata()
        for key in ("youtube_url", "video_url"):
            video_url = meta.get(key)
            if video_url:
                url_to_project[video_url.split("?")[0]] = project

    shorts: list[BestShortsOut] = []
    for row in rows:
        url = str(row.get("url", ""))
        project = url_to_project.get(url)
        raw_views = row.get("views", 0)
        views = raw_views if isinstance(raw_views, int) else 0
        shorts.append(BestShortsOut(
            url=url,
            title=project.title if project else str(row.get("title", "")),
            views=views,
            project_id=project.id if project else None,
            status=project.status if project else None,
            created_at=project.created_at if project else None,
        ))
    return BestShortsTableOut(shorts=shorts)


@router.post("/best-shorts/analyze", response_model=BestShortsAnalyzeOut)
async def analyze_best_shorts(body: BestShortsAnalyzeRequest):
    shorts = body.shorts[:25]
    if not shorts:
        raise HTTPException(400, "No shorts provided")

    payload = [
        {
            "title": item.title,
            "views": max(0, item.views),
        }
        for item in shorts
    ]
    prompt = _build_best_shorts_analysis_prompt(payload)

    svc = GenerationService()
    try:
        analysis = await asyncio.to_thread(
            svc.generate_text,
            prompt,
            _BEST_SHORTS_ANALYSIS_SYSTEM_PROMPT,
        )
    except Exception as e:
        raise HTTPException(502, f"LLM error: {e}")

    text = analysis.strip()
    if not text:
        raise HTTPException(502, "LLM returned empty analysis")
    return BestShortsAnalyzeOut(analysis=text)
