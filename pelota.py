#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import time
import os
import json
from datetime import datetime, timedelta
from pathlib import Path
from git import Repo
import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
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

MAX_EVENTS = 20
STREAM_TIMEOUT = 30

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
    opts.add_argument("--ignore-certificate-errors")
    opts.add_argument("--ignore-ssl-errors")
    opts.add_argument("--allow-running-insecure-content")
    opts.add_argument(f"--user-agent={DEFAULT_USER_AGENT}")
    
    # Enable performance logging to capture network requests
    opts.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=opts)
        driver.set_page_load_timeout(30)
        driver.set_script_timeout(30)
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
        r = requests.get(ROJA_URL, timeout=15, headers=headers, verify=False)
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
def get_network_requests(driver):
    """Extract all network requests from performance logs"""
    requests_list = []
    try:
        logs = driver.get_log("performance")
        for entry in logs:
            try:
                log_data = json.loads(entry["message"])
                message = log_data.get("message", {})
                method = message.get("method", "")
                
                # Look for network responses
                if method == "Network.responseReceived":
                    response = message.get("params", {}).get("response", {})
                    url = response.get("url", "")
                    if url:
                        requests_list.append({
                            "url": url,
                            "status": response.get("status", 0),
                            "mimeType": response.get("mimeType", ""),
                            "headers": response.get("headers", {})
                        })
            except:
                continue
    except:
        pass
    return requests_list

def extract_m3u8(event_info):
    """Extract m3u8 stream using performance logs"""
    url = event_info['url']
    partido = event_info['partido']
    channel = event_info['channel']
    
    drv = None
    try:
        print(f"  [{channel}] Loading page...")
        drv = init_driver()
        
        # Load the page
        try:
            drv.get(url)
        except Exception as e:
            print(f"  [{channel}] Page load warning: {str(e)[:80]}")
        
        time.sleep(4)
        
        # Clear performance logs from initial page load
        try:
            drv.get_log("performance")
        except:
            pass
        
        # Try to click play buttons
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
                    "div[class*='play']"
                ]
                
                for selector in selectors:
                    try:
                        elements = drv.find_elements(By.CSS_SELECTOR, selector)
                        for el in elements[:3]:
                            if el.is_displayed():
                                drv.execute_script("arguments[0].click();", el)
                                time.sleep(0.5)
                    except:
                        pass
                
                # Handle iframes
                iframes = drv.find_elements(By.TAG_NAME, "iframe")
                for iframe in iframes[:3]:
                    try:
                        drv.switch_to.frame(iframe)
                        drv.execute_script("""
                            var videos = document.querySelectorAll('video');
                            videos.forEach(function(v) { 
                                v.play(); 
                                v.click();
                                v.muted = true;
                            });
                            var buttons = document.querySelectorAll('button, [class*="play"], .vjs-big-play-button');
                            buttons.forEach(function(b) { b.click(); });
                        """)
                        drv.switch_to.default_content()
                        time.sleep(1)
                    except:
                        drv.switch_to.default_content()
                        
            except:
                pass
            
            time.sleep(1.5)
        
        # Search for m3u8 requests in performance logs
        print(f"  [{channel}] Searching for stream...")
        start_time = time.time()
        found_urls = set()
        
        while time.time() - start_time < STREAM_TIMEOUT:
            try:
                network_requests = get_network_requests(driver=drv)
                
                for req in network_requests:
                    req_url = req.get("url", "")
                    
                    # Look for m3u8 URLs
                    if ".m3u8" not in req_url:
                        continue
                        
                    # Filter out unwanted URLs
                    if any(x in req_url.lower() for x in ['google', 'analytics', 'facebook', 'doubleclick', 'googletagmanager']):
                        continue
                    
                    # Skip duplicates
                    if req_url in found_urls:
                        continue
                    
                    found_urls.add(req_url)
                    
                    # Get headers from the request if available
                    req_headers = req.get("headers", {})
                    
                    result = {
                        "url": req_url,
                        "referer": req_headers.get("Referer", FORCED_REFERER) or FORCED_REFERER,
                        "origin": req_headers.get("Origin", FORCED_ORIGIN) or FORCED_ORIGIN,
                        "user_agent": req_headers.get("User-Agent", DEFAULT_USER_AGENT) or DEFAULT_USER_AGENT,
                    }
                    
                    print(f"  [{channel}] ✓ Stream found!")
                    print(f"    URL: {req_url[:120]}")
                    
                    return result
                    
            except:
                pass
            time.sleep(1)
        
        print(f"  [{channel}] ✗ Timeout - no stream found")
        
    except Exception as e:
        print(f"  [{channel}] Error: {str(e)[:150]}")
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
        
        time.sleep(3)
    
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
