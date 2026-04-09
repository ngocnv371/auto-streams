from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, field_validator

from app.models import PROJECT_STATUSES


class ProjectCreate(BaseModel):
    title: str
    tags: list[str] = []
    metadata: dict[str, Any] = {}


class ProjectUpdate(BaseModel):
    title: Optional[str] = None
    tags: Optional[list[str]] = None
    metadata: Optional[dict[str, Any]] = None


class ProjectStatusUpdate(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in PROJECT_STATUSES:
            raise ValueError(f"status must be one of {PROJECT_STATUSES}")
        return v


class ProjectOut(BaseModel):
    id: str
    title: str
    status: str
    tags: list[str]
    metadata: dict[str, Any]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    model_config = {"from_attributes": True}


class DashboardOut(BaseModel):
    status_counts: dict[str, int]
    queue_counts: dict[str, int]
    total: int
