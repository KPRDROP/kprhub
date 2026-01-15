#!/usr/bin/env python3
import asyncio
import json
from urllib.parse import quote
from playwright.async_api import async_playwright

BASE = "https://pixelsport.tv"
API_EVENTS = f"{BASE}/backend/liveTV/events"
API_SLIDERS = f"{BASE}/backend/slider/getSliders"

OUTPUT_VLC = "pxl_vlc.m3u8"
OUTPUT_TIVIMATE = "pxl_tivimate.m3u8"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/143.0.0.0 Safari/537.36"
)

LIVE_TV_LOGO = "https://i.postimg.cc/3wvZ39KX/Pixel-Sport-Logo-1182b5f687c239810f6d.png"


# -------------------------------------------------------
async def fetch_json_text_safe(page, url, retries=3):
    for attempt in range(1, retries + 1):
        text = await page.evaluate(
            """(u) => fetch(u, {
                credentials: 'include',
                headers: { 'Accept': 'application/json, text/plain, */*' }
            }).then(r => r.text())""",
            url,
        )

        if not text:
            print(f"⚠️ Empty response (attempt {attempt})")
            await page.wait_for_timeout(1500)
            continue

        # HTML fallback → Cloudflare soft block
        if text.lstrip().startswith("<"):
            print(f"⚠️ HTML returned instead of JSON (attempt {attempt})")
            await page.wait_for_timeout(2000)
            continue

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            print(f"⚠️ Invalid JSON (attempt {attempt})")
            await page.wait_for_timeout(1500)

    raise RuntimeError(f"❌ Failed to fetch valid JSON from {url}")


# -------------------------------------------------------
def collect_links(channel):
    links = []
    for i in range(1, 4):
        u = channel.get(f"server{i}URL")
        if u and u.lower() != "null":
            links.append(u)
    return links


# -------------------------------------------------------
async def main():
    print("🚀 Running PixelSport scraper (HTML-safe mode)")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(user_agent=USER_AGENT)
        page = await ctx.new_page()

        # Warm session
        await page.goto(BASE, wait_until="networkidle")
        await page.wait_for_timeout(4000)

        events_data = await fetch_json_text_safe(page, API_EVENTS)
        sliders_data = await fetch_json_text_safe(page, API_SLIDERS)

        await browser.close()

    events = events_data.get("events", [])
    sliders = sliders_data.get("data", [])

    if not events:
        print("❌ No events found")
        return

    ua_enc = quote(USER_AGENT, safe="")
    vlc = ["#EXTM3U"]
    tivi = ["#EXTM3U"]

    for ev in events:
        title = ev.get("match_name", "Live Event")
        logo = ev.get("competitors1_logo", LIVE_TV_LOGO)

        for link in collect_links(ev.get("channel", {})):
            vlc += [
                f'#EXTINF:-1 tvg-logo="{logo}" group-title="Pxlsports",{title}',
                f"#EXTVLCOPT:http-user-agent={USER_AGENT}",
                f"#EXTVLCOPT:http-referrer={BASE}/",
                link,
            ]
            tivi.append(
                f'#EXTINF:-1 tvg-logo="{logo}" group-title="Pxlsports",{title}\n'
                f'{link}|referer={BASE}/|user-agent={ua_enc}'
            )

    with open(OUTPUT_VLC, "w", encoding="utf-8") as f:
        f.write("\n".join(vlc))
    with open(OUTPUT_TIVIMATE, "w", encoding="utf-8") as f:
        f.write("\n".join(tivi))

    print(f"✅ Saved {OUTPUT_VLC}")
    print(f"✅ Saved {OUTPUT_TIVIMATE}")


if __name__ == "__main__":
    asyncio.run(main())
