from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import Project, Topic
from app.schemas import TopicCreate, TopicOut

router = APIRouter()

Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("", response_model=list[TopicOut])
async def list_topics(session: Session):
    result = await session.execute(select(Topic).order_by(Topic.created_at.asc()))
    return [t.to_dict() for t in result.scalars().all()]


@router.post("", response_model=TopicOut, status_code=201)
async def create_topic(body: TopicCreate, session: Session):
    topic_text = body.topic.strip()
    if not topic_text:
        raise HTTPException(400, "topic cannot be empty")
    existing = await session.execute(select(Topic).where(Topic.topic == topic_text))
    if existing.scalar_one_or_none():
        raise HTTPException(409, "Topic already exists")
    topic = Topic(
        id=str(uuid.uuid4()),
        topic=topic_text,
        created_at=datetime.now(timezone.utc),
    )
    session.add(topic)
    await session.commit()
    await session.refresh(topic)
    return topic.to_dict()


@router.delete("/{topic_id}", status_code=204)
async def delete_topic(topic_id: str, session: Session):
    result = await session.execute(select(Topic).where(Topic.id == topic_id))
    topic = result.scalar_one_or_none()
    if not topic:
        raise HTTPException(404, "Topic not found")
    count = (
        await session.execute(
            select(func.count()).select_from(Project).where(Project.topic_id == topic_id)
        )
    ).scalar()
    if count:
        raise HTTPException(409, f"Cannot delete: {count} project(s) belong to this topic")
    await session.delete(topic)
    await session.commit()
