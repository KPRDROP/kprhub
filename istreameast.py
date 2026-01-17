#!/usr/bin/env python3
import asyncio
import aiohttp
import json
import re
import sys
import time
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import quote_plus

from selectolax.parser import HTMLParser

# --------------------------------------------------
# CONFIG
TAG = "iSTRMEAST"
BASE_URL = "https://istreameast.app"
OUTPUT_FILE = "istreameast.m3u"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:146.0) "
    "Gecko/20100101 Firefox/146.0"
)

REFERER = "https://gooz.aapmains.net/"
ORIGIN = "https://gooz.aapmains.net"

CACHE_FILE = Path("istreameast_cache.json")
CACHE_EXP = 10800  # 3 hours

INCLUDE_LIVE = True
INCLUDE_UPCOMING_MINUTES = 180
# --------------------------------------------------


def log(*a):
    print(*a)
    sys.stdout.flush()


# --------------------------------------------------
# SIMPLE CACHE
def load_cache():
    if not CACHE_FILE.exists():
        return {}
    try:
        with CACHE_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        now = int(time.time())
        return {
            k: v for k, v in data.items()
            if now - v.get("timestamp", 0) < CACHE_EXP
        }
    except Exception:
        return {}


def save_cache(data):
    with CACHE_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# --------------------------------------------------
def is_event_active(time_text: str) -> bool:
    if not time_text:
        return True

    t = time_text.lower()

    if INCLUDE_LIVE and any(x in t for x in ("live", "now", "progress")):
        return True

    m = re.search(r"(\d+)\s+minute", t)
    if m:
        return int(m.group(1)) <= INCLUDE_UPCOMING_MINUTES

    if time_text.isdigit():
        try:
            return int(time_text) >= int(time.time())
        except Exception:
            pass

    return True


# --------------------------------------------------
async def fetch(session, url):
    try:
        async with session.get(url, timeout=20) as r:
            if r.status != 200:
                return None
            return await r.text()
    except Exception:
        return None


# --------------------------------------------------
async def extract_m3u8(session, url, idx):
    html = await fetch(session, url)
    if not html:
        return None

    soup = HTMLParser(html)
    iframe = soup.css_first("iframe#wp_player")
    if not iframe:
        return None

    iframe_src = iframe.attributes.get("src")
    if not iframe_src:
        return None

    iframe_html = await fetch(session, iframe_src)
    if not iframe_html:
        return None

    m = re.search(
        r"source:\s*window\.atob\(\s*'([^']+)'\s*\)",
        iframe_html,
        re.I,
    )

    if not m:
        return None

    log(f"URL {idx}) Captured M3U8")
    return (
        __import__("base64")
        .b64decode(m.group(1))
        .decode("utf-8", "ignore")
    )


# --------------------------------------------------
async def scrape():
    log("🚀 Starting iStreamEast scraper...")

    cache = load_cache()
    collected = dict(cache)

    async with aiohttp.ClientSession(
        headers={"User-Agent": USER_AGENT}
    ) as session:

        homepage = await fetch(session, BASE_URL)
        if not homepage:
            log("❌ Failed to load homepage")
            return

        soup = HTMLParser(homepage)

        events = []
        for link in soup.css("li.f1-podium--item > a.f1-podium--link"):
            li = link.parent

            sport_el = li.css_first(".f1-podium--rank")
            time_el = li.css_first(".SaatZamanBilgisi")
            name_el = li.css_first(".f1-podium--driver")

            if not sport_el or not time_el or not name_el:
                continue

            time_text = (
                time_el.attributes.get("data-zaman")
                or time_el.text(strip=True)
            )

            if not is_event_active(time_text):
                continue

            sport = sport_el.text(strip=True)
            event = name_el.text(strip=True)

            if inner := name_el.css_first("span.d-md-inline"):
                event = inner.text(strip=True)

            key = f"[{sport}] {event} ({TAG})"
            if key in collected:
                continue

            href = link.attributes.get("href")
            if not href:
                continue

            events.append((key, sport, event, href))

        log(f"Processing {len(events)} event(s)")

        for i, (key, sport, event, link) in enumerate(events, 1):
            url = await extract_m3u8(session, link, i)
            if not url:
                continue

            collected[key] = {
                "url": url,
                "timestamp": int(time.time()),
                "sport": sport,
                "event": event,
            }

    save_cache(collected)

    if not collected:
        log("❌ No streams captured")
        return

    write_playlist(collected)
    log("✅ Done")


# --------------------------------------------------
def write_playlist(entries):
    ua = quote_plus(USER_AGENT)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")

        for key, e in entries.items():
            title = f"[{e['sport']}] {e['event']} ({TAG})"
            f.write(
                f'#EXTINF:-1 tvg-id="Live.Event.us" '
                f'tvg-name="{title}" '
                f'group-title="Live Events",{title}\n'
            )
            f.write(
                f"{e['url']}|referer={REFERER}"
                f"|origin={ORIGIN}"
                f"|user-agent={ua}\n"
            )


# --------------------------------------------------
if __name__ == "__main__":
    asyncio.run(scrape())
