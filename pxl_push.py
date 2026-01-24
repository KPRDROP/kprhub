import os
import requests
from pathlib import Path
from urllib.parse import quote

# ================= CONFIG =================

BASE_URL = os.getenv("PXL_BASE_URL", "").strip()
if not BASE_URL:
    raise RuntimeError("PXL_BASE_URL secret is not set or empty")

OUT_VLC = Path("pxl_vlc.m3u8")
OUT_TIVI = Path("pxl_tivimate.m3u8")

REFERER = "https://pixelsport.tv/"
ORIGIN = "https://pixelsport.tv"

UA_RAW = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/134.0.0.0 Safari/537.36 Edg/134.0.0.0"
)
UA_ENC = quote(UA_RAW)

# =========================================


def fetch_playlist() -> str:
    r = requests.get(
        BASE_URL,
        timeout=20,
        headers={
            "User-Agent": UA_RAW,
            "Referer": REFERER,
            "Origin": ORIGIN,
        },
    )

    if r.status_code != 200:
        raise RuntimeError(f"Failed to fetch playlist: HTTP {r.status_code}")

    return r.text.strip()


def build_vlc_playlist(m3u: str) -> str:
    lines = m3u.splitlines()
    out = ["#EXTM3U"]

    for line in lines:
        line = line.strip()

        if not line or line == "#EXTM3U":
            continue

        if line.startswith("#EXTINF"):
            out.append(line)
            out.append(f"#EXTVLCOPT:http-user-agent={UA_RAW}")
            out.append(f"#EXTVLCOPT:http-referrer={REFERER}")
            out.append(f"#EXTVLCOPT:http-origin={ORIGIN}")
            out.append("#EXTVLCOPT:http-icy-metadata=1")
            continue

        if line.startswith("#"):
            continue

        out.append(line)

    return "\n".join(out) + "\n"


def build_tivimate_playlist(m3u: str) -> str:
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

        out.append(
            f"{line}"
            f"|referer={REFERER}"
            f"|origin={ORIGIN}"
            f"|user-agent={UA_ENC}"
            f"|icy-metadata=1"
        )

    return "\n".join(out) + "\n"


def main():
    print("📡 Fetching PixelSports playlist...")
    raw = fetch_playlist()

    print("✍ Writing VLC playlist...")
    OUT_VLC.write_text(build_vlc_playlist(raw), encoding="utf-8")

    print("✍ Writing TiviMate playlist...")
    OUT_TIVI.write_text(build_tivimate_playlist(raw), encoding="utf-8")

    print("✅ Done:")
    print(f" - {OUT_VLC}")
    print(f" - {OUT_TIVI}")


if __name__ == "__main__":
    main()
