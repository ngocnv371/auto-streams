"""Stage 2b — music  (tts_ready → music_ready)"""
from __future__ import annotations

import asyncio
import logging
import os
import time

from app.config import get_config
from app.database import get_session_factory
from app.models import Project
from app.services.generation.service import GenerationService

from ._helpers import (
    _elapsed,
    _emit,
    _fail_project,
    _kb,
    _load_project,
    _project_dir,
)

log = logging.getLogger(__name__)


async def run_music_stage(project_id: str) -> None:
    """Generate background music for the project, then advance to music_ready."""
    from app.events import inc_active, dec_active
    log.info("music_stage start project=%s", project_id)
    inc_active()
    _emit("Music generation started", project_id=project_id, stage="music")
    try:
        project = await _load_project(project_id)
        if project is None:
            log.warning("music_stage: project %s not found", project_id)
            return

        meta = project.get_metadata()
        if not meta.get("scenes"):
            log.warning(
                "music_stage: project %s has no scenes in metadata (status=%s), skipping",
                project_id, project.status,
            )
            return

        music_prompt = meta.get("music") or "calm ambient background music"
        duration = int(meta.get("duration") or 60)
        log.info("music_stage: generating music  prompt=%r  duration=%ds  provider=%r",
                 music_prompt[:80], duration, get_config().providers.music)

        out_dir = _project_dir(project_id)
        svc = GenerationService()
        t_music = time.monotonic()
        music_bytes = await asyncio.to_thread(svc.generate_music, music_prompt, duration)
        music_path = os.path.join(out_dir, "music.wav")
        with open(music_path, "wb") as f:
            f.write(music_bytes)
        log.info("music_stage: done  size=%s  elapsed=%s  path=%s",
                 _kb(len(music_bytes)), _elapsed(t_music), music_path)

        factory = get_session_factory()
        async with factory() as session:
            p = await session.get(Project, project_id)
            m = p.get_metadata()
            m["music_path"] = music_path
            m["music_done"] = True
            p.set_metadata(m)
            if m.get("images_done"):
                p.status = "media_ready"
            p.touch()
            await session.commit()
            new_status = p.status

        log.info("music_stage done project=%s  status=%s", project_id, new_status)
        _emit("Music stage complete", level="success", project_id=project_id, stage="music")
        from app.events import emit as _emit_event
        _emit_event("project_update", project_id=project_id, status=new_status)

    except Exception:
        log.exception("music_stage failed project=%s", project_id)
        await _fail_project(project_id, "music_stage failed — see server logs")
    finally:
        dec_active()


async def rerun_music(project_id: str) -> None:
    """Re-generate background music for a project regardless of its current status."""
    from app.events import inc_active, dec_active
    log.info("rerun_music start project=%s", project_id)
    inc_active()
    _emit("Re-generating music", project_id=project_id, stage="music")
    try:
        project = await _load_project(project_id)
        if project is None:
            log.warning("rerun_music: project %s not found", project_id)
            return

        meta = project.get_metadata()
        music_prompt = meta.get("music") or "calm ambient background music"
        duration = int(
            meta.get("duration")
            or round(sum(s.get("duration", 0) for s in meta.get("scenes", [])))
            or 60
        )
        log.info(
            "rerun_music: generating music  prompt=%r  duration=%ds  provider=%r",
            music_prompt[:80], duration, get_config().providers.music,
        )

        out_dir = _project_dir(project_id)
        svc = GenerationService()
        t_music = time.monotonic()
        music_bytes = await asyncio.to_thread(svc.generate_music, music_prompt, duration)
        music_path = os.path.join(out_dir, "music.wav")
        with open(music_path, "wb") as f:
            f.write(music_bytes)
        log.info(
            "rerun_music: done  size=%s  elapsed=%s  path=%s",
            _kb(len(music_bytes)), _elapsed(t_music), music_path,
        )

        factory = get_session_factory()
        async with factory() as session:
            p = await session.get(Project, project_id)
            m = p.get_metadata()
            m["music_path"] = music_path
            p.set_metadata(m)
            p.touch()
            await session.commit()

        log.info("rerun_music done project=%s", project_id)
        _emit("Music regenerated", level="success", project_id=project_id, stage="music")
        from app.events import emit as _emit_event
        _emit_event("project_update", project_id=project_id, status=None)

    except Exception:
        log.exception("rerun_music failed project=%s", project_id)
        _emit("Music re-gen failed", level="error", project_id=project_id, stage="music")
    finally:
        dec_active()
