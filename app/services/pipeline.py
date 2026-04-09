"""Pipeline processing stages for the auto-streams generation workflow.

Status flow:
  approved      → [text_stage]   → scenes_ready
  scenes_ready  → [tts_stage]    → audio_ready   (TTS per scene + music)
  scenes_ready  → [music_stage]  →               (music only, no status change)
  audio_ready   → [image_stage]  → images_ready
  images_ready  → [render_stage] → clips_ready → done
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import time

from app.config import get_config
from app.database import get_session_factory
from app.models import Project, Topic
from app.services.generation.service import GenerationService

log = logging.getLogger(__name__)

_SCENE_SYSTEM_PROMPT = (
    "You are a YouTube Shorts script writer and video producer. "
    "You write engaging, punchy short-form content optimised for 60-second vertical videos."
)


# ═══════════════════════════════════════════════════════════
#  Shared helpers
# ═══════════════════════════════════════════════════════════

def _project_dir(project_id: str) -> str:
    cfg = get_config()
    path = os.path.join(cfg.temp_dir, project_id)
    os.makedirs(path, exist_ok=True)
    return path


def _kb(n_bytes: int) -> str:
    return f"{n_bytes / 1024:.1f} KB"


def _elapsed(t0: float) -> str:
    return f"{time.monotonic() - t0:.2f}s"


def _parse_json_response(raw: str) -> dict:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw.strip())


async def _load_project(project_id: str) -> Project | None:
    factory = get_session_factory()
    async with factory() as session:
        return await session.get(Project, project_id)


async def _fail_project(project_id: str, error: str) -> None:
    factory = get_session_factory()
    async with factory() as session:
        p = await session.get(Project, project_id)
        if p is None:
            return
        p.status = "failed"
        m = p.get_metadata()
        m["error"] = error
        p.set_metadata(m)
        p.touch()
        await session.commit()


# ═══════════════════════════════════════════════════════════
#  Stage 1 — text  (approved → scenes_ready)
# ═══════════════════════════════════════════════════════════

async def run_text_stage(project_id: str) -> None:
    """Use an LLM to generate the full script + scene breakdown."""
    log.info("text_stage start project=%s", project_id)
    try:
        project = await _load_project(project_id)
        if project is None:
            log.warning("text_stage: project %s not found", project_id)
            return
        if project.status != "approved":
            log.warning(
                "text_stage: project %s has status %r, expected 'approved'",
                project_id, project.status,
            )
            return

        # Load the topic sentence for richer context
        factory = get_session_factory()
        async with factory() as session:
            topic_row = await session.get(Topic, project.topic_id)
            topic_text = topic_row.topic if topic_row else project.title
        log.info("text_stage: topic=%r", topic_text)

        existing_summary = project.get_metadata().get("summary", "")
        if existing_summary:
            log.info("text_stage: using existing summary (%d chars)", len(existing_summary))

        cfg = get_config()
        log.info("text_stage: calling text provider=%r model=%r",
                 cfg.providers.text,
                 getattr(cfg.gemini if cfg.providers.text == "gemini" else cfg.openai, "text_model", "?"))

        summary_hint = f'\nContext: "{existing_summary}"' if existing_summary else ""
        prompt = (
            f'Video title: "{project.title}"\n'
            f'Topic: "{topic_text}"{summary_hint}\n\n'
            "Generate a complete, engaging YouTube Shorts script (target ~60 seconds).\n"
            "Respond with JSON ONLY — no explanation, no markdown fences:\n"
            "{\n"
            '  "transcript": "full narration as one block of text",\n'
            '  "narrator": "narrator character or tone description",\n'
            '  "music": "background music style/mood description",\n'
            '  "visual_guide": "overall visual style (colour palette, camera feel, etc.)",\n'
            '  "duration": 60,\n'
            '  "word_count": 120,\n'
            '  "scenes": [\n'
            '    {\n'
            '      "voiceover": "exact words spoken in this scene",\n'
            '      "image_prompt": "detailed image generation prompt for this scene",\n'
            '      "duration": 10\n'
            "    }\n"
            "  ]\n"
            "}"
        )
        log.debug("text_stage: prompt length=%d chars", len(prompt))

        svc = GenerationService()
        t_llm = time.monotonic()
        raw = await asyncio.to_thread(svc.generate_text, prompt, _SCENE_SYSTEM_PROMPT)
        data = _parse_json_response(raw)

        scenes = data.get("scenes", [])
        if not scenes:
            raise ValueError("LLM returned no scenes in the response")

        log.info(
            "text_stage: parsed ok  scenes=%d  duration=%ss  word_count=%s  narrator=%r",
            len(scenes),
            data.get("duration", "?"),
            data.get("word_count", "?"),
            str(data.get("narrator", ""))[:60],
        )
        for i, s in enumerate(scenes):
            log.debug(
                "text_stage: scene %d/%d  duration=%ss  voiceover=%r  image_prompt=%r",
                i + 1, len(scenes),
                s.get("duration", "?"),
                str(s.get("voiceover", ""))[:80],
                str(s.get("image_prompt", ""))[:80],
            )

        meta = {
            "transcript":   str(data.get("transcript", "")),
            "narrator":     str(data.get("narrator", "")),
            "music":        str(data.get("music", "")),
            "visual_guide": str(data.get("visual_guide", "")),
            "duration":     int(data.get("duration") or 60),
            "word_count":   int(data.get("word_count") or 0),
            "scenes":       scenes,
        }
        if existing_summary:
            meta["summary"] = existing_summary

        factory = get_session_factory()
        async with factory() as session:
            p = await session.get(Project, project_id)
            p.set_metadata(meta)
            p.status = "scenes_ready"
            p.touch()
            await session.commit()

        log.info("text_stage done project=%s scenes=%d", project_id, len(scenes))

    except Exception:
        log.exception("text_stage failed project=%s", project_id)
        await _fail_project(project_id, "text_stage failed — see server logs")


# ═══════════════════════════════════════════════════════════
#  Stage 2a — TTS  (scenes_ready → audio_ready)
# ═══════════════════════════════════════════════════════════

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
        duration = int(meta.get("duration") or 60)
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
            m["music_path"] = music_path
            p.set_metadata(m)
            p.status = "audio_ready"
            p.touch()
            await session.commit()

        log.info("tts_stage done project=%s", project_id)

    except Exception:
        log.exception("tts_stage failed project=%s", project_id)
        await _fail_project(project_id, "tts_stage failed — see server logs")


# ═══════════════════════════════════════════════════════════
#  Stage 2b — music only  (scenes_ready, no status change)
# ═══════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════
#  Stage 3 — images  (audio_ready → images_ready)
# ═══════════════════════════════════════════════════════════

async def run_image_stage(project_id: str) -> None:
    """Generate one image per scene."""
    log.info("image_stage start project=%s", project_id)
    try:
        project = await _load_project(project_id)
        if project is None or project.status != "audio_ready":
            log.warning(
                "image_stage: project %s not in audio_ready (status=%s)",
                project_id, project.status if project else "not found",
            )
            return

        meta = project.get_metadata()
        scenes = meta.get("scenes", [])
        visual_guide = meta.get("visual_guide", "")
        log.info("image_stage: %d scenes  provider=%r  visual_guide=%r",
                 len(scenes), get_config().providers.image, visual_guide[:80])

        out_dir = _project_dir(project_id)
        svc = GenerationService()

        updated_scenes = []
        for i, scene in enumerate(scenes):
            base_prompt = scene.get("image_prompt") or f"Cinematic scene: {scene.get('voiceover', '')}"
            prompt = f"{base_prompt}. Style: {visual_guide}" if visual_guide else base_prompt
            log.debug("image_stage: scene %d/%d  prompt=%r", i + 1, len(scenes), prompt[:120])

            t_img = time.monotonic()
            image_bytes = await asyncio.to_thread(svc.generate_image, prompt)
            image_path = os.path.join(out_dir, f"scene_{i:03d}_image.png")
            with open(image_path, "wb") as f:
                f.write(image_bytes)
            log.info(
                "image_stage: scene %d/%d done  size=%s  elapsed=%s  path=%s",
                i + 1, len(scenes), _kb(len(image_bytes)), _elapsed(t_img), image_path,
            )
            updated_scenes.append({**scene, "image_path": image_path})

        factory = get_session_factory()
        async with factory() as session:
            p = await session.get(Project, project_id)
            m = p.get_metadata()
            m["scenes"] = updated_scenes
            p.set_metadata(m)
            p.status = "images_ready"
            p.touch()
            await session.commit()

        log.info("image_stage done project=%s", project_id)

    except Exception:
        log.exception("image_stage failed project=%s", project_id)
        await _fail_project(project_id, "image_stage failed — see server logs")


# ═══════════════════════════════════════════════════════════
#  Stage 4 — render  (images_ready / clips_ready → done)
# ═══════════════════════════════════════════════════════════

def _audio_duration(audio_path: str, fallback: float) -> float:
    """Return the real duration of a WAV/audio file via ffprobe, or the fallback."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                audio_path,
            ],
            capture_output=True, text=True, check=True,
        )
        return float(result.stdout.strip()) or fallback
    except Exception:
        return fallback


