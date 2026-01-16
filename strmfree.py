#!/usr/bin/env python3
import os
import re
import urllib.request
from urllib.parse import quote

SOURCE_URL = os.environ.get("STRM_FREE_M3U_URL")
OUTPUT_FILE = "strm_free_tivimate.m3u8"

UA_RAW = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:146.0) "
    "Gecko/20100101 Firefox/146.0"
)
UA_ENCODED = quote(UA_RAW, safe="")

REFERER = "https://streamfree.to/"
ORIGIN = "https://streamfree.to"

# -------------------------
# League detection
# -------------------------
LEAGUES = {
    "ligue 1": "Ligue 1",
    "premier league": "Premier League",
    "la liga": "La Liga",
    "serie a": "Serie A",
    "bundesliga": "Bundesliga",
    "champions": "Champions League",
    "nba": "NBA",
    "nhl": "NHL",
    "nfl": "NFL",
    "mlb": "MLB",
}

def detect_league(title: str) -> str:
    t = title.lower()
    for k, v in LEAGUES.items():
        if k in t:
            return v
    return "StrmFree"

def detect_quality(text: str) -> str:
    m = re.search(r"(360|480|520|540|720|1080)p", text)
    return f"{m.group(1)}p" if m else "Auto"

def build_logo(title: str) -> str:
    slug = re.sub(r"[^a-z0-9\-]", "", title.lower().replace(" vs ", "-vs-").replace(" ", "-"))
    pretty = "_".join([w.capitalize() for w in slug.replace("-", " ").split()])
    return f"https://streamfree.to/thumbnails/soccer_{slug}_{pretty}"

def fetch_source():
    if not SOURCE_URL:
        raise RuntimeError("❌ STRM_FREE_M3U_URL secret not set")

    req = urllib.request.Request(
        SOURCE_URL,
        headers={"User-Agent": UA_RAW}
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="ignore")

def clean_stream_url(url: str) -> str:
    # remove ANY existing headers
    return url.split("|")[0].strip()

def main():
    print("🚀 Running StreamFree → TiviMate converter (CLEAN MODE)")

    raw = fetch_source()
    lines = [l.strip() for l in raw.splitlines() if l.strip()]

    output = ["#EXTM3U"]
    added = 0
    i = 0

    while i < len(lines):
        line = lines[i]

        if line.startswith("#EXTINF"):
            title = line.split(",", 1)[-1].strip()
            league = detect_league(title)
            quality = detect_quality(title)
            logo = build_logo(title)

            # find next stream URL
            url = None
            j = i + 1
            while j < len(lines):
                if lines[j].startswith("http") and ".m3u8" in lines[j]:
                    url = clean_stream_url(lines[j])
                    break
                j += 1

            if url:
                group = f"StrmFree | {league} | {quality}"

                output.append(
                    '#EXTINF:-1 '
                    f'tvg-logo="{logo}" '
                    f'group-title="{group}",'
                    f'{title}'
                )

                output.append(
                    f"{url}"
                    f"|Referer={REFERER}"
                    f"|Origin={ORIGIN}"
                    f"|User-Agent={UA_ENCODED}"
                )
                added += 1

            i = j
        else:
            i += 1

    if added == 0:
        raise RuntimeError("❌ No streams parsed — source format may have changed")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(output))

    print(f"✅ {added} streams written to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
