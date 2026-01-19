import os
import urllib.request
from urllib.parse import quote

# ================= CONFIG =================

SOURCE_URL = os.environ.get("MULTISPORT_URL")
OUTPUT_FILE = "multisports.m3u"

NEW_EPG = "https://epgshare01.online/epgshare01/epg_ripper_ALL_SOURCES1.xml.gz"

USER_AGENT_RAW = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/144.0.0.0 Safari/537.36"
)
USER_AGENT = quote(USER_AGENT_RAW, safe="")

# =========================================


def fetch_playlist(url: str) -> list[str]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT_RAW})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="ignore").splitlines()


def normalize_extm3u(line: str) -> str:
    if line.startswith("#EXTM3U"):
        if "url-tvg=" in line:
            return f'#EXTM3U url-tvg="{NEW_EPG}"'
        return f'#EXTM3U url-tvg="{NEW_EPG}"'
    return line


def normalize_title(line: str) -> str:
    if line.startswith("#EXTINF"):
        return line.replace("@", "vs")
    return line


def clean_stream_url(line: str) -> str:
    return line.split("|", 1)[0]


def main():
    if not SOURCE_URL:
        raise RuntimeError("❌ MULTISPORT_URL secret is missing")

    lines = fetch_playlist(SOURCE_URL)

    output = []
    pending_extinf = None

    for line in lines:
        line = line.strip()

        if not line:
            continue

        if line.startswith("#EXTM3U"):
            output.append(normalize_extm3u(line))
            continue

        if line.startswith("#EXTINF"):
            pending_extinf = normalize_title(line)
            output.append(pending_extinf)
            continue

        if line.startswith("http") and pending_extinf:
            base_url = clean_stream_url(line)
            output.append(f"{base_url}|User-Agent={USER_AGENT}")
            pending_extinf = None
            continue

        # Copy any other metadata lines exactly
        if line.startswith("#"):
            output.append(line)

    if len(output) < 2:
        raise RuntimeError("❌ Output playlist is empty")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(output))

    print(f"✅ Saved {OUTPUT_FILE} ({len(output)} lines)")


if __name__ == "__main__":
    main()
