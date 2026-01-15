#!/usr/bin/env python3
import os
import re
import urllib.request
from urllib.parse import quote

# --------------------------------------------------
# CONFIG
# --------------------------------------------------
SOURCE_URL = os.getenv("WEB_SPORTS_M3U_URL")
if not SOURCE_URL:
    raise RuntimeError("WEB_SPORTS_M3U_URL secret not set")

OUTPUT_FILE = "web_sports_tivimate.m3u8"

UA_RAW = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/143.0.0.0 Safari/537.36"
)
UA_ENC = quote(UA_RAW, safe="")

# --------------------------------------------------
# LEAGUE RULES (AUTHORITATIVE)
# --------------------------------------------------
LEAGUES = {
    "NHL": {
        "tvg_id": "NHL.Hockey.Dummy.us",
        "group": "NHLWebcast - Live Games",
        "logo": "https://i.postimg.cc/nV1jq3zQ/1280px-National-Hockey-League-shield-svg.png",
        "headers": lambda url: f"{url}|user-agent={UA_ENC}",
    },
    "NBA": {
        "tvg_id": "NBA.Basketball.Dummy.us",
        "group": "NBAWebcast - Live Games",
        "logo": "https://i.postimg.cc/43bZjFjY/images-q-tbn-ANd9Gc-QVIb-Y0Xaig-Di-N2XT1f-Kivwp-Nuz1r-KIYGsq-w-s.png",
        "headers": lambda url: (
            f"{url}"
            f"|referer=https://streamingonembed.pro/"
            f"|origin=https://streamingonembed.pro"
            f"|user-agent={UA_ENC}"
        ),
    },
}

# --------------------------------------------------
def normalize_title(title: str) -> str:
    title = title.replace("@", "vs")
    title = re.sub(r"\s+", " ", title).strip()
    return title

# --------------------------------------------------
def detect_league(title: str):
    t = title.lower()
    if "nhl" in t or "hockey" in t:
        return LEAGUES["NHL"]
    if "nba" in t or "basketball" in t:
        return LEAGUES["NBA"]
    return None

# --------------------------------------------------
def fetch_m3u(url: str) -> list[str]:
    with urllib.request.urlopen(url, timeout=30) as r:
        return r.read().decode("utf-8", "ignore").splitlines()

# --------------------------------------------------
def main():
    print("🚀 Running Web Sports playlist normalizer")

    lines = fetch_m3u(SOURCE_URL)

    out = ["#EXTM3U"]

    current_title = None

    for line in lines:
        line = line.strip()

        if line.startswith("#EXTINF"):
            raw_title = line.split(",", 1)[-1].strip()
            current_title = normalize_title(raw_title)

        elif line.startswith("http") and current_title:
            league = detect_league(current_title)
            if not league:
                current_title = None
                continue

            out.append(
                f'#EXTINF:-1 '
                f'tvg-id="{league["tvg_id"]}" '
                f'tvg-name="{current_title}" '
                f'tvg-logo="{league["logo"]}" '
                f'group-title="{league["group"]}",'
                f'{current_title}'
            )

            out.append(league["headers"](line))

            current_title = None

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(out))

    print(f"✅ Saved {OUTPUT_FILE}")

# --------------------------------------------------
if __name__ == "__main__":
    main()
