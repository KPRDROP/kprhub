import os
import sys
import time
import urllib.request
from urllib.parse import quote
from urllib.error import URLError, HTTPError

# ========= CONFIG =========
SOURCE_URL = os.getenv("SHARK_M3U_URL")
OUTPUT_FILE = "strmshark_tivimate.m3u8"

USER_AGENT_RAW = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/144.0.0.0 Safari/537.36"
)

USER_AGENT_ENCODED = quote(USER_AGENT_RAW, safe="")

MAX_RETRIES = 3
TIMEOUT = 40  # seconds
# ==========================


def fetch_playlist(url: str) -> list[str]:
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            print(f"🌐 Fetch attempt {attempt}/{MAX_RETRIES}...")
            req = urllib.request.Request(
                url,
                headers={"User-Agent": USER_AGENT_RAW}
            )
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return resp.read().decode("utf-8", errors="ignore").splitlines()

        except (URLError, HTTPError, TimeoutError) as e:
            last_error = e
            print(f"⚠️ Attempt {attempt} failed: {e}")
            time.sleep(5)

    raise RuntimeError(f"❌ Failed to fetch source playlist after {MAX_RETRIES} attempts") from last_error


def build_playlist(lines: list[str]) -> list[str]:
    output = ["#EXTM3U"]

    for line in lines:
        line = line.strip()

        if not line or line.startswith("#EXTM3U"):
            continue

        if line.startswith("#EXTINF"):
            output.append(line)
            continue

        # Drop VLC-only headers
        if line.startswith("#"):
            continue

        # Stream URL → remove existing headers and add UA only
        base_url = line.split("|", 1)[0]
        output.append(f"{base_url}|User-Agent={USER_AGENT_ENCODED}")

    return output


def main():
    if not SOURCE_URL:
        print("❌ SHARK_M3U_URL secret not set")
        sys.exit(1)

    print("🦈 Fetching SharkStreams playlist...")

    try:
        lines = fetch_playlist(SOURCE_URL)
    except Exception as e:
        # DO NOT FAIL WORKFLOW — keep last file if exists
        print(f"❌ Fetch failed: {e}")
        if os.path.exists(OUTPUT_FILE):
            print("⚠️ Using existing playlist to avoid workflow failure")
            return
        raise

    print("🛠 Processing playlist...")
    playlist = build_playlist(lines)

    if len(playlist) <= 1:
        print("❌ Empty playlist generated — aborting write")
        sys.exit(1)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(playlist) + "\n")

    print(f"✅ Saved: {OUTPUT_FILE} ({len(playlist) - 1} streams)")


if __name__ == "__main__":
    main()
