#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import time
import os
import json
import subprocess
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
STREAM_TIMEOUT = 45

# Default user agent
DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"

EXCLUDED_LEAGUES = []

# ───────── DRIVER ─────────
def get_chrome_version():
    """Get installed Chrome version"""
    try:
        result = subprocess.run(['google-chrome', '--version'], capture_output=True, text=True)
        version = result.stdout.strip()
        match = re.search(r'(\d+)\.', version)
        if match:
            return match.group(1)
    except:
        pass
    return None

def init_driver():
    """Initialize Chrome driver with correct version and network monitoring"""
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--disable-background-networking")
    opts.add_argument("--disable-sync")
    opts.add_argument("--disable-translate")
    opts.add_argument("--mute-audio")
    opts.add_argument("--ignore-certificate-errors")
    opts.add_argument("--ignore-ssl-errors")
    opts.add_argument("--allow-running-insecure-content")
    opts.add_argument("--disable-web-security")
    opts.add_argument("--autoplay-policy=no-user-gesture-required")
    opts.add_argument(f"--user-agent={DEFAULT_USER_AGENT}")
    
    # Enable performance logging
    opts.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    
    # Prevent timeout issues
    opts.add_argument("--disable-hang-monitor")
    opts.add_argument("--disable-prompt-on-repost")
    opts.add_argument("--disable-client-side-phishing-detection")
    opts.add_argument("--disable-component-update")
    opts.add_argument("--disable-default-apps")
    opts.add_argument("--no-first-run")
    opts.add_argument("--no-default-browser-check")
    
    try:
        # Try using webdriver_manager with specific version matching
        chrome_version = get_chrome_version()
        if chrome_version:
            print(f"    Chrome version: {chrome_version}")
            driver_path = ChromeDriverManager(driver_version=f"{chrome_version}.0.7778.97").install()
        else:
            driver_path = ChromeDriverManager().install()
        
        service = Service(driver_path)
        driver = webdriver.Chrome(service=service, options=opts)
        driver.set_page_load_timeout(45)
        driver.set_script_timeout(45)
        return driver
    except Exception as e:
        print(f"    Driver error: {e}")
        try:
            # Fallback: try system chromedriver
            return webdriver.Chrome(options=opts)
        except:
            # Last resort
            opts.binary_location = "/usr/bin/google-chrome"
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
    try:
        now = datetime.now()
        hour, minute = map(int, time_str.split(':'))
        event_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return event_time
    except:
        return None

# ───────── SCRAPER ─────────
def get_roja_events():
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

# ───────── M3U8 CAPTURE USING CDP ─────────

def capture_m3u8_via_cdp(driver, url):
    """Use Chrome DevTools Protocol to capture network requests"""
    m3u8_urls = []
    
    try:
        # Enable Network domain
        driver.execute_cdp_cmd("Network.enable", {})
        
        # Load the page
        driver.get(url)
        time.sleep(5)
        
        # Click play in iframes
        click_play_in_iframes(driver)
        
        # Poll for network requests
        start_time = time.time()
        while time.time() - start_time < STREAM_TIMEOUT:
            # Get all network requests
            try:
                # Use JavaScript to get performance entries
                requests_data = driver.execute_script("""
                    var entries = window.performance.getEntriesByType('resource');
                    var urls = [];
                    for (var i = 0; i < entries.length; i++) {
                        urls.push(entries[i].name);
                    }
                    return urls;
                """)
                
                for req_url in requests_data or []:
                    if ".m3u8" in req_url:
                        bad = ["google", "doubleclick", "facebook", "analytics", "googletagmanager"]
                        if not any(x in req_url.lower() for x in bad):
                            if req_url not in m3u8_urls:
                                m3u8_urls.append(req_url)
                                print(f"    Found via Performance API: {req_url[:150]}")
            except:
                pass
            
            # Also check performance logs
            try:
                logs = driver.get_log("performance")
                for entry in logs:
                    try:
                        log_data = json.loads(entry["message"])
                        message = log_data.get("message", {})
                        params = message.get("params", {})
                        
                        # Check request
                        req = params.get("request", {})
                        req_url = req.get("url", "")
                        if ".m3u8" in req_url:
                            bad = ["google", "doubleclick", "facebook", "analytics", "googletagmanager"]
                            if not any(x in req_url.lower() for x in bad):
                                if req_url not in m3u8_urls:
                                    m3u8_urls.append(req_url)
                                    print(f"    Found via logs: {req_url[:150]}")
                        
                        # Check response
                        resp = params.get("response", {})
                        resp_url = resp.get("url", "")
                        if ".m3u8" in resp_url:
                            bad = ["google", "doubleclick", "facebook", "analytics", "googletagmanager"]
                            if not any(x in resp_url.lower() for x in bad):
                                if resp_url not in m3u8_urls:
                                    m3u8_urls.append(resp_url)
                                    print(f"    Found via logs: {resp_url[:150]}")
                    except:
                        pass
            except:
                pass
                
            # If we have tokenized URLs, return immediately
            tokenized = [u for u in m3u8_urls if "md5=" in u or "expires=" in u or "token=" in u]
            if tokenized:
                return tokenized[0]
            
            # If we have any m3u8 with query params, return
            valid = [u for u in m3u8_urls if "?" in u]
            if valid:
                return valid[0]
            
            # Click play again
            click_play_in_iframes(driver)
            time.sleep(2)
        
        # Return any m3u8 found
        if m3u8_urls:
            return m3u8_urls[0]
            
    except Exception as e:
        print(f"    CDP error: {str(e)[:100]}")
    finally:
        try:
            driver.execute_cdp_cmd("Network.disable", {})
        except:
            pass
    
    return None

