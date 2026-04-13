"""Full pipeline  (approved → rendered)."""
from __future__ import annotations

import asyncio
import logging

from ._helpers import _load_project
from .image import run_image_stage
from .render import run_render_stage
from .music import run_music_stage
from .text import run_text_stage
from .tts import run_tts_stage
from .upload import run_upload_stage

log = logging.getLogger(__name__)


async def run_full_pipeline(project_id: str) -> None:
    """Run the pipeline for a single approved project.

    Stage order:
      1. text   (approved → scenes_ready)
      2. tts    (scenes_ready → tts_ready)   — needed first; sets duration + audio
      3. music + images in parallel           — both read from tts_ready metadata,
                                               converge to media_ready when both done
      4. render (media_ready → rendered)
      5. upload
    """
    log.info("full_pipeline start project=%s", project_id)

    # Stage 1: generate script / scenes
    await run_text_stage(project_id)
    project = await _load_project(project_id)
    if project is None or project.status == "failed":
        log.warning("full_pipeline aborted at text_stage for project=%s", project_id)
        return

    # Stage 2: TTS — must complete before music (duration) and before render (audio_path)
    await run_tts_stage(project_id)
    project = await _load_project(project_id)
    if project is None or project.status == "failed":
        log.warning("full_pipeline aborted at tts_stage for project=%s", project_id)
        return

    # Stage 3: music + images in parallel — they converge to media_ready
    await asyncio.gather(
        run_music_stage(project_id),
        run_image_stage(project_id),
    )
    project = await _load_project(project_id)
    if project is None or project.status == "failed":
        log.warning("full_pipeline aborted after music/image stages for project=%s", project_id)
        return

    # Stage 4+5: render then upload
    await run_render_stage(project_id)
    project = await _load_project(project_id)
    if project is None or project.status == "failed":
        log.warning("full_pipeline aborted at render_stage for project=%s", project_id)
        return

    await run_upload_stage(project_id)
    log.info("full_pipeline complete project=%s", project_id)
