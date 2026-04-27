#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import time
import os
from datetime import datetime, timedelta
from pathlib import Path
from git import Repo
import requests
from bs4 import BeautifulSoup
from seleniumwire import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from urllib.parse import quote, urlparse
import warnings
warnings.filterwarnings("ignore")

# ───────── CONFIG ─────────
ROJA_URL = "https://www.rojadirectaenvivo.pl/"
ROJA_BASE = "https://rojadirectablog.com"

# Forced headers for all streams
FORCED_REFERER = "https://capo7play.com/"
FORCED_ORIGIN = "https://capo7play.com"

REPO_DIR = Path(__file__).parent
EVENT_FILE = "eventos.m3u8"
TIVIMATE_FILE = "eventos_tivimate.m3u8"

MAX_EVENTS = 20  # Process more events since we scan all channels
STREAM_TIMEOUT = 25  # Max seconds to wait for stream per event

# Default user agent (will be URL encoded for Tivimate)
DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36 Edg/134.0.0.0"

EXCLUDED_LEAGUES = [
    #"NBA"
]

# ───────── DRIVER ─────────
def init_driver():
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--disable-logging")
    opts.add_argument("--log-level=3")
    opts.add_argument("--disable-background-networking")
    opts.add_argument("--disable-sync")
    opts.add_argument("--disable-translate")
    opts.add_argument("--mute-audio")
    opts.add_argument(f"--user-agent={DEFAULT_USER_AGENT}")
    
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=opts)
        driver.set_page_load_timeout(25)
        driver.set_script_timeout(25)
        return driver
    except:
        return webdriver.Chrome(options=opts)

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
    """Parse time string to datetime object"""
    try:
        now = datetime.now()
        hour, minute = map(int, time_str.split(':'))
        event_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return event_time
    except:
        return None

def is_event_live_or_soon(event_time, threshold_minutes=30):
    """Check if event is live or starting soon"""
    if not event_time:
        return False
    
    now = datetime.now()
    diff = (event_time - now).total_seconds() / 60
    
    # Event is within threshold (started within last 120 min or starts within threshold)
    return -120 <= diff <= threshold_minutes

# ───────── SCRAPER ─────────
def get_roja_events():
    """Extract ALL first channel links from each event"""
    events = []
    try:
        print(f"Fetching events from: {ROJA_URL}")
        headers = {
            'User-Agent': DEFAULT_USER_AGENT
        }
        r = requests.get(ROJA_URL, timeout=15, headers=headers)
        soup = BeautifulSoup(r.text, "html.parser")

        # Find all menu items
        menu_items = soup.select("ul.menu > li")
        print(f"Found {len(menu_items)} events on page")
        
        for li in menu_items:
            # Get time
            t = li.find("span", class_="t")
            if not t:
                continue
            hora = t.text.strip()

            # Get main event link
            link = li.find("a", recursive=False)
            if not link:
                continue

            raw = link.text.strip()
            if hora in raw:
                raw = raw.replace(hora, "").strip()

            if ":" not in raw:
                continue

            # Split league and match
            parts = raw.split(":", 1)
            if len(parts) != 2:
                continue
                
            liga, partido = parts[0].strip(), parts[1].strip()

            # Get ALL first channel links (subitem1) from <ul>
            subitem_links = li.select("ul > li.subitem1 > a")
            if not subitem_links:
                continue
            
            # Process each subitem1 link
            for channel_link in subitem_links:
                href = normalize(channel_link.get("href"))
                channel_name = channel_link.text.strip()
                
                if href:
                    event_time = parse_time(hora)
                    events.append({
                        'liga': liga,
                        'hora': hora,
                        'partido': partido,
                        'channel': channel_name,
                        'url': href,
                        'time_obj': event_time
                    })

        print(f"Extracted {len(events)} stream links")

    except Exception as e:
        print(f"Error scraping: {e}")
    
    return events

