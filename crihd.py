#!/usr/bin/env python3
import os
import sys
import json
import requests
from pathlib import Path
from urllib.parse import quote

# --------------------------------------------------
# CONFIG
# --------------------------------------------------
API_URL = os.getenv("CRICHD_API_URL")
if not API_URL:
    print("❌ Missing CRICHD_API_URL secret")
    sys.exit(1)

OUT_FILE = Path("crihd_tivimate.m3u8")

ENCODED_UA = "VLC%2F3.0.21%20LibVLC%2F3.0.21"

# --------------------------------------------------
def fetch_api() -> list[dict]:
    r = requests.get(API_URL, timeout=20)
    r.raise_for_status()
    return r.json()

# --------------------------------------------------
def build_playlist(data: list[dict]) -> str:
    out = ["#EXTM3U"]

    for ch in data:
        name = ch.get("name")
        cid = ch.get("id")
        logo = ch.get("logo")
        link = ch.get("link")
        referer = ch.get("referer")
        origin = ch.get("origin")

        if not (name and link):
            continue

        out.append(
            f'#EXTINF:-1 tvg-id="{cid}" tvg-name="{name}" '
            f'tvg-logo="{logo}",{name}'
        )

        out.append(
            f'{link}'
            f'|referer={referer}'
            f'|origin={origin}'
            f'|user-agent={ENCODED_UA}'
        )

    return "\n".join(out) + "\n"

# --------------------------------------------------
def main():
    print("📡 Fetching CricHD API...")
    data = fetch_api()

    print(f"📺 Channels found: {len(data)}")

    playlist = build_playlist(data)
    OUT_FILE.write_text(playlist, encoding="utf-8")

    print("✅ Playlist written: crihd_tivimate.m3u8")

# --------------------------------------------------
if __name__ == "__main__":
    main()
