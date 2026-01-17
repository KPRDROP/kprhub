#!/usr/bin/env python3

import asyncio
import base64
import json
import os
import re
import time
from urllib.parse import quote_plus

import aiohttp
from selectolax.parser import HTMLParser

# ================= CONFIG =================

BASE_URL = "https://istreameast.app"
OUTPUT_FILE = "istreameast.m3u"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:146.0) "
    "Gecko/20100101 Firefox/146.0"
)

ENCODED_UA = quote_plus(f"Agent={USER_AGENT}")

REFERER = "https://gooz.aapmains.net/"
ORIGIN = "https://gooz.aapmains.net"

TVG_ID = "Live.Event.us"
TAG = "iSTRMEAST"

CACHE_FILE = "istreameast_cache.json"
CACHE_EXP = 3 * 60 * 60  # 3 hours

DEFAULT_LOGO = "https://i.gyazo.com/4a5e9fa2525808ee4b65002b56d3450e.png"

# ================= HELPERS =================

def log(msg):
    print(msg, flush=True)


def load_cache():
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_cache(data):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


async def fetch(session, url):
    try:
        async with session.get(url, timeout=20) as r:
            if r.status == 200:
                return await r.text()
    except Exception:
        pass
    return None


# ================= SCRAPER =================

async def extract_stream(session, event_url):
    html = await fetch(session, event_url)
    if not html:
        return None

    soup = HTMLParser(html)

    iframe = soup.css_first("iframe")
    if not iframe:
        return None

    iframe_src = iframe.attributes.get("src")
    if not iframe_src:
        return None

    iframe_html = await fetch(session, iframe_src)
    if not iframe_html:
        return None

    m = re.search(r"window\.atob\(['\"]([^'\"]+)['\"]\)", iframe_html)
    if not m:
        return None

    try:
        decoded = base64.b64decode(m.group(1)).decode("utf-8")
        return decoded
    except Exception:
        return None


async def get_events(session):
    html = await fetch(session, BASE_URL)
    if not html:
        return []

    soup = HTMLParser(html)
    events = []

    for link in soup.css("li.f1-podium--item a.f1-podium--link"):
        href = link.attributes.get("href")
        if not href:
            continue

        li = link.parent

        sport_el = li.css_first(".f1-podium--rank")
        title_el = li.css_first("span.d-md-inline")

        if not sport_el or not title_el:
            continue

        sport = sport_el.text(strip=True)
        title = title_el.text(strip=True)

        events.append({
            "sport": sport,
            "title": title,
            "url": href
        })

    return events


# ================= MAIN =================

async def main():
    log("🚀 Starting iStreamEast scraper...")

    cache = load_cache()
    now = int(time.time())

    headers = {"User-Agent": USER_AGENT}

    async with aiohttp.ClientSession(headers=headers) as session:
        events = await get_events(session)
        log(f"📌 Found {len(events)} events")

        entries = []

        for i, ev in enumerate(events, 1):
            key = f"[{ev['sport']}] {ev['title']} ({TAG})"

            if key in cache and now - cache[key]["ts"] < CACHE_EXP:
                entries.append(cache[key]["entry"])
                continue

            log(f"🔎 [{i}/{len(events)}] {key}")

            stream = await extract_stream(session, ev["url"])
            if not stream:
                log("  ⚠️ No stream found")
                continue

            log(f"  ✅ STREAM FOUND: {stream}")

            entry = {
                "name": key,
                "url": stream,
                "logo": DEFAULT_LOGO,
            }

            cache[key] = {
                "ts": now,
                "entry": entry
            }

            entries.append(entry)

    if not entries:
        log("❌ No streams collected")
        return

    # ================= WRITE M3U =================

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for e in entries:
            f.write(
                f'#EXTINF:-1 tvg-id="{TVG_ID}" '
                f'tvg-name="{e["name"]}" '
                f'tvg-logo="{e["logo"]}" '
                f'group-title="Live Events",{e["name"]}\n'
            )
            f.write(
                f'{e["url"]}'
                f'|referer={REFERER}'
                f'|origin={ORIGIN}'
                f'|user-agent={ENCODED_UA}\n'
            )

    save_cache(cache)
    log("✅ istreameast.m3u saved")


if __name__ == "__main__":
    asyncio.run(main())
