"""Stage 2a — TTS  (scenes_ready → tts_ready)"""
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
    _emit,
    _fail_project,
    _kb,
    _load_project,
    _project_dir,
)

log = logging.getLogger(__name__)


async def run_tts_stage(project_id: str) -> None:
    """Generate TTS audio per scene, then advance to tts_ready."""
    from app.events import inc_active, dec_active, emit as _emit_event
    log.info("tts_stage start project=%s", project_id)
    inc_active()
    _emit("TTS stage started", project_id=project_id, stage="tts")
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
                _emit(f"Audio: scene {i + 1}/{len(scenes)} done", level="success", project_id=project_id, stage="tts")
                updated_scenes.append({**scene, "audio_path": audio_path, "duration": real_duration})
                tts_delay = cfg.providers.tts_delay
                if tts_delay > 0 and i < len(scenes) - 1:
                    log.debug("tts_stage: sleeping %.1fs before next TTS call", tts_delay)
                    await asyncio.sleep(tts_delay)
            else:
                log.debug("tts_stage: scene %d/%d skipped (no voiceover)", i + 1, len(scenes))
                updated_scenes.append(scene)

        duration = int(round(sum(s.get("duration", 0) for s in updated_scenes))) or 60

        factory = get_session_factory()
        async with factory() as session:
            p = await session.get(Project, project_id)
            m = p.get_metadata()
            m["scenes"] = updated_scenes
            m["duration"] = duration
            p.set_metadata(m)
            p.status = "tts_ready"
            p.touch()
            await session.commit()

        log.info("tts_stage done project=%s", project_id)
        _emit("TTS stage complete", level="success", project_id=project_id, stage="tts")
        _emit_event("project_update", project_id=project_id, status="tts_ready")

    except Exception:
        log.exception("tts_stage failed project=%s", project_id)
        await _fail_project(project_id, "tts_stage failed — see server logs")
    finally:
        dec_active()


async def run_scene_tts(project_id: str, scene_index: int) -> None:
    """Re-generate TTS audio for a single scene without changing project status."""
    from app.events import inc_active, dec_active
    log.info("scene_tts start project=%s scene=%d", project_id, scene_index)
    inc_active()
    _emit(f"Re-generating audio for scene {scene_index + 1}", project_id=project_id, stage="tts")
    try:
        project = await _load_project(project_id)
        if project is None:
            log.warning("scene_tts: project %s not found", project_id)
            return

        meta = project.get_metadata()
        scenes = meta.get("scenes", [])
        if scene_index < 0 or scene_index >= len(scenes):
            log.warning("scene_tts: scene index %d out of range (0-%d)", scene_index, len(scenes) - 1)
            return

        scene = scenes[scene_index]
        voiceover = scene.get("voiceover", "").strip()
        if not voiceover:
            log.warning("scene_tts: scene %d has no voiceover text", scene_index)
            return

        out_dir = _project_dir(project_id)
        svc = GenerationService()

        log.debug("scene_tts: scene %d  voiceover=%r", scene_index, voiceover[:80])
        t_tts = time.monotonic()
        audio_bytes = await asyncio.to_thread(svc.generate_speech, voiceover)
        audio_path = os.path.join(out_dir, f"scene_{scene_index:03d}_tts.wav")
        with open(audio_path, "wb") as f:
            f.write(audio_bytes)
        real_duration = _audio_duration(audio_path, float(scene.get("duration") or 5))
        log.info(
            "scene_tts: scene %d done  size=%s  elapsed=%s  duration=%.2fs  path=%s",
            scene_index, _kb(len(audio_bytes)), _elapsed(t_tts), real_duration, audio_path,
        )

        factory = get_session_factory()
        async with factory() as session:
            p = await session.get(Project, project_id)
            m = p.get_metadata()
            m["scenes"][scene_index] = {
                **m["scenes"][scene_index],
                "audio_path": audio_path,
                "duration": real_duration,
            }
            p.set_metadata(m)
            p.touch()
            await session.commit()

        log.info("scene_tts done project=%s scene=%d", project_id, scene_index)
        _emit(f"Scene {scene_index + 1} audio ready", level="success", project_id=project_id, stage="tts")
        from app.events import emit as _emit_event
        _emit_event("project_update", project_id=project_id, status=None)

    except Exception:
        log.exception("scene_tts failed project=%s scene=%d", project_id, scene_index)
        _emit(f"Scene {scene_index + 1} audio failed", level="error", project_id=project_id, stage="tts")
    finally:
        dec_active()


async def run_all_scene_tts(project_id: str) -> None:
    """Re-generate TTS audio for every scene without changing project status."""
    from app.events import inc_active, dec_active
    log.info("all_scene_tts start project=%s", project_id)
    inc_active()
    _emit("Re-generating all audio", project_id=project_id, stage="tts")
    try:
        project = await _load_project(project_id)
        if project is None:
            log.warning("all_scene_tts: project %s not found", project_id)
            return

        meta = project.get_metadata()
        scenes = meta.get("scenes", [])
        if not scenes:
            log.warning("all_scene_tts: project %s has no scenes", project_id)
            return

        out_dir = _project_dir(project_id)
        svc = GenerationService()
        updated_scenes = list(scenes)

        for i, scene in enumerate(scenes):
            voiceover = scene.get("voiceover", "").strip()
            if not voiceover:
                log.debug("all_scene_tts: scene %d/%d skipped (no voiceover)", i + 1, len(scenes))
                continue
            log.debug("all_scene_tts: scene %d/%d  voiceover=%r", i + 1, len(scenes), voiceover[:80])
            t_tts = time.monotonic()
            audio_bytes = await asyncio.to_thread(svc.generate_speech, voiceover)
            audio_path = os.path.join(out_dir, f"scene_{i:03d}_tts.wav")
            with open(audio_path, "wb") as f:
                f.write(audio_bytes)
            real_duration = _audio_duration(audio_path, float(scene.get("duration") or 5))
            log.info(
                "all_scene_tts: scene %d/%d done  size=%s  elapsed=%s  duration=%.2fs",
                i + 1, len(scenes), _kb(len(audio_bytes)), _elapsed(t_tts), real_duration,
            )
            updated_scenes[i] = {**updated_scenes[i], "audio_path": audio_path, "duration": real_duration}
            tts_delay = get_config().providers.tts_delay
            if tts_delay > 0 and i < len(scenes) - 1:
                log.debug("all_scene_tts: sleeping %.1fs before next TTS call", tts_delay)
                await asyncio.sleep(tts_delay)

        factory = get_session_factory()
        async with factory() as session:
            p = await session.get(Project, project_id)
            m = p.get_metadata()
            m["scenes"] = updated_scenes
            p.set_metadata(m)
            p.touch()
            await session.commit()

        log.info("all_scene_tts done project=%s", project_id)
        _emit("All scene audio ready", level="success", project_id=project_id, stage="tts")
        from app.events import emit as _emit_event
        _emit_event("project_update", project_id=project_id, status=None)

    except Exception:
        log.exception("all_scene_tts failed project=%s", project_id)
        _emit("All audio re-gen failed", level="error", project_id=project_id, stage="tts")
    finally:
        dec_active()
