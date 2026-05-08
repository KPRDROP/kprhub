import os
import re
import time
import json
import shutil
import requests

from bs4 import BeautifulSoup

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By

# ============================================================
# CONFIG
# ============================================================

BASE_URL = "https://www.rojadirectaenvivo.pl/"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/148.0.7778.96 Safari/537.36"
)

HEADERS = {
    "User-Agent": USER_AGENT
}

# ============================================================
# FIX CHROMEDRIVER VERSION WARNING
# ============================================================

def find_chrome_binary():
    candidates = [
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser"
    ]

    for path in candidates:
        if os.path.exists(path):
            return path

    return None

def create_driver():
    chrome_options = Options()

    chrome_binary = find_chrome_binary()

    if chrome_binary:
        chrome_options.binary_location = chrome_binary

    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--disable-features=IsolateOrigins,site-per-process")
    chrome_options.add_argument("--autoplay-policy=no-user-gesture-required")
    chrome_options.add_argument("--window-size=1920,1080")

    chrome_options.add_argument(f"user-agent={USER_AGENT}")

    # IMPORTANT
    # Selenium Manager auto-downloads correct driver
    # and avoids PATH chromedriver mismatch warning

    service = Service()

    chrome_options.set_capability(
        "goog:loggingPrefs",
        {
            "performance": "ALL"
        }
    )

    driver = webdriver.Chrome(
        service=service,
        options=chrome_options
    )

    driver.set_page_load_timeout(60)

    driver.execute_cdp_cmd("Network.enable", {})

    return driver

# ============================================================
# EVENTS
# ============================================================

def get_events():
    print(f"Fetching events from: {BASE_URL}")

    html = requests.get(
        BASE_URL,
        headers=HEADERS,
        timeout=30
    ).text

    soup = BeautifulSoup(html, "html.parser")

    events = []

    for a in soup.find_all("a", href=True):

        href = a["href"]

        if "/en-vivo/" not in href:
            continue

        title = a.get_text(" ", strip=True)

        if not title:
            continue

        if href.startswith("/"):
            href = "https://rojadirectablog.com" + href

        events.append({
            "title": title,
            "url": href
        })

    # REMOVE DUPLICATES
    seen = set()
    unique = []

    for e in events:

        if e["url"] in seen:
            continue

        seen.add(e["url"])
        unique.append(e)

    print(f"Found {len(unique)} events on page")

    return unique

# ============================================================
# GET CAPOPLAY URL
# ============================================================

def get_capoplay_url(event_url):
    try:
        html = requests.get(
            event_url,
            headers=HEADERS,
            timeout=30
        ).text

        match = re.search(
            r'<iframe[^>]+src="([^"]+capoplay[^"]+)"',
            html,
            re.I
        )

        if match:
            return match.group(1)

    except Exception as e:
        print("iframe parse error:", e)

    return None

# ============================================================
# EXTRACT STREAMS
# ============================================================

def extract_streams(driver):
    found = set()

    # --------------------------------------------------------
    # HTML
    # --------------------------------------------------------

    try:
        html = driver.page_source

        matches = re.findall(
            r'https?:\/\/[^"\']+\.m3u8[^"\']*',
            html,
            re.I
        )

        for m in matches:
            found.add(m)

    except:
        pass

    # --------------------------------------------------------
    # PERFORMANCE ENTRIES
    # --------------------------------------------------------

    try:
        resources = driver.execute_script("""
            return performance.getEntries()
                .map(e => e.name);
        """)

        for r in resources:
            if ".m3u8" in r:
                found.add(r)

    except:
        pass

    # --------------------------------------------------------
    # VIDEO TAGS
    # --------------------------------------------------------

    try:
        video_urls = driver.execute_script("""
            let out = [];

            document.querySelectorAll("video").forEach(v => {

                if (v.src)
                    out.push(v.src);

                if (v.currentSrc)
                    out.push(v.currentSrc);
            });

            return out;
        """)

        for v in video_urls:
            if ".m3u8" in v:
                found.add(v)

    except:
        pass

    # --------------------------------------------------------
    # NETWORK LOGS
    # --------------------------------------------------------

    try:
        logs = driver.get_log("performance")

        for entry in logs:

            try:
                msg = json.loads(
                    entry["message"]
                )["message"]

                if msg["method"] != "Network.responseReceived":
                    continue

                url = msg["params"]["response"]["url"]

                if ".m3u8" in url:
                    found.add(url)

            except:
                pass

    except:
        pass

    # --------------------------------------------------------
    # CLEAN URLS
    # --------------------------------------------------------

    cleaned = []

    for url in found:

        if ".m3u8" not in url:
            continue

        url = url.replace("\\u0026", "&")
        url = url.replace("\\/", "/")

        if url.startswith("//"):
            url = "https:" + url

        cleaned.append(url)

    cleaned = list(dict.fromkeys(cleaned))

    cleaned.sort(
        key=lambda x: (
            "md5=" not in x and "token=" not in x,
            len(x)
        )
    )

    return cleaned

