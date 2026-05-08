#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import os
import json
import time
import urllib3
import warnings

from pathlib import Path
from datetime import datetime
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup
from git import Repo

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

warnings.filterwarnings("ignore")
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

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/148.0.0.0 Safari/537.36"
)

EXCLUDED_LEAGUES = [
    # "NBA"
]

# ───────── DRIVER ─────────

def init_driver():

    opts = Options()

    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")

    opts.add_argument("--window-size=1920,1080")

    opts.add_argument(
        "--autoplay-policy=no-user-gesture-required"
    )

    opts.add_argument(
        "--disable-blink-features=AutomationControlled"
    )

    opts.add_argument("--disable-web-security")
    opts.add_argument("--allow-running-insecure-content")
    opts.add_argument("--ignore-certificate-errors")

    opts.add_argument(
        f"--user-agent={DEFAULT_USER_AGENT}"
    )

    # IMPORTANT
    opts.set_capability(
        "goog:loggingPrefs",
        {
            "performance": "ALL"
        }
    )

    try:

        service = Service(
            ChromeDriverManager().install()
        )

        driver = webdriver.Chrome(
            service=service,
            options=opts
        )

    except:

        driver = webdriver.Chrome(options=opts)

    driver.set_page_load_timeout(60)

    # IMPORTANT
    # Enable network BEFORE navigation
    driver.execute_cdp_cmd(
        "Network.enable",
        {}
    )

    return driver


# ───────── HELPERS ─────────

def normalize(url, base=ROJA_BASE):

    if not url:
        return ""

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

        hour, minute = map(
            int,
            time_str.split(":")
        )

        return now.replace(
            hour=hour,
            minute=minute,
            second=0,
            microsecond=0
        )

    except:
        return None


# ───────── EVENTS ─────────

def get_roja_events():

    events = []

    try:

        print(f"Fetching events from: {ROJA_URL}")

        r = requests.get(
            ROJA_URL,
            timeout=20,
            verify=False,
            headers={
                "User-Agent": DEFAULT_USER_AGENT
            }
        )

        soup = BeautifulSoup(
            r.text,
            "html.parser"
        )

        menu_items = soup.select(
            "ul.menu > li"
        )

        print(
            f"Found {len(menu_items)} events on page"
        )

        for li in menu_items:

            t = li.find("span", class_="t")

            if not t:
                continue

            hora = t.text.strip()

            main_link = li.find(
                "a",
                recursive=False
            )

            if not main_link:
                continue

            raw = main_link.text.strip()

            if hora in raw:
                raw = raw.replace(
                    hora,
                    ""
                ).strip()

            if ":" not in raw:
                continue

            liga, partido = raw.split(
                ":",
                1
            )

            liga = liga.strip()
            partido = partido.strip()

            first_channel = li.select_one(
                "ul > li.subitem1 > a"
            )

            if not first_channel:
                continue

            channel_name = (
                first_channel.text.strip()
            )

            if "Canal 1" not in channel_name:
                continue

            href = normalize(
                first_channel.get("href")
            )

            events.append({
                "liga": liga,
                "hora": hora,
                "partido": partido,
                "channel": channel_name,
                "url": href,
                "time_obj": parse_time(hora)
            })

        print(
            f"Extracted {len(events)} Canal 1 stream links"
        )

    except Exception as e:

        print(f"Error scraping: {e}")

    return events


# ───────── STREAM DETECTION ─────────

M3U8_REGEX = re.compile(
    r'https?://[^"\']+?\.m3u8(?:\?[^"\']*)?',
    re.IGNORECASE
)

BAD_WORDS = [
    "google",
    "analytics",
    "facebook",
    "doubleclick",
    "gstatic",
    "sharethis",
]


def clean_url(url):

    url = url.replace("\\/", "/")
    url = url.replace("&amp;", "&")

    return url.strip()


def valid_stream(url):

    if not url:
        return False

    url = url.lower()

    if ".m3u8" not in url:
        return False

    if any(x in url for x in BAD_WORDS):
        return False

    return True


def autoplay(driver):

    try:

        driver.execute_script("""
            try {

                document.querySelectorAll('video').forEach(v => {

                    try {
                        v.muted = true;
                        v.volume = 0;
                        v.autoplay = true;
                        v.play();
                    } catch(e){}

                });

                document.querySelectorAll(
                    'button,.play,.vjs-big-play-button,[onclick]'
                ).forEach(el => {

                    try {
                        el.click();
                    } catch(e){}

                });

            } catch(e){}
        """)

    except:
        pass


