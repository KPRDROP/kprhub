#!/usr/bin/env python3
import asyncio
import base64
import json
import os
import re
import time
from urllib.parse import quote_plus, urljoin

import aiohttp
from selectolax.parser import HTMLParser

# ================= CONFIG =================

BASE_URL = "https://thetvapp.plus/"
OUTPUT_FILE = "apptv.m3u8"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:146.0) "
    "Gecko/20100101 Firefox/146.0"
)

ENCODED_UA = quote_plus(USER_AGENT)

REFERER = "https://gooz.aapmains.net/"
ORIGIN = "https://gooz.aapmains.net"

TVG_ID = "Live.Event.us"
TAG = "APPTV"

CACHE_FILE = "apptv.json"
CACHE_EXP = 3 * 60 * 60

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


async def fetch(session, url, headers=None):
    try:
        default_headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }
        if headers:
            default_headers.update(headers)
        async with session.get(url, timeout=30, headers=default_headers) as r:
            if r.status == 200:
                return await r.text()
            log(f"Fetch error {r.status}: {url}")
    except Exception as e:
        log(f"Fetch error: {e}")
    return None


# ================= STREAM EXTRACTION =================

PLAYLIST_PATTERN = re.compile(
    r'(https?://[^"\']+/playlist/\d+/load-playlist)',
    re.I,
)
PLAYLIST_PATTERN_ALT = re.compile(
    r'(https?://[^"\']+/playlist/[^"\']+)',
    re.I,
)
BASE64_PATTERN = re.compile(
    r'window\.atob\([\'"]([A-Za-z0-9+/=]+)[\'"]\)',
    re.I,
)
CONST_SOURCE_PATTERN = re.compile(
    r'const\s+source\s*=\s*["\']([^"\']+)["\']',
    re.I,
)
M3U8_PATTERN = re.compile(
    r'(https?://[^"\']+\.m3u8[^"\']*)',
    re.I,
)


def _extract_from_html(html: str):
    m = PLAYLIST_PATTERN.search(html)
    if m:
        return m.group(1)
    m = BASE64_PATTERN.search(html)
    if m:
        try:
            decoded = base64.b64decode(m.group(1)).decode("utf-8")
            if decoded.startswith("http"):
                return decoded
        except Exception:
            pass
    m = CONST_SOURCE_PATTERN.search(html)
    if m:
        return m.group(1)
    m = PLAYLIST_PATTERN_ALT.search(html)
    if m:
        return m.group(1)
    m = M3U8_PATTERN.search(html)
    if m:
        return m.group(1)
    return None


async def extract_from_iframe_url(session, iframe_url):
    iframe_html = await fetch(session, iframe_url, headers={
        "Referer": REFERER,
        "Origin": ORIGIN,
    })
    if not iframe_html:
        log("  Failed to fetch iframe content")
        return None
    stream_url = _extract_from_html(iframe_html)
    if stream_url:
        log(f"   Found stream: {stream_url[:90]}")
        return stream_url
    log("   No stream found in iframe")
    return None


async def extract_stream(session, event_url):
    log(f"  Fetching event page: {event_url}")
    html = await fetch(session, event_url)
    if not html:
        log("  Failed to fetch event page")
        return None

    # Fast path: stream is directly embedded in the event page
    direct = _extract_from_html(html)
    if direct:
        log(f"   Found stream on event page: {direct[:90]}")
        return direct

    soup = HTMLParser(html)

    iframe = None
    for selector in (
        "iframe[src*='embed']",
        "iframe[src*='player']",
        "iframe[src*='stream']",
        "iframe",
    ):
        iframe = soup.css_first(selector)
        if iframe:
            break

    if not iframe:
        raw_match = re.search(
            r'<iframe[^>]+src=["\']([^"\']+)["\']', html, re.I
        )
        if raw_match:
            iframe_src = urljoin(event_url, raw_match.group(1))
            log(f"  Found iframe via regex: {iframe_src}")
            return await extract_from_iframe_url(session, iframe_src)
        log("  No iframe found")
        return None

    iframe_src = iframe.attributes.get("src")
    if not iframe_src:
        log("  No src attribute in iframe")
        return None

    iframe_src = urljoin(event_url, iframe_src)
    log(f"  Fetching iframe: {iframe_src}")
    return await extract_from_iframe_url(session, iframe_src)


# ================= EVENTS =================

