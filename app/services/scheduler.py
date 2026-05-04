from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from croniter import croniter
from sqlalchemy import func, select

from app.config import SchedulerConfig
from app.database import get_session_factory
from app.models import Project
from app.services.pipeline.upload import run_upload_stage

log = logging.getLogger(__name__)


def get_next_run_times(cron_expr: str, count: int = 3, from_time: datetime | None = None) -> list[datetime]:
    """Get the next N scheduled run times for a cron expression."""
    if count <= 0:
        return []

    base_time = from_time or datetime.now()
    cron = croniter(cron_expr, base_time)
    return [cron.get_next(datetime) for _ in range(count)]


class UploadScheduler:
    def __init__(self, config: SchedulerConfig) -> None:
        self._config = config
        self._cron: croniter | None = None
        self._loop_task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._upload_task: asyncio.Task[None] | None = None
        self._last_triggered_minute: datetime | None = None

    async def start(self) -> None:
        if not self._config.enabled:
            log.info("upload scheduler disabled")
            return

        self._cron = croniter(self._config.upload_rendered_cron, datetime.now())
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
            now = datetime.now()
            
            if self._cron is not None:
                next_run = self._cron.get_next(datetime)
                log.info("UploadScheduler loop tick at %s", now.isoformat())
                log.info("Next scheduled upload at %s", next_run.isoformat())
                # Check if current minute matches the schedule
                if now < next_run and now + timedelta(minutes=1) > next_run:
                    if self._last_triggered_minute != next_run:
                        self._last_triggered_minute = next_run
                        await self._trigger_upload()
                    # Reset the cron iterator to ensure proper future calculations
                    self._cron = croniter(self._config.upload_rendered_cron, now)

            next_minute = now + timedelta(minutes=1)
            sleep_for = max((next_minute - datetime.now()).total_seconds(), 1.0)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=sleep_for)
            except asyncio.TimeoutError:
                continue

    async def _trigger_upload(self) -> None:
        log.info("upload scheduler triggered at %s", datetime.now().isoformat())
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