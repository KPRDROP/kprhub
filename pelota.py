import asyncio
import re
import time
import urllib.parse
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

BASE_URL = "https://www.rojadirectaenvivo.pl/"
OUTPUT_VLC = "eventos.m3u8"
OUTPUT_TIVIMATE = "eventos_tivimate.m3u8"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/148.0.7778.96 Safari/537.36"
)

HEADERS = {
    "User-Agent": USER_AGENT,
    "Referer": "https://capo7play.com/",
    "Origin": "https://capo7play.com",
}


# ============================================================
# FETCH EVENTS
# ============================================================

def fetch_events():
    print(f"Fetching events from: {BASE_URL}")

    r = requests.get(BASE_URL, headers=HEADERS, timeout=30)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")

    events = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()

        if "/en-vivo/" not in href:
            continue

        if not href.endswith(".php"):
            continue

        text = a.get_text(" ", strip=True)

        if not text:
            continue

        if href.startswith("/"):
            href = "https://rojadirectablog.com" + href

        key = (text, href)
        if key in seen:
            continue

        seen.add(key)

        events.append(
            {
                "title": text,
                "link": href,
            }
        )

    print(f"Found {len(events)} events on page")

    return events


# ============================================================
# EXTRACT M3U8
# ============================================================

M3U8_REGEX = re.compile(
    r'https?://[^\s"\'<>]+\.m3u8(?:\?[^\s"\'<>]*)?',
    re.IGNORECASE,
)


async def extract_m3u8(page, url):
    print(f"  Loading: {url}")

    found_urls = set()
    final_url = None

    # --------------------------------------------------------
    # RESPONSE SNIFFER
    # --------------------------------------------------------
    async def handle_response(response):
        nonlocal final_url

        try:
            response_url = response.url

            if ".m3u8" in response_url:
                print(f"    [response] {response_url[:150]}")
                found_urls.add(response_url)
                final_url = response_url
                return

            content_type = response.headers.get("content-type", "")

            if (
                "mpegurl" in content_type.lower()
                or "application/vnd.apple.mpegurl" in content_type.lower()
            ):
                print(f"    [playlist] {response_url[:150]}")
                found_urls.add(response_url)
                final_url = response_url
                return

        except Exception:
            pass

    page.on("response", handle_response)

    # --------------------------------------------------------
    # REQUEST SNIFFER
    # --------------------------------------------------------
    async def handle_request(request):
        nonlocal final_url

        try:
            req_url = request.url

            if ".m3u8" in req_url:
                print(f"    [request] {req_url[:150]}")
                found_urls.add(req_url)
                final_url = req_url

        except Exception:
            pass

    page.on("request", handle_request)

    # --------------------------------------------------------
    # GOTO MAIN PAGE
    # --------------------------------------------------------
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=90000)
    except Exception as e:
        print(f"  goto warning: {e}")

    await page.wait_for_timeout(5000)

    # --------------------------------------------------------
    # FIND IFRAME
    # --------------------------------------------------------
    iframe_url = None

    try:
        frames = page.frames

        for frame in frames:
            f_url = frame.url

            if not f_url:
                continue

            if "capoplay" in f_url or "capo" in f_url:
                iframe_url = f_url
                print(f"  Found iframe: {iframe_url}")
                break

        if not iframe_url:
            html = await page.content()
            matches = re.findall(r'https://[^\"\']+', html)

            for m in matches:
                if "capoplay" in m:
                    iframe_url = m
                    print(f"  Found iframe in HTML: {iframe_url}")
                    break

    except Exception as e:
        print(f"  iframe parse error: {e}")

    # --------------------------------------------------------
    # LOAD IFRAME DIRECTLY
    # --------------------------------------------------------
    if iframe_url:
        try:
            await page.goto(iframe_url, wait_until="domcontentloaded", timeout=90000)
            await page.wait_for_timeout(8000)
        except Exception as e:
            print(f"  iframe goto error: {e}")

    # --------------------------------------------------------
    # CLICK BODY TO START PLAYER
    # --------------------------------------------------------
    try:
        await page.mouse.move(400, 300)
        await page.mouse.click(400, 300)
        await page.wait_for_timeout(2000)

        await page.keyboard.press("Space")
        await page.wait_for_timeout(2000)

    except Exception:
        pass

    # --------------------------------------------------------
    # JS EXTRACTION LOOP
    # --------------------------------------------------------
    print("  Searching for m3u8 streams...")

    start = time.time()

    while time.time() - start < 90:
        if final_url:
            break

        try:
            current_html = await page.content()

            matches = M3U8_REGEX.findall(current_html)

            for m in matches:
                if ".m3u8" in m:
                    print(f"    [html] {m[:150]}")
                    found_urls.add(m)
                    final_url = m
                    break

        except Exception:
            pass

        # Try extracting from JS variables
        try:
            js_result = await page.evaluate(
                """
                () => {
                    const results = [];

                    for (const key in window) {
                        try {
                            const val = window[key];

                            if (typeof val === 'string' && val.includes('.m3u8')) {
                                results.push(val);
                            }
                        } catch(e) {}
                    }

                    return results;
                }
                """
            )

            for item in js_result:
                matches = M3U8_REGEX.findall(item)

                for m in matches:
                    print(f"    [window] {m[:150]}")
                    found_urls.add(m)
                    final_url = m
                    break

        except Exception:
            pass

        # Scan performance entries
        try:
            perf = await page.evaluate(
                """
                () => performance.getEntries()
                    .map(e => e.name)
                    .filter(e => e.includes('.m3u8'))
                """
            )

            for p in perf:
                print(f"    [performance] {p[:150]}")
                found_urls.add(p)
                final_url = p

        except Exception:
            pass

        # Refresh interaction every loop
        try:
            await page.mouse.click(500, 350)
        except Exception:
            pass

        await page.wait_for_timeout(3000)

    # --------------------------------------------------------
    # CLEAN URL
    # --------------------------------------------------------
    if final_url:
        final_url = final_url.replace("\\u002F", "/")
        final_url = final_url.replace("\\/", "/")
        final_url = final_url.strip()

        print(f"  ✓ Stream found")
        print(f"    {final_url}")

        return final_url

    print(f"  ✗ No stream found after 90s")
    print(f"  Total m3u8 URLs found: {len(found_urls)}")

    return None


