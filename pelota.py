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
STREAM_TIMEOUT = 35  # Increased timeout

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
    opts.add_argument(f"--user-agent={DEFAULT_USER_AGENT}")
    
    # Enable performance logging
    opts.set_capability("goog:loggingPrefs", {"performance": "ALL", "browser": "ALL"})
    
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
    """Extract ALL first channel links (Canal 1 only) from each event"""
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

# ───────── STREAM EXTRACTION ─────────
def get_performance_logs(driver):
    """Extract all network requests from performance logs"""
    requests_list = []
    try:
        logs = driver.get_log("performance")
        for entry in logs:
            try:
                log_data = json.loads(entry["message"])
                message = log_data.get("message", {})
                method = message.get("method", "")
                
                # Capture both requests and responses
                if method in ["Network.requestWillBeSent", "Network.responseReceived"]:
                    if method == "Network.requestWillBeSent":
                        request_data = message.get("params", {}).get("request", {})
                        url = request_data.get("url", "")
                        requests_list.append({
                            "url": url,
                            "type": "request",
                            "headers": request_data.get("headers", {})
                        })
                    elif method == "Network.responseReceived":
                        response = message.get("params", {}).get("response", {})
                        url = response.get("url", "")
                        mime_type = response.get("mimeType", "")
                        requests_list.append({
                            "url": url,
                            "type": "response",
                            "status": response.get("status", 0),
                            "mimeType": mime_type,
                            "headers": response.get("headers", {})
                        })
            except:
                continue
    except Exception as e:
        print(f"    Log error: {str(e)[:50]}")
    return requests_list

