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

# ───────── DEEP STREAM HELPERS ─────────

M3U8_REGEX = re.compile(
    r'https?://[^"\']+\.m3u8(?:\?[^"\']+)?',
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
        url = url.replace("\\/", "/")
        url = url.strip()

        if is_valid_m3u8(url):
            found.append(url)

    return list(dict.fromkeys(found))


def inspect_browser_logs(driver):
    urls = []

    try:
        logs = driver.get_log("performance")

        for entry in logs:
            try:
                msg = json.loads(entry["message"])["message"]

                params = msg.get("params", {})

                # request
                request = params.get("request", {})
                req_url = request.get("url", "")

                if is_valid_m3u8(req_url):
                    urls.append(req_url)

                # response
                response = params.get("response", {})
                res_url = response.get("url", "")

                if is_valid_m3u8(res_url):
                    urls.append(res_url)

            except:
                pass

    except:
        pass

    return list(dict.fromkeys(urls))


def inspect_page_source(driver):
    urls = []

    try:
        source = driver.page_source
        urls.extend(extract_m3u8_from_text(source))
    except:
        pass

    return list(dict.fromkeys(urls))


def inspect_scripts(driver):
    urls = []

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

    return list(dict.fromkeys(urls))


def inspect_dom(driver):
    urls = []

    try:
        html = driver.execute_script("""
            return document.documentElement.outerHTML;
        """)

        urls.extend(extract_m3u8_from_text(html))
    except:
        pass

    return list(dict.fromkeys(urls))


def inspect_iframes_recursive(driver, depth=0, max_depth=4):
    urls = []

    if depth > max_depth:
        return urls

    try:
        iframes = driver.find_elements(By.TAG_NAME, "iframe")

        for iframe in iframes:
            try:
                src = iframe.get_attribute("src") or ""

                if src:
                    print(f"    iframe: {src[:120]}")

                driver.switch_to.frame(iframe)

                time.sleep(2)

                # inspect inside iframe
                urls.extend(inspect_page_source(driver))
                urls.extend(inspect_scripts(driver))
                urls.extend(inspect_dom(driver))
                urls.extend(inspect_browser_logs(driver))

                # recurse deeper
                urls.extend(
                    inspect_iframes_recursive(
                        driver,
                        depth + 1,
                        max_depth
                    )
                )

                driver.switch_to.parent_frame()

            except:
                try:
                    driver.switch_to.default_content()
                except:
                    pass

    except:
        pass

    return list(dict.fromkeys(urls))


# ───────── STREAM EXTRACTION ─────────

def extract_m3u8(event_info):
    url = event_info['url']
    partido = event_info['partido']

    drv = None

    try:
        print(f"  Loading: {url}")

        drv = init_driver()

        drv.get(url)

        # allow JS/player loading
        time.sleep(8)

        # autoplay attempt
        try:
            drv.execute_script("""
                var videos = document.querySelectorAll('video');

                videos.forEach(function(v){
                    try{
                        v.muted = true;
                        v.play();
                    }catch(e){}
                });

                var els = document.querySelectorAll(
                    'button, .play, .vjs-big-play-button, [onclick]'
                );

                els.forEach(function(el){
                    try{
                        el.click();
                    }catch(e){}
                });
            """)
        except:
            pass

        print("  Searching for m3u8 stream...")

        start = time.time()

        found = []

        while time.time() - start < STREAM_TIMEOUT:

            # main page inspection
            found.extend(inspect_browser_logs(drv))
            found.extend(inspect_page_source(drv))
            found.extend(inspect_scripts(drv))
            found.extend(inspect_dom(drv))

            # iframe inspection
            found.extend(inspect_iframes_recursive(drv))

            # remove duplicates
            found = list(dict.fromkeys(found))

            # prioritize tokenized URLs
            prioritized = []

            for u in found:
                if "md5=" in u or "expires=" in u:
                    prioritized.append(u)

            if prioritized:
                stream_url = prioritized[0]

                print("  ✓ Signed stream found!")
                print(f"    URL: {stream_url}")

                return {
                    "url": stream_url,
                    "referer": FORCED_REFERER,
                    "origin": FORCED_ORIGIN,
                    "user_agent": DEFAULT_USER_AGENT,
                }

            # fallback any m3u8
            if found:
                stream_url = found[0]

                print("  ✓ Stream found!")
                print(f"    URL: {stream_url}")

                return {
                    "url": stream_url,
                    "referer": FORCED_REFERER,
                    "origin": FORCED_ORIGIN,
                    "user_agent": DEFAULT_USER_AGENT,
                }

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
