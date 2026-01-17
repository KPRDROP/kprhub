import os
import urllib.request
from urllib.parse import quote

# ========= CONFIG =========
SOURCE_URL = os.getenv("SHARK_M3U_URL")
OUTPUT_FILE = "strmshark_tivimate.m3u8"

USER_AGENT_RAW = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/144.0.0.0 Safari/537.36"
)

USER_AGENT_ENCODED = quote(USER_AGENT_RAW, safe="")

# ==========================


def fetch_playlist(url: str) -> list[str]:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT_RAW}
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", errors="ignore").splitlines()


def build_playlist(lines: list[str]) -> list[str]:
    output = ["#EXTM3U"]

    for line in lines:
        line = line.strip()

        if not line or line.startswith("#EXTM3U"):
            continue

        if line.startswith("#EXTINF"):
            output.append(line)
            continue

        if line.startswith("#"):
            continue

        # Stream URL → append User-Agent ONLY
        if "|" in line:
            base_url = line.split("|", 1)[0]
        else:
            base_url = line

        final_url = f"{base_url}|User-Agent={USER_AGENT_ENCODED}"
        output.append(final_url)

    return output


def main():
    if not SOURCE_URL:
        raise RuntimeError("❌ SHARK_M3U_URL secret not set")

    print("🦈 Fetching SharkStreams playlist...")
    lines = fetch_playlist(SOURCE_URL)

    print("🛠 Processing playlist...")
    playlist = build_playlist(lines)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(playlist) + "\n")

    print(f"✅ Saved: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
