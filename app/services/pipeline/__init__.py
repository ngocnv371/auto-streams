"""Pipeline package — re-exports all public stage functions.

Status flow:
  approved      → [text_stage]   → scenes_ready
  scenes_ready  → [tts_stage]    → audio_ready   (TTS per scene + music)
  scenes_ready  → [music_stage]  →               (music only, no status change)
  audio_ready   → [image_stage]  → images_ready
  images_ready  → [render_stage] → clips_ready → done

Per-asset reruns (no status change):
  any           → [run_scene_image]  re-gen image for one scene
  any           → [run_scene_tts]    re-gen TTS audio for one scene
  any           → [rerun_music]      re-gen background music
"""

from .full import run_full_pipeline
from .image import run_all_scene_images, run_image_stage, run_scene_image
from .render import run_render_stage
from .text import run_text_stage
from .tts import rerun_music, run_all_scene_tts, run_music_stage, run_scene_tts, run_tts_stage

__all__ = [
    "run_text_stage",
    "run_tts_stage",
    "run_music_stage",
    "run_scene_tts",
    "run_all_scene_tts",
    "rerun_music",
    "run_image_stage",
    "run_scene_image",
    "run_all_scene_images",
    "run_render_stage",
    "run_full_pipeline",
]
