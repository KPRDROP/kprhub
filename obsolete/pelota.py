#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import time
import os
import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from git import Repo
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote, urlparse
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
import warnings
warnings.filterwarnings("ignore")

# Disable SSL warnings
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ───────── CONFIG ─────────
ROJA_URL = "https://www.rojadirectaenvivo.pl/"
ROJA_BASE = "https://rojadirectablog.com"

# Forced headers for all streams
FORCED_REFERER = "https://capo7play.com/"
FORCED_ORIGIN = "https://capo7play.com"

REPO_DIR = Path(__file__).parent
EVENT_FILE = "eventos.m3u8"
TIVIMATE_FILE = "eventos_tivimate.m3u8"

MAX_EVENTS = 20
STREAM_TIMEOUT = 30  # seconds per event

# Default user agent
DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"

EXCLUDED_LEAGUES = []

# ───────── HELPERS ─────────
def normalize(url, base=ROJA_BASE):
    if not url or url.startswith('#'):
        return ''
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return base + url
    if not url.startswith("http"):
        return base + "/" + url
    return url

def parse_time(time_str):
    try:
        now = datetime.now()
        hour, minute = map(int, time_str.split(':'))
        event_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return event_time
    except:
        return None

# ───────── SCRAPER ─────────
def get_roja_events():
    """Extract ONLY first channel links (Canal 1) from each event"""
    events = []
    try:
        print(f"Fetching events from: {ROJA_URL}")
        headers = {'User-Agent': DEFAULT_USER_AGENT}
        r = requests.get(ROJA_URL, timeout=15, headers=headers, verify=False)
        soup = BeautifulSoup(r.text, "html.parser")

        menu_items = soup.select("ul.menu > li")
        print(f"Found {len(menu_items)} events on page")
        
        for li in menu_items:
            t = li.find("span", class_="t")
            if not t:
                continue
            hora = t.text.strip()

            link = li.find("a", recursive=False)
            if not link:
                continue

            raw = link.text.strip()
            if hora in raw:
                raw = raw.replace(hora, "").strip()

            if ":" not in raw:
                continue

            parts = raw.split(":", 1)
            if len(parts) != 2:
                continue
                
            liga, partido = parts[0].strip(), parts[1].strip()

            first_channel = li.select_one("ul > li.subitem1 > a")
            if not first_channel:
                continue
            
            href = normalize(first_channel.get("href"))
            channel_name = first_channel.text.strip()
            
            if href and "Canal 1" in channel_name:
                event_time = parse_time(hora)
                events.append({
                    'liga': liga,
                    'hora': hora,
                    'partido': partido,
                    'channel': channel_name,
                    'url': href,
                    'time_obj': event_time
                })

        print(f"Extracted {len(events)} Canal 1 stream links")
    except Exception as e:
        print(f"Error scraping: {e}")
    
    return events

# ───────── PLAYWRIGHT STREAM EXTRACTION ─────────

