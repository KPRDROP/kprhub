import os
import re
import json
import time
import urllib.request
import urllib.parse
from urllib.parse import quote, urlencode
from concurrent.futures import ThreadPoolExecutor, as_completed

# ================= CONFIG =================
SOURCE_URL = os.environ.get("STRM_FREE_API_URL")
OUTPUT_FILE = "strmfree_tivimate.m3u8"

BASE_URL = "https://streamfree.top"
USER_AGENT_RAW = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/149.0.0.0 Safari/537.36"
)
USER_AGENT = quote(USER_AGENT_RAW, safe="")

# All known categories from the API
CATEGORIES = [
    "soccer", "basketball", "hockey", "combat",
    "baseball", "football", "racing", "tennis", "cricket"
]

# Expanded time window (seconds relative to now)
# Get events from 6 hours ago up to 2 hours in the future -> more events
TIME_WINDOW_PAST_SEC = 6 * 3600
TIME_WINDOW_FUTURE_SEC = 2 * 3600
# ===========================================

HEADERS = {
    "User-Agent": USER_AGENT_RAW,
    "Referer": BASE_URL,
    "Accept": "application/json, text/plain, */*",
}


def _request(url: str, timeout: int = 30, extra_headers: dict | None = None) -> str | None:
    """Fetch a URL and return text, or None on failure."""
    hdrs = dict(HEADERS)
    if extra_headers:
        hdrs.update(extra_headers)
    req = urllib.request.Request(url, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  ! Request failed {url}: {e}")
        return None


def fetch_json(url: str) -> dict | None:
    text = _request(url)
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception as e:
        print(f"  ! JSON parse failed {url}: {e}")
        return None


def get_stream_info(stream_key: str, category: str) -> str | None:
    """
    Replicates the working flow from the original code:
      1. api/stream-status/{stream_key} -> find available qualities
      2. get-stream-key/{stream_key}    -> get server_name
      3. embed/{category}/{stream_key}{num}?quality=..&category=.. -> HTML with _0x = {...};
      4. Parse JSON, urlencode m3u_info[qual]
      5. Build final m3u8 URL
    """
    sk = quote(stream_key)

    # 1) stream status
    status_url = f"{BASE_URL}/api/stream-status/{sk}"
    status_text = _request(status_url)
    if not status_text:
        return None
    try:
        quality_info = json.loads(status_text)
    except Exception:
        return None

    if not quality_info.get("available"):
        print(f"  - Stream unavailable for {stream_key}")
        return None
    sources = quality_info.get("sources")
    if not sources:
        print(f"  - No sources for {stream_key}")
        return None

    # Flatten quality sources
    quality_sources = {
        f"{quality}{source_num}": value
        for source_num, source_data in sources.items()
        for quality, value in source_data.get("qualities", {}).items()
    }

    # Sort by resolution (lowest first, same as original)
    available_quals = sorted(
        [q.split("p") for q, flag in quality_sources.items() if flag],
        key=lambda x: int(x[-1]) if x[-1].isdigit() else 0,
    )
    if not available_quals:
        print(f"  - No available qualities for {stream_key}")
        return None

    qual = f"{available_quals[0][0]}p"
    num = available_quals[0][-1]
    num = "" if num == "1" else num

    # 2) server name
    server_name = "cdn"
    server_text = _request(f"{BASE_URL}/get-stream-key/{sk}")
    if server_text:
        try:
            server_name = json.loads(server_text).get("server_name", "cdn")
        except Exception:
            pass

    # 3) embed page
    embed_url = (
        f"{BASE_URL}/embed/{category}/{sk}{num}"
        f"?{urlencode({'quality': qual, 'category': category})}"
    )
    embed_html = _request(embed_url, timeout=25)
    if not embed_html:
        return None

    # 4) extract _0x = {...};
    ptrn = re.compile(r"_0x\s+=\s+(.*?);", re.S)
    match = ptrn.search(embed_html)
    if not match:
        print(f"  - Unable to find stream info for {stream_key}")
        return None

    try:
        m3u_data = json.loads(match.group(1))
        m3u_info = m3u_data[qual]
    except Exception as e:
        print(f"  - Failed to parse stream JSON for {stream_key}: {e}")
        return None

    query = urlencode(m3u_info)
    final_url = f"{BASE_URL}/live-{server_name}/{sk}{qual}{num}/index.m3u8?{query}"
    return final_url


def process_stream(stream: dict) -> tuple[str | None, str | None]:
    """Process one stream: get metadata, capture m3u8, build TiviMate entry."""
    name = stream.get("name", "Unknown Event")
    category = stream.get("category", "unknown")
    stream_key = stream.get("stream_key", "")
    thumbnail = stream.get("thumbnail_url", "")
    league = stream.get("league", category.capitalize())

    if not stream_key:
        return None, None

    print(f" Processing: {name} ({league})")
    m3u8_url = get_stream_info(stream_key, category)

    if not m3u8_url:
        print(f" Retrying {name} after delay...")
        time.sleep(2)
        m3u8_url = get_stream_info(stream_key, category)

    if not m3u8_url:
        print(f" No m3u8 found for {name}")
        return None, None

    embed_ref = f"{BASE_URL}/embed/{category}/{quote(stream_key)}"
    entry = (
        f'#EXTINF:-1 tvg-id="{category}.{stream_key}" '
        f'tvg-name="[{league}] {name} | (STFREE)" '
        f'tvg-logo="{thumbnail}" '
        f'group-title="{league}",{name}\n'
        f'{m3u8_url}|referer={BASE_URL}|origin={BASE_URL}|user-agent={USER_AGENT}'
    )
    return embed_ref, entry


def main():
    if not SOURCE_URL:
        raise RuntimeError("STRM_FREE_API_URL secret is missing")

    all_streams = []
    print("📡 Fetching streams from all categories...")

    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_category = {
            executor.submit(fetch_json, f"{BASE_URL}/api/v1/streams?category={cat}"): cat
            for cat in CATEGORIES
        }
        for future in as_completed(future_to_category):
            category = future_to_category[future]
            data = future.result()
            if data and "streams" in data:
                streams = data["streams"]
                print(f" {category}: found {len(streams)} streams")
                all_streams.extend(streams)
            else:
                print(f" {category}: no streams or invalid data")

    if not all_streams:
        raise RuntimeError("No streams found in any category")

    # Expanded time filter to capture more events
    now_ts = int(time.time())
    lo = now_ts - TIME_WINDOW_PAST_SEC
    hi = now_ts + TIME_WINDOW_FUTURE_SEC

    filtered = []
    for s in all_streams:
        ts = s.get("match_timestamp")
        if ts is None:
            # include if no timestamp
            filtered.append(s)
            continue
        try:
            ts = int(ts)
        except Exception:
            filtered.append(s)
            continue
        if lo <= ts <= hi:
            filtered.append(s)

    print(f"\n Time filter kept {len(filtered)}/{len(all_streams)} streams "
          f"(-{TIME_WINDOW_PAST_SEC//3600}h .. +{TIME_WINDOW_FUTURE_SEC//3600}h)")
    print(f"\n Processing {len(filtered)} streams to capture M3U8 URLs...")

    output_lines = ["#EXTM3U"]
    processed_count = 0

    for stream in filtered:
        embed_url, entry = process_stream(stream)
        if entry:
            output_lines.append(entry)
            processed_count += 1
        time.sleep(1)

    if processed_count == 0:
        raise RuntimeError("No M3U8 URLs captured")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(output_lines))

    print(f"\n Saved {OUTPUT_FILE} with {processed_count} entries")


if __name__ == "__main__":
    main()
