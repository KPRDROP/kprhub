#!/usr/bin/env python3

import asyncio
import re
import sys
import base64
from urllib.parse import urljoin, quote_plus

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

# -------------------------------------------------
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:146.0) "
    "Gecko/20100101 Firefox/146.0"
)

HOMEPAGE = "https://mlbwebcast.com/"

OUTPUT_VLC = "emelbecast_VLC.m3u8"
OUTPUT_TIVI = "emelbecast_TiviMate.m3u8"

DEFAULT_LOGO = "https://i.postimg.cc/7L220Lmn/baseball4k.png"

TVG_ID = "MLB.Baseball.Dummy.us"
GROUP_TITLE = "MLB TEAM GAME"

# -------------------------------------------------
def log(*a):
    print(*a)
    sys.stdout.flush()

# -------------------------------------------------
def normalize_vs(text: str) -> str:
    text = re.sub(r"\s*@\s*", " vs ", text, flags=re.I)
    text = re.sub(r"\s+", " ", text)
    return text.strip()

# -------------------------------------------------
async def fetch_events_via_playwright(playwright):
    browser = await playwright.firefox.launch(headless=True)
    context = await browser.new_context(user_agent=USER_AGENT)
    page = await context.new_page()

    log("Loading homepage…")

    try:
        await page.goto(HOMEPAGE, wait_until="domcontentloaded", timeout=30000)

        # allow JS to inject content
        for _ in range(6):
            await page.wait_for_timeout(1000)
            anchors = await page.locator("a[href]").count()
            if anchors > 20:
                break

        html = await page.content()

    finally:
        await page.close()
        await context.close()
        await browser.close()

    soup = BeautifulSoup(html, "lxml")
    events = []

    # PRIMARY SELECTOR: team-logo links (from source HTML)
    team_links = soup.select("li.team-logo a")
    
    if not team_links:
        # Fallback: any link with /live or team name pattern
        team_links = soup.select("a[href*='-live']")
    
    for a in team_links:
        href = a.get("href")
        if not href:
            continue
        
        # Build absolute URL
        url = urljoin(HOMEPAGE, href)
        
        # Get team name from title attribute (primary)
        event_name = a.get("title", "")
        
        # If no title, try text content
        if not event_name:
            event_name = a.get_text(strip=True)
        
        # Clean up event name (remove "Live Stream" suffix if present)
        event_name = re.sub(r'\s*Live\s*Stream\s*$', '', event_name, flags=re.I)
        event_name = event_name.strip()
        
        if not event_name:
            event_name = "MLB Team Game"
        
        # Get logo from img inside the anchor
        logo = DEFAULT_LOGO
        img = a.find("img")
        if img and img.get("src"):
            logo = img.get("src")
        
        events.append({
            "url": url,
            "event": event_name,
            "logo": logo
        })
    
    # Remove duplicates by URL
    seen = set()
    unique_events = []
    for ev in events:
        if ev["url"] not in seen:
            seen.add(ev["url"])
            unique_events.append(ev)
    
    return unique_events

