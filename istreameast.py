#!/usr/bin/env python3

import sys
from pathlib import Path

# -------------------------------------------------
# HARD IMPORT FIX (GitHub Actions + Local + Module)
THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT = THIS_FILE.parent
PARENT_ROOT = PROJECT_ROOT.parent

for p in (PROJECT_ROOT, PARENT_ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from utils import Cache, Time, get_logger, leagues, network
# -------------------------------------------------

import base64
import re
from functools import partial
from datetime import datetime, timezone
from selectolax.parser import HTMLParser

log = get_logger(__name__)

TAG = "iSTRMEAST"
BASE_URL = "https://istreameast.app"

CACHE_FILE = Cache(f"{TAG.lower()}.json", exp=10_800)

urls: dict[str, dict[str, str | float]] = {}

# -------------------------------------------------
# Schedule-aware filtering
INCLUDE_LIVE = True
INCLUDE_UPCOMING_MINUTES = 180

# -------------------------------------------------
def is_event_active(time_text: str | None) -> bool:
    if not time_text:
        return True

    t = time_text.lower().strip()

    if INCLUDE_LIVE and any(x in t for x in ("live", "now", "in progress")):
        return True

    m = re.search(r"(\d+)\s+minute", t)
    if m:
        return int(m.group(1)) <= INCLUDE_UPCOMING_MINUTES

    if time_text.isdigit():
        try:
            event_ts = int(time_text)
            now = int(datetime.now(timezone.utc).timestamp())
            return event_ts >= now
        except Exception:
            return True

    return True


# -------------------------------------------------
async def process_event(url: str, url_num: int) -> str | None:
    if not (event_data := await network.request(url, log=log)):
        log.info(f"URL {url_num}) Failed to load page")
        return None

    soup = HTMLParser(event_data.content)

    iframe = soup.css_first("iframe#wp_player")
    if not iframe:
        log.warning(f"URL {url_num}) No iframe")
        return None

    iframe_src = iframe.attributes.get("src")
    if not iframe_src:
        return None

    iframe_data = await network.request(iframe_src, log=log)
    if not iframe_data:
        return None

    pattern = re.compile(
        r"source:\s*window\.atob\(\s*'([^']+)'\s*\)",
        re.IGNORECASE
    )

    m = pattern.search(iframe_data.text)
    if not m:
        log.warning(f"URL {url_num}) No encoded stream")
        return None

    log.info(f"URL {url_num}) Captured M3U8")
    return base64.b64decode(m[1]).decode("utf-8")


# -------------------------------------------------
async def get_events(cached_keys: list[str]) -> list[dict[str, str]]:
    events = []

    html_data = await network.request(BASE_URL, log=log)
    if not html_data:
        return events

    soup = HTMLParser(html_data.content)

    for link in soup.css("li.f1-podium--item > a.f1-podium--link"):
        li = link.parent

        rank = li.css_first(".f1-podium--rank")
        time_elem = li.css_first(".SaatZamanBilgisi")
        driver = li.css_first(".f1-podium--driver")

        if not rank or not time_elem or not driver:
            continue

        time_text = (
            time_elem.attributes.get("data-zaman")
            or time_elem.text(strip=True)
        )

        if not is_event_active(time_text):
            continue

        sport = rank.text(strip=True)

        event_name = driver.text(strip=True)
        if inner := driver.css_first("span.d-md-inline"):
            event_name = inner.text(strip=True)

        key = f"[{sport}] {event_name} ({TAG})"
        if key in cached_keys:
            continue

        href = link.attributes.get("href")
        if not href:
            continue

        events.append({
            "sport": sport,
            "event": event_name,
            "link": href,
        })

    return events


# -------------------------------------------------
async def scrape() -> None:
    cached_urls = CACHE_FILE.load()
    cached_count = len(cached_urls)

    urls.update(cached_urls)

    log.info(f"Loaded {cached_count} cached events")
    log.info(f'Scraping from "{BASE_URL}"')

    events = await get_events(list(cached_urls.keys()))
    log.info(f"Processing {len(events)} active events")

    if not events:
        log.info("No active events found")
        return

    now = Time.clean(Time.now()).timestamp()

    for i, ev in enumerate(events, start=1):
        handler = partial(process_event, ev["link"], i)

        url = await network.safe_process(
            handler,
            url_num=i,
            semaphore=network.HTTP_S,
            log=log,
        )

        if not url:
            continue

        sport, event, link = ev["sport"], ev["event"], ev["link"]
        key = f"[{sport}] {event} ({TAG})"

        tvg_id, logo = leagues.get_tvg_info(sport, event)

        urls[key] = cached_urls[key] = {
            "url": url,
            "logo": logo,
            "base": "https://gooz.aapmains.net",
            "timestamp": now,
            "id": tvg_id or "Live.Event.us",
            "link": link,
        }

    CACHE_FILE.write(cached_urls)

    new = len(cached_urls) - cached_count
    log.info(f"Collected {new} new events" if new else "No new events")


# -------------------------------------------------
if __name__ == "__main__":
    import asyncio

    log.info("🚀 Starting iStreamEast scraper...")
    asyncio.run(scrape())