# ============================================================
# WRITE PLAYLISTS
# ============================================================

def write_playlists(results):
    vlc_lines = ["#EXTM3U"]
    tivimate_lines = ["#EXTM3U"]

    encoded_ua = urllib.parse.quote(USER_AGENT)

    for idx, item in enumerate(results, start=1):
        title = item["title"]
        url = item["url"]

        vlc_lines.append(f'#EXTINF:-1 tvg-chno="{idx}",{title}')
        vlc_lines.append(url)

        tivimate_lines.append(f'#EXTINF:-1 tvg-chno="{idx}",{title}')
        tivimate_lines.append(
            url
            + "|user-agent="
            + encoded_ua
            + "&referer=https%3A%2F%2Frojadirectablog.com%2F"
        )

    Path(OUTPUT_VLC).write_text(
        "\n".join(vlc_lines),
        encoding="utf-8",
    )

    Path(OUTPUT_TIVIMATE).write_text(
        "\n".join(tivimate_lines),
        encoding="utf-8",
    )

    print("=" * 60)
    print(f"Results: {len(results)} streams captured")
    print("Files written:")
    print(f"  - {OUTPUT_VLC} ({len(results)} entries)")
    print(f"  - {OUTPUT_TIVIMATE} ({len(results)} entries)")


# ============================================================
# MAIN
# ============================================================

async def main():
    print("=" * 60)
    print("ROJADIRECTA STREAM SCRAPER")
    print(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    events = fetch_events()

    print(f"Events to process: {len(events)}")

    for ev in events:
        print(f"  | {ev['title']}")

    results = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-setuid-sandbox",
                "--autoplay-policy=no-user-gesture-required",
                "--mute-audio",
            ],
        )

        context = await browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1920, "height": 1080},
            ignore_https_errors=True,
        )

        await context.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            """
        )

        page = await context.new_page()

        for idx, ev in enumerate(events, start=1):
            print(f"[{idx}/{len(events)}] {ev['title']}")

            try:
                stream = await extract_m3u8(page, ev["link"])

                if stream:
                    results.append(
                        {
                            "title": ev["title"],
                            "url": stream,
                        }
                    )
                else:
                    print("  ✗ No stream found")

            except Exception as e:
                print(f"  Error: {e}")

        await browser.close()

    write_playlists(results)


if __name__ == "__main__":
    asyncio.run(main())
