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

REPO_DIR = Path(__file__).parent
EVENT_FILE = "eventos.m3u8"
TIVIMATE_FILE = "eventos_tivimate.m3u8"

MAX_EVENTS = 10  # Process only first N upcoming events
STREAM_TIMEOUT = 25  # Max seconds to wait for stream per event

# Default user agent (will be URL encoded for Tivimate)
DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36 Edg/134.0.0.0"

EXCLUDED_LEAGUES = [
    "NBA"
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

def extract_domain(url):
    """Extract domain from URL"""
    try:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}"
    except:
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
    """Extract events from RojaDirecta page"""
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

            # Get ONLY the first channel link from <ul>
            first_channel = li.select_one("ul > li.subitem1 > a")
            if not first_channel:
                continue
                
            href = normalize(first_channel.get("href"))
            channel_name = first_channel.text.strip()
            
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

    except Exception as e:
        print(f"Error scraping: {e}")
    
    return events

# ───────── STREAM EXTRACTION ─────────
def extract_m3u8(event_info):
    """Extract m3u8 stream from event URL with correct headers"""
    url = event_info['url']
    partido = event_info['partido']
    
    drv = None
    try:
        print(f"  Loading page...")
        drv = init_driver()
        drv.get(url)
        time.sleep(4)
        
        # Clear any previous requests
        try:
            del drv.requests
        except:
            pass
        
        # Find the actual streaming iframe to get correct referer
        stream_domain = None
        try:
            iframes = drv.find_elements(By.TAG_NAME, "iframe")
            for iframe in iframes:
                src = iframe.get_attribute("src")
                if src and any(x in src.lower() for x in ['capo', 'play', 'stream', 'video', 'embed']):
                    stream_domain = extract_domain(src)
                    print(f"  Found streaming iframe: {stream_domain}")
                    break
        except:
            pass
        
        # Click play buttons
        for attempt in range(3):
            try:
                # Try clicking play buttons
                selectors = [
                    "button[class*='play']",
                    ".vjs-big-play-button", 
                    "button",
                    "video",
                    "[class*='play']",
                    ".play-button"
                ]
                
                for selector in selectors:
                    try:
                        elements = drv.find_elements(By.CSS_SELECTOR, selector)
                        for el in elements[:2]:
                            if el.is_displayed():
                                drv.execute_script("arguments[0].click();", el)
                                time.sleep(0.5)
                    except:
                        pass
                
                # Try clicking inside iframes
                iframes = drv.find_elements(By.TAG_NAME, "iframe")
                for iframe in iframes:
                    try:
                        drv.switch_to.frame(iframe)
                        # Click any video/play elements
                        drv.execute_script("""
                            var videos = document.querySelectorAll('video');
                            videos.forEach(function(v) { 
                                v.play(); 
                                v.click();
                            });
                            var buttons = document.querySelectorAll('button, [class*="play"], .vjs-big-play-button');
                            buttons.forEach(function(b) { b.click(); });
                        """)
                        drv.switch_to.default_content()
                    except:
                        drv.switch_to.default_content()
                        
            except:
                pass
            
            time.sleep(2)
        
        # Search for m3u8 requests
        print(f"  Searching for stream...")
        start_time = time.time()
        while time.time() - start_time < STREAM_TIMEOUT:
            try:
                for req in drv.requests:
                    if not req.response:
                        continue
                        
                    req_url = req.url
                    if ".m3u8" in req_url:
                        # Filter out unwanted URLs
                        if any(x in req_url.lower() for x in ['google', 'analytics', 'facebook', 'doubleclick']):
                            continue
                        
                        # Determine correct referer and origin
                        if stream_domain:
                            referer = stream_domain + "/"
                            origin = stream_domain
                        else:
                            # Fallback to extracting from the m3u8 URL domain
                            m3u8_domain = extract_domain(req_url)
                            referer = m3u8_domain + "/"
                            origin = m3u8_domain
                        
                        # Get actual headers from request if available
                        headers = {}
                        try:
                            if hasattr(req, 'headers') and req.headers:
                                headers = dict(req.headers)
                        except:
                            pass
                        
                        result = {
                            "url": req_url,
                            "referer": headers.get("Referer", referer),
                            "origin": headers.get("Origin", origin),
                            "user_agent": headers.get("User-Agent", DEFAULT_USER_AGENT),
                        }
                        
                        print(f"  ✓ Stream found!")
                        print(f"    URL: {req_url[:80]}...")
                        print(f"    Referer: {result['referer']}")
                        print(f"    Origin: {result['origin']}")
                        
                        return result
            except:
                pass
            time.sleep(1)
        
        print(f"  ✗ Timeout - no stream found")
        
    except Exception as e:
        print(f"  Error: {str(e)[:100]}")
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
    
    # Get events
    all_events = get_roja_events()
    
    if not all_events:
        print("No events found!")
        return
    
    # Filter events that are live or starting soon
    live_events = [e for e in all_events if is_event_live_or_soon(e['time_obj'])]
    
    # If no live events, take the next upcoming ones
    if not live_events:
        print("\nNo live events found. Taking next upcoming events...")
        future_events = [e for e in all_events if e['time_obj'] and e['time_obj'] > datetime.now()]
        future_events.sort(key=lambda x: x['time_obj'])
        events_to_process = future_events[:MAX_EVENTS]
    else:
        events_to_process = live_events[:MAX_EVENTS]
    
    # Filter excluded leagues
    if EXCLUDED_LEAGUES:
        events_to_process = [e for e in events_to_process 
                           if not any(x.lower() in e['liga'].lower() for x in EXCLUDED_LEAGUES)]
    
    # Sort by time
    events_to_process.sort(key=lambda x: x['hora'])
    
    print(f"\nLive events: {len(live_events)}")
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
    
    # Process events
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
                
                # VLC format
                entries.append(f'#EXTINF:-1 group-title="{liga}",{title}')
                entries += vlc_headers(result)
                entries.append(result["url"])
                
                # Tivimate format
                tivimate.append(f'#EXTINF:-1 group-title="{liga}",{title}')
                tivimate_url_str = tivimate_url(result)
                tivimate.append(tivimate_url_str)
                
                successful += 1
                print(f"  ✓ Added to playlist")
            else:
                print(f"  ✗ No stream found")
                
        except Exception as e:
            print(f"  ✗ Error: {str(e)[:100]}")
        
        # Delay between events
        time.sleep(3)
    
    # Write files
    print(f"\n{'=' * 60}")
    print(f"Results: {successful}/{len(events_to_process)} streams captured")
    
    try:
        vlc_content = "\n".join(entries)
        tivimate_content = "\n".join(tivimate)
        
        (REPO_DIR / EVENT_FILE).write_text(vlc_content, encoding='utf-8')
        (REPO_DIR / TIVIMATE_FILE).write_text(tivimate_content, encoding='utf-8')
        
        print(f"Files written:")
        print(f"  - {EVENT_FILE} ({len(entries)-1} streams)")
        print(f"  - {TIVIMATE_FILE} ({len(tivimate)-1} streams)")
        
        # Show sample of Tivimate output
        if successful > 0:
            print(f"\nSample Tivimate entry:")
            for line in tivimate[-2:]:
                print(f"  {line[:120]}...")
            
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
