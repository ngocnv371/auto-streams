"""Subtitle alignment (stable-ts) and ffmpeg burn-in for scene clips.

Typical usage:

    from app.services.pipeline.render_subtitles import align_and_burn

    subtitled_clip = align_and_burn(scene, clip_path, out_path, style=cfg.video.subtitleStyle)
"""
from __future__ import annotations

import logging
import os
import re
import subprocess

log = logging.getLogger(__name__)

# ── Model cache ───────────────────────────────────────────────────────────────

_whisper_model: object | None = None


def _get_whisper_model(model_name: str = "base"):
    """Return a cached stable-whisper model, loading it on first use."""
    global _whisper_model
    if _whisper_model is None:
        import stable_whisper  # type: ignore

        log.info("render_subtitles: loading stable-whisper model %r", model_name)
        _whisper_model = stable_whisper.load_model(model_name)
        log.info("render_subtitles: model loaded")
    return _whisper_model


# ── Alignment ─────────────────────────────────────────────────────────────────


def align_scene_subtitles(
    audio_path: str,
    text: str,
    out_srt_path: str,
    language: str = "en",
    word_level: bool = False,
    model_name: str = "base",
) -> str:
    """Align *text* to *audio_path* using stable-ts and write an SRT file.

    Parameters
    ----------
    audio_path:
        Path to the WAV/MP3 audio produced by the TTS stage.
    text:
        Transcript text to align (the scene's voiceover string).
    out_srt_path:
        Destination path for the generated ``.srt`` file.
    language:
        BCP-47 / ISO 639-1 language code (default ``"en"``).
    word_level:
        Write word-level timestamps (karaoke style) when ``True``; 
        segment-level sentences when ``False`` (default).
    model_name:
        Whisper model size used for alignment (default ``"base"``).
        ``"tiny"`` is faster; ``"small"`` or ``"medium"`` are more accurate.

    Returns
    -------
    str
        ``out_srt_path`` after writing.
    """
    model = _get_whisper_model(model_name)
    log.debug(
        "align_scene_subtitles: audio=%s  lang=%s  word_level=%s  text=%r",
        audio_path, language, word_level, text[:80],
    )
    result = model.align(audio_path, text, language=language)
    result.to_srt_vtt(out_srt_path, word_level=word_level)
    log.debug("align_scene_subtitles: wrote %s", out_srt_path)
    return out_srt_path


# ── Style helpers ─────────────────────────────────────────────────────────────


def _hex_to_ass_color(hex_color: str, alpha: int = 0x00) -> str:
    """Convert ``#RRGGBB`` to ASS ``&HAABBGGRR`` color string.

    *alpha* follows the ASS convention: ``0x00`` = fully opaque,
    ``0xFF`` = fully transparent.
    """
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"


def _escape_srt_path_for_ffmpeg(path: str) -> str:
    """Escape an absolute path for use inside ffmpeg's ``subtitles`` filter value.

    On Windows the drive-letter colon must be written as ``\\:`` inside the
    filter graph string, e.g. ``C:/foo.srt`` → ``C\\:/foo.srt``.
    """
    path = os.path.abspath(path).replace("\\", "/")
    # Escape the drive-letter colon only (first colon in the path)
    path = re.sub(r"^([A-Za-z]):", r"\1\\:", path)
    return path


# ── Burn-in ───────────────────────────────────────────────────────────────────


def burn_subtitles_on_clip(
    clip_path: str,
    srt_path: str,
    out_path: str,
    style=None,
) -> None:
    """Burn subtitle timings from *srt_path* into *clip_path* via ffmpeg.

    The audio stream is stream-copied (no re-encode); only the video track is
    re-encoded so that the burnt text is embedded in the picture.

    Parameters
    ----------
    clip_path:
        Input video clip (MP4).
    srt_path:
        SRT subtitle file produced by :func:`align_scene_subtitles`.
    out_path:
        Destination MP4 path for the subtitled clip.
    style:
        :class:`~app.config.SubtitleStyle` instance; falls back to
        config defaults when ``None``.
    """
    if style is None:
        from app.config import SubtitleStyle

        style = SubtitleStyle()

    primary = _hex_to_ass_color(style.color)
    # Thin hard outline for crispness; most of the "edge" comes from the shadow.
    outline_color = _hex_to_ass_color(style.stroke)
    # Semi-transparent (50 %) version of the stroke color used as the drop shadow.
    # ASS alpha: 0x00 = fully opaque, 0xFF = fully transparent.
    shadow_color = _hex_to_ass_color(style.stroke, alpha=0x80)
    force_style = (
        f"FontName={style.font},"
        f"FontSize={style.fontSize},"
        f"PrimaryColour={primary},"
        f"OutlineColour={outline_color},"
        f"BackColour={shadow_color},"
        # Outline=1 keeps a thin crisp edge; Shadow=2 + Blur=2 create the
        # soft feathered drop-shadow so the overall effect fades out gently.
        "Outline=1,Shadow=2,Blur=2,Alignment=2,MarginV=40"
    )

    srt_escaped = _escape_srt_path_for_ffmpeg(srt_path)
    vf = f"subtitles='{srt_escaped}':force_style='{force_style}'"

    cmd = [
        "ffmpeg", "-y",
        "-i", clip_path,
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-c:a", "copy",
        out_path,
    ]
    log.debug("burn_subtitles_on_clip: cmd=%s", cmd)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log.error("burn_subtitles_on_clip ffmpeg failed\nSTDERR:\n%s", result.stderr)
        result.check_returncode()


# ── Convenience ───────────────────────────────────────────────────────────────


def align_and_burn(
    scene: dict,
    clip_path: str,
    out_path: str,
    style=None,
    language: str = "en",
    srt_path: str | None = None,
    model_name: str = "base",
    word_level: bool = False,
) -> str:
    """Align a scene's voiceover to its audio then burn subtitles onto the clip.

    If the scene has no ``"voiceover"`` text or no valid ``"audio_path"`` the
    function logs a warning and returns *clip_path* unchanged so the caller
    can continue without subtitles.

    Parameters
    ----------
    scene:
        Scene metadata dict; must contain ``"voiceover"`` and ``"audio_path"``.
    clip_path:
        Rendered scene video clip (output of the render stage).
    out_path:
        Destination path for the subtitled clip.
    style:
        :class:`~app.config.SubtitleStyle`; uses config defaults when ``None``.
    language:
        Language code passed to stable-ts (default ``"en"``).
    srt_path:
        Explicit path for the intermediate SRT file.
        Defaults to ``out_path + ".srt"``.
    model_name:
        Whisper model size for alignment (default ``"base"``).
    word_level:
        Pass ``True`` for word-level (karaoke-style) subtitles.

    Returns
    -------
    str
        Path to the subtitled clip on success, or *clip_path* if subtitles
        were skipped.
    """
    voiceover = (scene.get("voiceover") or "").strip()
    audio_path = scene.get("audio_path") or ""

    if not voiceover:
        log.warning("align_and_burn: scene has no voiceover text – skipping subtitles")
        return clip_path

    if not audio_path or not os.path.exists(audio_path):
        log.warning(
            "align_and_burn: audio_path missing or not found (%r) – skipping subtitles",
            audio_path,
        )
        return clip_path

    if srt_path is None:
        srt_path = out_path + ".srt"

    align_scene_subtitles(
        audio_path, voiceover, srt_path,
        language=language, word_level=word_level, model_name=model_name,
    )
    burn_subtitles_on_clip(clip_path, srt_path, out_path, style=style)
    return out_path
