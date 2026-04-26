#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import time
import os
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

# ───────── CONFIG ─────────
ROJA_URL = "https://www.rojadirectaenvivo.pl/"
ROJA_BASE = "https://rojadirectablog.com"  # Base for relative links

REPO_DIR = Path(__file__).parent
EVENT_FILE = "eventos.m3u8"
TIVIMATE_FILE = "eventos_tivimate.m3u8"

MAX_WORKERS = 4  # parallel threads (safe limit)

EXCLUDED_LEAGUES = [
    #"Super Lig",
    #"Liga Endesa",
    #"Super League",
    #"Bundesliga",
    #"MLS",
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
    opts.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36")

    try:
        service = Service(ChromeDriverManager().install())
        return webdriver.Chrome(service=service, options=opts)
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

# ───────── SCRAPERS ─────────
def get_roja_events():
    events = []
    try:
        print(f"Fetching: {ROJA_URL}")
        r = requests.get(ROJA_URL, timeout=15, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36'
        })
        soup = BeautifulSoup(r.text, "html.parser")

        for li in soup.select("ul.menu > li"):
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
            # Remove time from text if present
            if hora in raw:
                raw = raw.replace(hora, "").strip()

            if ":" not in raw:
                continue

            liga, partido = map(str.strip, raw.split(":", 1))

            # Get all sub-links (stream channels)
            for a in li.select("ul > li > a"):
                href = normalize(a.get("href"))
                if href:
                    channel_name = a.text.strip()
                    events.append((liga, hora, partido, channel_name, href))
                    print(f"  Found: {liga}: {partido} at {hora} -> {channel_name}: {href}")

    except Exception as e:
        print(f"Error scraping Roja: {e}")
    
    return events

# ───────── CLICK PLAY ─────────
def click_play(d):
    """Try multiple methods to click play button"""
    # Method 1: Direct button click
    for _ in range(3):
        try:
            btns = d.find_elements(By.CSS_SELECTOR, "button, .play, .vjs-big-play-button, .play-button, [class*='play']")
            for b in btns:
                if b.is_displayed() and b.is_enabled():
                    try:
                        d.execute_script("arguments[0].click()", b)
                        time.sleep(1)
                        return
                    except:
                        pass
        except:
            pass
        time.sleep(1)
    
    # Method 2: Click video element
    try:
        video = d.find_element(By.TAG_NAME, "video")
        if video:
            d.execute_script("arguments[0].play()", video)
            d.execute_script("arguments[0].click()", video)
            time.sleep(1)
    except:
        pass
    
    # Method 3: Click iframe content
    try:
        iframes = d.find_elements(By.TAG_NAME, "iframe")
        for iframe in iframes:
            try:
                d.switch_to.frame(iframe)
                # Try clicking anything clickable
                d.execute_script("document.querySelector('video')?.play()")
                d.switch_to.default_content()
            except:
                d.switch_to.default_content()
    except:
        pass

# ───────── STREAM EXTRACTION ─────────
def extract_m3u8(url):
    drv = init_driver()
    try:
        print(f"  Loading: {url}")
        drv.get(url)
        time.sleep(3)
        
        # Clear previous requests
        del drv.requests
        
        # Click play multiple times
        click_play(drv)
        time.sleep(2)
        click_play(drv)
        time.sleep(2)
        
        # Check for iframes and switch to them
        iframes = drv.find_elements(By.TAG_NAME, "iframe")
        for i, iframe in enumerate(iframes[:5]):
            try:
                src = iframe.get_attribute("src")
                if src and ("play" in src.lower() or "stream" in src.lower() or "video" in src.lower()):
                    print(f"  Found iframe: {src[:100]}")
                    drv.switch_to.frame(iframe)
                    click_play(drv)
                    time.sleep(2)
                    drv.switch_to.default_content()
            except:
                drv.switch_to.default_content()
        
        # Wait for m3u8 requests
        max_wait = 15
        for attempt in range(max_wait):
            for req in drv.requests:
                if req.response and req.response.status_code == 200:
                    url_lower = req.url.lower()
                    if ".m3u8" in url_lower or ".ts" in url_lower:
                        if "google" not in url_lower and "analytics" not in url_lower:
                            headers = dict(req.headers) if hasattr(req, 'headers') else {}
                            result = {
                                "url": req.url,
                                "referer": headers.get("Referer", ""),
                                "origin": headers.get("Origin", ""),
                                "user_agent": headers.get("User-Agent", ""),
                            }
                            print(f"  Found stream: {req.url[:100]}")
                            return result
            time.sleep(1)
        
        print(f"  No stream found after {max_wait}s")

    except Exception as e:
        print(f"  Error extracting stream: {e}")
    finally:
        drv.quit()

    return None

# ───────── HEADERS ─────────
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
    return r["url"] + "|" + "|".join(params) if params else r["url"]

# ───────── MAIN ─────────
def main():
    events = []
    
    # Only scrape RojaDirecta
    events += get_roja_events()

    print(f"\nRaw events: {len(events)}")

    # REMOVE DUPLICATES (by time + match name)
    unique = {}
    for liga, hora, partido, chan, url in events:
        key = (hora, partido, chan)  # Keep different channels for same match
        if key not in unique:
            unique[key] = (liga, hora, partido, chan, url)

    events = list(unique.values())
    print(f"Unique events: {len(events)}")

    # FILTER excluded leagues
    if EXCLUDED_LEAGUES:
        events = [e for e in events if not any(x.lower() in e[0].lower() for x in EXCLUDED_LEAGUES)]
        print(f"After filtering: {len(events)}")

    # SORT by time then league
    events.sort(key=lambda x: (x[1], x[0]))

    # Group by match to avoid processing same match multiple times
    # Take only first channel for each match
    matches = {}
    for liga, hora, partido, chan, url in events:
        key = (hora, partido)
        if key not in matches:
            matches[key] = (liga, hora, partido, url)
    
    print(f"Matches to process: {len(matches)}")

    entries = ["#EXTM3U"]
    tivimate = ["#EXTM3U"]

    #  PARALLEL PROCESSING
    to_process = list(matches.values())
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(extract_m3u8, url): (liga, hora, partido, url) 
                   for liga, hora, partido, url in to_process}

        for f in as_completed(futures):
            liga, hora, partido, url = futures[f]

            try:
                r = f.result()
                if not r:
                    print(f"No stream: {partido} ({hora})")
                    continue

                title = f"{hora} {liga} - {partido}"

                entries.append(f'#EXTINF:-1 group-title="{liga}",{title}')
                entries += vlc_headers(r)
                entries.append(r["url"])

                tivimate.append(f'#EXTINF:-1 group-title="{liga}",{title}')
                tivimate.append(tivimate_url(r))

                print(f"✓ {title}")

            except Exception as e:
                print(f"Error processing {partido}: {e}")

    # WRITE FILES
    (REPO_DIR / EVENT_FILE).write_text("\n".join(entries), encoding='utf-8')
    (REPO_DIR / TIVIMATE_FILE).write_text("\n".join(tivimate), encoding='utf-8')

    print(f"\nFiles written. VLC entries: {len(entries)-1}, Tivimate entries: {len(tivimate)-1}")

    # PUSH to git
    try:
        repo = Repo(REPO_DIR)
        repo.git.add(A=True)
        repo.index.commit(f"Auto update {time.strftime('%Y-%m-%d %H:%M:%S')}")
        repo.remote().push()
        print("Pushed to git successfully.")
    except Exception as e:
        print("Git error:", e)

if __name__ == "__main__":
    main()
