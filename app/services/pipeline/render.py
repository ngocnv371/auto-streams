"""Stage 4 — render  (media_ready / clips_ready → done)."""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import time

from app.config import get_config
from app.database import get_session_factory
from app.models import Project
from .render_subtitles import align_and_burn, burn_subtitles_on_clip, extract_audio_segment

from ._helpers import (
    _audio_duration,
    _elapsed,
    _emit,
    _fail_project,
    _format_project_slug,
    _load_project,
    _project_dir,
)

log = logging.getLogger(__name__)


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
    """Render per-scene clips then assemble the final video. images_ready / media_ready / clips_ready → done."""
    from app.events import inc_active, dec_active, emit as _emit_event
    log.info("render_stage start project=%s", project_id)
    inc_active()
    _emit("Render stage started", project_id=project_id, stage="render")
    try:
        project = await _load_project(project_id)
        if project is None or project.status not in ("images_ready", "media_ready", "clips_ready"):
            _emit(
                "render_stage: project %s not in images_ready/media_ready/clips_ready (status=%s)",
                project_id, project.status if project else "not found",
            )
            return
        log.info("render_stage: project=%s", _format_project_slug(project))
        _emit("Rendering video for %s", _format_project_slug(project), project_id=project_id, stage="render")

        meta = project.get_metadata()
        scenes = meta.get("scenes", [])
        music_path = meta.get("music_path")
        out_dir = _project_dir(project_id)

        cfg = get_config()

        # ── Per-scene clips ──────────────────────────────────────────
        updated_scenes = []
        clip_paths: list[str] = []
        for i, scene in enumerate(scenes):
            clip_path = os.path.join(out_dir, f"scene_{i:03d}_clip.mp4")

            # ── Resolve per-scene audio segment ───────────────────────
            # When the TTS stage ran in bulk mode the scene carries
            # audio_start/audio_end offsets into a shared combined_tts.wav.
            # Extract the segment so _render_scene_clip gets a standalone file.
            audio_start = scene.get("audio_start")
            audio_end = scene.get("audio_end")
            combined_audio = scene.get("audio_path")
            if audio_start is not None and audio_end is not None and combined_audio:
                seg_path = os.path.join(out_dir, f"scene_{i:03d}_tts_seg.wav")
                if not os.path.exists(seg_path):
                    await asyncio.to_thread(
                        extract_audio_segment,
                        combined_audio, audio_start, audio_end, seg_path,
                        cfg.video.scene_gap,
                    )
                scene_for_render = {**scene, "audio_path": seg_path}
            else:
                scene_for_render = scene

            if os.path.exists(clip_path):
                log.info("render_stage: clip %d/%d already exists, reusing  path=%s", i + 1, len(scenes), clip_path)
            else:
                t_clip = time.monotonic()
                await asyncio.to_thread(_render_scene_clip, scene_for_render, clip_path)
                log.info(
                    "render_stage: clip %d/%d done  elapsed=%s  path=%s",
                    i + 1, len(scenes), _elapsed(t_clip), clip_path,
                )
                _emit(f"Render: clip {i + 1}/{len(scenes)} done", level="success", project_id=project_id, stage="render")

            # ── Subtitle burn-in (optional) ──────────────────────────
            if cfg.video.enableSubtitles:
                sub_path = os.path.join(out_dir, f"scene_{i:03d}_clip_sub.mp4")
                if os.path.exists(sub_path):
                    log.info("render_stage: subtitled clip %d/%d already exists, reusing", i + 1, len(scenes))
                else:
                    t_sub = time.monotonic()
                    pre_built_srt = scene.get("srt_path")
                    if pre_built_srt and os.path.exists(pre_built_srt):
                        # Fast path: SRT was already produced during TTS alignment
                        await asyncio.to_thread(
                            burn_subtitles_on_clip, clip_path, pre_built_srt, sub_path,
                            cfg.video.subtitleStyle,
                        )
                    else:
                        # Fallback: align + burn for scenes without a pre-built SRT
                        sub_path = await asyncio.to_thread(
                            align_and_burn, scene_for_render, clip_path, sub_path,
                            style=cfg.video.subtitleStyle,
                        )
                    log.info(
                        "render_stage: subtitles %d/%d done  elapsed=%s  path=%s",
                        i + 1, len(scenes), _elapsed(t_sub), sub_path,
                    )
                    _emit(f"Subtitles: clip {i + 1}/{len(scenes)} done", level="success", project_id=project_id, stage="render")
                clip_path = sub_path

            clip_paths.append(clip_path)
            updated_scenes.append({**scene, "clip_path": clip_path})

        # Persist intermediate clips_ready state
        factory = get_session_factory()
        async with factory() as session:
            p = await session.get(Project, project_id)
            if (p is None):
                log.warning("render_stage: project %s disappeared during processing", project_id)
                return
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
            if (p is None):
                log.warning("render_stage: project %s disappeared during processing", project_id)
                return
            m = p.get_metadata()
            m["video_path"] = final_path
            p.set_metadata(m)
            p.status = "rendered"
            p.touch()
            await session.commit()

        log.info("render_stage done project=%s final=%s", project_id, final_path)
        _emit("Render complete", level="success", project_id=project_id, stage="render")
        _emit_event("project_update", project_id=project_id, status="rendered")

    except Exception:
        log.exception("render_stage failed project=%s", project_id)
        await _fail_project(project_id, "render_stage failed — see server logs")
    finally:
        dec_active()
