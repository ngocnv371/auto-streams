from __future__ import annotations

from app.config import AppConfig, get_config
from .providers.base import ImageProvider, MusicProvider, TextProvider, TTSProvider
from .providers.comfy import ComfyImageProvider, ComfyMusicProvider
from .providers.gemini import GeminiImageProvider, GeminiTextProvider, GeminiTTSProvider
from .providers.kittentts import KittenTTSProvider
from .providers.openai_compat import OpenAITextProvider

# Default dimensions for 9:16 short-form video.
_DEFAULT_WIDTH = 1080
_DEFAULT_HEIGHT = 1920


class GenerationService:
    """Dispatches generation requests to the provider configured in config.yml."""

    def __init__(self, config: AppConfig | None = None) -> None:
        self._config = config or get_config()
        self._text = self._build_text_provider()
        self._image = self._build_image_provider()
        self._tts = self._build_tts_provider()
        self._music = self._build_music_provider()

    # ------------------------------------------------------------------
    # Provider factories
    # ------------------------------------------------------------------

    def _build_text_provider(self) -> TextProvider:
        name = self._config.providers.text
        if name == "gemini":
            return GeminiTextProvider(self._config.gemini)
        if name == "openai":
            return OpenAITextProvider(self._config.openai)
        raise ValueError(f"Unknown text provider: {name!r}. Choose 'gemini' or 'openai'.")

    def _build_image_provider(self) -> ImageProvider:
        name = self._config.providers.image
        if name == "gemini":
            return GeminiImageProvider(self._config.gemini)
        if name == "comfy":
            return ComfyImageProvider(self._config.comfy)
        raise ValueError(f"Unknown image provider: {name!r}. Choose 'gemini' or 'comfy'.")

    def _build_tts_provider(self) -> TTSProvider:
        name = self._config.providers.tts
        if name == "gemini":
            return GeminiTTSProvider(self._config.gemini)
        if name == "kittentts":
            return KittenTTSProvider(self._config.kittentts)
        raise ValueError(f"Unknown TTS provider: {name!r}. Choose 'gemini' or 'kittentts'.")

    def _build_music_provider(self) -> MusicProvider:
        name = self._config.providers.music
        if name == "comfy":
            return ComfyMusicProvider(self._config.comfy)
        raise ValueError(f"Unknown music provider: {name!r}. Only 'comfy' is supported.")

    # ------------------------------------------------------------------
    # Public generation API
    # ------------------------------------------------------------------

    def generate_text(self, prompt: str, system_prompt: str | None = None) -> str:
        """Generate text from a prompt using the configured LLM provider."""
        return self._text.generate(prompt, system_prompt)

    def generate_image(
        self,
        prompt: str,
        width: int = _DEFAULT_WIDTH,
        height: int = _DEFAULT_HEIGHT,
    ) -> bytes:
        """Generate an image and return raw bytes (PNG/JPEG)."""
        return self._image.generate(prompt, width, height)

    def generate_speech(
        self,
        text: str,
        voice: str | None = None,
        speed: float = 1.0,
    ) -> bytes:
        """Synthesise speech and return raw WAV bytes."""
        return self._tts.synthesize(text, voice, speed)

    def generate_music(self, prompt: str, duration: int = 60) -> bytes:
        """Generate background music and return raw audio bytes."""
        return self._music.generate(prompt, duration)
