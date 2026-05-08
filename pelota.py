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
STREAM_TIMEOUT = 45  # Increased timeout

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

# ───────── M3U8 DETECTION HELPERS ─────────

M3U8_REGEX = re.compile(
    r'https?://[^"\'\s]+\.m3u8[^"\'\s]*',
    re.IGNORECASE
)

BAD_DOMAINS = [
    "google",
    "doubleclick",
    "facebook",
    "analytics",
    "googletagmanager",
    "gstatic",
]

def is_valid_m3u8(url):
    if not url:
        return False
    if ".m3u8" not in url.lower():
        return False
    if any(x in url.lower() for x in BAD_DOMAINS):
        return False
    return True

def extract_m3u8_from_text(text):
    found = []
    if not text:
        return found
    matches = M3U8_REGEX.findall(text)
    for url in matches:
        url = url.replace("\\/", "/").strip()
        if is_valid_m3u8(url):
            found.append(url)
    return list(dict.fromkeys(found))

def get_all_m3u8_from_logs(driver):
    """Extract all m3u8 URLs from browser performance logs"""
    urls = []
    try:
        logs = driver.get_log("performance")
        for entry in logs:
            try:
                msg = json.loads(entry["message"])["message"]
                params = msg.get("params", {})
                
                # Check request
                request = params.get("request", {})
                req_url = request.get("url", "")
                if is_valid_m3u8(req_url):
                    urls.append(req_url)
                
                # Check response
                response = params.get("response", {})
                res_url = response.get("url", "")
                if is_valid_m3u8(res_url):
                    urls.append(res_url)
            except:
                pass
    except:
        pass
    return list(dict.fromkeys(urls))

def get_all_m3u8_from_page(driver):
    """Extract m3u8 from page source and scripts"""
    urls = []
    
    # Page source
    try:
        source = driver.page_source
        urls.extend(extract_m3u8_from_text(source))
    except:
        pass
    
    # Script tags
    try:
        scripts = driver.find_elements(By.TAG_NAME, "script")
        for script in scripts:
            try:
                content = script.get_attribute("innerHTML") or ""
                urls.extend(extract_m3u8_from_text(content))
            except:
                pass
    except:
        pass
    
    # Full DOM
    try:
        html = driver.execute_script("return document.documentElement.outerHTML;")
        urls.extend(extract_m3u8_from_text(html))
    except:
        pass
    
    return list(dict.fromkeys(urls))

def get_capo7play_iframe_url(driver):
    """Find the capo7play iframe URL"""
    try:
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for iframe in iframes:
            src = iframe.get_attribute("src") or ""
            if "capo7play.com" in src or "capoplay.net" in src:
                if src.startswith("http"):
                    return src
        return None
    except:
        return None

# ───────── STREAM EXTRACTION ─────────

def extract_m3u8(event_info):
    """Extract m3u8 stream by navigating directly to capo7play iframe"""
    url = event_info['url']
    partido = event_info['partido']

    drv = None

    try:
        print(f"  Step 1: Loading {url}")
        drv = init_driver()
        drv.get(url)
        time.sleep(5)
        
        # Find the capo7play iframe URL
        capo_url = get_capo7play_iframe_url(driver=drv)
        
        if not capo_url:
            # Try clicking play buttons first
            try:
                iframes = drv.find_elements(By.TAG_NAME, "iframe")
                for iframe in iframes[:3]:
                    try:
                        drv.switch_to.frame(iframe)
                        drv.execute_script("""
                            var videos = document.querySelectorAll('video');
                            videos.forEach(function(v) { v.play(); v.muted = true; });
                            var buttons = document.querySelectorAll('button, [class*="play"]');
                            buttons.forEach(function(b) { b.click(); });
                        """)
                        drv.switch_to.default_content()
                        time.sleep(2)
                    except:
                        drv.switch_to.default_content()
            except:
                pass
            
            time.sleep(3)
            capo_url = get_capo7play_iframe_url(driver=drv)
        
        if capo_url:
            print(f"  Step 2: Loading capo7play: {capo_url[:120]}")
            drv.get(capo_url)
            time.sleep(8)
            
            # Click play button on capo7play
            try:
                # Try multiple play button approaches
                for attempt in range(5):
                    try:
                        # Click any play buttons
                        drv.execute_script("""
                            var videos = document.querySelectorAll('video');
                            videos.forEach(function(v) { 
                                v.play(); 
                                v.muted = true;
                                v.setAttribute('autoplay', 'true');
                                v.click();
                            });
                            var buttons = document.querySelectorAll('button, [class*="play"], .vjs-big-play-button, [aria-label*="play" i], div[onclick]');
                            buttons.forEach(function(b) { b.click(); });
                            // Click center of page
                            var el = document.elementFromPoint(window.innerWidth/2, window.innerHeight/2);
                            if (el) el.click();
                        """)
                        time.sleep(2)
                    except:
                        pass
                
                # Try clicking video element directly
                try:
                    video = drv.find_element(By.TAG_NAME, "video")
                    if video:
                        drv.execute_script("arguments[0].click(); arguments[0].play();", video)
                        time.sleep(2)
                except:
                    pass
                    
            except Exception as e:
                print(f"    Play click error: {str(e)[:50]}")
        else:
            print(f"  No capo7play iframe found, staying on current page")
            time.sleep(8)
        
        # Search for m3u8 stream
        print(f"  Step 3: Searching for m3u8 stream...")
        start = time.time()
        all_found = set()
        
        while time.time() - start < STREAM_TIMEOUT:
            # Collect from all sources
            new_urls = []
            new_urls.extend(get_all_m3u8_from_logs(drv))
            new_urls.extend(get_all_m3u8_from_page(drv))
            
            for u in new_urls:
                if u not in all_found:
                    all_found.add(u)
                    print(f"    Found: {u[:120]}")
            
            # Check for tokenized URLs first (these are the actual streams)
            prioritized = [u for u in all_found if "md5=" in u or "expires=" in u or "token=" in u]
            
            if prioritized:
                stream_url = prioritized[0]
                print(f"  ✓ Tokenized stream found!")
                print(f"    URL: {stream_url}")
                
                return {
                    "url": stream_url,
                    "referer": FORCED_REFERER,
                    "origin": FORCED_ORIGIN,
                    "user_agent": DEFAULT_USER_AGENT,
                }
            
            # Fallback to any m3u8
            if all_found:
                stream_url = list(all_found)[0]
                print(f"  ✓ Stream found!")
                print(f"    URL: {stream_url}")
                
                return {
                    "url": stream_url,
                    "referer": FORCED_REFERER,
                    "origin": FORCED_ORIGIN,
                    "user_agent": DEFAULT_USER_AGENT,
                }
            
            # Try clicking play again
            try:
                drv.execute_script("""
                    var videos = document.querySelectorAll('video');
                    videos.forEach(function(v) { v.play(); v.muted = true; });
                    var buttons = document.querySelectorAll('button, [class*="play"]');
                    buttons.forEach(function(b) { b.click(); });
                """)
            except:
                pass
            
            time.sleep(2)
        
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
        
        time.sleep(3)
    
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
