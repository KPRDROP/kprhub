#!/usr/bin/env python3

import asyncio
import re
import base64
from urllib.parse import urljoin, quote_plus

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from selectolax.parser import HTMLParser

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

# -------------------------------------------------
def fix_event(s: str) -> str:
    return " vs ".join(s.split("@"))

# -------------------------------------------------
async def fetch_events_via_playwright(playwright):
    """Extract events from homepage using selectolax"""
    browser = await playwright.firefox.launch(headless=True)
    context = await browser.new_context(user_agent=USER_AGENT)
    page = await context.new_page()

    log("Loading homepage…")

    try:
        await page.goto(HOMEPAGE, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)
        html = await page.content()

    finally:
        await page.close()
        await context.close()
        await browser.close()

    soup = HTMLParser(html)
    events = []

    for row in soup.css("tr.singele_match_date"):
        if not (vs_node := row.css_first("td.teamvs a")):
            continue

        event_name = vs_node.text(strip=True)

        # Remove date from event name
        for span in vs_node.css("span.mtdate"):
            date = span.text(strip=True)
            event_name = event_name.replace(date, "").strip()

        if not (href := vs_node.attributes.get("href")):
            continue

        event = fix_event(event_name)
        
        # Get logo from teamlogo td
        logo = DEFAULT_LOGO
        if logo_td := row.css_first("td.teamlogo img"):
            if src := logo_td.attributes.get("src"):
                logo = src

        events.append({
            "url": urljoin(HOMEPAGE, href),
            "event": event,
            "logo": logo
        })

    return events

# -------------------------------------------------
async def capture_m3u8_from_page(playwright, url, timeout_ms=60000):
    """Capture m3u8 stream URL from team page"""
    browser = await playwright.firefox.launch(headless=True)
    context = await browser.new_context(
        user_agent=USER_AGENT,
        viewport={'width': 1280, 'height': 720}
    )
    page = await context.new_page()
    
    captured = None
    
    # Monitor network requests for m3u8
    def on_response(response):
        nonlocal captured
        try:
            req_url = response.url
            if '.m3u8' in req_url.lower() and not captured:
                captured = req_url
                log(f"  ✓ CAPTURED: {captured[:100]}...")
        except Exception:
            pass
    
    context.on("response", on_response)
    
    try:
        log(f"  Loading: {url}")
        
        # Navigate to page
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except PlaywrightTimeoutError:
            pass
        
        await page.wait_for_timeout(5000)
        
        # Find and click any iframe or player element
        # Look for iframes that might contain the stream
        iframes = await page.query_selector_all("iframe")
        log(f"  Found {len(iframes)} iframes")
        
        for iframe in iframes:
            try:
                src = await iframe.get_attribute("src")
                if src and ("stream" in src.lower() or "player" in src.lower() or "embed" in src.lower()):
                    log(f"  Found stream iframe: {src[:80]}")
                    
                    # Navigate to iframe src directly
                    await page.goto(src, wait_until="domcontentloaded", timeout=30000)
                    await page.wait_for_timeout(5000)
                    break
            except Exception:
                pass
        
        # Try to click on video player
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
            ".vjs-control-bar",
            ".mejs__playpause-button"
        ]
        
        for selector in click_selectors:
            try:
                element = await page.query_selector(selector)
                if element:
                    await element.click(timeout=3000)
                    log(f"  Clicked: {selector}")
                    await page.wait_for_timeout(3000)
                    break
            except Exception:
                pass
        
        # Click body to trigger autoplay
        try:
            await page.mouse.click(500, 400)
            await page.wait_for_timeout(2000)
        except Exception:
            pass
        
        # Monitor for m3u8
        waited = 0
        while waited < 45 and not captured:
            await asyncio.sleep(2)
            waited += 2
            
            # Check page content for m3u8
            if waited % 6 == 0:
                html = await page.content()
                
                # Look for m3u8 URLs
                m3u8_matches = re.findall(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', html)
                for match in m3u8_matches:
                    if not captured:
                        captured = match
                        log(f"  ✓ HTML capture: {captured[:100]}...")
                        break
                
                # Look for base64 encoded streams
                b64_matches = re.findall(r'["\']([A-Za-z0-9+/=]{80,500})["\']', html)
                for b64_str in b64_matches:
                    try:
                        decoded = base64.b64decode(b64_str).decode('utf-8', errors='ignore')
                        url_match = re.search(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', decoded)
                        if url_match and not captured:
                            captured = url_match.group(0)
                            log(f"  ✓ Base64 capture: {captured[:100]}...")
                            break
                    except Exception:
                        pass
                
                # Look for b-cdn.net patterns
                bcdn_matches = re.findall(r'https?://[^\s"\'<>]*b-cdn\.net[^\s"\'<>]*\.m3u8[^\s"\'<>]*', html)
                for match in bcdn_matches:
                    if not captured:
                        captured = match
                        log(f"  ✓ CDN capture: {captured[:100]}...")
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
