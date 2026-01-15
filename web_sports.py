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
def clean_text(text: str) -> str:
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
# PARSER
# -------------------------------------------------
def convert_to_tivimate(m3u: str) -> str:
    lines = m3u.splitlines()
    out = ["#EXTM3U"]

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        if line.startswith("#EXTINF"):
            info = line

            # ---- find stream URL (skip EXTVLCOPT) ----
            j = i + 1
            while j < len(lines):
                candidate = lines[j].strip()
                if not candidate:
                    j += 1
                    continue
                if candidate.startswith("#"):
                    j += 1
                    continue
                stream_url = candidate
                break
            else:
                i += 1
                continue

            # ---- parse EXTINF attributes ----
            attrs = dict(re.findall(r'(\w+?)="(.*?)"', info))

            tvg_id = attrs.get("tvg-id", "")
            tvg_logo = attrs.get("tvg-logo", "")
            group = attrs.get("group-title", "")

            title = clean_text(info.split(",", 1)[-1])
            tvg_name = clean_text(attrs.get("tvg-name", title))

            # ---- output EXTINF ----
            out.append(
                f'#EXTINF:-1 tvg-id="{tvg_id}" '
                f'tvg-name="{tvg_name}" '
                f'tvg-logo="{tvg_logo}" '
                f'group-title="{group}",{title}'
            )

            # ---- extract params if any ----
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
    print("🚀 Running Web Sports TiviMate playlist updater")

    raw = fetch_m3u(SOURCE_URL)
    converted = convert_to_tivimate(raw)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(converted)

    print(f"✅ Saved {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
