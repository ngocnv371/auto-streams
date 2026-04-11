"""Simple in-memory SSE event bus for real-time UI feedback."""
from __future__ import annotations

import asyncio
import json
import time

_subscribers: list[asyncio.Queue] = []
_active_count: int = 0


def emit(event_type: str, **data) -> None:
    """Broadcast an event to all connected SSE clients (fire-and-forget)."""
    payload = json.dumps({"type": event_type, "ts": time.time(), **data})
    dead: list[asyncio.Queue] = []
    for q in _subscribers:
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        try:
            _subscribers.remove(q)
        except ValueError:
            pass


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    _subscribers.append(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    try:
        _subscribers.remove(q)
    except ValueError:
        pass


def inc_active() -> None:
    global _active_count
    _active_count += 1
    emit("status", active=_active_count)


def dec_active() -> None:
    global _active_count
    _active_count = max(0, _active_count - 1)
    emit("status", active=_active_count)
