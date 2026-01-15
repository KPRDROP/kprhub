#!/usr/bin/env python3
import os
import re
import urllib.request
from urllib.parse import quote

SOURCE_URL = os.environ.get("WEB_SPORTS_M3U_URL")
OUTPUT_FILE = "web_sports_tivimate.m3u8"

UA_RAW = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/143.0.0.0 Safari/537.36"
)
UA = quote(UA_RAW, safe="")

LEAGUES = {
    "NHL": {
        "tvg_id": "NHL.Hockey.Dummy.us",
        "group": "NHLWebcast - Live Games",
        "logo": "https://i.postimg.cc/nV1jq3zQ/1280px-National-Hockey-League-shield-svg.png",
        "referer": None,
        "origin": None,
    },
    "NBA": {
        "tvg_id": "NBA.Basketball.Dummy.us",
        "group": "NBAWebcast - Live Games",
        "logo": "https://i.postimg.cc/43bZjFjY/images-q-tbn-ANd9Gc-QVIb-Y0Xaig-Di-N2XT1f-Kivwp-Nuz1r-KIYGsq-w-s.png",
        "referer": "https://streamingonembed.pro/",
        "origin": "https://streamingonembed.pro",
    },
}

def detect_league(text: str):
    t = text.upper()
    if "NHL" in t or "FLYERS" in t or "PENGUINS" in t:
        return "NHL"
    if "NBA" in t or "GRIZZLIES" in t or "MAGIC" in t:
        return "NBA"
    return None

def clean_title(title: str) -> str:
    return title.replace(" @ ", " vs ").replace("@", " vs ").strip()

def fetch_source():
    if not SOURCE_URL:
        raise RuntimeError("WEB_SPORTS_M3U_URL secret not set")

    req = urllib.request.Request(
        SOURCE_URL,
        headers={"User-Agent": UA_RAW}
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="ignore")

def main():
    print("🚀 Running Web Sports playlist converter")

    raw = fetch_source()
    lines = [l.strip() for l in raw.splitlines() if l.strip()]

    out = ["#EXTM3U"]
    added = 0

    i = 0
    while i < len(lines):
        line = lines[i]

        if line.startswith("#EXTINF"):
            title = line.split(",", 1)[-1].strip()
            title = clean_title(title)
            league = detect_league(title)

            # find next m3u8 url
            url = None
            j = i + 1
            while j < len(lines):
                if lines[j].startswith("http") and ".m3u8" in lines[j]:
                    url = lines[j]
                    break
                j += 1

            if league and url:
                cfg = LEAGUES[league]

                extinf = (
                    f'#EXTINF:-1 '
                    f'tvg-id="{cfg["tvg_id"]}" '
                    f'tvg-name="{title}" '
                    f'tvg-logo="{cfg["logo"]}" '
                    f'group-title="{cfg["group"]}",{title}'
                )
                out.append(extinf)

                suffix = f"|user-agent={UA}"
                if cfg["referer"]:
                    suffix += f"|referer={cfg['referer']}|origin={cfg['origin']}"

                out.append(url + suffix)
                added += 1

            i = j
        else:
            i += 1

    if added == 0:
        raise RuntimeError("❌ No streams parsed — source format changed")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(out))

    print(f"✅ {added} streams written to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
