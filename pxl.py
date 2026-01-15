#!/usr/bin/env python3
import json
import gzip
import urllib.request
from urllib.parse import quote

BASE = "https://pixelsport.tv"
API_EVENTS = f"{BASE}/backend/liveTV/events"
API_SLIDERS = f"{BASE}/backend/slider/getSliders"

OUTPUT_VLC = "pxl_vlc.m3u8"
OUTPUT_TIVIMATE = "pxl_tivimate.m3u8"

LIVE_TV_LOGO = "https://i.postimg.cc/3wvZ39KX/Pixel-Sport-Logo-1182b5f687c239810f6d.png"
LIVE_TV_ID = "24.7.Dummy.us"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/143.0.0.0 Safari/537.36"
)

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

# ------------------------------------------------------------

def fetch_json(url):
    headers = {
        "User-Agent": UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Encoding": "gzip",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": f"{BASE}/",
        "Origin": BASE,
        "Connection": "keep-alive",
    }

    req = urllib.request.Request(url, headers=headers)
    resp = urllib.request.urlopen(req, timeout=15)

    raw = resp.read()
    if resp.headers.get("Content-Encoding") == "gzip":
        raw = gzip.decompress(raw)

    text = raw.decode("utf-8", errors="ignore")

    # Cloudflare safety check
    if text.startswith("<!DOCTYPE") or "<html" in text.lower():
        raise RuntimeError("Cloudflare HTML response received")

    return json.loads(text)

# ------------------------------------------------------------

def collect_links(obj):
    links = []
    for i in range(1, 4):
        u = obj.get(f"server{i}URL")
        if u and u.lower() != "null":
            links.append(u)
    return links

def league_info(name):
    for k, (tvid, logo, group) in LEAGUE_INFO.items():
        if k.lower() in name.lower():
            return tvid, logo, group
    return "Pxlsports.Dummy.us", LIVE_TV_LOGO, "Pxlsports"

# ------------------------------------------------------------

def build_playlists(events, sliders):
    vlc = ["#EXTM3U"]
    tm = ["#EXTM3U"]

    ua_enc = quote(UA, safe="")

    def add(title, tvid, logo, group, link):
        vlc.append(
            f'#EXTINF:-1 tvg-id="{tvid}" tvg-logo="{logo}" group-title="Pxlsports - {group}",{title}'
        )
        vlc.append(f"#EXTVLCOPT:http-user-agent={UA}")
        vlc.append(f"#EXTVLCOPT:http-referrer={BASE}/")
        vlc.append(link)

        tm.append(
            f'#EXTINF:-1 tvg-id="{tvid}" tvg-logo="{logo}" group-title="Pxlsports - {group}",{title}'
        )
        tm.append(f"{link}|referer={BASE}/|user-agent={ua_enc}|icy-metadata=1")

    for ev in events:
        title = ev.get("match_name", "Live Event")
        logo = ev.get("competitors1_logo", LIVE_TV_LOGO)
        league = ev.get("channel", {}).get("TVCategory", {}).get("name", "")
        tvid, logo2, group = league_info(league)

        for link in collect_links(ev.get("channel", {})):
            add(title, tvid, logo, group, link)

    for ch in sliders:
        title = ch.get("title", "Live TV")
        for link in collect_links(ch.get("liveTV", {})):
            add(title, LIVE_TV_ID, LIVE_TV_LOGO, "Live TV", link)

    return "\n".join(vlc), "\n".join(tm)

# ------------------------------------------------------------

def main():
    print("🚀 Running PixelSport scraper (direct JSON mode)")

    events_data = fetch_json(API_EVENTS)
    sliders_data = fetch_json(API_SLIDERS)

    events = events_data.get("events", [])
    sliders = sliders_data.get("data", [])

    if not events and not sliders:
        print("❌ No events found")
        return

    vlc, tm = build_playlists(events, sliders)

    open(OUTPUT_VLC, "w", encoding="utf-8").write(vlc)
    open(OUTPUT_TIVIMATE, "w", encoding="utf-8").write(tm)

    print(f"✅ Updated {OUTPUT_VLC}")
    print(f"✅ Updated {OUTPUT_TIVIMATE}")

# ------------------------------------------------------------

if __name__ == "__main__":
    main()
