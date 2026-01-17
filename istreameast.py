#!/usr/bin/env python3

import base64
import re
from functools import partial
from datetime import datetime, timezone

from selectolax.parser import HTMLParser

# -------------------------------------------------
# SAFE IMPORT FIX (CI + LOCAL)
try:
    from utils import Cache, Time, get_logger, leagues, network
except ModuleNotFoundError:
    import sys
    from pathlib import Path

    ROOT = Path(__file__).resolve().parent
    sys.path.insert(0, str(ROOT))

    from utils import Cache, Time, get_logger, leagues, network

# -------------------------------------------------
log = get_logger(__name__)

TAG = "iSTRMEAST"
BASE_URL = "https://istreameast.app"

CACHE_FILE = Cache(f"{TAG.lower()}.json", exp=10_800)

urls: dict[str, dict[str, str | float]] = {}

# -------------------------------------------------
# Schedule filtering
INCLUDE_LIVE = True
INCLUDE_UPCOMING_MINUTES = 180

# -------------------------------------------------
def is_event_active(time_text: str | None) -> bool:
    if not time_text:
        return True

    t = time_text.lower().strip()

    if INCLUDE_LIVE and any(k in t for k in ("live", "now", "in progress")):
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
        log.info(f"URL {url_num}) Failed to load url.")
        return None

    soup = HTMLParser(event_data.content)

    iframe = soup.css_first("iframe#wp_player")
    if not iframe:
        log.warning(f"URL {url_num}) No iframe found.")
        return None

    iframe_src = iframe.attributes.get("src")
    if not iframe_src:
        log.warning(f"URL {url_num}) No iframe src.")
        return None

    iframe_data = await network.request(iframe_src, log=log)
    if not iframe_data:
        log.info(f"URL {url_num}) Failed to load iframe.")
        return None

    pattern = re.compile(
        r"source:\s*window\.atob\(\s*'([^']+)'\s*\)",
        re.IGNORECASE
    )

    match = pattern.search(iframe_data.text)
    if not match:
        log.warning(f"URL {url_num}) No encoded stream found.")
        return None

    log.info(f"URL {url_num}) Captured M3U8")
    return base64.b64decode(match[1]).decode("utf-8")


# -------------------------------------------------
async def get_events(cached_keys: list[str]) -> list[dict[str, str]]:
    events = []

    html_data = await network.request(BASE_URL, log=log)
    if not html_data:
        return events

    soup = HTMLParser(html_data.content)

    for link in soup.css("li.f1-podium--item > a.f1-podium--link"):
        li_item = link.parent

        rank_elem = li_item.css_first(".f1-podium--rank")
        time_elem = li_item.css_first(".SaatZamanBilgisi")

        if not rank_elem or not time_elem:
            continue

        time_text = (
            time_elem.attributes.get("data-zaman")
            or time_elem.text(strip=True)
        )

        if not is_event_active(time_text):
            continue

        sport = rank_elem.text(strip=True)

        driver_elem = li_item.css_first(".f1-podium--driver")
        if not driver_elem:
            continue

        event_name = driver_elem.text(strip=True)
        if inner := driver_elem.css_first("span.d-md-inline"):
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

    log.info(f"Loaded {cached_count} cached event(s)")
    log.info(f'Scraping from "{BASE_URL}"')

    events = await get_events(list(cached_urls.keys()))
    log.info(f"Processing {len(events)} active event(s)")

    if not events:
        log.info("No active events found")
        return

    now = Time.clean(Time.now()).timestamp()

    for i, ev in enumerate(events, start=1):
        handler = partial(
            process_event,
            url=ev["link"],
            url_num=i,
        )

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

    new_count = len(cached_urls) - cached_count
    log.info(f"Collected {new_count} new event(s)" if new_count else "No new events")

    CACHE_FILE.write(cached_urls)


# -------------------------------------------------
if __name__ == "__main__":
    import asyncio

    log.info("🚀 Starting iStreamEast scraper...")
    asyncio.run(scrape())
