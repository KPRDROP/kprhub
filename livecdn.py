import os
import sys
import requests
import urllib.parse

SOURCE_URL = os.environ.get("LIVECDN_PLAYLIST_URL")

OUTPUT_VLC = "livecdn_vlc.m3u8"
OUTPUT_TIVI = "livecdn_tivimate.m3u8"

ORIGIN = "https://cdn-live.tv"
REFERER = "https://cdn-live.tv/"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

NEW_EPG = 'url-tvg="https://epgshare01.online/epgshare01/epg_ripper_ALL_SOURCES1.xml.gz"'

def main():
    if not SOURCE_URL:
        print("❌ Missing LIVECDN_PLAYLIST_URL secret", file=sys.stderr)
        sys.exit(1)

    print("📥 Fetching source playlist...")
    r = requests.get(SOURCE_URL, timeout=20)
    r.raise_for_status()
    lines = r.text.splitlines()

    vlc_out = []
    tivi_out = []

    encoded_ua = urllib.parse.quote(USER_AGENT, safe="")

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # --- EXTM3U HEADER (EPG REPLACEMENT ONLY) ---
        if line.startswith("#EXTM3U"):
            if "url-tvg=" in line:
                line = "#EXTM3U " + NEW_EPG
            vlc_out.append(line)
            tivi_out.append(line)
            i += 1
            continue

        # --- EXTINF BLOCK ---
        if line.startswith("#EXTINF"):
            extinf = line
            stream_url = None

            j = i + 1
            while j < len(lines):
                if lines[j].startswith("http"):
                    stream_url = lines[j].strip()
                    break
                j += 1

            if not stream_url:
                i += 1
                continue

            # VLC output
            vlc_out.append(extinf)
            vlc_out.append(f"#EXTVLCOPT:http-origin={ORIGIN}")
            vlc_out.append(f"#EXTVLCOPT:http-referrer={REFERER}")
            vlc_out.append(f"#EXTVLCOPT:http-user-agent={USER_AGENT}")
            vlc_out.append(stream_url)

            # TiviMate output
            tivi_out.append(extinf)
            tivi_out.append(
                f"{stream_url}"
                f"|referer={REFERER}"
                f"|origin={ORIGIN}"
                f"|user-agent={encoded_ua}"
            )

            i = j + 1
            continue

        i += 1

    with open(OUTPUT_VLC, "w", encoding="utf-8") as f:
        f.write("\n".join(vlc_out) + "\n")

    with open(OUTPUT_TIVI, "w", encoding="utf-8") as f:
        f.write("\n".join(tivi_out) + "\n")

    print("✅ Playlists generated:")
    print(f"   - {OUTPUT_VLC}")
    print(f"   - {OUTPUT_TIVI}")

if __name__ == "__main__":
    main()
