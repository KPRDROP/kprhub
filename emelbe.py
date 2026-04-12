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
        await page.goto(HOMEPAGE, wait_until="load", timeout=30000)

        # wait longer for JS
        await page.wait_for_timeout(8000)

        # 🔥 USE evaluate() (THIS FIXES EVERYTHING)
        links = await page.evaluate("""
        () => {
            const out = [];
            document.querySelectorAll('a').forEach(a => {
                const href = a.href || "";
                if (href.includes('-live')) {
                    out.push({
                        url: href,
                        title: a.title || a.textContent || ""
                    });
                }
            });
            return out;
        }
        """)

        events = []
        seen = set()

        for item in links:
            url = item["url"]

            if "-live" not in url:
                continue

            if url in seen:
                continue
            seen.add(url)

            name = item["title"].strip()
            if not name:
                name = "MLB TEAM GAME"

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

    # 🔥 INTERCEPT BOTH REQUEST + RESPONSE
    def handle_request(req):
        nonlocal captured
        try:
            if any(x in req.url for x in [".m3u8", "/playlist/", ".ts"]) and not captured:
                captured = req.url
        except:
            pass

    def handle_response(res):
        nonlocal captured
        try:
            url = res.url
            if any(x in url for x in [".m3u8", "/playlist/"]) and not captured:
                captured = url
        except:
            pass

    context.on("request", handle_request)
    context.on("response", handle_response)

    try:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        except PlaywrightTimeoutError:
            pass

        await page.wait_for_timeout(5000)

        # 🔥 FORCE PLAYER LOAD
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

        # 🔥 WAIT FOR NETWORK CAPTURE
        waited = 0
        while waited < 30 and not captured:
            await asyncio.sleep(1)
            waited += 1

        # 🔥 FALLBACK HTML PARSE
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
            context.remove_listener("request", handle_request)
            context.remove_listener("response", handle_response)
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
