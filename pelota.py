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
STREAM_TIMEOUT = 60  # Increased timeout for stream detection

# Default user agent
DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36"

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
    opts.add_argument("--disable-web-security")
    opts.add_argument("--disable-features=VizDisplayCompositor")
    opts.add_argument("--autoplay-policy=no-user-gesture-required")
    opts.add_argument(f"--user-agent={DEFAULT_USER_AGENT}")
    
    # Enable performance logging to capture ALL network requests
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

# ───────── SCRAPER ─────────
def get_roja_events():
    """Extract ONLY first channel links (Canal 1) from each event"""
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

            # Get ONLY the first channel link (Canal 1) - first subitem1
            first_channel = li.select_one("ul > li.subitem1 > a")
            if not first_channel:
                continue
            
            href = normalize(first_channel.get("href"))
            channel_name = first_channel.text.strip()
            
            # Only process "Canal 1" links
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

# ───────── M3U8 DETECTION ─────────

def is_valid_m3u8(url):
    """Check if URL is a valid m3u8 stream"""
    if not url:
        return False
    if ".m3u8" not in url.lower():
        return False
    
    bad_domains = ["google", "doubleclick", "facebook", "analytics", "googletagmanager", "gstatic"]
    if any(x in url.lower() for x in bad_domains):
        return False
    
    return True

def get_m3u8_from_performance_logs(driver):
    """Extract m3u8 URLs from Chrome performance logs"""
    urls = []
    try:
        logs = driver.get_log("performance")
        for entry in logs:
            try:
                log_data = json.loads(entry["message"])
                message = log_data.get("message", {})
                method = message.get("method", "")
                params = message.get("params", {})
                
                # Check both requests and responses
                if method == "Network.requestWillBeSent":
                    req_url = params.get("request", {}).get("url", "")
                    if is_valid_m3u8(req_url):
                        urls.append(req_url)
                        
                elif method == "Network.responseReceived":
                    res_url = params.get("response", {}).get("url", "")
                    if is_valid_m3u8(res_url):
                        urls.append(res_url)
            except:
                pass
    except:
        pass
    
    return list(dict.fromkeys(urls))

def click_play_in_iframe(driver):
    """Aggressively try to play video in all iframes"""
    try:
        # First try on main page
        driver.execute_script("""
            var videos = document.querySelectorAll('video');
            videos.forEach(function(v) { 
                v.muted = true; 
                v.play(); 
                v.click();
            });
            var buttons = document.querySelectorAll('button, [class*="play"], .vjs-big-play-button, [aria-label*="play" i]');
            buttons.forEach(function(b) { b.click(); });
        """)
    except:
        pass
    
    # Then try in all iframes
    try:
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for i, iframe in enumerate(iframes):
            try:
                driver.switch_to.frame(iframe)
                
                # Try to play video
                driver.execute_script("""
                    var videos = document.querySelectorAll('video');
                    videos.forEach(function(v) { 
                        v.muted = true; 
                        v.play();
                        v.setAttribute('autoplay', 'true');
                    });
                    
                    // Click play buttons
                    var buttons = document.querySelectorAll('button, [class*="play"], .vjs-big-play-button, [aria-label*="play" i], .plyr__control--overlaid');
                    buttons.forEach(function(b) { b.click(); });
                    
                    // Click center of video area
                    var videoArea = document.querySelector('video') || document.querySelector('.video-js') || document.querySelector('[class*="player"]');
                    if (videoArea) {
                        videoArea.click();
                    }
                    
                    // Try to click any element that looks like a play button
                    var allElements = document.querySelectorAll('*');
                    for (var el of allElements) {
                        var cls = (el.className || '').toString().toLowerCase();
                        var txt = (el.textContent || '').toLowerCase();
                        if (cls.indexOf('play') >= 0 || txt.indexOf('play') >= 0) {
                            el.click();
                        }
                    }
                """)
                
                driver.switch_to.default_content()
                time.sleep(1)
            except:
                try:
                    driver.switch_to.default_content()
                except:
                    pass
    except:
        pass

# ───────── STREAM EXTRACTION ─────────

