"""Pipeline package — re-exports all public stage functions.

Status flow:
  approved      → [text_stage]   → scenes_ready
  scenes_ready  → [tts_stage]    → audio_ready   (TTS per scene + music)
  scenes_ready  → [music_stage]  →               (music only, no status change)
  audio_ready   → [image_stage]  → images_ready
  images_ready  → [render_stage] → clips_ready → done
"""

from .full import run_full_pipeline
from .image import run_image_stage
from .render import run_render_stage
from .text import run_text_stage
from .tts import run_music_stage, run_tts_stage

__all__ = [
    "run_text_stage",
    "run_tts_stage",
    "run_music_stage",
    "run_image_stage",
    "run_render_stage",
    "run_full_pipeline",
]
