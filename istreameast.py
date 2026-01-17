import base64
import re
from functools import partial
from urllib.parse import quote_plus

from selectolax.parser import HTMLParser

from .utils import Cache, Time, get_logger, leagues, network

log = get_logger(__name__)

TAG = "iSTRMEAST"
BASE_URL = "https://istreameast.app"

CACHE_FILE = Cache("istreameast.json", exp=10_800)
OUTPUT_FILE = "istreameast.m3u"

urls: dict[str, dict] = {}

HEADERS_PIPE = (
    "|referer=https://gooz.aapmains.net/"
    "|origin=https://gooz.aapmains.net"
    "|user-agent=Agent=" + quote_plus(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:146.0) Gecko/20100101 Firefox/146.0"
    )
)


# ---------------- STREAM EXTRACTION ---------------- #

async def process_event(url: str, url_num: int) -> str | None:
    resp = await network.request(url, log=log)
    if not resp:
        log.warning(f"URL {url_num}) Failed to load event page")
        return None

    soup = HTMLParser(resp.content)

    # 1️⃣ DIRECT PLAYLIST URL
    direct = re.search(
        r"https://pfl\d+\.ascendastro\.space/playlist/\d+/load-playlist",
        resp.text,
    )
    if direct:
        log.info(f"URL {url_num}) Direct playlist found")
        return direct.group(0)

    # 2️⃣ iframe → atob()
    iframe = soup.css_first("iframe")
    if iframe and (src := iframe.attributes.get("src")):
        iframe_resp = await network.request(src, log=log)
        if iframe_resp:
            # atob('...')
            match = re.search(
                r"atob\(\s*['\"]([^'\"]+)['\"]\s*\)",
                iframe_resp.text,
                re.I,
            )
            if match:
                log.info(f"URL {url_num}) Base64 stream decoded")
                return base64.b64decode(match.group(1)).decode("utf-8")

            # fallback direct playlist in iframe
            direct = re.search(
                r"https://pfl\d+\.ascendastro\.space/playlist/\d+/load-playlist",
                iframe_resp.text,
            )
            if direct:
                log.info(f"URL {url_num}) Playlist found in iframe")
                return direct.group(0)

    log.warning(f"URL {url_num}) No stream found")
    return None


# ---------------- EVENT DISCOVERY ---------------- #

async def get_events(cached_keys: list[str]) -> list[dict]:
    events = []

    html = await network.request(BASE_URL, log=log)
    if not html:
        return events

    soup = HTMLParser(html.content)

    for a in soup.css("li.f1-podium--item > a.f1-podium--link"):
        li = a.parent

        sport_el = li.css_first(".f1-podium--rank")
        name_el = li.css_first("span.d-md-inline")

        if not sport_el or not name_el:
            continue

        sport = sport_el.text(strip=True)
        event = name_el.text(strip=True)

        key = f"[{sport}] {event} ({TAG})"
        if key in cached_keys:
            continue

        href = a.attributes.get("href")
        if not href:
            continue

        events.append(
            {
                "sport": sport,
                "event": event,
                "link": href,
            }
        )

    return events


# ---------------- SCRAPER ---------------- #

async def scrape() -> None:
    cached = CACHE_FILE.load()
    urls.update(cached)

    log.info(f"Loaded {len(cached)} cached events")
    log.info(f"Scraping from {BASE_URL}")

    events = await get_events(cached.keys())
    log.info(f"Processing {len(events)} new events")

    now = Time.clean(Time.now()).timestamp()

    for i, ev in enumerate(events, start=1):
        handler = partial(process_event, ev["link"], i)
        stream = await network.safe_process(
            handler,
            url_num=i,
            semaphore=network.HTTP_S,
            log=log,
        )

        if not stream:
            continue

        sport, event = ev["sport"], ev["event"]
        key = f"[{sport}] {event} ({TAG})"

        tvg_id, logo = leagues.get_tvg_info(sport, event)

        urls[key] = cached[key] = {
            "url": stream,
            "logo": logo,
            "id": tvg_id or "Live.Event.us",
            "sport": sport,
            "event": event,
            "timestamp": now,
        }

    CACHE_FILE.write(cached)
    write_m3u()


# ---------------- M3U OUTPUT ---------------- #

def write_m3u():
    lines = ["#EXTM3U"]

    for title, data in urls.items():
        name = f"[{data['sport']}] {data['event']} ({TAG})"
        logo = data.get("logo", "")
        tvg_id = data.get("id", "Live.Event.us")

        lines.append(
            f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-name="{name}" '
            f'tvg-logo="{logo}" group-title="Live Events",{name}'
        )
        lines.append(data["url"] + HEADERS_PIPE)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    log.info(f"Saved {len(urls)} events to {OUTPUT_FILE}")
