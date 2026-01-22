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
TIMEOUT = 30
# ==========================


def fetch_playlist(url: str) -> list[str] | None:
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
            print(f"⚠️ Network unreachable (attempt {attempt})")
            time.sleep(4)

    return None  # <-- critical change


def build_playlist(lines: list[str]) -> list[str]:
    output = ["#EXTM3U"]

    for line in lines:
        line = line.strip()

        if not line or line.startswith("#EXTM3U"):
            continue

        if line.startswith("#EXTINF"):
            output.append(line)
            continue

        # drop all VLC headers
        if line.startswith("#"):
            continue

        base_url = line.split("|", 1)[0]
        output.append(f"{base_url}|User-Agent={USER_AGENT_ENCODED}")

    return output


def main():
    if not SOURCE_URL:
        print("❌ SHARK_M3U_URL secret not set")
        sys.exit(1)

    print("🦈 Fetching SharkStreams playlist...")

    lines = fetch_playlist(SOURCE_URL)

    if not lines:
        print("⚠️ Source unreachable from GitHub Actions — keeping existing playlist")
        return  # ← SUCCESSFUL EXIT

    print("🛠 Processing playlist...")
    playlist = build_playlist(lines)

    if len(playlist) <= 1:
        print("⚠️ No streams parsed — skipping write")
        return

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(playlist) + "\n")

    print(f"✅ Updated {OUTPUT_FILE} ({len(playlist) - 1} streams)")


if __name__ == "__main__":
    main()
