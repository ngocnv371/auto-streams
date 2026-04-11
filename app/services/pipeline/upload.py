"""Stage 5 — upload  (done → uploaded)."""
from __future__ import annotations

import asyncio
import logging
import os
import time

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.firefox.options import Options

from app.config import get_config
from app.database import get_session_factory
from app.models import Project

from ._helpers import _elapsed, _fail_project, _load_project

log = logging.getLogger(__name__)

# ── YouTube Studio element selectors ────────────────────────────────────────

_TEXTBOX_ID = "textbox"
_MADE_FOR_KIDS_NAME = "VIDEO_MADE_FOR_KIDS_MFK"
_NOT_FOR_KIDS_NAME = "VIDEO_MADE_FOR_KIDS_NOT_MFK"
_NEXT_BUTTON_ID = "next-button"
_DONE_BUTTON_ID = "done-button"
_RADIO_BUTTON_XPATH = "//tp-yt-paper-radio-button"

# Visibility radio button indices on the YouTube Studio publish screen
_VISIBILITY_INDEX: dict[str, int] = {
    "public": 0,
    "private": 1,
    "unlisted": 2,
}


# ── Browser helpers ──────────────────────────────────────────────────────────

def _build_driver(profile_path: str) -> webdriver.Firefox:
    """Return a Firefox WebDriver, optionally using a pre-logged-in profile."""
    options = Options()
    if profile_path:
        options.add_argument("-profile")
        options.add_argument(os.path.abspath(profile_path))
    return webdriver.Firefox(options=options)


# ── Core upload logic (blocking — run in thread) ─────────────────────────────

def _do_upload(video_path: str, title: str, description: str, visibility: str) -> str:
    """
    Upload *video_path* to YouTube Shorts and return the public video URL.

    Raises on failure so the async wrapper can mark the project as failed.
    """
    cfg = get_config()
    profile_path: str = cfg.youtube.firefox_profile

    driver = _build_driver(profile_path)
    try:
        # ── Resolve channel ID ───────────────────────────────────────
        log.info("upload: navigating to YouTube Studio")
        driver.get("https://studio.youtube.com")
        time.sleep(3)
        channel_id = driver.current_url.rstrip("/").split("/")[-1]
        log.info("upload: channel_id=%s", channel_id)

        # ── Start upload ─────────────────────────────────────────────
        driver.get("https://www.youtube.com/upload")
        time.sleep(3)

        file_picker = driver.find_element(By.TAG_NAME, "ytcp-uploads-file-picker")
        file_input = file_picker.find_element(By.TAG_NAME, "input")
        file_input.send_keys(os.path.abspath(video_path))
        log.info("upload: file path sent, waiting for dialog")
        time.sleep(5)

        # ── Title ────────────────────────────────────────────────────
        textboxes = driver.find_elements(By.ID, _TEXTBOX_ID)
        title_el = textboxes[0]
        title_el.click()
        time.sleep(0.5)
        title_el.send_keys(Keys.CONTROL + "a")
        title_el.send_keys(title)
        log.info("upload: title set to %r", title)

        # ── Description ──────────────────────────────────────────────
        # Re-fetch textboxes after interaction; description is last element
        time.sleep(10)
        textboxes = driver.find_elements(By.ID, _TEXTBOX_ID)
        description_el = textboxes[-1]
        description_el.click()
        time.sleep(0.5)
        description_el.clear()
        description_el.send_keys(description)
        log.info("upload: description set (%d chars)", len(description))

        time.sleep(0.5)

        # ── Made for kids ────────────────────────────────────────────
        is_not_for_kids = driver.find_element(By.NAME, _NOT_FOR_KIDS_NAME)
        is_not_for_kids.click()
        time.sleep(0.5)

        # ── Click Next × 3 ───────────────────────────────────────────
        for step in range(1, 4):
            log.info("upload: next button click %d/3", step)
            next_button = driver.find_element(By.ID, _NEXT_BUTTON_ID)
            next_button.click()
            time.sleep(2)

        # ── Set visibility ───────────────────────────────────────────
        vis_index = _VISIBILITY_INDEX.get(visibility, _VISIBILITY_INDEX["unlisted"])
        log.info("upload: setting visibility=%s (index %d)", visibility, vis_index)
        radio_buttons = driver.find_elements(By.XPATH, _RADIO_BUTTON_XPATH)
        radio_buttons[vis_index].click()
        time.sleep(0.5)

        # ── Done ─────────────────────────────────────────────────────
        log.info("upload: clicking done")
        done_button = driver.find_element(By.ID, _DONE_BUTTON_ID)
        done_button.click()
        time.sleep(3)

        # ── Retrieve video URL ────────────────────────────────────────
        driver.get(
            f"https://studio.youtube.com/channel/{channel_id}/videos/short"
        )
        time.sleep(3)
        videos = driver.find_elements(By.TAG_NAME, "ytcp-video-row")
        first_video = videos[0]
        anchor = first_video.find_element(By.TAG_NAME, "a")
        href = anchor.get_attribute("href")
        log.info("upload: latest short href=%s", href)
        video_id = href.split("/")[-2]
        url = f"https://www.youtube.com/shorts/{video_id}"
        log.info("upload: video_url=%s", url)
        return url

    finally:
        driver.quit()


# ── Stage entry point ────────────────────────────────────────────────────────

async def run_upload_stage(project_id: str) -> None:
    """Upload the final rendered video to YouTube Shorts.  done → uploaded."""
    log.info("upload_stage start project=%s", project_id)
    try:
        project = await _load_project(project_id)
        if project is None or project.status != "done":
            log.warning(
                "upload_stage: project %s not in 'done' status (status=%s)",
                project_id, project.status if project else "not found",
            )
            return

        meta = project.get_metadata()
        video_path: str = meta.get("video_path", "")
        if not video_path:
            raise ValueError("video_path missing from project metadata")

        title: str = project.title
        description: str = meta.get("summary", "")
        cfg = get_config()
        visibility: str = cfg.youtube.visibility

        log.info(
            "upload_stage: video=%s  title=%r  visibility=%s",
            video_path, title, visibility,
        )

        t0 = time.monotonic()
        url = await asyncio.to_thread(_do_upload, video_path, title, description, visibility)
        log.info("upload_stage: upload done  elapsed=%s  url=%s", _elapsed(t0), url)

        factory = get_session_factory()
        async with factory() as session:
            p = await session.get(Project, project_id)
            m = p.get_metadata()
            m["youtube_url"] = url
            p.set_metadata(m)
            p.status = "uploaded"
            p.touch()
            await session.commit()

        log.info("upload_stage done project=%s url=%s", project_id, url)

    except Exception:
        log.exception("upload_stage failed project=%s", project_id)
        await _fail_project(project_id, "upload_stage failed — see server logs")
