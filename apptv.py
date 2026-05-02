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
            else:
                log(f"Fetch error {r.status}: {url}")
    except Exception as e:
        log(f"Fetch error: {e}")
    return None


# ================= STREAM EXTRACTION =================

async def extract_stream(session, event_url):
    """Extract stream URL from event page"""
    log(f"  Fetching event page: {event_url}")
    html = await fetch(session, event_url)
    if not html:
        log("  Failed to fetch event page")
        return None

    soup = HTMLParser(html)

    # Try multiple iframe selectors
    iframe = None
    for selector in ["iframe", "iframe[src*='playlist']", "iframe[src*='m3u8']", "div.embed-responsive iframe"]:
        iframe = soup.css_first(selector)
        if iframe:
            break
    
    if not iframe:
        # Try to find iframe in any div
        for div in soup.css("div"):
            iframe = div.css_first("iframe")
            if iframe:
                break
    
    if not iframe:
        log("  No iframe found, searching entire HTML...")
        # Last resort: search raw HTML for iframe src
        raw_match = re.search(r'<iframe[^>]+src=["\']([^"\']+)["\']', html, re.I)
        if raw_match:
            iframe_src = raw_match.group(1)
            log(f"  Found iframe via regex: {iframe_src}")
            iframe_src = urljoin(event_url, iframe_src)
            return await extract_from_iframe_url(session, iframe_src)
        log("  No iframe found at all")
        return None

    iframe_src = iframe.attributes.get("src")
    if not iframe_src:
        log("  No src attribute in iframe")
        return None

    # Handle relative iframe URLs
    iframe_src = urljoin(event_url, iframe_src)
    log(f"  Fetching iframe: {iframe_src}")
    
    return await extract_from_iframe_url(session, iframe_src)


