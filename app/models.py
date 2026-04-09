from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


PROJECT_STATUSES = [
    "idea",
    "approved",
    "content_ready",
    "scenes_ready",
    "audio_ready",
    "images_ready",
    "clips_ready",
    "done",
    "failed",
]


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="idea")
    tags_json: Mapped[str] = mapped_column("tags", Text, nullable=False, default="[]")
    # "metadata" is reserved on DeclarativeBase; map to column named "metadata"
    meta_json: Mapped[str] = mapped_column(
        "metadata", Text, nullable=False, default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # ------------------------------------------------------------------ helpers

    def get_tags(self) -> list[str]:
        return json.loads(self.tags_json or "[]")

    def get_metadata(self) -> dict[str, Any]:
        return json.loads(self.meta_json or "{}")

    def set_tags(self, tags: list[str]) -> None:
        self.tags_json = json.dumps(tags)

    def set_metadata(self, meta: dict[str, Any]) -> None:
        self.meta_json = json.dumps(meta)

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "tags": self.get_tags(),
            "metadata": self.get_metadata(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
