#!/usr/bin/env python3

import asyncio
import re
import sys
from urllib.parse import urljoin, quote_plus

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

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
async def fetch_events_via_playwright(playwright):
    browser = await playwright.firefox.launch(headless=True)
    context = await browser.new_context(user_agent=USER_AGENT)
    page = await context.new_page()

    log("Loading homepage…")

    try:
        await page.goto(HOMEPAGE, wait_until="domcontentloaded", timeout=30000)

        # 🔥 CRITICAL: wait for dynamic content
        await page.wait_for_timeout(6000)

        # wait until at least some live links appear
        try:
            await page.wait_for_selector("a[href*='-live']", timeout=10000)
        except:
            pass

        anchors = await page.locator("a[href*='-live']").all()

        events = []
        seen = set()

        for a in anchors:
            try:
                href = await a.get_attribute("href")
                title = await a.get_attribute("title")
                text = await a.inner_text()
            except:
                continue

            if not href:
                continue

            url = urljoin(HOMEPAGE, href)

            if "-live" not in url:
                continue

            if url in seen:
                continue
            seen.add(url)

            name = title or text or "MLB TEAM GAME"
            name = name.replace(" Live Stream", "").strip()

            events.append({
                "url": url,
                "event": name,
                "logo": DEFAULT_LOGO
            })

        return events

    finally:
        await page.close()
        await context.close()
        await browser.close()

# -------------------------------------------------
async def capture_m3u8_from_page(playwright, url, timeout_ms=30000):
    browser = await playwright.firefox.launch(headless=True)
    context = await browser.new_context(user_agent=USER_AGENT)
    page = await context.new_page()

    captured = None

    def on_request(req):
        nonlocal captured
        try:
            if ".m3u8" in req.url and not captured:
                captured = req.url
        except:
            pass

    context.on("requestfinished", on_request)

    try:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        except PlaywrightTimeoutError:
            pass

        await page.wait_for_timeout(5000)

        # CLICK PAGE
        for _ in range(3):
            try:
                await page.mouse.click(400, 300)
                await asyncio.sleep(1)
            except:
                pass

        # CLICK IFRAMES
        for frame in page.frames:
            try:
                await frame.click("body", timeout=2000)
                await asyncio.sleep(1)
            except:
                pass

        # WAIT FOR STREAM
        waited = 0
        while waited < 30 and not captured:
            await asyncio.sleep(1)
            waited += 1

        # FALLBACK HTML
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
        try:
            context.remove_listener("requestfinished", on_request)
        except:
            pass

        await page.close()
        await context.close()
        await browser.close()

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
        events = await fetch_events_via_playwright(p)
        log(f"Found {len(events)} events")

        if not events:
            log("No events detected")
            return

        collected = []

        for i, ev in enumerate(events, 1):
            log(f"[{i}/{len(events)}] {ev['event']}")

            m3u8 = await capture_m3u8_from_page(p, ev["url"])

            if m3u8:
                log(f"STREAM FOUND: {m3u8}")
                ev["m3u8"] = m3u8
                collected.append(ev)
            else:
                log("No streams found")

    if not collected:
        log("No streams captured.")
        return

    write_playlists(collected)

# -------------------------------------------------
if __name__ == "__main__":
    asyncio.run(main())
