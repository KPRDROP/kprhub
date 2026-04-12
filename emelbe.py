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

    # -------------------------------------------------
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
async def capture_m3u8_from_page(playwright, url, timeout_ms=30000):
    browser = await playwright.firefox.launch(headless=True)
    context = await browser.new_context(user_agent=USER_AGENT)
    page = await context.new_page()
    
    captured = None
    
    # CRITICAL: capture from ALL network requests
    def on_request(req):
        nonlocal captured
        try:
            req_url = req.url
            # Look for m3u8 URLs
            if '.m3u8' in req_url.lower() and not captured:
                captured = req_url
                log(f"  Network capture: {captured[:80]}...")
        except Exception:
            pass
    
    context.on("request", on_request)  # Use request instead of requestfinished for earlier capture
    
    try:
        # Navigate to page
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        except PlaywrightTimeoutError:
            pass
        
        # Wait for page to stabilize
        await page.wait_for_timeout(3000)
        
        # Try to find and click play buttons
        play_selectors = [
            "button:has-text('Play')",
            "button:has-text('Watch')",
            "button:has-text('Stream')",
            "button:has-text('Live')",
            "a:has-text('Play')",
            "a:has-text('Watch')",
            ".play-button",
            ".stream-button",
            ".watch-button",
            "button.vjs-big-play-button",
            ".vjs-big-play-button",
            "[aria-label='Play']",
            ".player-button"
        ]
        
        for selector in play_selectors:
            try:
                if await page.locator(selector).count() > 0:
                    await page.locator(selector).first.click()
                    log(f"  Clicked: {selector}")
                    await page.wait_for_timeout(2000)
                    break
            except Exception:
                pass
        
        # Click anywhere to trigger autoplay (some players need this)
        try:
            await page.mouse.click(400, 300)
            await page.wait_for_timeout(1000)
        except Exception:
            pass
        
        # Check all iframes
        frames = page.frames
        for i, frame in enumerate(frames):
            try:
                # Try to click inside iframe
                await frame.click("body", timeout=2000)
                await page.wait_for_timeout(1000)
            except Exception:
                pass
            
            # Get iframe content
            try:
                frame_html = await frame.content()
                # Search for m3u8 in iframe
                m3u8_matches = re.findall(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', frame_html)
                if m3u8_matches:
                    captured = m3u8_matches[0]
                    log(f"  Found in iframe {i}")
                    break
            except Exception:
                pass
        
        # Wait for stream capture with longer timeout
        waited = 0.0
        while waited < 20 and not captured:
            await asyncio.sleep(0.5)
            waited += 0.5
        
        # -------------------------------------------------
        # HTML FALLBACK - Search entire page content
        # -------------------------------------------------
        if not captured:
            html = await page.content()
            
            # Look for m3u8 URLs
            m3u8_matches = re.findall(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', html)
            if m3u8_matches:
                captured = m3u8_matches[0]
                log(f"  Found in HTML")
        
        # -------------------------------------------------
        # SCRIPT TAG FALLBACK - Look for stream URLs in JavaScript
        # -------------------------------------------------
        if not captured:
            # Look for source URLs in script tags
            script_patterns = [
                r'source:\s*["\']([^"\']+\.m3u8[^"\']*)["\']',
                r'file:\s*["\']([^"\']+\.m3u8[^"\']*)["\']',
                r'src:\s*["\']([^"\']+\.m3u8[^"\']*)["\']',
                r'url:\s*["\']([^"\']+\.m3u8[^"\']*)["\']',
                r'stream:\s*["\']([^"\']+\.m3u8[^"\']*)["\']',
                r'video:\s*["\']([^"\']+\.m3u8[^"\']*)["\']',
                r'["\'](https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*)["\']'
            ]
            
            html = await page.content()
            for pattern in script_patterns:
                matches = re.findall(pattern, html, re.IGNORECASE)
                if matches:
                    captured = matches[0]
                    log(f"  Found in script")
                    break
        
        # -------------------------------------------------
        # BASE64 FALLBACK
        # -------------------------------------------------
        if not captured:
            html = await page.content()
            # Look for base64 encoded strings
            b64_pattern = r'["\']([A-Za-z0-9+/=]{50,300})["\']'
            for b64_match in re.finditer(b64_pattern, html):
                b64_str = b64_match.group(1)
                try:
                    decoded = base64.b64decode(b64_str).decode('utf-8', errors='ignore')
                    if '.m3u8' in decoded:
                        # Extract URL from decoded string
                        url_match = re.search(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', decoded)
                        if url_match:
                            captured = url_match.group(0)
                            log(f"  Found in base64")
                            break
                except Exception:
                    pass
    
    finally:
        # Cleanup
        try:
            context.remove_listener("request", on_request)
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
