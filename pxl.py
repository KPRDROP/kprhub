#!/usr/bin/env python3
import json
from urllib.parse import quote
from pathlib import Path

EVENTS_FILE = "events.json"
SLIDERS_FILE = "sliders.json"

OUTPUT_VLC = "pxl_vlc.m3u8"
OUTPUT_TIVIMATE = "pxl_tivimate.m3u8"

USER_AGENT = "Mozilla/5.0"
BASE = "https://pixelsport.tv"
LIVE_TV_LOGO = "https://i.postimg.cc/3wvZ39KX/Pixel-Sport-Logo-1182b5f687c239810f6d.png"


def load_json(path):
    if not Path(path).exists():
        raise FileNotFoundError(f"Missing required file: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def collect_links(channel):
    links = []
    for i in range(1, 4):
        u = channel.get(f"server{i}URL")
        if u and u.lower() != "null":
            links.append(u)
    return links


def main():
    print("🚀 Running PixelSport scraper (LOCAL JSON MODE)")

    events_data = load_json(EVENTS_FILE)
    sliders_data = load_json(SLIDERS_FILE) if Path(SLIDERS_FILE).exists() else {}

    events = events_data.get("events", [])
    sliders = sliders_data.get("data", [])

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

    print("✅ Playlists generated successfully")


if __name__ == "__main__":
    main()