# ───────── STREAM EXTRACTION ─────────
def extract_m3u8(event_info):
    """Extract m3u8 stream with forced capo7play headers"""
    url = event_info['url']
    partido = event_info['partido']
    channel = event_info['channel']
    
    drv = None
    try:
        print(f"  [{channel}] Loading page...")
        drv = init_driver()
        drv.get(url)
        time.sleep(3)
        
        # Clear any previous requests
        try:
            del drv.requests
        except:
            pass
        
        # Click play buttons aggressively
        for attempt in range(4):
            try:
                # Try multiple selectors for play buttons
                selectors = [
                    "button[class*='play']",
                    ".vjs-big-play-button", 
                    "button",
                    "video",
                    "[class*='play']",
                    ".play-button",
                    "div[class*='play']",
                    "[onclick*='play']"
                ]
                
                for selector in selectors:
                    try:
                        elements = drv.find_elements(By.CSS_SELECTOR, selector)
                        for el in elements[:3]:
                            if el.is_displayed():
                                drv.execute_script("arguments[0].click();", el)
                                time.sleep(0.3)
                    except:
                        pass
                
                # Handle iframes - switch and click inside
                iframes = drv.find_elements(By.TAG_NAME, "iframe")
                for iframe in iframes:
                    try:
                        drv.switch_to.frame(iframe)
                        # Try to play video or click buttons inside iframe
                        drv.execute_script("""
                            var videos = document.querySelectorAll('video');
                            videos.forEach(function(v) { 
                                v.play(); 
                                v.click();
                                v.muted = true;
                            });
                            var buttons = document.querySelectorAll('button, [class*="play"], .vjs-big-play-button, div[onclick]');
                            buttons.forEach(function(b) { 
                                b.click(); 
                            });
                            // Try to click anywhere on the page
                            document.body.click();
                        """)
                        drv.switch_to.default_content()
                        time.sleep(1)
                    except:
                        drv.switch_to.default_content()
                        
            except:
                pass
            
            time.sleep(1.5)
        
        # Search for m3u8 requests
        print(f"  [{channel}] Searching for stream...")
        start_time = time.time()
        found_urls = set()
        
        while time.time() - start_time < STREAM_TIMEOUT:
            try:
                for req in drv.requests:
                    if not req.response:
                        continue
                        
                    req_url = req.url
                    
                    # Only process m3u8 URLs
                    if ".m3u8" not in req_url:
                        continue
                        
                    # Filter out unwanted URLs
                    if any(x in req_url.lower() for x in ['google', 'analytics', 'facebook', 'doubleclick', 'googletagmanager']):
                        continue
                    
                    # Skip duplicates
                    if req_url in found_urls:
                        continue
                    
                    found_urls.add(req_url)
                    
                    # Use FORCED headers
                    result = {
                        "url": req_url,
                        "referer": FORCED_REFERER,
                        "origin": FORCED_ORIGIN,
                        "user_agent": DEFAULT_USER_AGENT,
                    }
                    
                    print(f"  [{channel}] ✓ Stream found!")
                    print(f"    URL: {req_url[:100]}")
                    
                    return result
                    
            except:
                pass
            time.sleep(1)
        
        print(f"  [{channel}] ✗ Timeout - no stream found")
        
    except Exception as e:
        print(f"  [{channel}] Error: {str(e)[:100]}")
    finally:
        if drv:
            try:
                drv.quit()
            except:
                pass

    return None

# ───────── HEADERS FORMAT ─────────
def vlc_headers(r):
    """Format headers for VLC"""
    h = []
    if r.get("referer"):
        h.append(f'#EXTVLCOPT:http-referrer={r["referer"]}')
    if r.get("origin"):
        h.append(f'#EXTVLCOPT:http-origin={r["origin"]}')
    if r.get("user_agent"):
        h.append(f'#EXTVLCOPT:http-user-agent={r["user_agent"]}')
    return h