async def capture_stream(page: Page, url: str) -> str | None:
    """
    Load the event page, navigate through iframes to capo7play,
    click play, and capture the m3u8 URL from network requests.
    """
    captured_m3u8 = []
    
    async def handle_request(request):
        """Intercept network requests to find m3u8"""
        req_url = request.url
        if ".m3u8" in req_url:
            bad_domains = ["google", "doubleclick", "facebook", "analytics", "googletagmanager", "gstatic"]
            if not any(x in req_url.lower() for x in bad_domains):
                if req_url not in captured_m3u8:
                    captured_m3u8.append(req_url)
                    print(f"    Captured: {req_url[:150]}")
    
    async def handle_response(response):
        """Also check responses for m3u8"""
        resp_url = response.url
        if ".m3u8" in resp_url:
            bad_domains = ["google", "doubleclick", "facebook", "analytics", "googletagmanager", "gstatic"]
            if not any(x in resp_url.lower() for x in bad_domains):
                if resp_url not in captured_m3u8:
                    captured_m3u8.append(resp_url)
                    print(f"    Captured response: {resp_url[:150]}")
    
    # Attach network listeners
    page.on("request", handle_request)
    page.on("response", handle_response)
    
    try:
        # Load the rojadirectablog event page
        print(f"  Loading: {url}")
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        
        # Wait for iframes to load
        await asyncio.sleep(3)
        
        # Try to click play in all iframes
        for attempt in range(8):
            try:
                # Get all frames (including nested ones)
                frames = page.frames
                
                for frame in frames:
                    try:
                        # Try to click play buttons
                        await frame.evaluate("""
                            () => {
                                // Play all videos
                                var videos = document.querySelectorAll('video');
                                videos.forEach(function(v) { 
                                    v.muted = true; 
                                    v.play();
                                    v.setAttribute('autoplay', 'true');
                                });
                                
                                // Click all possible play buttons
                                var selectors = [
                                    'button',
                                    '[class*="play"]',
                                    '.vjs-big-play-button',
                                    '[aria-label*="play" i]',
                                    '.plyr__control--overlaid',
                                    'video',
                                    '[onclick]',
                                    'div[class*="player"]'
                                ];
                                
                                selectors.forEach(function(sel) {
                                    try {
                                        var els = document.querySelectorAll(sel);
                                        els.forEach(function(el) {
                                            el.click();
                                            el.dispatchEvent(new MouseEvent('click', {bubbles: true}));
                                        });
                                    } catch(e) {}
                                });
                                
                                // Click center of page
                                var el = document.elementFromPoint(window.innerWidth/2, window.innerHeight/2);
                                if (el) {
                                    el.click();
                                    el.dispatchEvent(new MouseEvent('click', {bubbles: true}));
                                }
                            }
                        """)
                    except:
                        pass
            except:
                pass
            
            await asyncio.sleep(2)
            
            # Check if we already have tokenized m3u8
            tokenized = [u for u in captured_m3u8 if "md5=" in u or "expires=" in u or "token=" in u]
            if tokenized:
                return tokenized[0]
            
            # Check if we have any m3u8 with params
            valid = [u for u in captured_m3u8 if "?" in u]
            if valid:
                return valid[0]
        
        # Wait additional time for streams to load
        await asyncio.sleep(5)
        
        # Final check
        tokenized = [u for u in captured_m3u8 if "md5=" in u or "expires=" in u or "token=" in u]
        if tokenized:
            return tokenized[0]
        
        valid = [u for u in captured_m3u8 if "?" in u]
        if valid:
            return valid[0]
        
        if captured_m3u8:
            return captured_m3u8[0]
        
        print(f"  Total m3u8 found: {len(captured_m3u8)}")
        for u in captured_m3u8:
            print(f"    - {u[:150]}")
        
    except Exception as e:
        print(f"  Page error: {str(e)[:100]}")
    finally:
        page.remove_listener("request", handle_request)
        page.remove_listener("response", handle_response)
    
    return None


async def extract_m3u8_async(context: BrowserContext, event_info: dict) -> dict | None:
    """Extract m3u8 stream from event page using Playwright"""
    url = event_info['url']
    partido = event_info['partido']
    
    page = None
    try:
        page = await context.new_page()
        
        stream_url = await capture_stream(page, url)
        
        if stream_url:
            print(f"  ✓ Stream captured!")
            print(f"    URL: {stream_url}")
            
            return {
                "url": stream_url,
                "referer": FORCED_REFERER,
                "origin": FORCED_ORIGIN,
                "user_agent": DEFAULT_USER_AGENT,
            }
        else:
            print(f"  ✗ No stream found")
            
    except Exception as e:
        print(f"  Error: {str(e)[:150]}")
    finally:
        if page:
            await page.close()
    
    return None


async def process_all_events(events_to_process: list) -> tuple[list, list, int]:
    """Process all events using a single browser instance"""
    entries = ["#EXTM3U"]
    tivimate = ["#EXTM3U"]
    successful = 0
    
    async with async_playwright() as p:
        # Launch browser with specific args for headless environment
        browser = await p.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu',
                '--disable-web-security',
                '--ignore-certificate-errors',
                '--autoplay-policy=no-user-gesture-required',
                '--mute-audio',
            ]
        )
        
        context = await browser.new_context(
            user_agent=DEFAULT_USER_AGENT,
            viewport={'width': 1920, 'height': 1080},
            ignore_https_errors=True,
            bypass_csp=True,
        )
        
        try:
            for idx, event in enumerate(events_to_process, 1):
                print(f"\n[{idx}/{len(events_to_process)}] {event['hora']} - {event['partido']}")
                
                result = await extract_m3u8_async(context, event)
                
                if result:
                    liga = event['liga']
                    hora = event['hora']
                    partido = event['partido']
                    title = f"{hora} {liga} - {partido}"
                    
                    # VLC format
                    entries.append(f'#EXTINF:-1 group-title="{liga}",{title}')
                    if result.get("referer"):
                        entries.append(f'#EXTVLCOPT:http-referrer={result["referer"]}')
                    if result.get("origin"):
                        entries.append(f'#EXTVLCOPT:http-origin={result["origin"]}')
                    if result.get("user_agent"):
                        entries.append(f'#EXTVLCOPT:http-user-agent={result["user_agent"]}')
                    entries.append(result["url"])
                    
                    # Tivimate format
                    tivimate.append(f'#EXTINF:-1 group-title="{liga}",{title}')
                    params = []
                    if result.get("referer"):
                        params.append(f"referer={result['referer']}")
                    if result.get("origin"):
                        params.append(f"origin={result['origin']}")
                    if result.get("user_agent"):
                        params.append(f"user-agent={quote(result['user_agent'])}")
                    if params:
                        tivimate.append(f'{result["url"]}|{"|".join(params)}')
                    else:
                        tivimate.append(result["url"])
                    
                    successful += 1
                    print(f"  ✓ Added to playlist")
                else:
                    print(f"  ✗ No stream found")
                
                # Small delay between events
                await asyncio.sleep(2)
                
        finally:
            await context.close()
            await browser.close()
    
    return entries, tivimate, successful