def get_m3u8_from_logs(driver):

    found = []

    try:

        logs = driver.get_log("performance")

        for entry in logs:

            try:

                msg = json.loads(
                    entry["message"]
                )["message"]

                method = msg.get(
                    "method",
                    ""
                )

                params = msg.get(
                    "params",
                    {}
                )

                if method == "Network.requestWillBeSent":

                    request = params.get(
                        "request",
                        {}
                    )

                    url = request.get(
                        "url",
                        ""
                    )

                    if valid_stream(url):

                        found.append(
                            clean_url(url)
                        )

                elif method == "Network.responseReceived":

                    response = params.get(
                        "response",
                        {}
                    )

                    url = response.get(
                        "url",
                        ""
                    )

                    mime = response.get(
                        "mimeType",
                        ""
                    )

                    if (
                        valid_stream(url)
                        or
                        "mpegurl" in mime.lower()
                        or
                        "application/vnd.apple.mpegurl" in mime.lower()
                    ):

                        found.append(
                            clean_url(url)
                        )

            except:
                pass

    except:
        pass

    # remove duplicates
    found = list(dict.fromkeys(found))

    # prioritize signed token streams
    for url in found:

        if (
            "md5=" in url
            and
            "expires=" in url
        ):
            return url

    if found:
        return found[0]

    return None


# ───────── EXTRACT STREAM ─────────

def extract_m3u8(event_info):

    url = event_info["url"]

    drv = None

    try:

        print(f"  Step 1: Loading {url}")

        drv = init_driver()

        try:
            drv.get_log("performance")
        except:
            pass

        drv.get(url)

        time.sleep(5)

        iframe = drv.find_element(
            By.TAG_NAME,
            "iframe"
        )

        iframe_src = iframe.get_attribute("src")

        print(
            f"  Step 2: Loading capo7play: "
            f"{iframe_src}"
        )

        # IMPORTANT
        # open iframe directly
        drv.get(iframe_src)

        time.sleep(10)

        autoplay(drv)

        print(
            "  Step 3: Searching for m3u8 stream..."
        )

        start = time.time()

        while (
            time.time() - start
            < STREAM_TIMEOUT
        ):

            autoplay(drv)

            # 1. PERFORMANCE LOGS
            stream = get_m3u8_from_logs(drv)

            if stream:

                print("  ✓ Stream found!")
                print(f"    URL: {stream}")

                return {
                    "url": stream,
                    "referer": FORCED_REFERER,
                    "origin": FORCED_ORIGIN,
                    "user_agent": DEFAULT_USER_AGENT,
                }

            # 2. PAGE SOURCE
            try:

                html = drv.page_source

                matches = M3U8_REGEX.findall(html)

                for m in matches:

                    m = clean_url(m)

                    if valid_stream(m):

                        print(
                            "  ✓ Stream found in HTML!"
                        )

                        print(f"    URL: {m}")

                        return {
                            "url": m,
                            "referer": FORCED_REFERER,
                            "origin": FORCED_ORIGIN,
                            "user_agent": DEFAULT_USER_AGENT,
                        }

            except:
                pass

            # 3. JAVASCRIPT VARIABLES
            try:

                js_urls = drv.execute_script("""
                    let out = [];

                    try {

                        const html =
                            document.documentElement.outerHTML;

                        const regex =
                            /https?:\\\\/\\\\/[^"'\\s]+?\\.m3u8(?:\\?[^"'\\s]*)?/gi;

                        const matches = html.match(regex);

                        if(matches){
                            out.push(...matches);
                        }

                    } catch(e){}

                    return out;
                """)

                if js_urls:

                    for m in js_urls:

                        m = clean_url(m)

                        if valid_stream(m):

                            print(
                                "  ✓ Stream found via JS!"
                            )

                            print(f"    URL: {m}")

                            return {
                                "url": m,
                                "referer": FORCED_REFERER,
                                "origin": FORCED_ORIGIN,
                                "user_agent": DEFAULT_USER_AGENT,
                            }

            except:
                pass

            time.sleep(2)

        print(
            f"  ✗ No stream found after "
            f"{STREAM_TIMEOUT}s"
        )

    except Exception as e:

        print(f"  Error: {str(e)[:300]}")

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
        h.append(
            f'#EXTVLCOPT:http-referrer={r["referer"]}'
        )

    if r.get("origin"):
        h.append(
            f'#EXTVLCOPT:http-origin={r["origin"]}'
        )

    if r.get("user_agent"):
        h.append(
            f'#EXTVLCOPT:http-user-agent={r["user_agent"]}'
        )

    return h