def tivimate_url(r):
    """Format URL with pipe headers for Tivimate"""
    params = []
    if r.get("referer"):
        params.append(f"referer={r['referer']}")
    if r.get("origin"):
        params.append(f"origin={r['origin']}")
    if r.get("user_agent"):
        # URL encode the user agent
        params.append(f"user-agent={quote(r['user_agent'])}")
    
    if params:
        return r["url"] + "|" + "|".join(params)
    return r["url"]

# ───────── MAIN ─────────
def main():
    print("=" * 60)
    print("ROJADIRECTA STREAM SCRAPER")
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"Time: {current_time}")
    print("=" * 60)
    
    # Get ALL events (no filtering)
    all_events = get_roja_events()
    
    if not all_events:
        print("No events found!")
        return
    
    print(f"\nTotal events found: {len(all_events)}")
    
    # OPTIONAL: filter excluded leagues
    if EXCLUDED_LEAGUES:
        all_events = [
            e for e in all_events
            if not any(x.lower() in e['liga'].lower() for x in EXCLUDED_LEAGUES)
        ]
    
    # Sort by time
    all_events.sort(key=lambda x: (x['hora'], x['liga']))
    
    # REMOVE duplicate matches (keep first channel only)
    seen_matches = set()
    unique_events = []
    
    for e in all_events:
        match_key = (e['hora'], e['liga'], e['partido'])
        if match_key not in seen_matches:
            seen_matches.add(match_key)
            unique_events.append(e)
    
    # Limit total processed events (optional safety)
    events_to_process = unique_events[:MAX_EVENTS]
    
    print(f"Events to process: {len(events_to_process)}")
    
    if not events_to_process:
        print("No events to process!")
        (REPO_DIR / EVENT_FILE).write_text("#EXTM3U\n", encoding='utf-8')
        (REPO_DIR / TIVIMATE_FILE).write_text("#EXTM3U\n", encoding='utf-8')
        return
    
    # Show events
    for e in events_to_process:
        print(f"  {e['hora']} | {e['liga']}: {e['partido']} -> {e['channel']}")
    
    # Prepare output
    entries = ["#EXTM3U"]
    tivimate = ["#EXTM3U"]
    
    successful = 0
    
    # ───── PROCESS ALL EVENTS ─────
    for idx, event in enumerate(events_to_process, 1):
        print(f"\n[{idx}/{len(events_to_process)}] {event['hora']} - {event['partido']} ({event['channel']})")
        
        try:
            result = extract_m3u8(event)
            
            if result:
                liga = event['liga']
                hora = event['hora']
                partido = event['partido']
                
                title = f"{hora} {liga} - {partido}"
                
                # VLC
                entries.append(f'#EXTINF:-1 group-title="{liga}",{title}')
                entries += vlc_headers(result)
                entries.append(result["url"])
                
                # Tivimate
                tivimate.append(f'#EXTINF:-1 group-title="{liga}",{title}')
                tivimate.append(tivimate_url(result))
                
                successful += 1
                print(f"  ✓ Added")
            else:
                print(f"  ✗ No stream")
                
        except Exception as e:
            print(f"  ✗ Error: {str(e)[:100]}")
        
        time.sleep(2)
    
    # ───── SAVE FILES ─────
    print(f"\n{'=' * 60}")
    print(f"Results: {successful}/{len(events_to_process)} streams captured")
    
    try:
        (REPO_DIR / EVENT_FILE).write_text("\n".join(entries), encoding='utf-8')
        (REPO_DIR / TIVIMATE_FILE).write_text("\n".join(tivimate), encoding='utf-8')
        
        print(f"Files written:")
        print(f"  - {EVENT_FILE}")
        print(f"  - {TIVIMATE_FILE}")
        
    except Exception as e:
        print(f"Error writing files: {e}")
    
    # ───── GIT PUSH ─────
    if successful > 0:
        try:
            repo = Repo(REPO_DIR)
            repo.git.add(A=True)
            repo.index.commit(f"Update {current_time} - {successful} streams")
            repo.remote().push()
            print("✓ Pushed to git")
        except Exception as e:
            print(f"Git error: {e}")
    else:
        print("No streams to push")

if __name__ == "__main__":
    main()
