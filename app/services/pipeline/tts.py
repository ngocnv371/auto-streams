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
    _format_project_slug,
    _kb,
    _load_project,
    _project_dir,
)

log = logging.getLogger(__name__)


async def run_tts_stage(project_id: str) -> None:
    """Generate TTS audio for the whole script in one request, then align to scenes.

    Instead of calling the TTS service once per scene (which triggers rate-limits
    on providers like Gemini), the full transcript is sent as a single request.
    stable-ts is then used to align the combined audio back to each scene's
    voiceover text, producing per-scene ``audio_start`` / ``audio_end`` timestamps
    and SRT subtitle files—without any additional TTS calls.
    """
    from app.events import inc_active, dec_active, emit as _emit_event
    from app.services.pipeline.render_subtitles import align_full_audio_to_scenes

    log.info("tts_stage start project=%s", project_id)
    inc_active()
    _emit("TTS stage started", project_id=project_id, stage="tts")
    try:
        project = await _load_project(project_id)
        if project is None:
            log.warning("tts_stage: project %s not found", project_id)
            return
        log.info("tts_stage: project=%s", _format_project_slug(project))
        _emit("Generating TTS audio for %s", _format_project_slug(project), project_id=project_id, stage="tts")
        
        meta = project.get_metadata()
        scenes = meta.get("scenes", [])
        if not scenes:
            log.warning(
                "tts_stage: project %s has no scenes in metadata (status=%s), skipping",
                project_id, project.status,
            )
            return

        out_dir = _project_dir(project_id)
        svc = GenerationService()
        cfg = get_config()

        log.info(
            "tts_stage: %d scenes  tts_provider=%r  music_provider=%r",
            len(scenes), cfg.providers.tts, cfg.providers.music,
        )

        # ── Single whole-script TTS call ──────────────────────────────
        full_text = meta.get("transcript", "").strip()
        if not full_text:
            raise ValueError("No transcript found in project metadata")

        log.info("tts_stage: sending full script (%d chars) as one TTS request", len(full_text))
        t_tts = time.monotonic()
        audio_bytes = await asyncio.to_thread(svc.generate_speech, full_text)
        combined_path = os.path.join(out_dir, "combined_tts.wav")
        with open(combined_path, "wb") as f:
            f.write(audio_bytes)
        log.info(
            "tts_stage: combined TTS done  size=%s  elapsed=%s  path=%s",
            _kb(len(audio_bytes)), _elapsed(t_tts), combined_path,
        )
        _emit("TTS audio generated", level="success", project_id=project_id, stage="tts")

        # ── Align full audio to individual scenes ─────────────────────
        log.info("tts_stage: aligning audio to %d scenes with stable-ts", len(scenes))
        t_align = time.monotonic()
        updated_scenes = await asyncio.to_thread(
            align_full_audio_to_scenes,
            combined_path,
            scenes,
            out_dir,
            full_text,
            cfg.providers.tts_language,
            cfg.video.whisper_model,
        )
        log.info("tts_stage: alignment done  elapsed=%s", _elapsed(t_align))
        _emit("Script aligned to audio", level="success", project_id=project_id, stage="tts")

        # Attach the shared combined audio path to every scene so the render
        # stage knows which file to slice segments from.
        updated_scenes = [{**s, "audio_path": combined_path} for s in updated_scenes]

        duration = int(round(sum(s.get("duration", 0) for s in updated_scenes))) or 60

        factory = get_session_factory()
        async with factory() as session:
            p = await session.get(Project, project_id)
            m = p.get_metadata()
            m["scenes"] = updated_scenes
            m["duration"] = duration
            m["combined_tts_path"] = combined_path
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
        log.info("scene_tts: project=%s, scene=%d", _format_project_slug(project), scene_index)
        _emit(f"Re-generating audio for scene {scene_index + 1} of %s", _format_project_slug(project), project_id=project_id, stage="tts")

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
    """Re-generate TTS audio for the whole script in one request, then re-align scenes.

    Mirrors run_tts_stage but does not change project status so it can be
    triggered at any point after scenes_ready.
    """
    from app.events import inc_active, dec_active, emit as _emit_event
    from app.services.pipeline.render_subtitles import align_full_audio_to_scenes

    log.info("all_scene_tts start project=%s", project_id)
    inc_active()
    _emit("Re-generating all audio", project_id=project_id, stage="tts")
    try:
        project = await _load_project(project_id)
        if project is None:
            log.warning("all_scene_tts: project %s not found", project_id)
            return
        log.info("all_scene_tts: project=%s", _format_project_slug(project))
        _emit("Re-generating all audio %s", _format_project_slug(project), project_id=project_id, stage="tts")

        meta = project.get_metadata()
        scenes = meta.get("scenes", [])
        if not scenes:
            log.warning("all_scene_tts: project %s has no scenes", project_id)
            return

        transcript = meta.get("transcript", "").strip()
        if not transcript:
            raise ValueError("No transcript found in project metadata")

        out_dir = _project_dir(project_id)
        svc = GenerationService()
        cfg = get_config()

        log.info("all_scene_tts: sending full script (%d chars) as one TTS request", len(transcript))
        t_tts = time.monotonic()
        audio_bytes = await asyncio.to_thread(svc.generate_speech, transcript)
        combined_path = os.path.join(out_dir, "combined_tts.wav")
        with open(combined_path, "wb") as f:
            f.write(audio_bytes)
        log.info(
            "all_scene_tts: TTS done  size=%s  elapsed=%s",
            _kb(len(audio_bytes)), _elapsed(t_tts),
        )
        _emit("TTS audio generated", level="success", project_id=project_id, stage="tts")

        log.info("all_scene_tts: aligning audio to %d scenes with stable-ts", len(scenes))
        t_align = time.monotonic()
        updated_scenes = await asyncio.to_thread(
            align_full_audio_to_scenes,
            combined_path,
            scenes,
            out_dir,
            transcript,
            cfg.providers.tts_language,
            cfg.video.whisper_model,
        )
        log.info("all_scene_tts: alignment done  elapsed=%s", _elapsed(t_align))

        updated_scenes = [{**s, "audio_path": combined_path} for s in updated_scenes]
        duration = int(round(sum(s.get("duration", 0) for s in updated_scenes))) or 60

        factory = get_session_factory()
        async with factory() as session:
            p = await session.get(Project, project_id)
            m = p.get_metadata()
            m["scenes"] = updated_scenes
            m["duration"] = duration
            m["combined_tts_path"] = combined_path
            p.set_metadata(m)
            p.touch()
            await session.commit()

        log.info("all_scene_tts done project=%s", project_id)
        _emit("All scene audio ready", level="success", project_id=project_id, stage="tts")
        _emit_event("project_update", project_id=project_id, status=None)

    except Exception:
        log.exception("all_scene_tts failed project=%s", project_id)
        _emit("All audio re-gen failed", level="error", project_id=project_id, stage="tts")
    finally:
        dec_active()
