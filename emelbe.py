#!/usr/bin/env python3

import asyncio
import re
import base64
import json
from urllib.parse import urljoin, quote_plus

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from selectolax.lexbor import LexborHTMLParser as HTMLParser

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
        await page.goto(HOMEPAGE, wait_until="networkidle", timeout=30000)
        
        try:
            await page.wait_for_selector("table#mtable, tr.singele_match_date", timeout=15000)
        except Exception:
            await page.wait_for_timeout(5000)
        
        await page.wait_for_timeout(3000)
        html = await page.content()

    finally:
        await page.close()
        await context.close()
        await browser.close()

    soup = HTMLParser(html)
    events = []
    
    rows = soup.css("tr.singele_match_date")
    log(f"Found {len(rows)} match rows")
    
    for row in rows:
        if not (vs_node := row.css_first("td.teamvs a")):
            continue

        event_name = vs_node.text(strip=True)

        for span in vs_node.css("span.mtdate"):
            date = span.text(strip=True)
            event_name = event_name.replace(date, "").strip()

        if not (href := vs_node.attributes.get("href")):
            continue

        event = fix_event(event_name)
        
        logo = DEFAULT_LOGO
        if logo_td := row.css_first("td.teamlogo img"):
            if src := logo_td.attributes.get("src"):
                logo = src

        events.append({
            "url": urljoin(HOMEPAGE, href),
            "event": event,
            "logo": logo
        })
        
        log(f"  Found event: {event}")

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
    captured_response = None
    
    # Monitor network requests for m3u8
    def on_response(response):
        nonlocal captured
        nonlocal captured_response
        try:
            req_url = response.url
            # Check for m3u8 in response URL
            if '.m3u8' in req_url.lower() and not captured:
                captured = req_url
                captured_response = response
                log(f"  ✓ CAPTURED via network: {req_url[:100]}...")
        except Exception:
            pass
    
    page.on("response", on_response)
    
    try:
        log(f"  Loading: {url}")
        
        # Navigate to page
        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
        except PlaywrightTimeoutError:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        
        await page.wait_for_timeout(3000)
        
        # Find the main iframe
        iframes = await page.query_selector_all("iframe")
        log(f"  Found {len(iframes)} iframes")
        
        # Look for the specific iframe with name="srcFrame"
        main_iframe = None
        for iframe in iframes:
            try:
                name = await iframe.get_attribute("name")
                src = await iframe.get_attribute("src")
                if name == "srcFrame" or (src and "stream" in src.lower()):
                    main_iframe = iframe
                    log(f"  Found main iframe: {src}")
                    break
            except Exception:
                pass
        
        # If we found the main iframe, navigate to it
        if main_iframe:
            try:
                src = await main_iframe.get_attribute("src")
                if src and src != "about:blank":
                    # Navigate to iframe src
                    log(f"  Navigating to iframe: {src}")
                    await page.goto(src, wait_until="domcontentloaded", timeout=15000)
                    await page.wait_for_timeout(3000)
                    
                    # Get iframe content and look for m3u8
                    html = await page.content()
                    
                    # Look for Clappr data
                    clappr_pattern = re.compile(r'var\s+\w*=\[([^"]*)\];', re.I)
                    match = clappr_pattern.search(html)
                    
                    if match:
                        try:
                            # Parse the Clappr data
                            values = eval(match[1])
                            if len(values) >= 3:
                                ev_id, ev_ts, ev_pt = values[:3]
                                log(f"  Found Clappr data: id={ev_id}, ts={ev_ts}, pt={ev_pt}")
                                
                                # Try to get stream from API
                                api_url = f"https://mlbwebcast.com/stream/check_stream.php?id={ev_id}&ts={ev_ts}&pt={ev_pt}"
                                log(f"  Calling API: {api_url}")
                                
                                try:
                                    # Make API request through page
                                    result = await page.evaluate(f'''
                                        async () => {{
                                            try {{
                                                const response = await fetch('{api_url}', {{
                                                    headers: {{
                                                        'Referer': '{src}',
                                                        'User-Agent': '{USER_AGENT}'
                                                    }}
                                                }});
                                                const data = await response.json();
                                                return data;
                                            }} catch(e) {{
                                                return null;
                                            }}
                                        }}
                                    ''')
                                    
                                    if result and result.get('url'):
                                        captured = result['url']
                                        log(f"  ✓ CAPTURED via API: {captured[:100]}...")
                                except Exception as e:
                                    log(f"  API call failed: {e}")
                        except Exception as e:
                            log(f"  Clappr parsing failed: {e}")
                    
                    # Search for m3u8 in iframe content
                    if not captured:
                        m3u8_patterns = [
                            r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*',
                            r'https?://[^\s"\'<>]*b-cdn\.net[^\s"\'<>]*\.m3u8[^\s"\'<>]*',
                            r'https?://[^\s"\'<>]*cloudfront\.net[^\s"\'<>]*\.m3u8[^\s"\'<>]*',
                        ]
                        for pattern in m3u8_patterns:
                            matches = re.findall(pattern, html, re.IGNORECASE)
                            for match in matches:
                                if not captured:
                                    captured = match
                                    log(f"  ✓ CAPTURED via HTML: {captured[:100]}...")
                                    break
                            if captured:
                                break
            except Exception as e:
                log(f"  Iframe navigation error: {e}")
        
        # If still not captured, try to find m3u8 in the page content
        if not captured:
            html = await page.content()
            
            # Look for m3u8 URLs in various patterns
            patterns = [
                r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*',
                r'https?://[^\s"\'<>]*b-cdn\.net[^\s"\'<>]*\.m3u8[^\s"\'<>]*',
                r'https?://[^\s"\'<>]*cloudfront\.net[^\s"\'<>]*\.m3u8[^\s"\'<>]*',
                r'["\'](https?://[^"\']+\.m3u8[^"\']*)["\']'
            ]
            
            for pattern in patterns:
                matches = re.findall(pattern, html, re.IGNORECASE)
                for match in matches:
                    if not captured:
                        captured = match
                        log(f"  ✓ CAPTURED via HTML: {captured[:100]}...")
                        break
                if captured:
                    break
            
            # Look for base64 encoded streams
            if not captured:
                b64_matches = re.findall(r'["\']([A-Za-z0-9+/=]{80,500})["\']', html)
                for b64_str in b64_matches:
                    try:
                        decoded = base64.b64decode(b64_str).decode('utf-8', errors='ignore')
                        url_match = re.search(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', decoded)
                        if url_match and not captured:
                            captured = url_match.group(0)
                            log(f"  ✓ CAPTURED via base64: {captured[:100]}...")
                            break
                    except Exception:
                        pass
        
        # Wait a bit more for network responses
        if not captured:
            log(f"  Monitoring for stream (max 45s)...")
            waited = 0
            while waited < 45 and not captured:
                await asyncio.sleep(2)
                waited += 2
                
                # Check for any new m3u8 in network
                if not captured:
                    html = await page.content()
                    patterns = [
                        r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*',
                        r'https?://[^\s"\'<>]*b-cdn\.net[^\s"\'<>]*\.m3u8[^\s"\'<>]*',
                    ]
                    for pattern in patterns:
                        matches = re.findall(pattern, html, re.IGNORECASE)
                        for match in matches:
                            if not captured:
                                captured = match
                                log(f"  ✓ CAPTURED during monitoring: {captured[:100]}...")
                                break
                        if captured:
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
                f'tvg-logo="{e["logo"]}" '
                f'group-title="{GROUP_TITLE}",{safe_name}\n'
            )
            f.write(
                f"{e['m3u8']}|referer={HOMEPAGE}|origin={HOMEPAGE}|user-agent={ua_encoded}\n\n"
            )
    
    log(f"\nPlaylists saved: {OUTPUT_VLC} / {OUTPUT_TIVI}")

# -------------------------------------------------
async def main():
    log("Starting MLB Webcast Updater...")
    
    async with async_playwright() as p:
        events = await fetch_events_via_playwright(p)
        log(f"Found {len(events)} total events")
        
        if not events:
            log("No events detected")
            return
        
        collected = []
        
        for i, ev in enumerate(events, 1):
            log(f"\n[{i}/{len(events)}] {ev['event']}")
            m3u8 = await capture_m3u8_from_page(p, ev["url"])
            
            if m3u8:
                log(f"   ✓ STREAM CAPTURED")
                ev["m3u8"] = m3u8
                collected.append(ev)
            else:
                log(f"   ✗ No stream found")
    
    if not collected:
        log("\nNo streams captured.")
        return
    
    log(f"\nCaptured {len(collected)}/{len(events)} streams")
    write_playlists(collected)

# -------------------------------------------------
if __name__ == "__main__":
    asyncio.run(main())
