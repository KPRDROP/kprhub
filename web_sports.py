#!/usr/bin/env python3
import os
import re
import urllib.request
from urllib.parse import quote

# -------------------------------------------------
# CONFIG
# -------------------------------------------------
OUTPUT_FILE = "web_sports_tivimate.m3u8"

USER_AGENT_RAW = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/143.0.0.0 Safari/537.36"
)

USER_AGENT_ENC = quote(USER_AGENT_RAW, safe="")

SOURCE_URL = os.getenv("WEB_SPORTS_M3U_URL")
if not SOURCE_URL:
    raise RuntimeError("❌ WEB_SPORTS_M3U_URL secret not set")

# -------------------------------------------------
# HELPERS
# -------------------------------------------------
def clean_title(text: str) -> str:
    return text.replace("@", "vs").strip()

def fetch_m3u(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT_RAW,
            "Accept": "*/*",
            "Connection": "close",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="ignore")

# -------------------------------------------------
# MAIN PARSER
# -------------------------------------------------
def convert_playlist(m3u: str) -> str:
    lines = m3u.splitlines()
    out = ["#EXTM3U"]

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        if line.startswith("#EXTINF"):
            info = line

            # Read stream URL (next non-empty line)
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j >= len(lines):
                break

            stream_url = lines[j].strip()

            # Parse EXTINF attributes
            attrs = dict(re.findall(r'(\w+?)="(.*?)"', info))

            tvg_id = attrs.get("tvg-id", "").strip()
            tvg_logo = attrs.get("tvg-logo", "").strip()
            group = attrs.get("group-title", "").strip()

            title = info.split(",", 1)[-1].strip()
            title = clean_title(title)

            tvg_name = clean_title(attrs.get("tvg-name", title))

            # Write EXTINF
            out.append(
                f'#EXTINF:-1 tvg-id="{tvg_id}" '
                f'tvg-name="{tvg_name}" '
                f'tvg-logo="{tvg_logo}" '
                f'group-title="{group}",{title}'
            )

            # Preserve referer/origin if present
            params = []

            if "|" in stream_url:
                base, param_str = stream_url.split("|", 1)
                stream_url = base
                for p in param_str.split("|"):
                    if p.startswith(("referer=", "origin=")):
                        params.append(p)

            params.append(f"user-agent={USER_AGENT_ENC}")

            out.append(stream_url + "|" + "|".join(params))

            i = j + 1
            continue

        i += 1

    return "\n".join(out) + "\n"

# -------------------------------------------------
# RUN
# -------------------------------------------------
def main():
    print("🚀 Running Web Sports playlist updater")
    raw = fetch_m3u(SOURCE_URL)
    converted = convert_playlist(raw)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(converted)

    print(f"✅ Saved {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
