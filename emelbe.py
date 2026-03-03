import asyncio
import os
import re
from functools import partial
from pathlib import Path
from urllib.parse import urljoin, quote

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

from utils import Cache, Time, get_logger, leagues, network

log = get_logger(__name__)

# --------------------------------------------------
# CONFIG
# --------------------------------------------------

TAG = "WEBCAST"

BASE_URL = os.environ.get("WEBTV_MLB_BASE_URL")
if not BASE_URL:
    raise RuntimeError("Missing WEBTV_MLB_BASE_URL secret")

BASE_URL = BASE_URL.rstrip("/") + "/"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:146.0) "
    "Gecko/20100101 Firefox/146.0"
)

UA_ENC = quote(USER_AGENT)

OUT_VLC = Path("webtv_vlc.m3u8")
OUT_TIVI = Path("webtv_tivimate.m3u8")

CACHE_FILE = Cache(TAG, exp=19_800)

urls: dict[str, dict[str, str | float]] = {}

# --------------------------------------------------

def fix_event(s: str) -> str:
    return " vs ".join(map(str.strip, s.split("@")))

# --------------------------------------------------
# PLAYWRIGHT EVENT FETCHER (REPLACES OLD get_events)
# --------------------------------------------------

async def get_events(playwright, cached_keys: list[str]):

    browser = await playwright.firefox.launch(headless=True)
    context = await browser.new_context(user_agent=USER_AGENT)
    page = await context.new_page()

    log("Loading homepage via browser...")

    try:
        await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)

        for _ in range(6):
            await page.wait_for_timeout(1000)
            if await page.locator("a[href]").count() > 20:
                break

        html = await page.content()

    finally:
        await page.close()
        await context.close()
        await browser.close()

    soup = BeautifulSoup(html, "lxml")

    events = []
    seen = set()

    for a in soup.select("a[href*='live']"):
        href = a.get("href")
        if not href:
            continue

        url = urljoin(BASE_URL, href)

        if url in seen:
            continue
        seen.add(url)

        raw_text = a.get_text(" ", strip=True)
        event_name = fix_event(raw_text) if raw_text else "MLB Game"

        key = f"[MLB] {event_name} ({TAG})"

        if key in cached_keys:
            continue

        events.append({
            "sport": "MLB",
            "event": event_name,
            "link": url,
        })

    return events

# --------------------------------------------------
# PLAYWRIGHT STREAM CAPTURE
# --------------------------------------------------

async def process_event(playwright, url: str, url_num: int) -> str | None:

    browser = await playwright.firefox.launch(headless=True)
    context = await browser.new_context(user_agent=USER_AGENT)
    page = await context.new_page()

    captured = None

    def handle_request(request):
        nonlocal captured
        if ".m3u8" in request.url and not captured:
            captured = request.url

    context.on("request", handle_request)

    try:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except PlaywrightTimeoutError:
            pass

        await page.wait_for_timeout(4000)

        # momentum click
        for _ in range(2):
            try:
                await page.mouse.click(500, 350)
                await asyncio.sleep(1)
            except Exception:
                pass

        for frame in page.frames:
            try:
                await frame.click("body", timeout=1500)
                await asyncio.sleep(1)
            except Exception:
                pass

        waited = 0
        while waited < 20 and not captured:
            await asyncio.sleep(1)
            waited += 1

        if not captured:
            html = await page.content()
            m = re.search(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', html)
            if m:
                captured = m.group(0)

    finally:
        context.remove_listener("request", handle_request)
        await page.close()
        await context.close()
        await browser.close()

    if captured:
        log.info(f"URL {url_num}) Captured M3U8")
    else:
        log.warning(f"URL {url_num}) No stream found")

    return captured

# --------------------------------------------------
# PLAYLIST BUILDER
# --------------------------------------------------

def build_playlists(data: dict[str, dict]):

    vlc = ["#EXTM3U"]
    tivimate = ["#EXTM3U"]

    chno = 200

    for name, e in data.items():

        if not e.get("url"):
            continue

        chno += 1

        vlc.extend([
            f'#EXTINF:-1 tvg-chno="{chno}" tvg-id="{e["id"]}" '
            f'tvg-name="{name}" tvg-logo="{e["logo"]}" '
            f'group-title="Live Events",{name}',
            f"#EXTVLCOPT:http-referrer={BASE_URL}",
            f"#EXTVLCOPT:http-origin={BASE_URL}",
            f"#EXTVLCOPT:http-user-agent={USER_AGENT}",
            e["url"],
        ])

        tivimate.extend([
            f'#EXTINF:-1 tvg-chno="{chno}" tvg-id="{e["id"]}" '
            f'tvg-name="{name}" tvg-logo="{e["logo"]}" '
            f'group-title="Live Events",{name}',
            f'{e["url"]}|referer={BASE_URL}|origin={BASE_URL}|user-agent={UA_ENC}',
        ])

    OUT_VLC.write_text("\n".join(vlc), encoding="utf-8")
    OUT_TIVI.write_text("\n".join(tivimate), encoding="utf-8")

    log.info("Playlists written successfully")

# --------------------------------------------------
# MAIN SCRAPER
# --------------------------------------------------

async def scrape():

    cached_urls = CACHE_FILE.load() or {}
    cached_count = len(cached_urls)

    log.info(f"Loaded {cached_count} event(s) from cache")
    log.info(f'Scraping from "{BASE_URL}"')

    async with async_playwright() as p:

        events = await get_events(p, list(cached_urls.keys()))

        if not events:
            log.info("No new events found")
            CACHE_FILE.write(cached_urls)
            build_playlists(cached_urls)
            return

        now = Time.clean(Time.now())

        for i, ev in enumerate(events, 1):

            stream_url = await process_event(p, ev["link"], i)

            if not stream_url:
                continue

            key = f"[MLB] {ev['event']} ({TAG})"

            tvg_id, logo = leagues.get_tvg_info("MLB", ev["event"])

            cached_urls[key] = {
                "url": stream_url,
                "logo": logo,
                "base": BASE_URL,
                "timestamp": now.timestamp(),
                "id": tvg_id or "MLB.Baseball.Dummy.us",
                "link": ev["link"],
            }

    CACHE_FILE.write(cached_urls)
    build_playlists(cached_urls)

# --------------------------------------------------

if __name__ == "__main__":
    asyncio.run(scrape())
