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

BASE_URL = "https://the-tv.app/"
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
    except Exception as e:
        log(f"Fetch error: {e}")
    return None


# ================= STREAM EXTRACTION =================

async def extract_stream(session, event_url):
    """Extract stream URL from event page"""
    log(f"Fetching event page: {event_url}")
    html = await fetch(session, event_url)
    if not html:
        log("Failed to fetch event page")
        return None

    soup = HTMLParser(html)

    # Find iframe
    iframe = soup.css_first("iframe")
    if not iframe:
        log("No iframe found")
        return None

    iframe_src = iframe.attributes.get("src")
    if not iframe_src:
        log("No src attribute in iframe")
        return None

    # Handle relative iframe URLs
    iframe_src = urljoin(BASE_URL, iframe_src)
    log(f"Fetching iframe: {iframe_src}")

    iframe_html = await fetch(session, iframe_src)
    if not iframe_html:
        log("Failed to fetch iframe content")
        return None

    # ================= PATTERNS =================

    # 1. New playlist pattern (IMPORTANT - from the example)
    pattern_playlist = r'(https?://[^"\']+/playlist/\d+/load-playlist)'
    match = re.search(pattern_playlist, iframe_html)
    if match:
        stream_url = match.group(1)
        log(f"Found playlist URL: {stream_url}")
        return stream_url

    # 2. Base64 encoded pattern
    pattern_base64 = r'const\s+source\s*=\s*"([^"]+)"'
    match = re.search(pattern_base64, iframe_html, re.I)
    if match:
        try:
            decoded = base64.b64decode(match.group(1)).decode("utf-8")
            if decoded.startswith("http"):
                log(f"Found base64 encoded stream: {decoded[:80]}...")
                return decoded
        except Exception:
            pass

    # 3. Direct m3u8 pattern
    pattern_m3u8 = r'(https?://[^"\']+\.m3u8[^"\']*)'
    match = re.search(pattern_m3u8, iframe_html)
    if match:
        log(f"Found m3u8 stream: {match.group(1)[:80]}...")
        return match.group(1)

    # 4. Generic HTTP stream fallback
    pattern_http = r'(https?://[^"\']+)'
    match = re.search(pattern_http, iframe_html)
    if match:
        log(f"Found generic stream: {match.group(1)[:80]}...")
        return match.group(1)

    log("No stream found in iframe")
    return None


# ================= EVENTS =================

async def get_events(session):
    """Parse events from the main page"""
    log(f"Fetching main page: {BASE_URL}")
    html = await fetch(session, BASE_URL)
    if not html:
        log("Failed to fetch main page")
        return []

    soup = HTMLParser(html)
    events = []

    # Find all sport categories (h3 tags)
    for category in soup.css("div.col-lg-12"):
        # Get category title from h3
        h3 = category.css_first("h3")
        if not h3:
            continue
        
        sport = h3.text(strip=True).replace(" Streams", "").strip()
        
        # Find all event links in this category
        for link in category.css("a.list-group-item"):
            href = link.attributes.get("href")
            if not href:
                continue
            
            # Get event title (clean up text)
            title_text = link.text(strip=True)
            # Remove time badge and HD text if present
            title = re.sub(r'\s*[0-9]+\s*(hours?|mins?)\s*from\s*now', '', title_text, flags=re.I)
            title = re.sub(r'\s*In\s*Progress', '', title, flags=re.I)
            title = re.sub(r'\s*[0-9]+\'\+?[0-9]*\'?', '', title)
            title = re.sub(r'\s*HD\s*$', '', title)
            title = title.strip()
            title = title.rstrip(':')
            
            if not title:
                continue
            
            # Build full URL
            full_url = urljoin(BASE_URL, href)
            
            events.append({
                "sport": sport,
                "title": title,
                "url": full_url
            })
            log(f"Found event: {sport} - {title}")

    return events


# ================= MAIN =================

async def main():
    log("=" * 60)
    log("TheTVApp Scraper Started")
    log("=" * 60)

    cache = load_cache()
    now = int(time.time())

    headers = {"User-Agent": USER_AGENT}

    async with aiohttp.ClientSession(headers=headers) as session:
        events = await get_events(session)
        log(f"\nFound {len(events)} total events")
        
        if not events:
            log("No events found")
            return

        entries = []

        for i, ev in enumerate(events, 1):
            # Create unique key for cache
            key = f"[{ev['sport']}] {ev['title']} ({TAG})"
            
            # Check cache
            if key in cache and now - cache[key]["ts"] < CACHE_EXP:
                log(f"[{i}/{len(events)}]Cached: {key}")
                entries.append(cache[key]["entry"])
                continue

            log(f"\n[{i}/{len(events)}]Processing: {key}")
            
            # Extract stream URL
            stream = await extract_stream(session, ev["url"])
            
            if not stream:
                log(f"  ✗ No stream found for: {key}")
                continue
            
            # Add headers to stream URL
            stream_with_headers = (
                f"{stream}"
                f"|referer={REFERER}"
                f"|origin={ORIGIN}"
                f"|user-agent={ENCODED_UA}"
            )
            
            log(f"Stream URL: {stream[:80]}...")
            
            entry = {
                "name": key,
                "url": stream_with_headers,
                "logo": DEFAULT_LOGO,
            }
            
            # Update cache
            cache[key] = {
                "ts": now,
                "entry": entry
            }
            
            entries.append(entry)
            
            # Small delay to avoid overwhelming the server
            await asyncio.sleep(0.5)

    if not entries:
        log("\nNo streams collected")
        return

    # ================= WRITE M3U =================
    log(f"\nWriting {len(entries)} streams to {OUTPUT_FILE}")
    
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for e in entries:
            f.write(
                f'#EXTINF:-1 tvg-id="{TVG_ID}" '
                f'tvg-name="{e["name"]}" '
                f'tvg-logo="{e["logo"]}" '
                f'group-title="Live Events",{e["name"]}\n'
            )
            f.write(f'{e["url"]}\n')

    save_cache(cache)
    
    log("\n" + "=" * 60)
    log(f"Success! Saved {len(entries)} streams to {OUTPUT_FILE}")
    log("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
