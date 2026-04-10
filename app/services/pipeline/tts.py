"""Stage 2a — TTS  (scenes_ready → audio_ready)
Stage 2b — music only  (scenes_ready, no status change)
"""
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
    _audio_duration,
    _elapsed,
    _fail_project,
    _kb,
    _load_project,
    _project_dir,
)

log = logging.getLogger(__name__)


async def run_tts_stage(project_id: str) -> None:
    """Generate TTS audio per scene and background music, then advance to audio_ready."""
    log.info("tts_stage start project=%s", project_id)
    try:
        project = await _load_project(project_id)
        if project is None or project.status != "scenes_ready":
            log.warning(
                "tts_stage: project %s not in scenes_ready (status=%s)",
                project_id, project.status if project else "not found",
            )
            return

        meta = project.get_metadata()
        scenes = meta.get("scenes", [])
        if not scenes:
            raise ValueError("No scenes in project metadata")

        out_dir = _project_dir(project_id)
        svc = GenerationService()

        cfg = get_config()
        log.info(
            "tts_stage: %d scenes  tts_provider=%r  music_provider=%r",
            len(scenes), cfg.providers.tts, cfg.providers.music,
        )

        # ── Per-scene TTS ────────────────────────────────────────────
        updated_scenes = []
        for i, scene in enumerate(scenes):
            voiceover = scene.get("voiceover", "").strip()
            if voiceover:
                log.debug(
                    "tts_stage: scene %d/%d  voiceover=%r",
                    i + 1, len(scenes), voiceover[:80],
                )
                t_tts = time.monotonic()
                audio_bytes = await asyncio.to_thread(svc.generate_speech, voiceover)
                audio_path = os.path.join(out_dir, f"scene_{i:03d}_tts.wav")
                with open(audio_path, "wb") as f:
                    f.write(audio_bytes)
                real_duration = _audio_duration(audio_path, float(scene.get("duration") or 5))
                log.info(
                    "tts_stage: scene %d/%d done  size=%s  elapsed=%s  duration=%.2fs  path=%s",
                    i + 1, len(scenes), _kb(len(audio_bytes)), _elapsed(t_tts), real_duration, audio_path,
                )
                updated_scenes.append({**scene, "audio_path": audio_path, "duration": real_duration})
            else:
                log.debug("tts_stage: scene %d/%d skipped (no voiceover)", i + 1, len(scenes))
                updated_scenes.append(scene)

        # ── Background music ─────────────────────────────────────────
        music_prompt = meta.get("music") or "calm ambient background music"
        duration = int(round(sum(s.get("duration", 0) for s in updated_scenes))) or 60
        log.info(
            "tts_stage: generating music  prompt=%r  duration=%ds",
            music_prompt[:80], duration,
        )
        t_music = time.monotonic()
        music_bytes = await asyncio.to_thread(svc.generate_music, music_prompt, duration)
        music_path = os.path.join(out_dir, "music.wav")
        with open(music_path, "wb") as f:
            f.write(music_bytes)
        log.info(
            "tts_stage: music done  size=%s  elapsed=%s  path=%s",
            _kb(len(music_bytes)), _elapsed(t_music), music_path,
        )

        factory = get_session_factory()
        async with factory() as session:
            p = await session.get(Project, project_id)
            m = p.get_metadata()
            m["scenes"] = updated_scenes
            m["duration"] = duration
            m["music_path"] = music_path
            p.set_metadata(m)
            p.status = "audio_ready"
            p.touch()
            await session.commit()

        log.info("tts_stage done project=%s", project_id)

    except Exception:
        log.exception("tts_stage failed project=%s", project_id)
        await _fail_project(project_id, "tts_stage failed — see server logs")


async def run_music_stage(project_id: str) -> None:
    """Re-generate (or generate standalone) background music without advancing status."""
    log.info("music_stage start project=%s", project_id)
    try:
        project = await _load_project(project_id)
        if project is None or project.status != "scenes_ready":
            log.warning(
                "music_stage: project %s not in scenes_ready (status=%s)",
                project_id, project.status if project else "not found",
            )
            return

        meta = project.get_metadata()
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
            p.set_metadata(m)
            p.touch()
            await session.commit()

        log.info("music_stage done project=%s", project_id)

    except Exception:
        log.exception("music_stage failed project=%s", project_id)
        await _fail_project(project_id, "music_stage failed — see server logs")