def extract_m3u8(event_info):
    """Extract m3u8 stream from event page"""
    url = event_info['url']
    partido = event_info['partido']
    channel = event_info['channel']
    
    drv = None
    try:
        print(f"  Loading: {url}")
        drv = init_driver()
        
        # Load the page
        try:
            drv.get(url)
        except Exception as e:
            print(f"  Page load warning: {str(e)[:80]}")
        
        # Wait for page to load
        time.sleep(5)
        
        # Clear initial logs
        try:
            drv.get_log("performance")
        except:
            pass
        
        # Try to interact with the page to trigger video loading
        try:
            # Wait for iframe and switch to it
            iframes = drv.find_elements(By.TAG_NAME, "iframe")
            for i, iframe in enumerate(iframes[:5]):
                try:
                    src = iframe.get_attribute("src") or ""
                    if src:
                        print(f"  Found iframe {i}: {src[:100]}")
                    
                    drv.switch_to.frame(iframe)
                    
                    # Try to click play buttons
                    selectors = [
                        "button[class*='play']",
                        ".vjs-big-play-button",
                        "button",
                        "video",
                        "[class*='play']",
                        ".play-button",
                        "div[onclick]",
                        "[aria-label='Play']",
                        "[aria-label='play']"
                    ]
                    
                    for selector in selectors:
                        try:
                            elements = drv.find_elements(By.CSS_SELECTOR, selector)
                            for el in elements:
                                try:
                                    if el.is_displayed() and el.is_enabled():
                                        drv.execute_script("arguments[0].click();", el)
                                        time.sleep(1)
                                except:
                                    pass
                        except:
                            pass
                    
                    # Try to play video directly
                    try:
                        drv.execute_script("""
                            var videos = document.querySelectorAll('video');
                            videos.forEach(function(v) { 
                                v.play(); 
                                v.muted = true;
                                v.setAttribute('autoplay', 'true');
                            });
                            var buttons = document.querySelectorAll('button, [class*="play"], .vjs-big-play-button, [aria-label*="play" i]');
                            buttons.forEach(function(b) { b.click(); });
                        """)
                    except:
                        pass
                    
                    drv.switch_to.default_content()
                    time.sleep(1)
                except:
                    try:
                        drv.switch_to.default_content()
                    except:
                        pass
            
            # Also try on main page
            try:
                drv.execute_script("""
                    var videos = document.querySelectorAll('video');
                    videos.forEach(function(v) { 
                        v.play(); 
                        v.muted = true;
                    });
                    var buttons = document.querySelectorAll('button, [class*="play"], .vjs-big-play-button, [aria-label*="play" i]');
                    buttons.forEach(function(b) { b.click(); });
                """)
            except:
                pass
                
        except Exception as e:
            print(f"  Interaction error: {str(e)[:50]}")
        
        # Now search for m3u8 in performance logs
        print(f"  Searching for m3u8 stream...")
        start_time = time.time()
        found_urls = set()
        
        while time.time() - start_time < STREAM_TIMEOUT:
            try:
                # Get fresh performance logs
                network_requests = get_performance_logs(driver=drv)
                
                # Check for m3u8 URLs
                for req in network_requests:
                    req_url = req.get("url", "")
                    
                    # Look for m3u8, ts, or stream URLs
                    if not (".m3u8" in req_url or ".ts" in req_url or "hls" in req_url.lower()):
                        continue
                    
                    # Only care about m3u8 master playlists
                    if ".m3u8" not in req_url:
                        continue
                    
                    # Filter out unwanted URLs
                    if any(x in req_url.lower() for x in ['google', 'analytics', 'facebook', 'doubleclick', 'googletagmanager', 'tag.min.js']):
                        continue
                    
                    # Skip duplicates
                    if req_url in found_urls:
                        continue
                    
                    found_urls.add(req_url)
                    
                    # Get headers
                    req_headers = req.get("headers", {})
                    
                    # Use forced headers as defaults
                    referer = req_headers.get("Referer", "") or req_headers.get("referer", "") or FORCED_REFERER
                    origin = req_headers.get("Origin", "") or req_headers.get("origin", "") or FORCED_ORIGIN
                    user_agent = req_headers.get("User-Agent", "") or req_headers.get("user-agent", "") or DEFAULT_USER_AGENT
                    
                    result = {
                        "url": req_url,
                        "referer": referer,
                        "origin": origin,
                        "user_agent": user_agent,
                    }
                    
                    print(f"  ✓ Stream found!")
                    print(f"    URL: {req_url}")
                    print(f"    Referer: {referer}")
                    
                    return result
            
            except Exception as e:
                print(f"    Search error: {str(e)[:50]}")
            
            time.sleep(2)
        
        # If no m3u8 found, try checking the page source for stream URLs
        print(f"  Checking page source for stream URLs...")
        try:
            page_source = drv.page_source
            m3u8_matches = re.findall(r'https?://[^"\'\s]+\.m3u8[^"\'\s]*', page_source)
            if m3u8_matches:
                for m3u8_url in m3u8_matches[:3]:
                    if "google" not in m3u8_url.lower():
                        result = {
                            "url": m3u8_url,
                            "referer": FORCED_REFERER,
                            "origin": FORCED_ORIGIN,
                            "user_agent": DEFAULT_USER_AGENT,
                        }
                        print(f"  ✓ Stream found in page source!")
                        print(f"    URL: {m3u8_url}")
                        return result
        except:
            pass
        
        print(f"  ✗ No stream found after {STREAM_TIMEOUT}s")
        
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
    
    # Remove duplicate matches (keep first occurrence)
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
    
    # Show events
    for e in events_to_process:
        print(f"  {e['hora']} | {e['liga']}: {e['partido']}")
    
    # Prepare output
    entries = ["#EXTM3U"]
    tivimate = ["#EXTM3U"]
    
    successful = 0
    
    # Process events
    for idx, event in enumerate(events_to_process, 1):
        print(f"\n[{idx}/{len(events_to_process)}] {event['hora']} - {event['partido']}")
        
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
                print(f"  ✓ Added to playlist")
            else:
                print(f"  ✗ No stream found")
                
        except Exception as e:
            print(f"  ✗ Error: {str(e)[:100]}")
        
        time.sleep(3)
    
    # Save files
    print(f"\n{'=' * 60}")
    print(f"Results: {successful}/{len(events_to_process)} streams captured")
    
    try:
        (REPO_DIR / EVENT_FILE).write_text("\n".join(entries), encoding='utf-8')
        (REPO_DIR / TIVIMATE_FILE).write_text("\n".join(tivimate), encoding='utf-8')
        
        print(f"Files written:")
        print(f"  - {EVENT_FILE} ({len(entries)-1} entries)")
        print(f"  - {TIVIMATE_FILE} ({len(tivimate)-1} entries)")
        
        # Show sample output
        if successful > 0:
            print(f"\nSample output:")
            for line in entries[1:6]:
                print(f"  {line[:120]}")
        
    except Exception as e:
        print(f"Error writing files: {e}")
    
    # Git push
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
