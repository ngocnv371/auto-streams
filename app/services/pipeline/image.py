"""Stage 3 — images  (audio_ready → images_ready)."""
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
    _fail_project,
    _kb,
    _load_project,
    _project_dir,
)

log = logging.getLogger(__name__)


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


async def run_scene_image(project_id: str, scene_index: int) -> None:
    """Re-generate the image for a single scene without changing project status."""
    log.info("scene_image start project=%s scene=%d", project_id, scene_index)
    try:
        project = await _load_project(project_id)
        if project is None:
            log.warning("scene_image: project %s not found", project_id)
            return

        meta = project.get_metadata()
        scenes = meta.get("scenes", [])
        if scene_index < 0 or scene_index >= len(scenes):
            log.warning("scene_image: scene index %d out of range (0-%d)", scene_index, len(scenes) - 1)
            return

        scene = scenes[scene_index]
        visual_guide = meta.get("visual_guide", "")
        base_prompt = scene.get("image_prompt") or f"Cinematic scene: {scene.get('voiceover', '')}"
        prompt = f"{base_prompt}. Style: {visual_guide}" if visual_guide else base_prompt

        out_dir = _project_dir(project_id)
        svc = GenerationService()

        log.debug("scene_image: scene %d  prompt=%r", scene_index, prompt[:120])
        t_img = time.monotonic()
        image_bytes = await asyncio.to_thread(svc.generate_image, prompt)
        image_path = os.path.join(out_dir, f"scene_{scene_index:03d}_image.png")
        with open(image_path, "wb") as f:
            f.write(image_bytes)
        log.info(
            "scene_image: scene %d done  size=%s  elapsed=%s  path=%s",
            scene_index, _kb(len(image_bytes)), _elapsed(t_img), image_path,
        )

        factory = get_session_factory()
        async with factory() as session:
            p = await session.get(Project, project_id)
            m = p.get_metadata()
            m["scenes"][scene_index] = {**m["scenes"][scene_index], "image_path": image_path}
            p.set_metadata(m)
            p.touch()
            await session.commit()

        log.info("scene_image done project=%s scene=%d", project_id, scene_index)

    except Exception:
        log.exception("scene_image failed project=%s scene=%d", project_id, scene_index)