async def extract_from_iframe_url(session, iframe_url):
    """Extract stream URL from iframe content"""
    iframe_html = await fetch(session, iframe_url)
    if not iframe_html:
        log("  Failed to fetch iframe content")
        return None

    # ================= PATTERNS =================

    # 1. New playlist pattern (IMPORTANT - from the example)
    pattern_playlist = r'(https?://[^"\']+/playlist/\d+/load-playlist)'
    match = re.search(pattern_playlist, iframe_html)
    if match:
        stream_url = match.group(1)
        log(f"   Found playlist URL: {stream_url}")
        return stream_url

    # 2. Alternative playlist pattern with different path
    pattern_playlist2 = r'(https?://[^"\']+/playlist/[^"\']+)'
    match = re.search(pattern_playlist2, iframe_html)
    if match:
        stream_url = match.group(1)
        log(f"   Found alternative playlist URL: {stream_url[:80]}...")
        return stream_url

    # 3. Base64 encoded pattern
    pattern_base64 = r'const\s+source\s*=\s*["\']([^"\']+)["\']'
    for match in re.finditer(pattern_base64, iframe_html, re.I):
        try:
            decoded = base64.b64decode(match.group(1)).decode("utf-8")
            if decoded.startswith("http"):
                log(f"   Found base64 encoded stream: {decoded[:80]}...")
                return decoded
        except Exception:
            pass

    # 4. Direct m3u8 pattern
    pattern_m3u8 = r'(https?://[^"\']+\.m3u8[^"\']*)'
    match = re.search(pattern_m3u8, iframe_html)
    if match:
        log(f"   Found m3u8 stream: {match.group(1)[:80]}...")
        return match.group(1)

    # 5. JavaScript variable patterns
    pattern_js = r'(?:src|source|file|url|video)[\s]*[:=][\s]*["\']([^"\']+\.(?:m3u8|mp4)[^"\']*)["\']'
    match = re.search(pattern_js, iframe_html, re.I)
    if match:
        stream_url = match.group(1)
        if stream_url.startswith("http"):
            log(f"   Found JS variable stream: {stream_url[:80]}...")
            return stream_url

    # 6. Look for any HTTP URL containing m3u8 or playlist
    pattern_http = r'(https?://[^"\'\s<>]+(?:m3u8|playlist|stream)[^"\'\s<>]*)'
    match = re.search(pattern_http, iframe_html, re.I)
    if match:
        stream_url = match.group(1)
        log(f"   Found generic stream: {stream_url[:80]}...")
        return stream_url

    # 7. Try to find any HTTP URL as last resort
    pattern_any = r'(https?://[^"\'\s<>]+)'
    match = re.search(pattern_any, iframe_html)
    if match:
        stream_url = match.group(1)
        log(f"   Using fallback URL: {stream_url[:80]}...")
        return stream_url

    log("   No stream found in iframe")
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

    # Method 1: Find events in #games-list container
    games_list = soup.css_first("#games-list")
    if games_list:
        log("Found #games-list container")
        # Find all category containers
        for category in games_list.css("div.col-lg-12"):
            # Get category title from h3 or h4
            title_elem = category.css_first("h3") or category.css_first("h4")
            if not title_elem:
                continue
            
            sport = title_elem.text(strip=True)
            sport = re.sub(r'\s*Streams$', '', sport, flags=re.I)
            sport = sport.strip()
            
            if not sport:
                continue
            
            # Find all event links in this category
            for link in category.css("a.list-group-item"):
                href = link.attributes.get("href")
                if not href:
                    continue
                
                # Get event title (clean up text)
                title_text = link.text(strip=True)
                # Remove time badge and HD text if present
                title = re.sub(r'\s*[0-9]+\s*(hours?|mins?|day|days?)\s*ago', '', title_text, flags=re.I)
                title = re.sub(r'\s*[0-9]+\s*(hours?|mins?)\s*from\s*now', '', title, flags=re.I)
                title = re.sub(r'\s*In\s*Progress', '', title, flags=re.I)
                title = re.sub(r'\s*Not\s*started', '', title, flags=re.I)
                title = re.sub(r'\s*[0-9]+\'\+?[0-9]*\'?', '', title)
                title = re.sub(r'\s*HD\s*$', '', title)
                title = title.strip()
                title = title.rstrip(':')
                
                if not title or len(title) < 3:
                    continue
                
                # Build full URL
                full_url = urljoin(BASE_URL, href)
                
                events.append({
                    "sport": sport,
                    "title": title,
                    "url": full_url
                })
                log(f"Found event: {sport} - {title}")
    
    # Method 2: Fallback - search all list-group-item links
    if not events:
        log("Searching all list-group-item links...")
        for link in soup.css("a.list-group-item"):
            href = link.attributes.get("href")
            if not href:
                continue
            
            # Only process event links (skip TV channel links)
            if not href.startswith("/live/") and not href.startswith("/tv-live/"):
                continue
            
            # Try to determine sport from parent category
            sport = "Other"
            parent = link.parent
            while parent:
                if parent.tag == "div" and "col-lg-12" in parent.attributes.get("class", ""):
                    title_elem = parent.css_first("h3") or parent.css_first("h4")
                    if title_elem:
                        sport = title_elem.text(strip=True)
                        sport = re.sub(r'\s*Streams$', '', sport, flags=re.I)
                        break
                parent = parent.parent
            
            # Get event title
            title_text = link.text(strip=True)
            title = re.sub(r'\s*[0-9]+\s*(hours?|mins?|day|days?)\s*ago', '', title_text, flags=re.I)
            title = re.sub(r'\s*[0-9]+\s*(hours?|mins?)\s*from\s*now', '', title, flags=re.I)
            title = re.sub(r'\s*In\s*Progress', '', title, flags=re.I)
            title = re.sub(r'\s*Not\s*started', '', title, flags=re.I)
            title = re.sub(r'\s*HD\s*$', '', title)
            title = title.strip()
            
            if not title or len(title) < 3:
                continue
            
            full_url = urljoin(BASE_URL, href)
            events.append({
                "sport": sport,
                "title": title,
                "url": full_url
            })
            log(f"Found event (fallback): {sport} - {title}")

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
            log("You may need to update the selectors in get_events()")
            return

        entries = []

        for i, ev in enumerate(events, 1):
            # Create unique key for cache
            key = f"[{ev['sport']}] {ev['title']} ({TAG})"
            
            # Check cache
            if key in cache and now - cache[key]["ts"] < CACHE_EXP:
                log(f"[{i}/{len(events)}] Cached: {key[:60]}...")
                entries.append(cache[key]["entry"])
                continue

            log(f"\n[{i}/{len(events)}] Processing: {key[:60]}...")
            
            # Extract stream URL
            stream = await extract_stream(session, ev["url"])
            
            if not stream:
                log(f"   No stream found for: {key}")
                continue
            
            # Add headers to stream URL
            stream_with_headers = (
                f"{stream}"
                f"|referer={REFERER}"
                f"|origin={ORIGIN}"
                f"|user-agent={ENCODED_UA}"
            )
            
            log(f"   Stream URL: {stream[:80]}...")
            
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
            # Escape special characters in name
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
