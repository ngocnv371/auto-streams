"""Stage 1 — text  (approved → scenes_ready)."""
from __future__ import annotations

import asyncio
import logging
import time

from app.config import get_config
from app.database import get_session_factory
from app.models import Project, Topic
from app.services.generation.service import GenerationService

from ._helpers import (
    _SCENE_SYSTEM_PROMPT,
    _emit,
    _fail_project,
    _load_project,
    _parse_json_response,
)

log = logging.getLogger(__name__)


async def run_text_stage(project_id: str) -> None:
    """Use an LLM to generate the full script + scene breakdown."""
    from app.events import inc_active, dec_active
    log.info("text_stage start project=%s", project_id)
    inc_active()
    _emit("Generating script…", project_id=project_id, stage="text")
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
            '  "tags": ["up to 5 short hashtag-style keywords relevant to the video, without the # symbol"],\n'
            '  "scenes": [\n'
            '    {\n'
            '      "voiceover": "exact words spoken in this scene",\n'
            '      "image_prompt": "detailed image generation prompt for this scene"\n'
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

        transcript = str(data.get("transcript", ""))
        word_count = len(transcript.split())
        raw_tags = data.get("tags", [])
        tags = [str(t).strip().lstrip("#") for t in raw_tags if str(t).strip()][:5]
        log.info(
            "text_stage: parsed ok  scenes=%d  word_count=%d  narrator=%r  tags=%r",
            len(scenes),
            word_count,
            str(data.get("narrator", ""))[:60],
            tags,
        )
        for i, s in enumerate(scenes):
            log.debug(
                "text_stage: scene %d/%d  voiceover=%r  image_prompt=%r",
                i + 1, len(scenes),
                str(s.get("voiceover", ""))[:80],
                str(s.get("image_prompt", ""))[:80],
            )

        meta = {
            "transcript":   transcript,
            "narrator":     str(data.get("narrator", "")),
            "music":        str(data.get("music", "")),
            "visual_guide": str(data.get("visual_guide", "")),
            "word_count":   word_count,
            "scenes":       scenes,
            "tags":         tags,
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
        _emit(f"Script ready — {len(scenes)} scenes", level="success", project_id=project_id, stage="text")
        from app.events import emit
        emit("project_update", project_id=project_id, status="scenes_ready")

    except Exception:
        log.exception("text_stage failed project=%s", project_id)
        await _fail_project(project_id, "text_stage failed — see server logs")
    finally:
        dec_active()