TIME_BADGE_PATTERN = re.compile(
    r'\s*(In\s*Progress|Not\s*started|Finished|Delayed|'
    r'\d+\s*(?:hours?|mins?|minutes?|days?)\s*(?:ago|from\s*now))\s*',
    re.I,
)
HD_TEXT_PATTERN = re.compile(r'\s*HD\s*$', re.I)
TRAILING_COLON = re.compile(r':\s*$')


def _clean_title(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\xa0", " ")
    text = TIME_BADGE_PATTERN.sub(" ", text)
    text = HD_TEXT_PATTERN.sub("", text)
    text = re.sub(r'\s+', " ", text).strip()
    text = TRAILING_COLON.sub("", text).strip()
    return text


def _parse_anchor(link, base_url):
    href = link.attributes.get("href")
    if not href:
        return None

    full_url = urljoin(base_url, href)

    # Only live/tv-live events
    if not (
        "/tv-live/" in full_url
        or "/live/" in full_url
    ):
        return None

    # Sport category
    sport = None
    strong = link.css_first("strong")
    if strong:
        sport = strong.text(strip=True)

    if not sport:
        # Derive from URL: /tv-live/{sport}/{...}
        m = re.search(r'/tv-live/([^/]+)/', full_url)
        if m:
            sport = m.group(1).upper()

    if not sport:
        sport = "Other"

    # Sport logo
    logo = None
    img = link.css_first("img")
    if img:
        src = img.attributes.get("src")
        if src:
            logo = urljoin(base_url, src)

    if not logo:
        logo = DEFAULT_LOGO

    # Event name: text after the closing </span> that contains the img
    name = _clean_title(link.text(strip=True))
    if not name or len(name) < 3:
        return None

    return {
        "sport": sport,
        "title": name,
        "url": full_url,
        "logo": logo,
    }


async def get_events(session):
    log(f"Fetching main page: {BASE_URL}")
    html = await fetch(session, BASE_URL)
    if not html:
        log("Failed to fetch main page")
        return []

    soup = HTMLParser(html)
    events = []
    seen = set()

    for link in soup.css("a.list-group-item"):
        parsed = _parse_anchor(link, BASE_URL)
        if not parsed:
            continue
        key = parsed["url"]
        if key in seen:
            continue
        seen.add(key)
        events.append(parsed)
        log(
            f"Found event: {parsed['sport']} - {parsed['title']}"
        )

    return events


# ================= MAIN =================

async def main():
    log("=" * 60)
    log("TheTVApp Scraper Started")
    log("=" * 60)

    cache = load_cache()
    now = int(time.time())

    async with aiohttp.ClientSession() as session:
        events = await get_events(session)
        log(f"\nFound {len(events)} total events")

        if not events:
            log("No events found - check if website structure changed")
            return

        entries = []

        for i, ev in enumerate(events, 1):
            key = f"[{ev['sport']}] {ev['title']} ({TAG})"

            if key in cache and now - cache[key]["ts"] < CACHE_EXP:
                log(f"[{i}/{len(events)}] Cached: {key[:60]}")
                entries.append(cache[key]["entry"])
                continue

            log(f"\n[{i}/{len(events)}] Processing: {key[:60]}")

            stream = await extract_stream(session, ev["url"])

            if not stream:
                log(f"   No stream found for: {key}")
                continue

            stream_with_headers = (
                f"{stream}"
                f"|referer={REFERER}"
                f"|origin={ORIGIN}"
                f"|user-agent={ENCODED_UA}"
            )

            log(f"   Stream URL: {stream[:80]}")

            entry = {
                "name": key,
                "url": stream_with_headers,
                "logo": ev.get("logo") or DEFAULT_LOGO,
            }

            cache[key] = {"ts": now, "entry": entry}
            entries.append(entry)

            await asyncio.sleep(0.5)

    if not entries:
        log("\nNo streams collected")
        return

    log(f"\nWriting {len(entries)} streams to {OUTPUT_FILE}")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for e in entries:
            safe_name = e["name"].replace(",", "\\,")
            f.write(
                f'#EXTINF:-1 tvg-id="{TVG_ID}" '
                f'tvg-name="{safe_name}" '
                f'tvg-logo="{e["logo"]}" '
                f'group-title="Live Events",{safe_name}\n'
            )
            f.write(f'{e["url"]}\n')

    save_cache(cache)

    log("\n" + "=" * 60)
    log(f"Success! Saved {len(entries)} streams to {OUTPUT_FILE}")
    log("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
