#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import time
import json
from datetime import datetime
from pathlib import Path
from git import Repo
import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from urllib.parse import quote
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
STREAM_TIMEOUT = 35

# Default user agent
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/144.0.0.0 Safari/537.36"
)

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

    # Performance logs
    opts.set_capability(
        "goog:loggingPrefs",
        {
            "performance": "ALL",
            "browser": "ALL"
        }
    )

    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=opts)
    except:
        driver = webdriver.Chrome(options=opts)

    driver.set_page_load_timeout(45)
    driver.set_script_timeout(45)

    return driver

# ───────── HELPERS ─────────
def normalize(url, base=ROJA_BASE):
    if not url or url.startswith("#"):
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

        hour, minute = map(int, time_str.split(":"))

        return now.replace(
            hour=hour,
            minute=minute,
            second=0,
            microsecond=0
        )
    except:
        return None

# ───────── EVENT SCRAPER ─────────
def get_roja_events():
    events = []

    try:
        print(f"Fetching events from: {ROJA_URL}")

        headers = {
            "User-Agent": DEFAULT_USER_AGENT
        }

        r = requests.get(
            ROJA_URL,
            timeout=20,
            headers=headers,
            verify=False
        )

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

            liga = parts[0].strip()
            partido = parts[1].strip()

            # ONLY Canal 1
            first_channel = li.select_one(
                "ul > li.subitem1 > a"
            )

            if not first_channel:
                continue

            channel_name = first_channel.text.strip()

            if "Canal 1" not in channel_name:
                continue

            href = normalize(first_channel.get("href"))

            if not href:
                continue

            events.append({
                "liga": liga,
                "hora": hora,
                "partido": partido,
                "channel": channel_name,
                "url": href,
                "time_obj": parse_time(hora)
            })

        print(f"Extracted {len(events)} Canal 1 stream links")

    except Exception as e:
        print(f"Error scraping: {e}")

    return events

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


def clean_url(url):
    url = url.replace("\\/", "/")
    url = url.replace("&amp;", "&")
    url = url.strip()

    return url


def extract_m3u8_from_text(text):
    found = []

    if not text:
        return found

    matches = M3U8_REGEX.findall(text)

    for url in matches:
        url = clean_url(url)

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

                request = params.get("request", {})
                req_url = request.get("url", "")

                if is_valid_m3u8(req_url):
                    urls.append(clean_url(req_url))

                response = params.get("response", {})
                res_url = response.get("url", "")

                if is_valid_m3u8(res_url):
                    urls.append(clean_url(res_url))

            except:
                pass

    except:
        pass

    return list(dict.fromkeys(urls))


def inspect_page_source(driver):
    urls = []

    try:
        source = driver.page_source

        urls.extend(
            extract_m3u8_from_text(source)
        )

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

                urls.extend(
                    extract_m3u8_from_text(content)
                )

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

        urls.extend(
            extract_m3u8_from_text(html)
        )

    except:
        pass

    return list(dict.fromkeys(urls))


def inspect_iframes_recursive(driver, depth=0, max_depth=5):
    urls = []

    if depth > max_depth:
        return urls

    try:
        iframes = driver.find_elements(By.TAG_NAME, "iframe")

        for iframe in iframes:
            try:
                src = iframe.get_attribute("src") or ""

                if src:
                    print(f"    iframe[{depth}]: {src[:120]}")

                driver.switch_to.frame(iframe)

                time.sleep(2)

                urls.extend(inspect_page_source(driver))
                urls.extend(inspect_scripts(driver))
                urls.extend(inspect_dom(driver))
                urls.extend(inspect_browser_logs(driver))

                # autoplay inside iframe
                try:
                    driver.execute_script("""
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

                # recursive deeper
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

    url = event_info["url"]

    drv = None

    try:
        print(f"  Loading: {url}")

        drv = init_driver()

        drv.get(url)

        time.sleep(8)

        # autoplay
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

            # main page
            found.extend(inspect_browser_logs(drv))
            found.extend(inspect_page_source(drv))
            found.extend(inspect_scripts(drv))
            found.extend(inspect_dom(drv))

            # iframes
            found.extend(
                inspect_iframes_recursive(drv)
            )

            # deduplicate
            found = list(dict.fromkeys(found))

            # prioritize signed URLs
            signed = []

            for u in found:
                if "md5=" in u or "expires=" in u:
                    signed.append(u)

            if signed:
                stream_url = signed[0]

                print("  ✓ Signed stream found!")
                print(f"    URL: {stream_url}")

                return {
                    "url": stream_url,
                    "referer": FORCED_REFERER,
                    "origin": FORCED_ORIGIN,
                    "user_agent": DEFAULT_USER_AGENT,
                }

            # fallback
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

    print(f"\nTotal Canal 1 events found: {len(all_events)}")

    # exclude leagues
    if EXCLUDED_LEAGUES:
        all_events = [
            e for e in all_events
            if not any(
                x.lower() in e["liga"].lower()
                for x in EXCLUDED_LEAGUES
            )
        ]

    # sort
    all_events.sort(
        key=lambda x: (
            x["hora"],
            x["liga"]
        )
    )

    # dedupe
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

    print(f"Events to process: {len(events_to_process)}")

    if not events_to_process:

        (REPO_DIR / EVENT_FILE).write_text(
            "#EXTM3U\n",
            encoding="utf-8"
        )

        (REPO_DIR / TIVIMATE_FILE).write_text(
            "#EXTM3U\n",
            encoding="utf-8"
        )

        return

    for e in events_to_process:
        print(
            f'  {e["hora"]} | '
            f'{e["liga"]}: '
            f'{e["partido"]}'
        )

    entries = ["#EXTM3U"]
    tivimate = ["#EXTM3U"]

    successful = 0

    for idx, event in enumerate(events_to_process, 1):

        print(
            f'\n[{idx}/{len(events_to_process)}] '
            f'{event["hora"]} - {event["partido"]}'
        )

        try:
            result = extract_m3u8(event)

            if result:

                liga = event["liga"]
                hora = event["hora"]
                partido = event["partido"]

                title = f"{hora} {liga} - {partido}"

                # VLC
                entries.append(
                    f'#EXTINF:-1 group-title="{liga}",{title}'
                )

                entries += vlc_headers(result)

                entries.append(result["url"])

                # Tivimate
                tivimate.append(
                    f'#EXTINF:-1 group-title="{liga}",{title}'
                )

                tivimate.append(
                    tivimate_url(result)
                )

                successful += 1

                print("  ✓ Added to playlist")

            else:
                print("  ✗ No stream found")

        except Exception as e:
            print(f"  ✗ Error: {str(e)[:100]}")

        time.sleep(3)

    # save files
    print(f"\n{'=' * 60}")
    print(
        f"Results: "
        f"{successful}/{len(events_to_process)} "
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
            f"({len(entries)-1} entries)"
        )

        print(
            f"  - {TIVIMATE_FILE} "
            f"({len(tivimate)-1} entries)"
        )

        if successful > 0:

            print("\nSample output:")

            for line in entries[1:6]:
                print(f"  {line[:120]}")

    except Exception as e:
        print(f"Error writing files: {e}")

    # git push
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
