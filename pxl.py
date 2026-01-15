import json
import urllib.request
from urllib.error import URLError, HTTPError
from urllib.parse import quote

BASE = "https://pixelsport.tv"
API_EVENTS = f"{BASE}/backend/liveTV/events"
API_SLIDERS = f"{BASE}/backend/slider/getSliders"

# OUTPUT FILES
OUTPUT_VLC = "pxl_vlc.m3u8"
OUTPUT_TIVIMATE = "pxl_tivimate.m3u8"

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
    for key, (tvid, logo, group) in LEAGUE_INFO.items():
        if key.lower() in name.lower():
            return tvid, logo, group
    return ("Pxlsports.Dummy.us", LIVE_TV_LOGO, "Pxlsports")


def build_playlists(events, sliders):
    vlc_lines = ["#EXTM3U"]
    tm_lines = ["#EXTM3U"]

    ua_encoded = quote(VLC_USER_AGENT, safe="")
    referer_encoded = quote(VLC_REFERER, safe="")

    def add_entry(title, tvid, logo, group, link):
        # VLC
        vlc_lines.append(
            f'#EXTINF:-1 tvg-id="{tvid}" tvg-logo="{logo}" group-title="Pxlsports - {group}",{title}'
        )
        vlc_lines.append(f"#EXTVLCOPT:http-user-agent={VLC_USER_AGENT}")
        vlc_lines.append(f"#EXTVLCOPT:http-referrer={VLC_REFERER}")
        vlc_lines.append(f"#EXTVLCOPT:http-icy-metadata={VLC_ICY}")
        vlc_lines.append(link)

        # TiviMate
        tm_lines.append(
            f'#EXTINF:-1 tvg-id="{tvid}" tvg-logo="{logo}" group-title="Pxlsports - {group}",{title}'
        )
        tm_lines.append(
            f"{link}|referer={VLC_REFERER}|user-agent={ua_encoded}|icy-metadata=1"
        )

    for ev in events:
        title = ev.get("match_name", "Unknown Event").strip()
        logo = ev.get("competitors1_logo", LIVE_TV_LOGO)
        league = ev.get("channel", {}).get("TVCategory", {}).get("name", "Sports")
        tvid, _, group = get_league_info(league)
        links = collect_links(ev.get("channel", {}))
        for link in links:
            add_entry(title, tvid, logo, group, link)

    for ch in sliders:
        title = ch.get("title", "Live Channel").strip()
        links = collect_links(ch.get("liveTV", {}))
        for link in links:
            add_entry(title, LIVE_TV_ID, LIVE_TV_LOGO, "Live TV", link)

    return "\n".join(vlc_lines), "\n".join(tm_lines)


def main():
    try:
        print("[*] Fetching PixelSport data...")
        events_data = fetch_json(API_EVENTS)
        events = events_data.get("events", []) if isinstance(events_data, dict) else []
        sliders_data = fetch_json(API_SLIDERS)
        sliders = sliders_data.get("data", []) if isinstance(sliders_data, dict) else []

        vlc, tivimate = build_playlists(events, sliders)

        with open(OUTPUT_VLC, "w", encoding="utf-8") as f:
            f.write(vlc)

        with open(OUTPUT_TIVIMATE, "w", encoding="utf-8") as f:
            f.write(tivimate)

        print(f"[+] Saved: {OUTPUT_VLC}")
        print(f"[+] Saved: {OUTPUT_TIVIMATE}")

    except Exception as e:
        print(f"[!] Error: {e}")


if __name__ == "__main__":
    main()
