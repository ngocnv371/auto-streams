from __future__ import annotations

import base64

import requests

from app.config import GeminiConfig
from .base import ImageProvider, TextProvider, TTSProvider

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

# Dedicated model names for modalities that need a specific checkpoint.
_IMAGE_MODEL = "gemini-2.0-flash-preview-image-generation"
_TTS_MODEL = "gemini-2.5-flash-preview-tts"
_DEFAULT_TTS_VOICE = "Kore"


class GeminiTextProvider(TextProvider):
    def __init__(self, config: GeminiConfig) -> None:
        self._config = config

    def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        url = f"{_BASE_URL}/models/{self._config.model}:generateContent"
        body: dict = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        }
        if system_prompt:
            body["systemInstruction"] = {"parts": [{"text": system_prompt}]}

        resp = requests.post(
            url,
            params={"key": self._config.api_key},
            json=body,
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"]


class GeminiImageProvider(ImageProvider):
    def __init__(self, config: GeminiConfig) -> None:
        self._config = config

    def generate(self, prompt: str, width: int, height: int) -> bytes:
        url = f"{_BASE_URL}/models/{_IMAGE_MODEL}:generateContent"
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]},
        }

        resp = requests.post(
            url,
            params={"key": self._config.api_key},
            json=body,
            timeout=120,
        )
        resp.raise_for_status()

        for part in resp.json()["candidates"][0]["content"]["parts"]:
            if "inlineData" in part:
                return base64.b64decode(part["inlineData"]["data"])

        raise RuntimeError("Gemini image generation returned no image data")


class GeminiTTSProvider(TTSProvider):
    def __init__(self, config: GeminiConfig) -> None:
        self._config = config

    def synthesize(self, text: str, voice: str | None = None, speed: float = 1.0) -> bytes:
        url = f"{_BASE_URL}/models/{_TTS_MODEL}:generateContent"
        body = {
            "contents": [{"role": "user", "parts": [{"text": text}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {
                        "prebuiltVoiceConfig": {"voiceName": voice or _DEFAULT_TTS_VOICE}
                    }
                },
            },
        }

        resp = requests.post(
            url,
            params={"key": self._config.api_key},
            json=body,
            timeout=120,
        )
        resp.raise_for_status()

        for part in resp.json()["candidates"][0]["content"]["parts"]:
            if "inlineData" in part:
                return base64.b64decode(part["inlineData"]["data"])

        raise RuntimeError("Gemini TTS returned no audio data")
