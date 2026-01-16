#!/usr/bin/env python3
import os
import sys
import urllib.request
from urllib.parse import quote

# =========================
# CONFIG
# =========================

SOURCE_ENV = "STRM_FREE_M3U_URL"
OUTPUT_FILE = "strm_free_tivimate.m3u8"

REFERER = "https://streamfree.to/"
ORIGIN = "https://streamfree.to"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:146.0) Gecko/20100101 Firefox/146.0"

UA_ENCODED = quote(USER_AGENT, safe="")

# =========================
# FETCH SOURCE M3U
# =========================

def fetch_m3u(url: str) -> list[str]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        content = resp.read().decode("utf-8", errors="ignore")
        return content.splitlines()


# =========================
# CONVERT VLC → TIVIMATE
# =========================

def convert_to_tivimate(lines: list[str]) -> list[str]:
    out = ["#EXTM3U"]
    last_extinf = None

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Keep EXTINF as-is
        if line.startswith("#EXTINF"):
            last_extinf = line
            out.append(line)
            continue

        # Skip VLC-only options
        if line.startswith("#EXTVLCOPT"):
            continue

        # Stream URL
        if line.startswith("http"):
            url = (
                f"{line}"
                f"|referer={REFERER}"
                f"|origin={ORIGIN}"
                f"|user-agent={UA_ENCODED}"
            )
            out.append(url)
            continue

    return out


# =========================
# MAIN
# =========================

def main():
    print("🚀 Running strm free playlist updater")

    src_url = os.getenv(SOURCE_ENV)
    if not src_url:
        print(f"❌ Missing environment variable: {SOURCE_ENV}")
        sys.exit(1)

    print(f"📥 Fetching source playlist")
    lines = fetch_m3u(src_url)

    if not lines:
        print("❌ Empty playlist received")
        sys.exit(1)

    print("🔄 Converting to TiviMate format")
    tivimate_lines = convert_to_tivimate(lines)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(tivimate_lines))

    print(f"✅ Saved: {OUTPUT_FILE}")
    print(f"📊 Entries: {sum(1 for l in tivimate_lines if l.startswith('#EXTINF'))}")


if __name__ == "__main__":
    main()