def _render_scene_clip(scene: dict, out_path: str) -> None:
    """Combine a still image (+ optional audio) into a 1080×1920 MP4 clip using ffmpeg."""
    cfg = get_config()
    image_path = scene["image_path"]
    audio_path = scene.get("audio_path")
    duration = float(scene.get("duration") or 5)
    log.debug(
        "_render_scene_clip: image=%s  audio=%s  duration=%.1fs  ken_burns=%s",
        image_path, audio_path, duration, getattr(cfg.video, "enableKenBurns", False),
    )

    if audio_path and os.path.exists(audio_path):
        duration = _audio_duration(audio_path, duration)

        if cfg.video.enableKenBurns:
            frames = max(1, int(duration * 25))
            vf = (
                "scale=iw*3:ih*3,"
                f"zoompan=z='min(zoom+0.0004,1.5)'"
                f":x='iw/2-(iw/zoom/2)'"
                f":y='ih/2-(ih/zoom/2)'"
                f":d={frames}:s=1080x1920:fps=25"
            )
        else:
            vf = (
                "scale=1080:1920:force_original_aspect_ratio=decrease,"
                "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black"
            )

        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", image_path,
            "-i", audio_path,
            "-vf", vf,
            "-c:v", "libx264", "-tune", "stillimage",
            "-c:a", "aac", "-b:a", "192k",
            "-pix_fmt", "yuv420p",
            "-shortest",
            out_path,
        ]
        log.debug("_render_scene_clip: cmd=%s", cmd)
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            log.error("_render_scene_clip ffmpeg failed\nSTDERR:\n%s", result.stderr)
            result.check_returncode()
    else:
        vf = (
            "scale=1080:1920:force_original_aspect_ratio=decrease,"
            "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black"
        )
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", image_path,
            "-vf", vf,
            "-c:v", "libx264",
            "-t", str(duration),
            "-pix_fmt", "yuv420p",
            out_path,
        ]
        log.debug("_render_scene_clip: cmd=%s", cmd)
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            log.error("_render_scene_clip ffmpeg failed\nSTDERR:\n%s", result.stderr)
            result.check_returncode()


