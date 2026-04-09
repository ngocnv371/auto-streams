from __future__ import annotations

import io

import soundfile as sf

from kittentts import KittenTTS

from app.config import KittenTTSConfig
from .base import TTSProvider

_SAMPLE_RATE = 24_000  # KittenTTS native sample rate


class KittenTTSProvider(TTSProvider):
    def __init__(self, config: KittenTTSConfig) -> None:
        self._config = config
        # KittenTTS downloads its model from HuggingFace on first instantiation.
        self._tts = KittenTTS(model_name=config.model)

    def synthesize(self, text: str, voice: str | None = None, speed: float = 1.0) -> bytes:
        effective_voice = voice or self._config.voice
        audio_array = self._tts.generate(text, voice=effective_voice, speed=speed)

        buf = io.BytesIO()
        sf.write(buf, audio_array, _SAMPLE_RATE, format="WAV")
        buf.seek(0)
        return buf.read()
