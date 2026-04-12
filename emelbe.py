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
async def fetch_events_via_playwright(playwright):
    """Extract team events from homepage using DOM selectors"""
    browser = await playwright.firefox.launch(headless=True)
    context = await browser.new_context(user_agent=USER_AGENT)
    page = await context.new_page()

    log("Loading homepage…")

    try:
        await page.goto(HOMEPAGE, wait_until="networkidle", timeout=30000)
        
        # Wait for team logos to load
        await page.wait_for_selector("li.team-logo a", timeout=10000)
        
        # Get all team links with their titles
        team_elements = await page.query_selector_all("li.team-logo a")
        
        events = []
        for element in team_elements:
            href = await element.get_attribute("href")
            title = await element.get_attribute("title")
            
            if not href:
                continue
            
            # Get logo image src
            img = await element.query_selector("img")
            logo = DEFAULT_LOGO
            if img:
                logo_src = await img.get_attribute("src")
                if logo_src:
                    logo = logo_src
            
            url = urljoin(HOMEPAGE, href)
            
            # Clean up event name
            event_name = title or ""
            event_name = re.sub(r'\s*Live\s*Stream\s*$', '', event_name, flags=re.I)
            event_name = event_name.strip()
            
            if not event_name:
                event_name = "MLB Team Game"
            
            events.append({
                "url": url,
                "event": event_name,
                "logo": logo
            })
        
        # Also check for any additional links with "-live" pattern
        live_links = await page.query_selector_all("a[href*='-live']")
        for element in live_links:
            href = await element.get_attribute("href")
            if not href:
                continue
            
            url = urljoin(HOMEPAGE, href)
            
            # Skip if already in events
            if any(e["url"] == url for e in events):
                continue
            
            title = await element.get_attribute("title") or await element.inner_text()
            event_name = re.sub(r'\s*Live\s*Stream\s*$', '', title, flags=re.I).strip()
            
            events.append({
                "url": url,
                "event": event_name,
                "logo": DEFAULT_LOGO
            })
        
        return events
    
    finally:
        await page.close()
        await context.close()
        await browser.close()

# -------------------------------------------------
async def capture_m3u8_from_page(playwright, url, timeout_ms=60000):
    """Capture m3u8 stream URL from team page by monitoring network"""
    browser = await playwright.firefox.launch(headless=True)
    context = await browser.new_context(
        user_agent=USER_AGENT,
        viewport={'width': 1280, 'height': 720}
    )
    page = await context.new_page()
    
    captured = None
    all_requests = []
    
    # Monitor ALL network requests
    def on_request(request):
        nonlocal captured
        req_url = request.url
        all_requests.append(req_url)
        
        # Check for m3u8 in URL
        if '.m3u8' in req_url.lower() and not captured:
            captured = req_url
            log(f"  ✓ CAPTURED: {captured[:120]}...")
        
        # Also check for CDN patterns
        elif 'b-cdn.net' in req_url.lower() and '.m3u8' in req_url.lower() and not captured:
            captured = req_url
            log(f"  ✓ CDN CAPTURED: {captured[:120]}...")
    
    context.on("request", on_request)
    
    try:
        log(f"  Loading: {url}")
        
        # Navigate to page
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except PlaywrightTimeoutError:
            log(f"  Timeout on load, continuing...")
        
        # Wait for page to settle
        await page.wait_for_timeout(3000)
        
        # Find and click the video player
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
            ".video-player",
            "iframe",
            ".elementor-video"
        ]
        
        for selector in click_selectors:
            try:
                element = await page.query_selector(selector)
                if element:
                    await element.click(timeout=3000)
                    log(f"  Clicked: {selector}")
                    await page.wait_for_timeout(2000)
                    break
            except Exception:
                pass
        
        # Try clicking on the body to trigger autoplay
        try:
            await page.mouse.click(500, 400)
            await page.wait_for_timeout(1000)
        except Exception:
            pass
        
        # Check all iframes for content
        frames = page.frames
        log(f"  Found {len(frames)} frames")
        
        for frame in frames:
            try:
                # Click inside iframe
                await frame.click("body", timeout=2000)
                await page.wait_for_timeout(1000)
            except Exception:
                pass
        
        # Monitor for m3u8 with longer timeout
        waited = 0
        check_interval = 2
        max_wait = timeout_ms / 1000
        
        log(f"  Monitoring network for m3u8 (max {max_wait}s)...")
        
        while waited < max_wait and not captured:
            await asyncio.sleep(check_interval)
            waited += check_interval
            
            # Periodically check page source for m3u8
            if waited % 6 == 0:
                html = await page.content()
                m3u8_matches = re.findall(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', html)
                for match in m3u8_matches:
                    if not captured:
                        captured = match
                        log(f"  ✓ HTML capture: {captured[:120]}...")
                        break
                
                # Also look for base64 encoded
                b64_matches = re.findall(r'["\']([A-Za-z0-9+/=]{50,300})["\']', html)
                for b64_str in b64_matches:
                    try:
                        decoded = base64.b64decode(b64_str).decode('utf-8', errors='ignore')
                        url_match = re.search(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', decoded)
                        if url_match and not captured:
                            captured = url_match.group(0)
                            log(f"  ✓ Base64 capture: {captured[:120]}...")
                            break
                    except Exception:
                        pass
        
        # If still no capture, check all collected requests
        if not captured and all_requests:
            for req in all_requests:
                if '.m3u8' in req.lower():
                    captured = req
                    log(f"  ✓ Request capture: {captured[:120]}...")
                    break
    
    except Exception as e:
        log(f"  Error: {str(e)[:100]}")
    
    finally:
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