def _concat_clips(clip_paths: list[str], out_path: str) -> None:
    """Concatenate MP4 clips into one using ffmpeg concat demuxer."""
    log.debug("_concat_clips: %d clips -> %s", len(clip_paths), out_path)
    list_path = out_path + ".txt"
    with open(list_path, "w", encoding="utf-8") as f:
        for p in clip_paths:
            # Use absolute paths so ffmpeg doesn't resolve relative to the list file location.
            # ffmpeg requires forward slashes even on Windows inside concat list.
            abs_p = os.path.abspath(p).replace(chr(92), "/")
            f.write(f"file '{abs_p}'\n")
    try:
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", list_path,
            "-c", "copy",
            out_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            log.error("_concat_clips ffmpeg failed\nSTDERR:\n%s", result.stderr)
            result.check_returncode()
    finally:
        try:
            os.remove(list_path)
        except OSError:
            pass


def _mix_music(video_path: str, music_path: str, out_path: str) -> None:
    """Mix background music (at low volume) under the video's existing audio."""
    log.debug("_mix_music: video=%s  music=%s -> %s", video_path, music_path, out_path)
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", music_path,
        "-filter_complex",
        "[1:a]volume=0.12[bg];[0:a][bg]amix=inputs=2:duration=first[a]",
        "-map", "0:v", "-map", "[a]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        out_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log.error("_mix_music ffmpeg failed\nSTDERR:\n%s", result.stderr)
        result.check_returncode()


