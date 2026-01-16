import os
import re
import urllib.request
from urllib.parse import quote

# ================= CONFIG =================

SOURCE_URL = os.environ.get("STRM_FREE_M3U_URL")  # GitHub Secret
OUTPUT_FILE = "strm_free_tivimate.m3u8"

REFERER = "https://streamfree.to/"
ORIGIN = "https://streamfree.to"
USER_AGENT_RAW = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:146.0) "
    "Gecko/20100101 Firefox/146.0"
)
USER_AGENT = quote(USER_AGENT_RAW, safe="")

# =========================================


def fetch_playlist(url: str) -> list[str]:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT_RAW},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="ignore").splitlines()


def extract_logo_from_extinf(line: str) -> str | None:
    m = re.search(r'tvg-logo="([^"]+)"', line, re.IGNORECASE)
    return m.group(1) if m else None


def detect_category(title: str) -> str:
    t = title.lower()
    if any(x in t for x in ["nba", "basketball"]):
        return "basketball"
    if any(x in t for x in ["nhl", "hockey"]):
        return "hockey"
    if any(x in t for x in ["tennis", "atp", "wta"]):
        return "tennis"
    return "soccer"


def build_logo(title: str, category: str) -> str:
    slug = (
        title.lower()
        .replace("@", " vs ")
        .replace(" vs ", "-vs-")
        .replace(" ", "-")
    )
    slug = re.sub(r"[^a-z0-9\-]", "", slug)
    pretty = "_".join(w.capitalize() for w in slug.replace("-", " ").split())
    return f"https://streamfree.to/thumbnails/{category}_{slug}_{pretty}"


def extract_quality(title: str) -> str:
    m = re.search(r"\[(\d{3,4}p)\]", title)
    return m.group(1) if m else "Auto"


def build_group(title: str) -> str:
    quality = extract_quality(title)
    return f"StrmFree - {quality}"


def normalize_title(title: str) -> str:
    return title.replace("@", " vs ").strip()


def main():
    if not SOURCE_URL:
        raise RuntimeError("❌ STRM_FREE_M3U_URL secret is missing")

    lines = fetch_playlist(SOURCE_URL)

    output = ["#EXTM3U"]
    current_extinf = None
    current_logo = None
    current_title = None

    for line in lines:
        line = line.strip()

        if line.startswith("#EXTINF"):
            current_extinf = line

            title_match = re.search(r",(.+)$", line)
            if not title_match:
                continue

            current_title = normalize_title(title_match.group(1))

            source_logo = extract_logo_from_extinf(line)
            if source_logo:
                current_logo = source_logo
            else:
                category = detect_category(current_title)
                current_logo = build_logo(current_title, category)

        elif line.startswith("http") and current_extinf:
            group = build_group(current_title)

            output.append(
                f'#EXTINF:-1 tvg-logo="{current_logo}" '
                f'group-title="{group}",{current_title}'
            )

            output.append(
                f"{line}"
                f"|Referer={REFERER}"
                f"|Origin={ORIGIN}"
                f"|User-Agent={USER_AGENT}"
            )

            current_extinf = None
            current_title = None
            current_logo = None

    if len(output) <= 1:
        raise RuntimeError("❌ Output playlist is empty")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(output))

    print(f"✅ Saved {OUTPUT_FILE} ({len(output) - 1} entries)")


if __name__ == "__main__":
    main()
