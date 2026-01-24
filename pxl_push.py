import os
import requests
from pathlib import Path
from urllib.parse import quote

# ========= CONFIG =========
BASE_URL = os.getenv("PXL_BASE_URL")
if not BASE_URL:
    raise RuntimeError("PXL_BASE_URL secret is not set")

OUT_VLC = Path("pxl_vlc.m3u8")
OUT_TIVI = Path("pxl_tivimate.m3u8")

REFERER = "https://pixelsport.tv/"
ORIGIN = "https://pixelsport.tv"

UA_RAW = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/134.0.0.0 Safari/537.36"
)
UA_ENC = quote(UA_RAW)

# ==========================


def fetch_playlist() -> str:
    r = requests.get(
        BASE_URL,
        timeout=20,
        headers={"User-Agent": UA_RAW},
    )
    r.raise_for_status()
    return r.text.strip()


def convert_to_tivimate(m3u: str) -> str:
    lines = m3u.splitlines()
    out = ["#EXTM3U"]

    for line in lines:
        line = line.strip()

        if not line or line == "#EXTM3U":
            continue

        if line.startswith("#EXTINF"):
            out.append(line)
            continue

        if line.startswith("#"):
            continue

        # Stream URL → Tivimate format
        out.append(
            f"{line}"
            f"|referer={REFERER}"
            f"|origin={ORIGIN}"
            f"|user-agent={UA_ENC}"
        )

    return "\n".join(out) + "\n"


def main():
    print("📡 Fetching PixelSports playlist...")
    raw = fetch_playlist()

    # VLC version (original)
    OUT_VLC.write_text(raw + "\n", encoding="utf-8")

    # Tivimate version
    tivimate = convert_to_tivimate(raw)
    OUT_TIVI.write_text(tivimate, encoding="utf-8")

    print("✅ Written:")
    print(f" - {OUT_VLC}")
    print(f" - {OUT_TIVI}")


if __name__ == "__main__":
    main()