def click_play_in_iframes(driver):
    """Click play buttons in all iframes"""
    try:
        # Main page
        driver.execute_script("""
            var videos = document.querySelectorAll('video');
            videos.forEach(function(v) { v.muted = true; v.play(); });
            var buttons = document.querySelectorAll('button, [class*="play"], [onclick]');
            buttons.forEach(function(b) { try { b.click(); } catch(e) {} });
        """)
    except:
        pass
    
    # Iframes
    try:
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for iframe in iframes[:5]:
            try:
                src = iframe.get_attribute("src") or ""
                driver.switch_to.frame(iframe)
                
                driver.execute_script("""
                    var videos = document.querySelectorAll('video');
                    videos.forEach(function(v) { 
                        v.muted = true; 
                        v.play();
                        v.setAttribute('autoplay', 'true');
                    });
                    
                    // Click all possible play elements
                    var selectors = 'button, [class*="play"], .vjs-big-play-button, [aria-label*="play" i], .plyr__control--overlaid, video';
                    var elements = document.querySelectorAll(selectors);
                    elements.forEach(function(el) { 
                        try { 
                            el.click(); 
                            var event = new MouseEvent('click', {bubbles: true});
                            el.dispatchEvent(event);
                        } catch(e) {} 
                    });
                    
                    // Click center of page
                    var el = document.elementFromPoint(window.innerWidth/2, window.innerHeight/2);
                    if (el) {
                        el.click();
                        var event = new MouseEvent('click', {bubbles: true});
                        el.dispatchEvent(event);
                    }
                """)
                
                # Check inside nested iframes
                nested_iframes = driver.find_elements(By.TAG_NAME, "iframe")
                for nested_iframe in nested_iframes[:2]:
                    try:
                        driver.switch_to.frame(nested_iframe)
                        driver.execute_script("""
                            var videos = document.querySelectorAll('video');
                            videos.forEach(function(v) { v.muted = true; v.play(); });
                            var buttons = document.querySelectorAll('button, [class*="play"]');
                            buttons.forEach(function(b) { b.click(); });
                        """)
                        driver.switch_to.parent_frame()
                    except:
                        pass
                
                driver.switch_to.default_content()
                time.sleep(0.5)
            except:
                try:
                    driver.switch_to.default_content()
                except:
                    pass
    except:
        pass

# ───────── STREAM EXTRACTION ─────────

def extract_m3u8(event_info):
    url = event_info['url']
    partido = event_info['partido']

    drv = None
    try:
        print(f"  Loading: {url}")
        drv = init_driver()
        
        # Capture m3u8 using CDP
        stream_url = capture_m3u8_via_cdp(drv, url)
        
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
        if drv:
            try:
                drv.quit()
            except:
                pass

    return None

# ───────── HEADERS FORMAT ─────────
def vlc_headers(r):
    h = []
    if r.get("referer"):
        h.append(f'#EXTVLCOPT:http-referrer={r["referer"]}')
    if r.get("origin"):
        h.append(f'#EXTVLCOPT:http-origin={r["origin"]}')
    if r.get("user_agent"):
        h.append(f'#EXTVLCOPT:http-user-agent={r["user_agent"]}')
    return h

def tivimate_url(r):
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
    
    all_events = get_roja_events()
    
    if not all_events:
        print("No events found!")
        return
    
    print(f"\nTotal Canal 1 events found: {len(all_events)}")
    
    if EXCLUDED_LEAGUES:
        all_events = [e for e in all_events if not any(x.lower() in e['liga'].lower() for x in EXCLUDED_LEAGUES)]
    
    all_events.sort(key=lambda x: (x['hora'], x['liga']))
    
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
