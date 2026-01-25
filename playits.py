import requests
import zstandard as zstd
import io
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import datetime
import sys
import os
import urllib.parse

# --- 1.1. IstPlay: Error-tolerant decompression function ---
def decompress_content_istplay(response):
    try:
        if response.headers.get("content-encoding") == "zstd":
            dctx = zstd.ZstdDecompressor()
            with dctx.stream_reader(io.BytesIO(response.content)) as reader:
                return reader.read()
        else:
            return response.content
    except zstd.ZstdError:
        return response.content

# --- 1.2. IstPlay: Function to fetch m3u8 link ---
def get_m3u8_istplay(stream_id, headers):
    try:
        url = f"https://istplay.xyz/tv/?stream_id={stream_id}"
        response = requests.get(url, headers=headers, timeout=10)
        data = decompress_content_istplay(response)
        soup = BeautifulSoup(data.decode("utf-8", errors="replace"), "html.parser")
        source = soup.find("source", {"type": "application/x-mpegURL"})
        if source and source.get("src"):
            return stream_id, source["src"]
    except Exception as e:
        print(f"⚠️ Error (stream_id={stream_id}): {e}", file=sys.stderr)
    return stream_id, None

DEFAULT_LOGO = "https://cdn-icons-png.flaticon.com/512/531/531313.png"
FALLBACK_EPG = "Sports.Dummy.us"

# (UNCHANGED sport map – kept intact)
SPORT_TRANSLATION_ISTPLAY = { **SPORT_TRANSLATION_ISTPLAY** }

def main():
    print("📢 [IstPlay] Fetching stream list...")

    url_list = os.environ.get("ISTPLAY_API_URL")
    if not url_list:
        print("❌ Missing ISTPLAY_API_URL secret", file=sys.stderr)
        return

    headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Origin": "https://istplay.xyz",
        "Referer": "https://istplay.xyz/",
        "User-Agent": "Mozilla/5.0",
    }

    response = requests.get(url_list, headers=headers, timeout=15)
    parsed = json.loads(decompress_content_istplay(response))

    all_events = []
    sports_data = parsed.get("sports", {})
    for sport_key, sport_category in sports_data.items():
        events = sport_category.get("events", {})
        for _, event in events.items():
            if event.get("stream_id"):
                all_events.append((sport_key, event))

    print(f"🔗 [IstPlay] Fetching links for {len(all_events)} events...")

    with ThreadPoolExecutor(max_workers=20) as ex:
        futures = {
            ex.submit(get_m3u8_istplay, e["stream_id"], headers): e
            for _, e in all_events
        }
        for f in as_completed(futures):
            _, url = f.result()
            futures[f]["m3u8_url"] = url

    ua = urllib.parse.quote("VLC/3.0.21 LibVLC/3.0.21")
    output = ['#EXTM3U url-tvg="https://epgshare01.online/epgshare01/epg_ripper_DUMMY_CHANNELS.xml.gz"', ""]

    count = 0
    for sport_key, event in all_events:
        if not event.get("m3u8_url"):
            continue

        info = SPORT_TRANSLATION_ISTPLAY.get(sport_key.upper(), {})
        title = event.get("league", "EVENT")
        logo = info.get("logo", DEFAULT_LOGO)
        epg = info.get("epg", FALLBACK_EPG)
        group = info.get("name", sport_key)

        final_url = f'{event["m3u8_url"]}|user-agent={ua}'

        output.append(
            f'#EXTINF:-1 tvg-id="{epg}" tvg-logo="{logo}" group-title="{group}",{title}\n{final_url}'
        )
        count += 1

    with open("playits_vlc.m3u8", "w", encoding="utf-8") as f:
        f.write("\n".join(output))

    print(f"💾 M3U saved ({count} streams).")

if __name__ == "__main__":
    main()
