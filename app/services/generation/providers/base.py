from __future__ import annotations

from abc import ABC, abstractmethod


class TextProvider(ABC):
    """Generates text from a prompt using an LLM."""

    @abstractmethod
    def generate(self, prompt: str, system_prompt: str | None = None) -> str: ...


class ImageProvider(ABC):
    """Generates an image and returns raw bytes (PNG/JPEG)."""

    @abstractmethod
    def generate(self, prompt: str, width: int, height: int) -> bytes: ...


class TTSProvider(ABC):
    """Synthesises speech and returns raw WAV bytes."""

    @abstractmethod
    def synthesize(self, text: str, narrator: str | None = None, voice: str | None = None, speed: float = 1.0) -> bytes: ...


class MusicProvider(ABC):
    """Generates background music and returns raw audio bytes."""

    @abstractmethod
    def generate(self, prompt: str, duration: int = 60) -> bytes: ...
