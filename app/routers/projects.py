from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import Project, Topic
from app.schemas import ProjectCreate, ProjectOut, ProjectStatusUpdate, ProjectUpdate
from app.services.pipeline import (
    run_full_pipeline,
    run_render_stage,
    run_scene_image,
    run_all_scene_images,
    run_scene_tts,
    run_all_scene_tts,
    rerun_music,
    run_upload_stage,
)

router = APIRouter()

Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("", response_model=list[ProjectOut])
async def list_projects(
    session: Session,
    topic_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    stmt = select(Project).order_by(Project.created_at.desc())
    if topic_id:
        stmt = stmt.where(Project.topic_id == topic_id)
    if status:
        stmt = stmt.where(Project.status == status)
    if search:
        stmt = stmt.where(Project.title.ilike(f"%{search}%"))
    stmt = stmt.offset(offset).limit(limit)
    result = await session.execute(stmt)
    projects = result.scalars().all()
    return [p.to_dict() for p in projects]


@router.post("", response_model=ProjectOut, status_code=201)
async def create_project(body: ProjectCreate, session: Session):
    topic = await session.get(Topic, body.topic_id)
    if not topic:
        raise HTTPException(404, f"Topic '{body.topic_id}' not found")
    project = Project(
        id=str(uuid.uuid4()),
        topic_id=body.topic_id,
        title=body.title,
        status="idea",
        tags_json=__import__("json").dumps(body.tags),
        meta_json=__import__("json").dumps(body.metadata),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add(project)
    await session.commit()
    await session.refresh(project)
    return project.to_dict()


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(project_id: str, session: Session):
    project = await _get_or_404(session, project_id)
    return project.to_dict()


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(project_id: str, body: ProjectUpdate, session: Session):
    project = await _get_or_404(session, project_id)
    if body.title is not None:
        project.title = body.title
    if body.tags is not None:
        project.set_tags(body.tags)
    if body.metadata is not None:
        project.set_metadata(body.metadata)
    project.touch()
    await session.commit()
    await session.refresh(project)
    return project.to_dict()


@router.put("/{project_id}/status", response_model=ProjectOut)
async def set_status(project_id: str, body: ProjectStatusUpdate, session: Session):
    project = await _get_or_404(session, project_id)
    project.status = body.status
    project.touch()
    await session.commit()
    await session.refresh(project)
    return project.to_dict()


@router.post("/{project_id}/run", response_model=ProjectOut)
async def run_project_pipeline(project_id: str, session: Session, background_tasks: BackgroundTasks):
    project = await _get_or_404(session, project_id)
    if project.status != "approved":
        raise HTTPException(400, "Only 'approved' projects can be run through the pipeline")
    background_tasks.add_task(_process_pipeline, project_id)
    return project.to_dict()


@router.post("/{project_id}/render", response_model=ProjectOut)
async def render_project(project_id: str, session: Session, background_tasks: BackgroundTasks):
    """Force a re-render stage. Accepts failed, images_ready, or clips_ready projects."""
    project = await _get_or_404(session, project_id)
    if project.status not in ("done", "failed", "images_ready", "clips_ready"):
        raise HTTPException(400, "Project must be in 'failed', 'images_ready', or 'clips_ready' status to re-render")
    project.status = "images_ready"
    project.touch()
    await session.commit()
    await session.refresh(project)
    from app.config import get_config
    cfg = get_config()
    proj_dir = os.path.join(cfg.temp_dir, project_id)
    if os.path.isdir(proj_dir):
        for f in os.listdir(proj_dir):
            if f.endswith(".mp4"):
                os.remove(os.path.join(proj_dir, f))
    background_tasks.add_task(_process_render, project_id)
    return project.to_dict()


@router.post("/{project_id}/approve", response_model=ProjectOut)
async def approve_project(project_id: str, session: Session):
    project = await _get_or_404(session, project_id)
    if project.status != "idea":
        raise HTTPException(400, "Only 'idea' projects can be approved")
    project.status = "approved"
    project.touch()
    await session.commit()
    await session.refresh(project)
    return project.to_dict()


@router.post("/{project_id}/reject", response_model=ProjectOut)
async def reject_project(project_id: str, session: Session):
    project = await _get_or_404(session, project_id)
    if project.status not in ("idea", "approved"):
        raise HTTPException(400, "Only 'idea' or 'approved' projects can be rejected")
    project.status = "failed"
    project.touch()
    await session.commit()
    await session.refresh(project)
    return project.to_dict()


@router.delete("/{project_id}", status_code=204)
async def delete_project(project_id: str, session: Session):
    project = await _get_or_404(session, project_id)
    await session.delete(project)
    await session.commit()


@router.post("/{project_id}/scenes/{scene_index}/rerun/image", response_model=ProjectOut)
async def rerun_scene_image(
    project_id: str, scene_index: int, session: Session, background_tasks: BackgroundTasks
):
    """Re-generate the image for a single scene without touching any other assets."""
    project = await _get_or_404(session, project_id)
    meta = project.get_metadata()
    scenes = meta.get("scenes", [])
    if not scenes or scene_index < 0 or scene_index >= len(scenes):
        raise HTTPException(400, f"Scene index {scene_index} is out of range (0–{len(scenes)-1})")
    background_tasks.add_task(_process_scene_image, project_id, scene_index)
    return project.to_dict()


@router.post("/{project_id}/scenes/{scene_index}/rerun/audio", response_model=ProjectOut)
async def rerun_scene_audio(
    project_id: str, scene_index: int, session: Session, background_tasks: BackgroundTasks
):
    """Re-generate TTS audio for a single scene without touching any other assets."""
    project = await _get_or_404(session, project_id)
    meta = project.get_metadata()
    scenes = meta.get("scenes", [])
    if not scenes or scene_index < 0 or scene_index >= len(scenes):
        raise HTTPException(400, f"Scene index {scene_index} is out of range (0–{len(scenes)-1})")
    if not scenes[scene_index].get("voiceover", "").strip():
        raise HTTPException(400, f"Scene {scene_index} has no voiceover text")
    background_tasks.add_task(_process_scene_tts, project_id, scene_index)
    return project.to_dict()


@router.post("/{project_id}/upload", response_model=ProjectOut)
async def upload_project(project_id: str, session: Session, background_tasks: BackgroundTasks):
    """Upload the finished video to YouTube Shorts. Project must be in 'done' status."""
    project = await _get_or_404(session, project_id)
    if project.status != "done":
        raise HTTPException(400, "Only 'done' projects can be uploaded")
    background_tasks.add_task(_process_upload, project_id)
    return project.to_dict()


@router.post("/{project_id}/rerun/music", response_model=ProjectOut)
async def rerun_music_endpoint(project_id: str, session: Session, background_tasks: BackgroundTasks):
    """Re-generate the background music track without touching any other assets."""
    project = await _get_or_404(session, project_id)
    meta = project.get_metadata()
    if not meta.get("scenes"):
        raise HTTPException(400, "Project has no scenes yet — run the pipeline first")
    background_tasks.add_task(_process_rerun_music, project_id)
    return project.to_dict()


@router.post("/{project_id}/rerun/images", response_model=ProjectOut)
async def rerun_all_images(project_id: str, session: Session, background_tasks: BackgroundTasks):
    """Re-generate images for all scenes without changing project status."""
    project = await _get_or_404(session, project_id)
    meta = project.get_metadata()
    if not meta.get("scenes"):
        raise HTTPException(400, "Project has no scenes yet — run the pipeline first")
    background_tasks.add_task(_process_all_scene_images, project_id)
    return project.to_dict()


@router.post("/{project_id}/rerun/audio", response_model=ProjectOut)
async def rerun_all_audio(project_id: str, session: Session, background_tasks: BackgroundTasks):
    """Re-generate TTS audio for all scenes without changing project status."""
    project = await _get_or_404(session, project_id)
    meta = project.get_metadata()
    if not meta.get("scenes"):
        raise HTTPException(400, "Project has no scenes yet — run the pipeline first")
    background_tasks.add_task(_process_all_scene_tts, project_id)
    return project.to_dict()


@router.get("/{project_id}/audio/{filename}", include_in_schema=False)
async def serve_audio(project_id: str, filename: str, session: Session):
    """Stream a generated audio file (TTS scene or music) for in-browser preview."""
    # Reject any path-traversal or non-WAV attempts
    if not re.fullmatch(r"[\w\-]+\.wav", filename):
        raise HTTPException(400, "Invalid filename")
    project = await _get_or_404(session, project_id)
    from app.config import get_config
    cfg = get_config()
    audio_path = os.path.join(cfg.temp_dir, project_id, filename)
    if not os.path.isfile(audio_path):
        raise HTTPException(404, "Audio file not found")
    return FileResponse(audio_path, media_type="audio/wav")


@router.get("/{project_id}/image/{filename}", include_in_schema=False)
async def serve_image(project_id: str, filename: str, session: Session):
    """Serve a generated scene image for in-browser preview."""
    if not re.fullmatch(r"[\w\-]+\.png", filename):
        raise HTTPException(400, "Invalid filename")
    project = await _get_or_404(session, project_id)
    from app.config import get_config
    cfg = get_config()
    image_path = os.path.join(cfg.temp_dir, project_id, filename)
    if not os.path.isfile(image_path):
        raise HTTPException(404, "Image file not found")
    return FileResponse(image_path, media_type="image/png")


@router.get("/{project_id}/video/{filename}", include_in_schema=False)
async def serve_video(project_id: str, filename: str, session: Session):
    """Stream the final rendered video for in-browser preview."""
    if not re.fullmatch(r"[\w\-]+\.mp4", filename):
        raise HTTPException(400, "Invalid filename")
    project = await _get_or_404(session, project_id)
    from app.config import get_config
    cfg = get_config()
    video_path = os.path.join(cfg.temp_dir, project_id, filename)
    if not os.path.isfile(video_path):
        raise HTTPException(404, "Video file not found")
    return FileResponse(video_path, media_type="video/mp4")


# ------------------------------------------------------------------ helpers

async def _get_or_404(session: AsyncSession, project_id: str) -> Project:
    result = await session.execute(
        select(Project).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(404, f"Project '{project_id}' not found")
    return project


async def _process_pipeline(project_id: str) -> None:
    """Background task — runs the full generation pipeline for an approved project."""
    await run_full_pipeline(project_id)


async def _process_render(project_id: str) -> None:
    """Background task — runs only the render stage."""
    await run_render_stage(project_id)


async def _process_scene_image(project_id: str, scene_index: int) -> None:
    await run_scene_image(project_id, scene_index)


async def _process_scene_tts(project_id: str, scene_index: int) -> None:
    await run_scene_tts(project_id, scene_index)


async def _process_rerun_music(project_id: str) -> None:
    await rerun_music(project_id)


async def _process_all_scene_images(project_id: str) -> None:
    await run_all_scene_images(project_id)


async def _process_all_scene_tts(project_id: str) -> None:
    await run_all_scene_tts(project_id)


async def _process_upload(project_id: str) -> None:
    await run_upload_stage(project_id)
