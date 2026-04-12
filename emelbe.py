#!/usr/bin/env python3

import asyncio
import re
import sys
from urllib.parse import urljoin, quote_plus

from playwright.async_api import async_playwright

# -------------------------------------------------
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:146.0) "
    "Gecko/20100101 Firefox/146.0"
)

HOMEPAGE = "https://mlbwebcast.com/"

OUTPUT_VLC = "emelbecast_VLC.m3u8"
OUTPUT_TIVI = "emelbecast_TiviMate.m3u8"

DEFAULT_LOGO = "https://i.postimg.cc/7L220Lmn/baseball4k.png"

TVG_ID = "MLB.Baseball.Dummy.us"
GROUP_TITLE = "MLB TEAM GAME"

# -------------------------------------------------
def log(*a):
    print(*a)
    sys.stdout.flush()

# -------------------------------------------------
def clean_name(name: str) -> str:
    return name.replace(" Live Stream", "").strip()

# -------------------------------------------------
async def get_events(page):
    log("Extracting events from DOM...")

    # 🔥 DIRECT DOM extraction (no BS4, no broken selectors)
    data = await page.evaluate("""
    () => {
        const events = [];
        document.querySelectorAll('a[href*="-live"]').forEach(a => {
            events.push({
                url: a.href,
                title: a.title || a.textContent || ""
            });
        });
        return events;
    }
    """)

    events = []
    seen = set()

    for item in data:
        url = item["url"]

        if "-live" not in url:
            continue

        if url in seen:
            continue
        seen.add(url)

        name = item["title"] or "MLB TEAM GAME"
        name = name.replace(" Live Stream", "").strip()

        events.append({
            "url": url,
            "event": name,
            "logo": DEFAULT_LOGO
        })

    return events

# -------------------------------------------------
async def capture_stream(context, url):
    page = await context.new_page()

    captured = None

    # 🔥 NETWORK INTERCEPTION
    def handle_request(req):
        nonlocal captured
        if any(x in req.url for x in [".m3u8", "/playlist/"]):
            captured = req.url

    def handle_response(res):
        nonlocal captured
        if any(x in res.url for x in [".m3u8", "/playlist/"]):
            captured = res.url

    context.on("request", handle_request)
    context.on("response", handle_response)

    try:
        await page.goto(url, timeout=30000)
        await page.wait_for_timeout(5000)

        # 🔥 trigger player
        for _ in range(3):
            try:
                await page.mouse.click(400, 300)
                await asyncio.sleep(1)
            except:
                pass

        for frame in page.frames:
            try:
                await frame.click("body", timeout=2000)
                await asyncio.sleep(1)
            except:
                pass

        # wait for capture
        for _ in range(30):
            if captured:
                break
            await asyncio.sleep(1)

        # fallback regex
        if not captured:
            html = await page.content()

            m = re.search(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', html)
            if m:
                captured = m.group(0)

            if not captured:
                m = re.search(r'https?://[^"\']+/playlist/\d+/load-playlist', html)
                if m:
                    captured = m.group(0)

    finally:
        await page.close()

    return captured

# -------------------------------------------------
def write_playlists(entries):
    with open(OUTPUT_VLC, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for e in entries:
            f.write(
                f'#EXTINF:-1 tvg-id="{TVG_ID}" '
                f'tvg-name="{e["event"]}" '
                f'tvg-logo="{e["logo"]}" '
                f'group-title="{GROUP_TITLE}",{e["event"]}\n'
            )
            f.write(f"#EXTVLCOPT:http-referrer={HOMEPAGE}\n")
            f.write(f"#EXTVLCOPT:http-origin={HOMEPAGE}\n")
            f.write(f"#EXTVLCOPT:http-user-agent={USER_AGENT}\n")
            f.write(f"{e['m3u8']}\n\n")

    ua = quote_plus(USER_AGENT)

    with open(OUTPUT_TIVI, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for e in entries:
            f.write(
                f'#EXTINF:-1 tvg-id="{TVG_ID}" '
                f'tvg-name="{e["event"]}" '
                f'tvg-logo="{e["logo"]}",{e["event"]}\n'
            )
            f.write(
                f"{e['m3u8']}|referer={HOMEPAGE}|origin={HOMEPAGE}|user-agent={ua}\n"
            )

    log("Playlists saved")

# -------------------------------------------------
async def main():
    log("Starting MLB Webcast Updater...")

    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        context = await browser.new_context(user_agent=USER_AGENT)
        page = await context.new_page()

        log("Loading homepage…")
        await page.goto(HOMEPAGE, timeout=30000)
        await page.wait_for_timeout(8000)

        events = await get_events(page)

        log(f"Found {len(events)} events")

        if not events:
            log("No events detected")
            return

        collected = []

        for i, ev in enumerate(events, 1):
            log(f"[{i}/{len(events)}] {ev['event']}")

            stream = await capture_stream(context, ev["url"])

            if stream:
                log(f"STREAM FOUND: {stream}")
                ev["m3u8"] = stream
                collected.append(ev)
            else:
                log("No streams found")

        await browser.close()

    if not collected:
        log("No streams captured.")
        return

    write_playlists(collected)

# -------------------------------------------------
if __name__ == "__main__":
    asyncio.run(main())
