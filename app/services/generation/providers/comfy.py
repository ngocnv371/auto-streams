from __future__ import annotations

import json
import random
import time

import requests

from app.config import ComfyConfig
from .base import ImageProvider, MusicProvider

_POLL_INTERVAL = 2.0   # seconds between history polls
_POLL_TIMEOUT = 600    # max seconds to wait per job


class _ComfyClient:
    """Thin wrapper around the ComfyUI HTTP API."""

    def __init__(self, base_url: str) -> None:
        self._base = base_url.rstrip("/")

    def queue_prompt(self, workflow: dict) -> str:
        resp = requests.post(
            f"{self._base}/prompt",
            json={"prompt": workflow, "client_id": "auto-streams"},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["prompt_id"]

    def get_history(self, prompt_id: str) -> dict:
        resp = requests.get(f"{self._base}/history/{prompt_id}", timeout=30)
        resp.raise_for_status()
        return resp.json()

    def download(self, filename: str, subfolder: str, file_type: str = "output") -> bytes:
        resp = requests.get(
            f"{self._base}/view",
            params={"filename": filename, "subfolder": subfolder, "type": file_type},
            timeout=120,
        )
        resp.raise_for_status()
        return resp.content

    def wait_for_result(self, prompt_id: str) -> dict:
        """Block until the workflow completes and return the outputs dict."""
        deadline = time.monotonic() + _POLL_TIMEOUT
        while time.monotonic() < deadline:
            history = self.get_history(prompt_id)
            if prompt_id in history:
                entry = history[prompt_id]
                status = entry.get("status", {})
                if status.get("completed"):
                    return entry["outputs"]
                if status.get("status_str") == "error":
                    raise RuntimeError(f"ComfyUI workflow failed: {status}")
            time.sleep(_POLL_INTERVAL)
        raise TimeoutError(
            f"ComfyUI workflow {prompt_id!r} did not complete within {_POLL_TIMEOUT}s"
        )


def _load_workflow(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _apply_placeholders(workflow: dict, replacements: dict[str, str]) -> dict:
    """String-replace __PLACEHOLDER__ tokens in the serialised workflow."""
    text = json.dumps(workflow)
    for token, value in replacements.items():
        text = text.replace(token, value)
    return json.loads(text)


def _randomise_seeds(workflow: dict) -> None:
    """Randomise any fixed 'seed' values so each run is unique."""
    for node in workflow.values():
        if isinstance(node, dict) and "seed" in node.get("inputs", {}):
            node["inputs"]["seed"] = random.randint(0, 2**32 - 1)


class ComfyImageProvider(ImageProvider):
    def __init__(self, config: ComfyConfig) -> None:
        self._config = config
        self._client = _ComfyClient(config.base_url)

    def generate(self, prompt: str, width: int, height: int) -> bytes:
        workflow = _load_workflow(self._config.workflows.image)
        workflow = _apply_placeholders(workflow, {
            "__PROMPT__": prompt,
            "__WIDTH__": str(width),
            "__HEIGHT__": str(height),
        })
        _randomise_seeds(workflow)

        prompt_id = self._client.queue_prompt(workflow)
        outputs = self._client.wait_for_result(prompt_id)

        for node_output in outputs.values():
            if "images" in node_output:
                img = node_output["images"][0]
                return self._client.download(img["filename"], img.get("subfolder", ""))

        raise RuntimeError("ComfyUI image workflow produced no image output")


class ComfyMusicProvider(MusicProvider):
    def __init__(self, config: ComfyConfig) -> None:
        self._config = config
        self._client = _ComfyClient(config.base_url)

    def generate(self, prompt: str, duration: int = 60) -> bytes:
        workflow = _load_workflow(self._config.workflows.music)
        workflow = _apply_placeholders(workflow, {
            "__PROMPT__": prompt,
            "__DURATION__": str(duration),
        })
        _randomise_seeds(workflow)

        prompt_id = self._client.queue_prompt(workflow)
        outputs = self._client.wait_for_result(prompt_id)

        for node_output in outputs.values():
            if "audio" in node_output:
                aud = node_output["audio"][0]
                return self._client.download(aud["filename"], aud.get("subfolder", ""))

        raise RuntimeError("ComfyUI music workflow produced no audio output")