def tivimate_url(r):

    params = []

    if r.get("referer"):
        params.append(
            f'referer={r["referer"]}'
        )

    if r.get("origin"):
        params.append(
            f'origin={r["origin"]}'
        )

    if r.get("user_agent"):

        params.append(
            f'user-agent={quote(r["user_agent"])}'
        )

    if params:
        return r["url"] + "|" + "|".join(params)

    return r["url"]


# ───────── MAIN ─────────

def main():

    print("=" * 60)
    print("ROJADIRECTA STREAM SCRAPER")

    current_time = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    print(f"Time: {current_time}")
    print("=" * 60)

    all_events = get_roja_events()

    if not all_events:

        print("No events found!")

        return

    print(
        f"Total Canal 1 events found: "
        f"{len(all_events)}"
    )

    # remove excluded leagues
    if EXCLUDED_LEAGUES:

        all_events = [

            e for e in all_events

            if not any(
                x.lower() in e["liga"].lower()
                for x in EXCLUDED_LEAGUES
            )
        ]

    # remove duplicates
    seen = set()

    unique_events = []

    for e in all_events:

        key = (
            e["hora"],
            e["liga"],
            e["partido"]
        )

        if key not in seen:

            seen.add(key)

            unique_events.append(e)

    events_to_process = unique_events[:MAX_EVENTS]

    print(
        f"Events to process: "
        f"{len(events_to_process)}"
    )

    for e in events_to_process:

        print(
            f"  {e['hora']} | "
            f"{e['liga']}: "
            f"{e['partido']}"
        )

    entries = ["#EXTM3U"]
    tivimate = ["#EXTM3U"]

    successful = 0

    for idx, event in enumerate(
        events_to_process,
        1
    ):

        print(
            f"\n[{idx}/{len(events_to_process)}] "
            f"{event['hora']} - "
            f"{event['partido']}"
        )

        try:

            result = extract_m3u8(event)

            if result:

                liga = event["liga"]
                hora = event["hora"]
                partido = event["partido"]

                title = (
                    f"{hora} "
                    f"{liga} - "
                    f"{partido}"
                )

                # VLC
                entries.append(
                    f'#EXTINF:-1 group-title="{liga}",{title}'
                )

                entries += vlc_headers(result)

                entries.append(
                    result["url"]
                )

                # Tivimate
                tivimate.append(
                    f'#EXTINF:-1 group-title="{liga}",{title}'
                )

                tivimate.append(
                    tivimate_url(result)
                )

                successful += 1

                print(
                    "  ✓ Added to playlist"
                )

            else:

                print(
                    "  ✗ No stream found"
                )

        except Exception as e:

            print(
                f"  ✗ Error: {str(e)[:150]}"
            )

        time.sleep(3)

    print("\n" + "=" * 60)

    print(
        f"Results: "
        f"{successful}/"
        f"{len(events_to_process)} "
        f"streams captured"
    )

    try:

        (REPO_DIR / EVENT_FILE).write_text(
            "\n".join(entries),
            encoding="utf-8"
        )

        (REPO_DIR / TIVIMATE_FILE).write_text(
            "\n".join(tivimate),
            encoding="utf-8"
        )

        print("Files written:")
        print(
            f"  - {EVENT_FILE} "
            f"({max(0, successful)} entries)"
        )

        print(
            f"  - {TIVIMATE_FILE} "
            f"({max(0, successful)} entries)"
        )

    except Exception as e:

        print(f"Error writing files: {e}")

    # Git push
    if successful > 0:

        try:

            repo = Repo(REPO_DIR)

            repo.git.add(A=True)

            repo.index.commit(
                f"Update {current_time} - "
                f"{successful} streams"
            )

            repo.remote().push()

            print("✓ Pushed to git")

        except Exception as e:

            print(f"Git error: {e}")

    else:

        print("No streams to push")


if __name__ == "__main__":
    main()
