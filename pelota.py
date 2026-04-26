#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import time
import os
import signal
from pathlib import Path
from git import Repo
import requests
from bs4 import BeautifulSoup
from seleniumwire import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor, as_completed
import warnings
warnings.filterwarnings("ignore")

# ───────── CONFIG ─────────
ROJA_URL = "https://www.rojadirectaenvivo.pl/"
ROJA_BASE = "https://rojadirectablog.com"

REPO_DIR = Path(__file__).parent
EVENT_FILE = "eventos.m3u8"
TIVIMATE_FILE = "eventos_tivimate.m3u8"

MAX_WORKERS = 2  # Reduced to avoid memory issues
MAX_EVENTS = 15   # Process only first N upcoming events

EXCLUDED_LEAGUES = []

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
    opts.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36")
    
    # Performance optimizations
    opts.add_argument("--disable-background-networking")
    opts.add_argument("--disable-sync")
    opts.add_argument("--disable-translate")
    opts.add_argument("--disable-default-apps")
    opts.add_argument("--mute-audio")
    opts.add_argument("--disable-features=TranslateUI,BlinkGenPropertyTrees")
    opts.add_argument("--disable-ipc-flooding-protection")
    
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=opts)
        driver.set_page_load_timeout(30)
        driver.set_script_timeout(30)
        return driver
    except Exception as e:
        print(f"Error init driver: {e}")
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

# ───────── SCRAPER ─────────
def get_roja_events():
    """Extract events from RojaDirecta page"""
    events = []
    try:
        print(f"Fetching events from: {ROJA_URL}")
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        r = requests.get(ROJA_URL, timeout=15, headers=headers)
        soup = BeautifulSoup(r.text, "html.parser")

        # Find all menu items
        menu_items = soup.select("ul.menu > li")
        print(f"Found {len(menu_items)} events")
        
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
                events.append({
                    'liga': liga,
                    'hora': hora,
                    'partido': partido,
                    'channel': channel_name,
                    'url': href
                })
                print(f"  {hora} | {liga}: {partido} -> {channel_name}")

    except Exception as e:
        print(f"Error scraping: {e}")
    
    return events

# ───────── STREAM EXTRACTION ─────────
def extract_m3u8(event_info):
    """Extract m3u8 stream from event URL"""
    url = event_info['url']
    partido = event_info['partido']
    
    drv = None
    try:
        print(f"\n  Loading: {partido}")
        drv = init_driver()
        drv.get(url)
        time.sleep(4)  # Initial load wait
        
        # Clear any previous requests
        del drv.requests
        
        # Try to click play button multiple times
        for attempt in range(3):
            try:
                # Try different play button selectors
                selectors = [
                    "button[class*='play']",
                    ".vjs-big-play-button", 
                    ".play-button",
                    "button",
                    "[onclick*='play']",
                    "video",
                    ".video-js button"
                ]
                
                for selector in selectors:
                    try:
                        elements = drv.find_elements(By.CSS_SELECTOR, selector)
                        for el in elements[:3]:  # Only first few
                            if el.is_displayed():
                                drv.execute_script("arguments[0].click();", el)
                                time.sleep(0.5)
                    except:
                        pass
                
                # Try iframes
                iframes = drv.find_elements(By.TAG_NAME, "iframe")
                for iframe in iframes[:2]:
                    try:
                        drv.switch_to.frame(iframe)
                        # Click anything clickable
                        drv.execute_script("""
                            var videos = document.querySelectorAll('video');
                            videos.forEach(function(v) { v.play(); });
                            var buttons = document.querySelectorAll('button, [class*="play"]');
                            buttons.forEach(function(b) { b.click(); });
                        """)
                        drv.switch_to.default_content()
                    except:
                        drv.switch_to.default_content()
                        
            except Exception as e:
                pass
            
            time.sleep(2)
        
        # Search for m3u8 requests
        print(f"  Searching for stream...")
        for _ in range(12):  # Wait up to 12 seconds
            try:
                for req in drv.requests:
                    if not req.response:
                        continue
                        
                    req_url = req.url
                    if ".m3u8" in req_url or ".ts?" in req_url:
                        # Filter out unwanted URLs
                        if any(x in req_url.lower() for x in ['google', 'analytics', 'facebook', 'doubleclick']):
                            continue
                            
                        # Get headers
                        headers = {}
                        try:
                            if hasattr(req, 'headers'):
                                headers = dict(req.headers)
                        except:
                            pass
                            
                        result = {
                            "url": req_url,
                            "referer": headers.get("Referer", url),
                            "origin": headers.get("Origin", ""),
                            "user_agent": headers.get("User-Agent", ""),
                        }
                        
                        print(f"  ✓ Stream found: {req_url[:100]}...")
                        return result
            except:
                pass
            time.sleep(1)
        
        print(f"  ✗ No stream found for {partido}")
        
    except Exception as e:
        print(f"  Error: {e}")
    finally:
        if drv:
            try:
                drv.quit()
                time.sleep(0.5)
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
    print("=" * 60)
    
    # Get events
    events = get_roja_events()
    
    if not events:
        print("No events found!")
        return
    
    # Sort by time
    events.sort(key=lambda x: x['hora'])
    
    # Limit to first N events
    events = events[:MAX_EVENTS]
    print(f"\nProcessing {len(events)} events")
    
    # Prepare output
    entries = ["#EXTM3U"]
    tivimate = ["#EXTM3U"]
    
    # Process events sequentially for stability
    successful = 0
    
    for idx, event in enumerate(events[:MAX_EVENTS], 1):
        print(f"\n[{idx}/{min(len(events), MAX_EVENTS)}] ", end="")
        
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
                tivimate.append(tivimate_url(result))
                
                successful += 1
                print(f"  ✓ Added: {title}")
            else:
                print(f"  ✗ Failed: {event['partido']}")
                
        except Exception as e:
            print(f"  ✗ Error processing {event['partido']}: {e}")
        
        # Small delay between events
        time.sleep(2)
    
    # Write files
    print(f"\n{'=' * 60}")
    print(f"Results: {successful}/{len(events)} streams captured")
    
    if entries:
        (REPO_DIR / EVENT_FILE).write_text("\n".join(entries), encoding='utf-8')
        (REPO_DIR / TIVIMATE_FILE).write_text("\n".join(tivimate), encoding='utf-8')
        print(f"Files written:")
        print(f"  - {EVENT_FILE} ({len(entries)-1} streams)")
        print(f"  - {TIVIMATE_FILE} ({len(tivimate)-1} streams)")
    
    # Git push
    try:
        repo = Repo(REPO_DIR)
        repo.git.add(A=True)
        repo.index.commit(f"Auto update {time.strftime('%Y-%m-%d %H:%M:%S')} - {successful} streams")
        repo.remote().push()
        print("✓ Pushed to git")
    except Exception as e:
        print(f"Git error: {e}")

if __name__ == "__main__":
    # Set timeout for entire script
    signal.alarm(300)  # 5 minutes max
    
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted by user")
    except Exception as e:
        print(f"Fatal error: {e}")
