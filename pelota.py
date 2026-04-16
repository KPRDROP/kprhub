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
FUTLIB_URL = "https://futbollibre.mx/"
LIBPEL_URL = "https://librepelota.com/"
PELOTA1_URL = "https://www.pelotalibre1.pe/"

REPO_DIR = Path(__file__).parent
EVENT_FILE = "eventos.m3u"
TIVIMATE_FILE = "eventos_tivimate.m3u"

MAX_WORKERS = 4  # parallel threads (safe limit)

EXCLUDED_LEAGUES = [
    "Super Lig","Liga Endesa","Super League","Bundesliga","MLS",
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

    try:
        service = Service(ChromeDriverManager().install())
        return webdriver.Chrome(service=service, options=opts)
    except:
        return webdriver.Chrome(options=opts)

# ───────── HELPERS ─────────
def normalize(url):
    if not url or url.startswith('#'): return ''
    if url.startswith("//"): return "https:" + url
    if not url.startswith("http"): return "https://" + url
    return url

# ───────── SCRAPERS ─────────
def get_roja_events():
    events = []
    try:
        r = requests.get(ROJA_URL, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")

        for li in soup.select("ul.menu > li"):
            t = li.find("span", class_="t")
            if not t: continue
            hora = t.text.strip()

            link = li.find("a", recursive=False)
            if not link: continue

            raw = link.text.strip()
            if ":" not in raw: continue

            liga, partido = map(str.strip, raw.split(":", 1))

            for a in li.select("ul > li > a"):
                href = normalize(a.get("href"))
                if href:
                    events.append((liga, hora, partido, "Roja", href))
    except:
        pass
    return events

def get_futbollibre_style_events(url, name):
    events = []
    drv = init_driver()
    try:
        drv.get(url)
        time.sleep(5)

        for a in drv.find_elements(By.TAG_NAME, "a"):
            try:
                href = a.get_attribute("href")
                txt = a.text
                if not href or not txt: continue

                match = re.search(r'(\d{2}:\d{2})', txt)
                if match:
                    hora = match.group(1)
                    clean = txt.replace(hora, "").strip()

                    if ":" in clean:
                        liga, partido = clean.split(":", 1)
                    else:
                        liga, partido = "Varios", clean

                    events.append((liga.strip(), hora, partido.strip(), name, href))
            except:
                continue
    finally:
        drv.quit()

    return events

# ───────── CLICK PLAY ─────────
def click_play(d):
    for _ in range(2):
        try:
            btns = d.find_elements(By.CSS_SELECTOR, "button, .play, .vjs-big-play-button")
            for b in btns:
                if b.is_displayed():
                    d.execute_script("arguments[0].click()", b)
                    time.sleep(0.5)
        except:
            pass

# ───────── STREAM EXTRACTION (IMPROVED) ─────────
def extract_m3u8(url):
    drv = init_driver()
    try:
        drv.get(url)
        time.sleep(3)

        drv.requests.clear()  # important

        click_play(drv)

        # Try iframes
        for frame in drv.find_elements(By.TAG_NAME, "iframe")[:2]:
            try:
                drv.switch_to.frame(frame)
                click_play(drv)
                drv.switch_to.default_content()
            except:
                pass

        # wait loop instead of static sleep
        for _ in range(10):
            for req in drv.requests:
                if req.response and req.response.status_code == 200:
                    if ".m3u8" in req.url and "google" not in req.url:
                        headers = req.headers
                        return {
                            "url": req.url,
                            "referer": headers.get("Referer",""),
                            "origin": headers.get("Origin",""),
                            "user_agent": headers.get("User-Agent",""),
                        }
            time.sleep(1)

    except:
        pass
    finally:
        drv.quit()

    return None

# ───────── HEADERS ─────────
def vlc_headers(r):
    h=[]
    if r["referer"]: h.append(f'#EXTVLCOPT:http-referrer={r["referer"]}')
    if r["origin"]: h.append(f'#EXTVLCOPT:http-origin={r["origin"]}')
    if r["user_agent"]: h.append(f'#EXTVLCOPT:http-user-agent={r["user_agent"]}')
    return h

def tivimate_url(r):
    params=[]
    if r["referer"]: params.append(f"referer={r['referer']}")
    if r["origin"]: params.append(f"origin={r['origin']}")
    if r["user_agent"]: params.append(f"user-agent={quote(r['user_agent'])}")
    return r["url"] + "|" + "|".join(params) if params else r["url"]

# ───────── MAIN ─────────
def main():
    events = []
    events += get_roja_events()
    events += get_futbollibre_style_events(FUTLIB_URL, "FutbolLibre")
    events += get_futbollibre_style_events(LIBPEL_URL, "LibrePelota")
    events += get_futbollibre_style_events(PELOTA1_URL, "Pelota1")

    print(f"Raw events: {len(events)}")

    # REMOVE DUPLICATES
    unique = {}
    for liga, hora, partido, chan, url in events:
        key = (hora, partido)
        if key not in unique:
            unique[key] = (liga, hora, partido, chan, url)

    events = list(unique.values())
    print(f"Unique events: {len(events)}")

    # FILTER
    events = [e for e in events if not any(x.lower() in e[0].lower() for x in EXCLUDED_LEAGUES)]

    # SORT
    events.sort(key=lambda x: (x[1], x[0]))

    entries = ["#EXTM3U"]
    tivimate = ["#EXTM3U"]

    # ⚡ PARALLEL PROCESSING
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(extract_m3u8, e[4]): e for e in events}

        for f in as_completed(futures):
            liga, hora, partido, chan, url = futures[f]

            try:
                r = f.result()
                if not r:
                    print(f"No stream: {partido}")
                    continue

                title = f"{hora} {liga} - {partido}"

                entries.append(f'#EXTINF:-1 group-title="{liga}", {title}')
                entries += vlc_headers(r)
                entries.append(r["url"])

                tivimate.append(f'#EXTINF:-1 group-title="{liga}", {title}')
                tivimate.append(tivimate_url(r))

                print(f"{partido}")

            except:
                continue

    # WRITE FILES (ALWAYS)
    (REPO_DIR / EVENT_FILE).write_text("\n".join(entries))
    (REPO_DIR / TIVIMATE_FILE).write_text("\n".join(tivimate))

    # FORCE CHANGE (guarantee commit)
    with open(REPO_DIR / EVENT_FILE, "a") as f:
        f.write(f"\n# updated {time.time()}")

    print("Files written.")

    # PUSH
    try:
        repo = Repo(REPO_DIR)
        repo.git.add(A=True)
        repo.index.commit(f"Auto update {time.time()}")
        repo.remote().push()
        print("Pushed.")
    except Exception as e:
        print("Git error:", e)

if __name__ == "__main__":
    main()