# -------------------------------------------------
async def capture_m3u8_from_page(playwright, url, timeout_ms=45000):
    """Capture m3u8 stream URL from team page with extended timeout and network monitoring"""
    browser = await playwright.firefox.launch(headless=True)
    context = await browser.new_context(
        user_agent=USER_AGENT,
        viewport={'width': 1280, 'height': 720}
    )
    page = await context.new_page()
    
    captured = None
    all_m3u8_urls = set()
    
    # Monitor all network requests for m3u8 files
    def on_response(response):
        nonlocal captured
        try:
            req_url = response.url
            if '.m3u8' in req_url.lower():
                all_m3u8_urls.add(req_url)
                if not captured:
                    captured = req_url
                    log(f"  ✓ Network capture: {captured[:100]}...")
        except Exception:
            pass
    
    context.on("response", on_response)
    
    try:
        # Navigate to page with longer timeout
        log(f"  Loading page...")
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except PlaywrightTimeoutError:
            log(f"  Page load timeout, continuing...")
        
        # Wait for page to fully load
        await page.wait_for_timeout(5000)
        
        # Find and interact with the video player
        # Look for iframes that might contain the stream
        frames = page.frames
        log(f"  Found {len(frames)} frames")
        
        # Try to find the stream iframe
        stream_iframe = None
        for frame in frames:
            frame_url = frame.url
            if 'stream' in frame_url.lower() or 'player' in frame_url.lower() or 'embed' in frame_url.lower():
                stream_iframe = frame
                log(f"  Found potential stream iframe: {frame_url[:80]}")
                break
        
        # If no obvious stream iframe, try the main page
        if not stream_iframe:
            stream_iframe = page
        
        # Try to click on the video player to start playback
        click_selectors = [
            "video",
            ".player-container",
            ".video-js",
            ".vjs-big-play-button",
            ".play-button",
            "button[aria-label='Play']",
            ".stream-player",
            "#player",
            ".jwplayer",
            ".video-player"
        ]
        
        for selector in click_selectors:
            try:
                element = stream_iframe.locator(selector).first
                if await element.count() > 0:
                    await element.click(timeout=3000)
                    log(f"  Clicked: {selector}")
                    await page.wait_for_timeout(2000)
                    break
            except Exception:
                pass
        
        # Also try clicking anywhere on the page to trigger autoplay
        try:
            await page.mouse.click(500, 400)
            await page.wait_for_timeout(1000)
        except Exception:
            pass
        
        # Monitor network for m3u8 with extended timeout
        waited = 0
        check_interval = 1.5
        max_wait = 35  # seconds
        
        log(f"  Monitoring network for m3u8 (max {max_wait}s)...")
        while waited < max_wait and not captured:
            await asyncio.sleep(check_interval)
            waited += check_interval
            
            # Also check page content periodically
            if waited % 5 == 0:
                html = await page.content()
                m3u8_matches = re.findall(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', html)
                for match in m3u8_matches:
                    if match not in all_m3u8_urls:
                        all_m3u8_urls.add(match)
                        if not captured:
                            captured = match
                            log(f"  ✓ HTML capture: {captured[:100]}...")
                            break
        
        # If still not captured, check all collected URLs
        if not captured and all_m3u8_urls:
            captured = list(all_m3u8_urls)[0]
            log(f"  ✓ Using captured URL from network")
        
        # -------------------------------------------------
        # DEEP PAGE ANALYSIS - look for stream URLs in all scripts
        # -------------------------------------------------
        if not captured:
            log(f"  Scanning page scripts for stream URLs...")
            html = await page.content()
            
            # Look for patterns in scripts
            script_patterns = [
                r'(?:source|file|src|url|stream|video|playlist|hls)[\s:]*["\']([^"\']+\.m3u8[^"\']*)["\']',
                r'(?:src|href)=["\']([^"\']+\.m3u8[^"\']*)["\']',
                r'["\'](https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*)["\']',
                r'([a-zA-Z0-9+/=]{50,})'  # Base64 pattern
            ]
            
            for pattern in script_patterns:
                matches = re.findall(pattern, html, re.IGNORECASE)
                for match in matches:
                    # Check if it's base64
                    if len(match) > 50 and not match.startswith('http'):
                        try:
                            decoded = base64.b64decode(match).decode('utf-8', errors='ignore')
                            url_match = re.search(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', decoded)
                            if url_match:
                                captured = url_match.group(0)
                                log(f"  ✓ Base64 decode: {captured[:100]}...")
                                break
                        except Exception:
                            pass
                    elif '.m3u8' in match.lower():
                        captured = match
                        log(f"  ✓ Script capture: {captured[:100]}...")
                        break
                if captured:
                    break
        
        # -------------------------------------------------
        # CHECK ALL IFRAMES DEEPLY
        # -------------------------------------------------
        if not captured:
            log(f"  Deep scanning iframes...")
            for i, frame in enumerate(frames):
                try:
                    frame_html = await frame.content()
                    m3u8_matches = re.findall(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', frame_html)
                    if m3u8_matches:
                        captured = m3u8_matches[0]
                        log(f"  ✓ Iframe {i} capture: {captured[:100]}...")
                        break
                except Exception:
                    pass
        
        # -------------------------------------------------
        # CHECK FOR TOKENIZED URLS (b-cdn.net pattern)
        # -------------------------------------------------
        if not captured:
            html = await page.content()
            # Look for b-cdn.net patterns
            bcdn_pattern = r'https?://[^\s"\'<>]*b-cdn\.net[^\s"\'<>]*\.m3u8[^\s"\'<>]*'
            matches = re.findall(bcdn_pattern, html, re.IGNORECASE)
            if matches:
                captured = matches[0]
                log(f"  ✓ CDN capture: {captured[:100]}...")
    
    except Exception as e:
        log(f"  Error during capture: {str(e)[:100]}")
    
    finally:
        # Cleanup
        try:
            context.remove_listener("response", on_response)
        except Exception:
            pass
        try:
            await page.close()
            await context.close()
            await browser.close()
        except Exception:
            pass
    
    return captured

# -------------------------------------------------
def write_playlists(entries):
    if not entries:
        log("No entries to write")
        return
    
    with open(OUTPUT_VLC, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for e in entries:
            safe_name = e["event"].replace(",", "").strip()
            f.write(
                f'#EXTINF:-1 tvg-id="{TVG_ID}" '
                f'tvg-name="{safe_name}" '
                f'tvg-logo="{e["logo"]}" '
                f'group-title="{GROUP_TITLE}",{safe_name}\n'
            )
            f.write(f"#EXTVLCOPT:http-referrer={HOMEPAGE}\n")
            f.write(f"#EXTVLCOPT:http-origin={HOMEPAGE}\n")
            f.write(f"#EXTVLCOPT:http-user-agent={USER_AGENT}\n")
            f.write(f"{e['m3u8']}\n\n")
    
    ua_encoded = quote_plus(USER_AGENT)
    with open(OUTPUT_TIVI, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for e in entries:
            safe_name = e["event"].replace(",", "").strip()
            f.write(
                f'#EXTINF:-1 tvg-id="{TVG_ID}" '
                f'tvg-name="{safe_name}" '
                f'tvg-logo="{e["logo"]}",{safe_name}\n'
            )
            f.write(
                f"{e['m3u8']}|referer={HOMEPAGE}|origin={HOMEPAGE}|user-agent={ua_encoded}\n\n"
            )
    
    log(f"Playlists saved: {OUTPUT_VLC} / {OUTPUT_TIVI}")

# -------------------------------------------------
async def main():
    log("Starting MLB Webcast Updater...")
    
    async with async_playwright() as p:
        events = await fetch_events_via_playwright(p)
        log(f"Found {len(events)} events")
        
        if not events:
            log("No events detected")
            return
        
        collected = []
        
        for i, ev in enumerate(events, 1):
            log(f"\n[{i}/{len(events)}] {ev['event']}")
            log(f"  URL: {ev['url']}")
            
            m3u8 = await capture_m3u8_from_page(p, ev["url"])
            
            if m3u8:
                log(f"  ✓ STREAM CAPTURED")
                ev["m3u8"] = m3u8
                collected.append(ev)
            else:
                log(f"  ✗ No streams found")
    
    if not collected:
        log("\nNo streams captured.")
        return
    
    log(f"\nCaptured {len(collected)}/{len(events)} streams")
    write_playlists(collected)

# -------------------------------------------------
if __name__ == "__main__":
    asyncio.run(main())