# ============================================================
# MAIN EXTRACTOR
# ============================================================

def extract_m3u8(event_url):
    driver = None

    try:
        print(f"  Loading: {event_url}")

        capoplay = get_capoplay_url(event_url)

        if not capoplay:
            print("  ✗ No capoplay iframe found")
            return None

        print(f"  Capoplay: {capoplay}")

        driver = create_driver()

        # ----------------------------------------------------
        # OPEN EVENT PAGE
        # ----------------------------------------------------

        driver.get(event_url)

        time.sleep(5)

        # ----------------------------------------------------
        # OPEN CAPOPLAY PAGE
        # ----------------------------------------------------

        driver.get(capoplay)

        print("  Waiting for player init...")

        for i in range(15):

            print(f"    Scan {i+1}/15")

            time.sleep(4)

            # CLICK BODY
            try:
                driver.find_element(By.TAG_NAME, "body").click()
            except:
                pass

            # FORCE PLAY
            try:
                driver.execute_script("""
                    document.querySelectorAll("video").forEach(v => {
                        v.muted = true;
                        v.play().catch(()=>{});
                    });
                """)
            except:
                pass

            streams = extract_streams(driver)

            if streams:

                print(f"  Found {len(streams)} stream(s)")

                for s in streams:
                    print(f"    STREAM: {s}")

                # PREFER TOKENIZED URL
                for s in streams:
                    if "md5=" in s:
                        return s

                return streams[0]

        print("  ✗ No stream found after deep scan")

        return None

    except Exception as e:
        print("  Error:", e)
        return None

    finally:
        if driver:
            driver.quit()

# ============================================================
# WRITE PLAYLISTS
# ============================================================

def write_m3u(results):

    vlc = ["#EXTM3U"]
    tivimate = ["#EXTM3U"]

    for idx, item in enumerate(results, 1):

        title = item["title"]
        stream = item["stream"]

        vlc.append(
            f'#EXTINF:-1 tvg-chno="{idx}" group-title="Eventos",{title}'
        )
        vlc.append(stream)

        encoded_ua = USER_AGENT.replace(" ", "%20")

        tivimate_stream = (
            stream
            + f"|User-Agent={encoded_ua}&Referer=https://www.capoplay.net/"
        )

        tivimate.append(
            f'#EXTINF:-1 tvg-chno="{idx}" group-title="Eventos",{title}'
        )
        tivimate.append(tivimate_stream)

    with open("eventos.m3u8", "w", encoding="utf-8") as f:
        f.write("\n".join(vlc))

    with open("eventos_tivimate.m3u8", "w", encoding="utf-8") as f:
        f.write("\n".join(tivimate))

# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)
    print("ROJADIRECTA STREAM SCRAPER")
    print("Time:", time.strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 60)

    events = get_events()

    print(f"Events to process: {len(events)}")

    results = []

    for idx, event in enumerate(events, 1):

        print(f"[{idx}/{len(events)}] {event['title']}")

        stream = extract_m3u8(event["url"])

        if stream:

            print("  ✓ STREAM CAPTURED")
            print(f"  {stream}")

            results.append({
                "title": event["title"],
                "stream": stream
            })

        else:
            print("  ✗ No stream found")

        print()

    print("=" * 60)
    print(f"Results: {len(results)}/{len(events)} streams captured")

    write_m3u(results)

    print("Files written:")
    print(f"  - eventos.m3u8 ({len(results)} entries)")
    print(f"  - eventos_tivimate.m3u8 ({len(results)} entries)")

# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