# ───────── GIT PUSH ─────────
def push_to_github(successful: int):
    """Push generated files to GitHub repository.
    When running in GitHub Actions, only writes files (workflow handles staging/push).
    When running locally, does full commit and push.
    """
    is_github_actions = os.getenv("GITHUB_ACTIONS") == "true"
    
    if is_github_actions:
        # In GitHub Actions, just note that files are ready
        # The workflow step will handle git operations
        print("Running in GitHub Actions - files ready for workflow to push")
    else:
        # Running locally - do full commit and push
        try:
            repo = Repo(REPO_DIR)
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # Add files using string paths (not Path objects)
            repo.git.add(EVENT_FILE)
            repo.git.add(TIVIMATE_FILE)
            
            # Add caches if they exist
            caches_dir = REPO_DIR / "caches"
            if caches_dir.exists():
                repo.git.add("caches")
            
            # Check if there are changes
            if repo.is_dirty(untracked_files=True):
                repo.index.commit(f"Update {current_time} - {successful} streams")
                repo.remote("origin").push()
                print("✓ Pushed to git")
            else:
                print("No changes to commit")
        except Exception as e:
            print(f"Git error: {e}")


# ───────── MAIN ─────────
async def main_async():
    print("=" * 60)
    print("ROJADIRECTA STREAM SCRAPER (Playwright)")
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"Time: {current_time}")
    print("=" * 60)
    
    # Get events
    all_events = get_roja_events()
    
    if not all_events:
        print("No events found!")
        return
    
    print(f"\nTotal Canal 1 events found: {len(all_events)}")
    
    # Filter excluded leagues
    if EXCLUDED_LEAGUES:
        all_events = [e for e in all_events if not any(x.lower() in e['liga'].lower() for x in EXCLUDED_LEAGUES)]
    
    # Sort by time
    all_events.sort(key=lambda x: (x['hora'], x['liga']))
    
    # Remove duplicate matches
    seen_matches = set()
    unique_events = []
    for e in all_events:
        match_key = (e['hora'], e['liga'], e['partido'])
        if match_key not in seen_matches:
            seen_matches.add(match_key)
            unique_events.append(e)
    
    events_to_process = unique_events[:MAX_EVENTS]
    print(f"Events to process: {len(events_to_process)}")
    
    if not events_to_process:
        print("No events to process!")
        (REPO_DIR / EVENT_FILE).write_text("#EXTM3U\n", encoding='utf-8')
        (REPO_DIR / TIVIMATE_FILE).write_text("#EXTM3U\n", encoding='utf-8')
        return
    
    for e in events_to_process:
        print(f"  {e['hora']} | {e['liga']}: {e['partido']}")
    
    # Process all events
    entries, tivimate, successful = await process_all_events(events_to_process)
    
    # Save files
    print(f"\n{'=' * 60}")
    print(f"Results: {successful}/{len(events_to_process)} streams captured")
    
    try:
        (REPO_DIR / EVENT_FILE).write_text("\n".join(entries), encoding='utf-8')
        (REPO_DIR / TIVIMATE_FILE).write_text("\n".join(tivimate), encoding='utf-8')
        print(f"Files written:")
        print(f"  - {EVENT_FILE} ({len(entries)-1} entries)")
        print(f"  - {TIVIMATE_FILE} ({len(tivimate)-1} entries)")
        
        if successful > 0:
            print(f"\nSample output:")
            for line in entries[1:6]:
                print(f"  {line[:120]}")
    except Exception as e:
        print(f"Error writing files: {e}")
    
    # Push to GitHub
    if successful > 0:
        push_to_github(successful)
    else:
        print("No streams to push")


def main():
    """Entry point for the script"""
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
