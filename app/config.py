from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import yaml


@dataclass
class DatabaseConfig:
    path: str = "./data/auto-streams.db"


@dataclass
class GeminiConfig:
    api_key: str = ""
    text_model: str = "gemini-2.0-flash"
    image_model: str = "gemini-3.1-flash-image-preview"
    tts_model: str = "gemini-2.5-flash-preview-tts"
    tts_voice: str = "Kore"


@dataclass
class OpenAIConfig:
    base_url: str = "http://localhost:11434/v1"
    api_key: str = "ollama"
    model: str = "llama3.2"


@dataclass
class ComfyWorkflows:
    image: str = "./assets/comfy-zimage.json"
    music: str = "./assets/comfy-music.json"


@dataclass
class ComfyConfig:
    base_url: str = "http://127.0.0.1:8188"
    workflows: ComfyWorkflows = field(default_factory=ComfyWorkflows)


@dataclass
class KittenTTSConfig:
    model: str = "KittenML/kitten-tts-nano-0.8"
    voice: str = "expr-voice-5-m"


@dataclass
class ProvidersConfig:
    text: str = "gemini"    # gemini | openai
    image: str = "comfy"    # gemini | comfy
    tts: str = "kittentts"  # gemini | kittentts
    music: str = "comfy"    # comfy
    tts_delay: float = 0.0  # seconds to wait between per-scene TTS calls
    tts_language: str = "en"  # BCP-47 language code for TTS alignment


@dataclass
class SubtitleStyle:
    font: str = "Arial"
    fontSize: int = 24
    color: str = "#FFFFFF"
    stroke: str = "#000000"


@dataclass
class VideoConfig:
    enableKenBurns: bool = True
    enableParticles: bool = False
    enableSubtitles: bool = False
    subtitleStyle: SubtitleStyle = field(default_factory=SubtitleStyle)
    whisper_model: str = "base"  # stable-ts model for script alignment (tiny/base/small/medium/large)
    scene_gap: float = 0.5  # seconds of silence appended to each scene's audio segment


@dataclass
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 8000


@dataclass
class YouTubeConfig:
    firefox_profile: str = ""       # absolute or relative path to a Firefox profile directory
    visibility: str = "unlisted"    # public | unlisted | private
    headless: bool = False          # Whether to run the browser in headless mode (no GUI). Set to true for server deployments.


@dataclass
class SchedulerConfig:
    enabled: bool = False
    upload_rendered_cron: str = "0 9 * * *"


@dataclass
class AppConfig:
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    temp_dir: str = "./temp"
    providers: ProvidersConfig = field(default_factory=ProvidersConfig)
    gemini: GeminiConfig = field(default_factory=GeminiConfig)
    openai: OpenAIConfig = field(default_factory=OpenAIConfig)
    comfy: ComfyConfig = field(default_factory=ComfyConfig)
    kittentts: KittenTTSConfig = field(default_factory=KittenTTSConfig)
    video: VideoConfig = field(default_factory=VideoConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    youtube: YouTubeConfig = field(default_factory=YouTubeConfig)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)


def _build_config(data: dict) -> AppConfig:
    cfg = AppConfig()

    if "database" in data:
        cfg.database = DatabaseConfig(**data["database"])

    if "temp_dir" in data:
        cfg.temp_dir = data["temp_dir"]

    if "providers" in data:
        cfg.providers = ProvidersConfig(**data["providers"])

    if "gemini" in data:
        cfg.gemini = GeminiConfig(**data["gemini"])

    if "openai" in data:
        cfg.openai = OpenAIConfig(**data["openai"])

    if "comfy" in data:
        d = data["comfy"]
        cfg.comfy = ComfyConfig(
            base_url=d.get("base_url", "http://127.0.0.1:8188"),
            workflows=ComfyWorkflows(**d.get("workflows", {})),
        )

    if "kittentts" in data:
        d = data["kittentts"]
        # Legacy configs may only have 'model' as a Piper voice name;
        # map that to 'voice' and keep the HF model name as default.
        if "model" in d and "voice" not in d:
            cfg.kittentts = KittenTTSConfig(voice=d["model"])
        else:
            cfg.kittentts = KittenTTSConfig(**d)

    if "video" in data:
        d = data["video"]
        cfg.video = VideoConfig(
            enableKenBurns=d.get("enableKenBurns", True),
            enableParticles=d.get("enableParticles", False),
            enableSubtitles=d.get("enableSubtitles", False),
            subtitleStyle=SubtitleStyle(**d.get("subtitleStyle", {})),
            whisper_model=d.get("whisper_model", "base"),
            scene_gap=d.get("scene_gap", 0.5),
        )

    if "server" in data:
        cfg.server = ServerConfig(**data["server"])

    if "youtube" in data:
        cfg.youtube = YouTubeConfig(**data["youtube"])

    if "scheduler" in data:
        cfg.scheduler = SchedulerConfig(**data["scheduler"])

    return cfg


_config: Optional[AppConfig] = None


def load_config(path: str = "config.yml") -> AppConfig:
    global _config
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    _config = _build_config(data)
    return _config


def get_config() -> AppConfig:
    global _config
    if _config is None:
        _config = load_config()
    return _config
