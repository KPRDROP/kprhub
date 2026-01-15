#!/usr/bin/env python3
import asyncio
import json
from urllib.parse import quote
from playwright.async_api import async_playwright

BASE = "https://pixelsport.tv"
EVENTS_API_PATH = "/backend/liveTV/events"
SLIDERS_API_PATH = "/backend/slider/getSliders"

OUTPUT_VLC = "pxl_vlc.m3u8"
OUTPUT_TIVIMATE = "pxl_tivimate.m3u8"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
UA_ENC = quote(UA, safe="")

LIVE_TV_LOGO = "https://i.postimg.cc/3wvZ39KX/Pixel-Sport-Logo-1182b5f687c239810f6d.png"

LEAGUE_INFO = {
    "NFL": ("NFL.Dummy.us", "NFL"),
    "NBA": ("NBA.Dummy.us", "NBA"),
    "MLB": ("MLB.Dummy.us", "MLB"),
    "NHL": ("NHL.Dummy.us", "NHL"),
    "UFC": ("UFC.Dummy.us", "UFC"),
    "SOCCER": ("Soccer.Dummy.us", "Soccer"),
    "BOXING": ("Boxing.Dummy.us", "Boxing"),
}

# ------------------------------------------------------------

def league_info(name: str):
    for k, (tvid, grp) in LEAGUE_INFO.items():
        if k.lower() in name.lower():
            return tvid, grp
    return "Pxlsports.Dummy.us", "Pxlsports"

# ------------------------------------------------------------

async def capture_api_data(page):
    events_data = None
    sliders_data = None

    async def on_response(res):
        nonlocal events_data, sliders_data
        try:
            if EVENTS_API_PATH in res.url and res.status == 200:
                txt = await res.text()
                if txt.startswith("{"):
                    events_data = json.loads(txt)

            if SLIDERS_API_PATH in res.url and res.status == 200:
                txt = await res.text()
                if txt.startswith("{"):
                    sliders_data = json.loads(txt)
        except Exception:
            pass

    page.on("response", on_response)

    await page.goto(BASE, wait_until="networkidle")
    await page.wait_for_timeout(6000)

    page.remove_listener("response", on_response)

    return events_data or {}, sliders_data or {}

# ------------------------------------------------------------

def extract_links(obj):
    links = []
    for i in range(1, 4):
        u = obj.get(f"server{i}URL")
        if u and u != "null":
            links.append(u)
    return links

# ------------------------------------------------------------

def build_playlists(events, sliders):
    vlc = ["#EXTM3U"]
    tm = ["#EXTM3U"]

    def add(title, link, tvid, logo, group):
        vlc.append(
            f'#EXTINF:-1 tvg-id="{tvid}" tvg-logo="{logo}" group-title="Pxlsports - {group}",{title}'
        )
        vlc.append(f"#EXTVLCOPT:http-user-agent={UA}")
        vlc.append(f"#EXTVLCOPT:http-referrer={BASE}/")
        vlc.append(link)

        tm.append(
            f'#EXTINF:-1 tvg-id="{tvid}" tvg-logo="{logo}" group-title="Pxlsports - {group}",{title}'
        )
        tm.append(f"{link}|referer={BASE}/|user-agent={UA_ENC}|icy-metadata=1")

    for ev in events:
        title = ev.get("match_name", "Live Event")
        logo = ev.get("competitors1_logo", LIVE_TV_LOGO)
        league = ev.get("channel", {}).get("TVCategory", {}).get("name", "")
        tvid, group = league_info(league)

        for link in extract_links(ev.get("channel", {})):
            add(title, link, tvid, logo, group)

    for ch in sliders:
        title = ch.get("title", "Live TV")
        for link in extract_links(ch.get("liveTV", {})):
            add(title, link, "LiveTV.Dummy", LIVE_TV_LOGO, "Live TV")

    return "\n".join(vlc), "\n".join(tm)

# ------------------------------------------------------------

async def main():
    print("🚀 Running PixelSport scraper (Cloudflare-safe)")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(user_agent=UA)
        page = await ctx.new_page()

        events_json, sliders_json = await capture_api_data(page)
        await browser.close()

    events = events_json.get("events", [])
    sliders = sliders_json.get("data", [])

    if not events and not sliders:
        print("❌ No data captured (Cloudflare blocked)")
        return

    vlc, tm = build_playlists(events, sliders)

    with open(OUTPUT_VLC, "w", encoding="utf-8") as f:
        f.write(vlc)

    with open(OUTPUT_TIVIMATE, "w", encoding="utf-8") as f:
        f.write(tm)

    print(f"✅ Updated {OUTPUT_VLC}")
    print(f"✅ Updated {OUTPUT_TIVIMATE}")

# ------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(main())