async def run_render_stage(project_id: str) -> None:
    """Render per-scene clips then assemble the final video. images_ready / clips_ready → done."""
    log.info("render_stage start project=%s", project_id)
    try:
        project = await _load_project(project_id)
        if project is None or project.status not in ("images_ready", "clips_ready"):
            log.warning(
                "render_stage: project %s not in images_ready/clips_ready (status=%s)",
                project_id, project.status if project else "not found",
            )
            return

        meta = project.get_metadata()
        scenes = meta.get("scenes", [])
        music_path = meta.get("music_path")
        out_dir = _project_dir(project_id)

        # ── Per-scene clips ──────────────────────────────────────────
        updated_scenes = []
        clip_paths: list[str] = []
        for i, scene in enumerate(scenes):
            clip_path = os.path.join(out_dir, f"scene_{i:03d}_clip.mp4")
            if os.path.exists(clip_path):
                log.info("render_stage: clip %d/%d already exists, reusing  path=%s", i + 1, len(scenes), clip_path)
            else:
                t_clip = time.monotonic()
                await asyncio.to_thread(_render_scene_clip, scene, clip_path)
                log.info(
                    "render_stage: clip %d/%d done  elapsed=%s  path=%s",
                    i + 1, len(scenes), _elapsed(t_clip), clip_path,
                )
            clip_paths.append(clip_path)
            updated_scenes.append({**scene, "clip_path": clip_path})

        # Persist intermediate clips_ready state
        factory = get_session_factory()
        async with factory() as session:
            p = await session.get(Project, project_id)
            m = p.get_metadata()
            m["scenes"] = updated_scenes
            p.set_metadata(m)
            p.status = "clips_ready"
            p.touch()
            await session.commit()

        # ── Concatenate ──────────────────────────────────────────────
        merged_path = os.path.join(out_dir, "merged.mp4")
        log.info("render_stage: concatenating %d clips -> %s", len(clip_paths), merged_path)
        t_concat = time.monotonic()
        await asyncio.to_thread(_concat_clips, clip_paths, merged_path)
        log.info("render_stage: concat done  elapsed=%s", _elapsed(t_concat))

        # ── Mix music ────────────────────────────────────────────────
        final_path = os.path.join(out_dir, "final.mp4")
        if music_path and os.path.exists(music_path):
            log.info("render_stage: mixing music  music=%s", music_path)
            t_mix = time.monotonic()
            await asyncio.to_thread(_mix_music, merged_path, music_path, final_path)
            log.info("render_stage: mix done  elapsed=%s", _elapsed(t_mix))
        else:
            log.info("render_stage: no music track, using merged video as final")
            os.replace(merged_path, final_path)

        factory = get_session_factory()
        async with factory() as session:
            p = await session.get(Project, project_id)
            m = p.get_metadata()
            m["video_path"] = final_path
            p.set_metadata(m)
            p.status = "done"
            p.touch()
            await session.commit()

        log.info("render_stage done project=%s final=%s", project_id, final_path)

    except Exception:
        log.exception("render_stage failed project=%s", project_id)
        await _fail_project(project_id, "render_stage failed — see server logs")


# ═══════════════════════════════════════════════════════════
#  Full pipeline  (approved → done)
# ═══════════════════════════════════════════════════════════

async def run_full_pipeline(project_id: str) -> None:
    """Run all stages sequentially for a single approved project."""
    log.info("full_pipeline start project=%s", project_id)

    for stage in (run_text_stage, run_tts_stage, run_image_stage, run_render_stage):
        await stage(project_id)
        project = await _load_project(project_id)
        if project is None or project.status == "failed":
            log.warning("full_pipeline aborted at %s for project=%s", stage.__name__, project_id)
            return

    log.info("full_pipeline complete project=%s", project_id)
