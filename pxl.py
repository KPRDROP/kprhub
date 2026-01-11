import json
import urllib.request
from urllib.error import URLError, HTTPError

BASE = "https://pixelsport.tv"
API_EVENTS = f"{BASE}/backend/liveTV/events"
API_SLIDERS = f"{BASE}/backend/slider/getSliders"
OUTPUT_FILE = "pxl_vlc.m3u8"

LIVE_TV_LOGO = "https://i.postimg.cc/3wvZ39KX/Pixel-Sport-Logo-1182b5f687c239810f6d.png"
LIVE_TV_ID = "24.7.Dummy.us"

VLC_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
VLC_REFERER = f"{BASE}/"
VLC_ICY = "1"

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


def fetch_json(url):
    """Fetch JSON from URL with headers"""
    headers = {
        "User-Agent": VLC_USER_AGENT,
        "Referer": VLC_REFERER,
        "Accept": "*/*",
        "Connection": "close",
        "Icy-MetaData": VLC_ICY,
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def collect_links(obj, prefix=""):
    """Collect valid stream links from object"""
    links = []
    if not obj:
        return links
    for i in range(1, 4):
        key = f"{prefix}server{i}URL" if prefix else f"server{i}URL"
        url = obj.get(key)
        if url and url.lower() != "null":
            links.append(url)
    return links


def get_league_info(name):
    """Return league info tuple: (tvg-id, logo, group name)"""
    for key, (tvid, logo, group) in LEAGUE_INFO.items():
        if key.lower() in name.lower():
            return tvid, logo, group
    return ("Pxlsports.Dummy.us", LIVE_TV_LOGO, "Pxlsports")


def build_m3u(events, sliders):
    """Build the M3U playlist text"""
    lines = ["#EXTM3U"]

    for ev in events:
        title = ev.get("match_name", "Unknown Event").strip()
        logo = ev.get("competitors1_logo", LIVE_TV_LOGO)
        league = ev.get("channel", {}).get("TVCategory", {}).get("name", "Sports")
        tvid, group_logo, group_display = get_league_info(league)
        links = collect_links(ev.get("channel", {}))
        if not links:
            continue

        for link in links:
            lines.append(f'#EXTINF:-1 tvg-id="{tvid}" tvg-logo="{logo}" group-title="Pxlsports - {group_display}",{title}')
            lines.append(f"#EXTVLCOPT:http-user-agent={VLC_USER_AGENT}")
            lines.append(f"#EXTVLCOPT:http-referrer={VLC_REFERER}")
            lines.append(f"#EXTVLCOPT:http-icy-metadata={VLC_ICY}")
            lines.append(link)

    for ch in sliders:
        title = ch.get("title", "Live Channel").strip()
        live = ch.get("liveTV", {})
        logo = LIVE_TV_LOGO  
        links = collect_links(live)
        if not links:
            continue

        for link in links:
            lines.append(f'#EXTINF:-1 tvg-id="{LIVE_TV_ID}" tvg-logo="{logo}" group-title="Pxlsports - Live TV",{title}')
            lines.append(f"#EXTVLCOPT:http-user-agent={VLC_USER_AGENT}")
            lines.append(f"#EXTVLCOPT:http-referrer={VLC_REFERER}")
            lines.append(f"#EXTVLCOPT:http-icy-metadata={VLC_ICY}")
            lines.append(link)

    return "\n".join(lines)


def main():
    try:
        print("[*] Fetching PixelSport data...")
        events_data = fetch_json(API_EVENTS)
        events = events_data.get("events", []) if isinstance(events_data, dict) else []
        sliders_data = fetch_json(API_SLIDERS)
        sliders = sliders_data.get("data", []) if isinstance(sliders_data, dict) else []

        playlist = build_m3u(events, sliders)
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write(playlist)

        print(f"[+] Saved: {OUTPUT_FILE} ({len(events)} events + {len(sliders)} live channels)")
    except Exception as e:
        print(f"[!] Error: {e}")


if __name__ == "__main__":
    main()
