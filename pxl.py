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
LIVE_TV_ID = "24.7.Dummy.us"

LEAGUE_INFO = {
    "NFL": ("NFL.Dummy.us", "https://i.postimg.cc/76LYgtfV/nfl-logo-png-seeklogo-168592.png", "NFL"),
    "MLB": ("MLB.Baseball.Dummy.us", "https://i.postimg.cc/y6g3tW89/mlb-logo-png-seeklogo-250501.png", "MLB"),
    "NHL": ("NHL.Hockey.Dummy.us", "https://i.postimg.cc/qRtqPZ4v/nhl-logo-png-seeklogo-196350.png", "NHL"),
    "NBA": ("NBA.Basketball.Dummy.us", "https://i.postimg.cc/pXMrSZ7v/nba-logo-png-seeklogo-247736.png", "NBA"),
    "NASCAR": ("Racing.Dummy.us", "https://i.postimg.cc/9QJfrjf4/nascar-logo-png-seeklogo-294566.png", "NASCAR"),
    "UFC": ("UFC.Fight.Pass.Dummy.us", "https://i.postimg.cc/LXZ4CY3f/ufc-logo-png-seeklogo-272931.png", "UFC"),
    "SOCCER": ("Soccer.Dummy.us", "https://i.postimg.cc/Kv5GHyBw/soccer-ball-logo-png-seeklogo-480250.png", "Soccer"),
    "BOXING": ("PPV.EVENTS.Dummy.us", "https://i.postimg.cc/brhPm6vF/boxing-zone-logo-png-seeklogo-244856.png", "Boxing"),
}


# -------------------------------------------------------
def league_info(name):
    for k, v in LEAGUE_INFO.items():
        if k.lower() in name.lower():
            return v
    return ("Pxlsports.Dummy.us", LIVE_TV_LOGO, "Pxlsports")


def collect_links(channel):
    out = []
    for i in range(1, 4):
        u = channel.get(f"server{i}URL")
        if u and u.lower() != "null":
            out.append(u)
    return out


# -------------------------------------------------------
async def fetch_json_via_browser(page, url):
    resp = await page.context.request.get(
        url,
        headers={
            "Accept": "application/json, text/plain, */*",
            "Referer": BASE + "/",
            "Origin": BASE,
        },
    )
    return await resp.json()


# -------------------------------------------------------
def build_playlists(events, sliders):
    vlc = ["#EXTM3U"]
    tivi = ["#EXTM3U"]
    ua_enc = quote(USER_AGENT, safe="")

    def add(title, tvid, logo, group, url):
        vlc.append(
            f'#EXTINF:-1 tvg-id="{tvid}" tvg-logo="{logo}" group-title="Pxlsports - {group}",{title}'
        )
        vlc.append(f"#EXTVLCOPT:http-user-agent={USER_AGENT}")
        vlc.append(f"#EXTVLCOPT:http-referrer={BASE}/")
        vlc.append(url)

        tivi.append(
            f'#EXTINF:-1 tvg-id="{tvid}" tvg-logo="{logo}" group-title="Pxlsports - {group}",{title}'
        )
        tivi.append(f"{url}|referer={BASE}/|user-agent={ua_enc}|icy-metadata=1")

    for ev in events:
        title = ev.get("match_name", "Live Event")
        logo = ev.get("competitors1_logo", LIVE_TV_LOGO)
        league = ev.get("channel", {}).get("TVCategory", {}).get("name", "Sports")
        tvid, _, group = league_info(league)

        for link in collect_links(ev.get("channel", {})):
            add(title, tvid, logo, group, link)

    for ch in sliders:
        title = ch.get("title", "Live TV")
        for link in collect_links(ch.get("liveTV", {})):
            add(title, LIVE_TV_ID, LIVE_TV_LOGO, "Live TV", link)

    return "\n".join(vlc), "\n".join(tivi)


# -------------------------------------------------------
async def main():
    print("🚀 Running PixelSport scraper (Cloudflare SAFE)")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(user_agent=USER_AGENT)
        page = await ctx.new_page()

        # 🔑 THIS CLEARS CLOUDFLARE
        await page.goto(BASE, wait_until="networkidle")
        await page.wait_for_timeout(3000)

        events_data = await fetch_json_via_browser(page, API_EVENTS)
        sliders_data = await fetch_json_via_browser(page, API_SLIDERS)

        await browser.close()

    events = events_data.get("events", [])
    sliders = sliders_data.get("data", [])

    if not events and not sliders:
        print("❌ No data captured")
        return

    vlc, tivi = build_playlists(events, sliders)

    with open(OUTPUT_VLC, "w", encoding="utf-8") as f:
        f.write(vlc)
    with open(OUTPUT_TIVIMATE, "w", encoding="utf-8") as f:
        f.write(tivi)

    print(f"✅ Saved {OUTPUT_VLC}")
    print(f"✅ Saved {OUTPUT_TIVIMATE}")


if __name__ == "__main__":
    asyncio.run(main())
