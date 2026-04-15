"""Shared helpers used by all pipeline stages."""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time

from app.config import get_config
from app.database import get_session_factory
from app.models import Project
from app.events import emit, inc_active, dec_active

log = logging.getLogger(__name__)

_SCENE_SYSTEM_PROMPT = (
    "You are a YouTube Shorts script writer and video producer. "
    "You write engaging, punchy short-form content optimised for 60-second vertical videos."
)


# ── Path / formatting helpers ────────────────────────────────────────────────

def _project_dir(project_id: str) -> str:
    cfg = get_config()
    path = os.path.join(cfg.temp_dir, project_id)
    os.makedirs(path, exist_ok=True)
    return path


def _kb(n_bytes: int) -> str:
    return f"{n_bytes / 1024:.1f} KB"


def _elapsed(t0: float) -> str:
    return f"{time.monotonic() - t0:.2f}s"

def _format_project_slug(project: Project) -> str:
    return f"{project.title} ({project.id[:8]})"

def _parse_json_response(raw: str) -> dict:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw.strip())


# ── DB helpers ───────────────────────────────────────────────────────────────

async def _load_project(project_id: str) -> Project | None:
    factory = get_session_factory()
    async with factory() as session:
        return await session.get(Project, project_id)


def _emit(msg: str, *args, level: str = "info", project_id: str | None = None, **extra) -> None:
    """Emit a pipeline activity event (best-effort)."""
    if args:
        msg = msg % args
    kw: dict = {"msg": msg, "level": level, **extra}
    if project_id:
        kw["project_id"] = project_id
    emit("activity", **kw)


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
    _emit(f"Failed: {error}", level="error", project_id=project_id)
    emit("project_update", project_id=project_id, status="failed")


# ── Audio helper (used by tts + render stages) ───────────────────────────────

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
