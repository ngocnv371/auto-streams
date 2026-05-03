from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select

from app.config import SchedulerConfig
from app.database import get_session_factory
from app.models import Project
from app.services.pipeline.upload import run_upload_stage

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class _CronField:
    values: set[int]

    def matches(self, value: int) -> bool:
        return value in self.values


@dataclass(frozen=True)
class _CronSchedule:
    minute: _CronField
    hour: _CronField
    day: _CronField
    month: _CronField
    weekday: _CronField

    @classmethod
    def parse(cls, expr: str) -> "_CronSchedule":
        parts = expr.split()
        if len(parts) != 5:
            raise ValueError("Cron expression must have exactly 5 fields: minute hour day month weekday")
        minute, hour, day, month, weekday = parts
        return cls(
            minute=_CronField(_expand_field(minute, 0, 59)),
            hour=_CronField(_expand_field(hour, 0, 23)),
            day=_CronField(_expand_field(day, 1, 31)),
            month=_CronField(_expand_field(month, 1, 12)),
            weekday=_CronField(_expand_field(weekday, 0, 7, normalize_weekday=True)),
        )

    def matches(self, dt: datetime) -> bool:
        weekday = (dt.weekday() + 1) % 7
        return (
            self.minute.matches(dt.minute)
            and self.hour.matches(dt.hour)
            and self.day.matches(dt.day)
            and self.month.matches(dt.month)
            and self.weekday.matches(weekday)
        )


def _expand_field(token: str, minimum: int, maximum: int, normalize_weekday: bool = False) -> set[int]:
    values: set[int] = set()
    for part in token.split(","):
        part = part.strip()
        if not part:
            raise ValueError("Empty cron field segment")

        step = 1
        base = part
        if "/" in part:
            base, step_text = part.split("/", 1)
            step = int(step_text)
            if step <= 0:
                raise ValueError("Cron step must be greater than zero")

        if base == "*":
            start, end = minimum, maximum
        elif "-" in base:
            start_text, end_text = base.split("-", 1)
            start, end = int(start_text), int(end_text)
        else:
            start = end = int(base)

        if normalize_weekday:
            if start == 7:
                start = 0
            if end == 7:
                end = 0

        if start < minimum or start > maximum or end < minimum or end > maximum:
            raise ValueError(f"Cron value out of range: {part}")
        if end < start:
            raise ValueError(f"Cron range must be ascending: {part}")

        values.update(range(start, end + 1, step))

    return values


def get_next_run_times(cron_expr: str, count: int = 3, from_time: datetime | None = None) -> list[datetime]:
    if count <= 0:
        return []

    schedule = _CronSchedule.parse(cron_expr)
    cursor = (from_time or datetime.now()).replace(second=0, microsecond=0) + timedelta(minutes=1)
    found: list[datetime] = []

    max_minutes_search = 366 * 24 * 60
    for _ in range(max_minutes_search):
        if schedule.matches(cursor):
            found.append(cursor)
            if len(found) >= count:
                break
        cursor += timedelta(minutes=1)

    return found


class UploadScheduler:
    def __init__(self, config: SchedulerConfig) -> None:
        self._config = config
        self._schedule: _CronSchedule | None = None
        self._loop_task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._upload_task: asyncio.Task[None] | None = None
        self._last_tick: tuple[int, int, int, int, int] | None = None

    async def start(self) -> None:
        if not self._config.enabled:
            log.info("upload scheduler disabled")
            return

        self._schedule = _CronSchedule.parse(self._config.upload_rendered_cron)
        self._stop_event.clear()
        self._loop_task = asyncio.create_task(self._run_loop(), name="upload-scheduler")
        log.info("upload scheduler started cron=%s", self._config.upload_rendered_cron)

    async def stop(self) -> None:
        self._stop_event.set()

        if self._loop_task is not None:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
            self._loop_task = None

        if self._upload_task is not None:
            try:
                await self._upload_task
            finally:
                self._upload_task = None

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            now = datetime.now().replace(second=0, microsecond=0)
            tick = (now.year, now.month, now.day, now.hour, now.minute)

            if tick != self._last_tick and self._schedule is not None and self._schedule.matches(now):
                self._last_tick = tick
                await self._trigger_upload()

            next_minute = now + timedelta(minutes=1)
            sleep_for = max((next_minute - datetime.now()).total_seconds(), 1.0)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=sleep_for)
            except asyncio.TimeoutError:
                continue

    async def _trigger_upload(self) -> None:
        if self._upload_task is not None and not self._upload_task.done():
            log.info("upload scheduler skipped; previous scheduled upload still running")
            return

        project_id = await self._pick_random_rendered_project_id()
        if project_id is None:
            log.info("upload scheduler found no rendered projects to upload")
            return

        log.info("upload scheduler picked project=%s", project_id)
        self._upload_task = asyncio.create_task(run_upload_stage(project_id), name=f"scheduled-upload-{project_id}")

    async def _pick_random_rendered_project_id(self) -> str | None:
        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(
                select(Project.id)
                .where(Project.status == "rendered")
                .order_by(func.random())
                .limit(1)
            )
            return result.scalar_one_or_none()