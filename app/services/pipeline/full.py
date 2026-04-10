"""Full pipeline  (approved → done)."""
from __future__ import annotations

import logging

from ._helpers import _load_project
from .image import run_image_stage
from .render import run_render_stage
from .text import run_text_stage
from .tts import run_tts_stage

log = logging.getLogger(__name__)


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
