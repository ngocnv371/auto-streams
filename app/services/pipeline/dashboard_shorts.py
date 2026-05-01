from __future__ import annotations

import logging
import re
import time

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options

from app.config import get_config

log = logging.getLogger(__name__)


def _extract_channel_id(current_url: str) -> str:
    parts = [part for part in current_url.rstrip("/").split("/") if part]
    for index, part in enumerate(parts):
        if part == "channel" and index + 1 < len(parts):
            return parts[index + 1]
    return parts[-1]


def _normalize_short_url(href: str | None) -> str | None:
    if not href:
        return None
    if "/shorts/" in href:
        return href.split("?")[0]
    if "/video/" in href:
        # https://studio.youtube.com/video/qoSJNtGLBUY/edit
        # replace the '/edit'
        withoutEdit = href.split("/edit")[0]
        video_id = withoutEdit.rstrip("/").split("/")[-1]
        return f"https://www.youtube.com/shorts/{video_id}"
    return href.split("?")[0]


def _parse_views(raw_text: str) -> int:
    match = re.search(r"([\d,]+)", raw_text or "")
    if not match:
        return 0
    return int(match.group(1).replace(",", ""))

# --- Helper to build browser driver ---
def build_dashboard_driver():
    cfg = get_config()
    options = Options()
    profile_path = cfg.youtube.firefox_profile
    if profile_path:
        options.add_argument("-profile")
        options.add_argument(profile_path)
    options.headless = cfg.youtube.headless
    return webdriver.Firefox(options=options)

# --- Main function to fetch best performing shorts ---
def fetch_best_shorts(max_results: int = 50) -> list[dict[str, object]]:
    driver = build_dashboard_driver()
    try:
        log.info("Navigating to YouTube Studio Shorts page...")
        driver.get("https://studio.youtube.com")
        time.sleep(3)
        channel_id = _extract_channel_id(driver.current_url)
        driver.get(f"https://studio.youtube.com/channel/{channel_id}/videos/short")
        time.sleep(3)
        # Click on the View header once
        view_header = driver.find_element(By.ID, "views-header-name")
        view_header.click()
        time.sleep(3)

        # Fetch video metadata from the visible table
        video_rows = driver.find_elements(By.TAG_NAME, "ytcp-video-row")
        rows: list[dict[str, object]] = []
        for row in video_rows[:max_results]:
            titleCell = row.find_element(By.CSS_SELECTOR, "#video-title")
            title = titleCell.text or ""

            href = titleCell.get_attribute("href")
            href = _normalize_short_url(href)

            viewCell = row.find_element(By.CSS_SELECTOR, "#row-container .cell-body:nth-child(6)")
            views = _parse_views(viewCell.text)
            
            rows.append({"url": href, "title": title, "views": views})
        return rows
    finally:
        driver.quit()