def extract_m3u8(event_info):
    """Extract m3u8 stream from event page"""
    url = event_info['url']
    partido = event_info['partido']

    drv = None

    try:
        print(f"  Loading: {url}")
        drv = init_driver()
        
        # Load the rojadirectablog page with the iframe
        drv.get(url)
        
        # Wait for page to load and iframe to appear
        print(f"  Waiting for page to load...")
        time.sleep(5)
        
        # Clear performance logs from initial page load
        try:
            drv.get_log("performance")
        except:
            pass
        
        # Click play aggressively
        print(f"  Attempting to start video...")
        for attempt in range(6):
            click_play_in_iframe(drv)
            time.sleep(3)
        
        # Now search for m3u8 in network requests
        print(f"  Searching for m3u8 streams...")
        start_time = time.time()
        all_found = []
        
        while time.time() - start_time < STREAM_TIMEOUT:
            # Get m3u8 from performance logs
            m3u8_urls = get_m3u8_from_performance_logs(drv)
            
            for u in m3u8_urls:
                if u not in all_found:
                    all_found.append(u)
                    print(f"    Found: {u[:150]}")
            
            # Prioritize URLs with tokens (these are the actual working streams)
            tokenized = [u for u in all_found if "md5=" in u or "expires=" in u or "token=" in u or "?" in u]
            
            if tokenized:
                stream_url = tokenized[0]
                print(f"  ✓ Tokenized stream found!")
                print(f"    URL: {stream_url}")
                
                return {
                    "url": stream_url,
                    "referer": FORCED_REFERER,
                    "origin": FORCED_ORIGIN,
                    "user_agent": DEFAULT_USER_AGENT,
                }
            
            # Fallback to any m3u8 that's not a simple playlist without params
            valid_streams = [u for u in all_found if "?" in u]
            if valid_streams:
                stream_url = valid_streams[0]
                print(f"  ✓ Stream found!")
                print(f"    URL: {stream_url}")
                
                return {
                    "url": stream_url,
                    "referer": FORCED_REFERER,
                    "origin": FORCED_ORIGIN,
                    "user_agent": DEFAULT_USER_AGENT,
                }
            
            # If we found any m3u8, use it
            if all_found:
                stream_url = all_found[0]
                print(f"  Using first found stream: {stream_url[:120]}")
                
                return {
                    "url": stream_url,
                    "referer": FORCED_REFERER,
                    "origin": FORCED_ORIGIN,
                    "user_agent": DEFAULT_USER_AGENT,
                }
            
            # Click play again to trigger video loading
            if int(time.time() - start_time) % 5 == 0:
                click_play_in_iframe(drv)
            
            time.sleep(2)
        
        print(f"  ✗ No stream found after {STREAM_TIMEOUT}s")
        print(f"  Total m3u8 URLs found: {len(all_found)}")
        for u in all_found:
            print(f"    - {u[:150]}")

    except Exception as e:
        print(f"  Error: {str(e)[:150]}")

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
    
    # Get ALL events
    all_events = get_roja_events()
    
    if not all_events:
        print("No events found!")
        return
    
    print(f"\nTotal Canal 1 events found: {len(all_events)}")
    
    # Filter excluded leagues
    if EXCLUDED_LEAGUES:
        all_events = [
            e for e in all_events
            if not any(x.lower() in e['liga'].lower() for x in EXCLUDED_LEAGUES)
        ]
    
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
    
    entries = ["#EXTM3U"]
    tivimate = ["#EXTM3U"]
    successful = 0
    
    for idx, event in enumerate(events_to_process, 1):
        print(f"\n[{idx}/{len(events_to_process)}] {event['hora']} - {event['partido']}")
        
        try:
            result = extract_m3u8(event)
            
            if result:
                liga = event['liga']
                hora = event['hora']
                partido = event['partido']
                
                title = f"{hora} {liga} - {partido}"
                
                entries.append(f'#EXTINF:-1 group-title="{liga}",{title}')
                entries += vlc_headers(result)
                entries.append(result["url"])
                
                tivimate.append(f'#EXTINF:-1 group-title="{liga}",{title}')
                tivimate.append(tivimate_url(result))
                
                successful += 1
                print(f"  ✓ Added to playlist")
            else:
                print(f"  ✗ No stream found")
                
        except Exception as e:
            print(f"  ✗ Error: {str(e)[:100]}")
        
        time.sleep(2)
    
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
