from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, field_validator

from app.models import PROJECT_STATUSES


class TopicCreate(BaseModel):
    topic: str


class TopicOut(BaseModel):
    id: str
    topic: str
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ProjectCreate(BaseModel):
    topic_id: str
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
    topic_id: str
    title: str
    status: str
    tags: list[str]
    metadata: dict[str, Any]
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class GenerateIdeasRequest(BaseModel):
    topic_id: str
    count: int = 5


class DashboardOut(BaseModel):
    status_counts: dict[str, int]
    queue_counts: dict[str, int]
    total: int
    scheduler: "DashboardSchedulerOut"


class DashboardSchedulerOut(BaseModel):
    enabled: bool
    upload_rendered_cron: str
    next_runs: list[str]
    parse_error: str | None = None


class BestShortsOut(BaseModel):
    url: str
    title: str
    views: int
    project_id: str | None = None
    status: str | None = None
    created_at: Optional[datetime] = None
    # Add more fields as needed


class BestShortsTableOut(BaseModel):
    shorts: list[BestShortsOut]


class BestShortsAnalyzeItem(BaseModel):
    title: str
    views: int


class BestShortsAnalyzeRequest(BaseModel):
    shorts: list[BestShortsAnalyzeItem]


class BestShortsAnalyzeOut(BaseModel):
    analysis: str
