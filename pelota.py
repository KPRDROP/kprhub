import os
import re
import time
import json
import base64
import requests
from bs4 import BeautifulSoup

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
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
# SELENIUM
# ============================================================

def create_driver():
    chrome_options = Options()

    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--disable-features=IsolateOrigins,site-per-process")
    chrome_options.add_argument("--autoplay-policy=no-user-gesture-required")
    chrome_options.add_argument("--window-size=1920,1080")

    chrome_options.add_argument(f"user-agent={USER_AGENT}")

    # PERFORMANCE LOGS ENABLED
    chrome_options.set_capability(
        "goog:loggingPrefs",
        {
            "performance": "ALL"
        }
    )

    driver = webdriver.Chrome(options=chrome_options)

    driver.set_page_load_timeout(60)

    # ENABLE NETWORK
    driver.execute_cdp_cmd("Network.enable", {})

    return driver

# ============================================================
# GET EVENTS
# ============================================================

def get_events():
    print(f"Fetching events from: {BASE_URL}")

    html = requests.get(BASE_URL, headers=HEADERS, timeout=30).text

    soup = BeautifulSoup(html, "html.parser")

    events = []

    links = soup.find_all("a", href=True)

    for a in links:
        href = a["href"]

        if "/en-vivo/" not in href:
            continue

        text = a.get_text(" ", strip=True)

        if not text:
            continue

        if href.startswith("/"):
            href = "https://rojadirectablog.com" + href

        events.append({
            "title": text,
            "url": href
        })

    # remove duplicates
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
# PARSE CAPOPLAY URL
# ============================================================

def get_capoplay_url(event_url):
    try:
        html = requests.get(event_url, headers=HEADERS, timeout=30).text

        m = re.search(r'<iframe[^>]+src="([^"]+capoplay[^"]+)"', html, re.I)

        if m:
            return m.group(1)

    except Exception as e:
        print("Error parsing capoplay:", e)

    return None

# ============================================================
# EXTRACT DIRECT STREAM FROM JS
# ============================================================

def extract_direct_from_page(driver):
    """
    VERY IMPORTANT PATCH

    The stream is NOT always visible in normal requests.
    It is usually created dynamically by capo.js.

    This function aggressively inspects:

    - HTML
    - inline scripts
    - video tags
    - network logs
    - JS variables
    - performance resources
    """

    found = set()

    # --------------------------------------------------------
    # 1. PAGE SOURCE
    # --------------------------------------------------------

    try:
        src = driver.page_source

        matches = re.findall(
            r'https?:\/\/[^"\']+\.m3u8[^"\']*',
            src,
            re.I
        )

        for m in matches:
            found.add(m)
    except:
        pass

    # --------------------------------------------------------
    # 2. PERFORMANCE ENTRIES
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
    # 3. VIDEO TAGS
    # --------------------------------------------------------

    try:
        videos = driver.execute_script("""
            let out = [];

            document.querySelectorAll("video").forEach(v => {
                if (v.src) out.push(v.src);

                if (v.currentSrc) out.push(v.currentSrc);
            });

            return out;
        """)

        for v in videos:
            if ".m3u8" in v:
                found.add(v)
    except:
        pass

    # --------------------------------------------------------
    # 4. PERFORMANCE NETWORK LOGS
    # --------------------------------------------------------

    try:
        logs = driver.get_log("performance")

        for entry in logs:

            try:
                msg = json.loads(entry["message"])["message"]

                if msg["method"] != "Network.responseReceived":
                    continue

                url = msg["params"]["response"]["url"]

                if ".m3u8" in url:
                    found.add(url)

            except:
                continue

    except Exception as e:
        print("Performance log error:", e)

    # --------------------------------------------------------
    # 5. FULL HTML REGEX FALLBACK
    # --------------------------------------------------------

    try:
        html = driver.execute_script("""
            return document.documentElement.outerHTML;
        """)

        matches = re.findall(
            r'https?:\/\/[^"\']+',
            html,
            re.I
        )

        for m in matches:
            if ".m3u8" in m:
                found.add(m)

    except:
        pass

    # --------------------------------------------------------
    # CLEAN STREAMS
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

    # prefer tokenized links
    cleaned.sort(
        key=lambda x: (
            "token" not in x and "md5=" not in x,
            len(x)
        )
    )

    return cleaned

# ============================================================
# MAIN M3U8 EXTRACTOR
# ============================================================

def extract_m3u8(event_url):
    driver = None

    try:
        print(f"  Loading: {event_url}")

        capoplay = get_capoplay_url(event_url)

        if not capoplay:
            print("  ✗ No capoplay iframe found")
            return None

        print(f"  Capoplay iframe: {capoplay}")

        driver = create_driver()

        # ----------------------------------------------------
        # LOAD EVENT PAGE FIRST
        # ----------------------------------------------------

        driver.get(event_url)

        time.sleep(5)

        # ----------------------------------------------------
        # DIRECTLY LOAD CAPOPLAY PAGE
        # ----------------------------------------------------

        driver.get(capoplay)

        print("  Waiting for player init...")

        # IMPORTANT:
        # capo.js sometimes waits many seconds
        # before generating player
        for i in range(12):

            print(f"    wait {i+1}/12")

            time.sleep(5)

            streams = extract_direct_from_page(driver)

            if streams:

                print(f"  Found {len(streams)} stream(s)")

                for s in streams:
                    print(f"    STREAM: {s}")

                # prefer tokenized stream
                for s in streams:
                    if "md5=" in s or "token=" in s:
                        return s

                return streams[0]

            # CLICK BODY TO TRIGGER PLAY
            try:
                driver.find_element(By.TAG_NAME, "body").click()
            except:
                pass

            # TRY PLAY VIDEO
            try:
                driver.execute_script("""
                    document.querySelectorAll("video").forEach(v => {
                        v.muted = true;
                        v.play().catch(()=>{});
                    });
                """)
            except:
                pass

        print("  ✗ No stream found after deep inspection")

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

def write_m3u(events):
    vlc_lines = ["#EXTM3U"]
    tivimate_lines = ["#EXTM3U"]

    for idx, e in enumerate(events, 1):

        title = e["title"]
        url = e["stream"]

        vlc_lines.append(
            f'#EXTINF:-1 tvg-chno="{idx}" group-title="Eventos",{title}'
        )
        vlc_lines.append(url)

        encoded_ua = USER_AGENT.replace(" ", "%20")

        tivimate_url = (
            url +
            f'|User-Agent={encoded_ua}&Referer=https://www.capoplay.net/'
        )

        tivimate_lines.append(
            f'#EXTINF:-1 tvg-chno="{idx}" group-title="Eventos",{title}'
        )
        tivimate_lines.append(tivimate_url)

    with open("eventos.m3u8", "w", encoding="utf-8") as f:
        f.write("\n".join(vlc_lines))

    with open("eventos_tivimate.m3u8", "w", encoding="utf-8") as f:
        f.write("\n".join(tivimate_lines))

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

        title = event["title"]
        url = event["url"]

        print(f"[{idx}/{len(events)}] {title}")

        stream = extract_m3u8(url)

        if stream:
            print("  ✓ STREAM CAPTURED")
            print(" ", stream)

            results.append({
                "title": title,
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

    if results:
        print("Done.")
    else:
        print("No streams captured")

# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
