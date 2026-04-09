from __future__ import annotations

import base64

import requests

from app.config import GeminiConfig
from .base import ImageProvider, TextProvider, TTSProvider

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

class GeminiTextProvider(TextProvider):
    def __init__(self, config: GeminiConfig) -> None:
        self._config = config

    def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        url = f"{_BASE_URL}/models/{self._config.text_model}:generateContent"
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
        aspectRatio = "9:16" if width < height else "16:9"
        url = f"{_BASE_URL}/models/{self._config.image_model}:generateContent"
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseModalities": ["IMAGE"],
                "imageConfig": {"aspectRatio": aspectRatio},
            }
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
        url = f"{_BASE_URL}/models/{self._config.tts_model}:generateContent"
        body = {
            "contents": [{"role": "user", "parts": [{"text": text}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {
                        "prebuiltVoiceConfig": {"voiceName": voice or self._config.tts_voice}
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
