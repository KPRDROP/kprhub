#!/usr/bin/env python3
import os
import re
import base64
import requests
from datetime import datetime
from urllib.parse import quote_plus

# ================= CONFIG =================

APAW_BASE_URL = os.getenv('APAW_BASE_URL')

VLC_OUTPUT = "apaw_vlc.m3u8"
TIVIMATE_OUTPUT = "apaw_tivimate.m3u8"

REFERER = "https://wapa.tv/"
ORIGIN = "https://wapa.tv"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
ENCODED_UA = quote_plus(USER_AGENT)

TAG = "WAPA-DT1"
TVG_ID = "WAPADT1.pr"
LOGO = "https://i.imgur.com/m5L6pyj.png"
GROUP_TITLE = "Live Events"

GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
GITHUB_REPO = os.getenv('GITHUB_REPO')

# ================= HELPER FUNCTIONS =================

def log(msg):
    print(msg, flush=True)


def clean_text(text):
    """Clean CDATA, whitespace, and XML artifacts from text"""
    if not text:
        return ""
    # Remove CDATA wrappers
    text = re.sub(r'<!\[CDATA\[', '', text)
    text = re.sub(r'\]\]>', '', text)
    # Remove any XML tags
    text = re.sub(r'<[^>]+>', '', text)
    # Normalize whitespace (including newlines)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def fetch_xml():
    """Fetch the schedule XML from Field59"""
    if not APAW_BASE_URL:
        log("ERROR: APAW_BASE_URL environment variable is not set")
        return None

    log(f"Fetching: {APAW_BASE_URL}")

    try:
        headers = {
            'User-Agent': USER_AGENT,
            'Accept': 'application/xml, text/xml, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': REFERER,
            'Origin': ORIGIN,
        }

        response = requests.get(APAW_BASE_URL, timeout=30, headers=headers)
        response.raise_for_status()

        log(f"OK: Fetched XML ({len(response.text)} bytes)")
        return response.text

    except requests.RequestException as e:
        log(f"ERROR: Failed to fetch XML: {e}")
        return None


def extract_all_instances(xml_content):
    if not xml_content:
        return []

    events = []

    # Find all <instance>...</instance> blocks
    instance_blocks = re.findall(
        r'<instance>(.*?)</instance>',
        xml_content,
        re.DOTALL | re.IGNORECASE
    )

    log(f"Found {len(instance_blocks)} <instance> block(s)")

    if not instance_blocks:
        log("WARNING: No <instance> blocks found. Trying fallback...")
        # Fallback: try to find title/url pairs anywhere in XML
        titles = re.findall(r'<title>(.*?)</title>', xml_content, re.DOTALL | re.IGNORECASE)
        urls = re.findall(r'<url>(.*?)</url>', xml_content, re.DOTALL | re.IGNORECASE)

        for i, (title_raw, url_raw) in enumerate(zip(titles, urls), 1):
            title = clean_text(title_raw)
            url = clean_text(url_raw)

            if url and '.m3u8' in url:
                events.append({
                    'title': title or f"WAPA Event {i}",
                    'stream_url': url,
                    'logo': LOGO,
                    'tvg_id': TVG_ID,
                    'tag': TAG,
                    'group': GROUP_TITLE,
                })

        return events

    # Process each <instance> block
    for idx, block in enumerate(instance_blocks, 1):
        # Extract <title> from block
        title_match = re.search(
            r'<title>(.*?)</title>',
            block,
            re.DOTALL | re.IGNORECASE
        )
        title = clean_text(title_match.group(1)) if title_match else None

        # Extract <url> from block
        url_match = re.search(
            r'<url>(.*?)</url>',
            block,
            re.DOTALL | re.IGNORECASE
        )
        stream_url = clean_text(url_match.group(1)) if url_match else None

        # Validate we have both title and URL
        if not title:
            log(f"WARNING: Instance {idx}: no title, skipping")
            continue

        if not stream_url:
            log(f"WARNING: Instance {idx} '{title}': no URL, skipping")
            continue

        # Validate it's actually an m3u8 stream (not an image)
        if '.m3u8' not in stream_url:
            log(f"WARNING: Instance {idx} '{title}': URL is not m3u8, skipping")
            continue

        if not stream_url.startswith('http'):
            log(f"WARNING: Instance {idx} '{title}': invalid URL, skipping")
            continue

        events.append({
            'title': title,
            'stream_url': stream_url,
            'logo': LOGO,
            'tvg_id': TVG_ID,
            'tag': TAG,
            'group': GROUP_TITLE,
        })

        log(f"OK: Instance {idx}: {title}")
        log(f"    Stream: {stream_url[:80]}...")

    return events


def save_vlc_playlist(events, output_file):
    """Save VLC playlist with EXTVLCOPT headers"""
    log(f"Saving VLC playlist: {output_file}")

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("#EXTM3U\n")

        ch_no = 1
        for event in events:
            f.write(
                f'#EXTINF:-1 tvg-chno="{ch_no}" '
                f'tvg-id="{event["tvg_id"]}" '
                f'tvg-name="{event["title"]} ({event["tag"]})" '
                f'tvg-logo="{event["logo"]}" '
                f'group-title="{event["group"]}",'
                f'{event["title"]}\n'
            )
            f.write(f'#EXTVLCOPT:http-referrer={REFERER}\n')
            f.write(f'#EXTVLCOPT:http-origin={ORIGIN}\n')
            f.write(f'#EXTVLCOPT:http-user-agent={USER_AGENT}\n')
            f.write(f'{event["stream_url"]}\n\n')
            ch_no += 1

    log(f"OK: VLC playlist saved with {ch_no - 1} stream(s)")
    return output_file


def save_tivimate_playlist(events, output_file):
    """Save TiviMate playlist with pipe headers and encoded user agent"""
    log(f"Saving TiviMate playlist: {output_file}")

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("#EXTM3U\n")

        ch_no = 1
        for event in events:
            url_with_headers = (
                f'{event["stream_url"]}'
                f'|referer={REFERER}'
                f'|origin={ORIGIN}'
                f'|user-agent={ENCODED_UA}'
            )

            f.write(
                f'#EXTINF:-1 tvg-chno="{ch_no}" '
                f'tvg-id="{event["tvg_id"]}" '
                f'tvg-name="{event["title"]} ({event["tag"]})" '
                f'tvg-logo="{event["logo"]}" '
                f'group-title="{event["group"]}",'
                f'{event["title"]}\n'
            )
            f.write(f'{url_with_headers}\n\n')
            ch_no += 1

    log(f"OK: TiviMate playlist saved with {ch_no - 1} stream(s)")
    return output_file


def push_to_github(filename):
    """Push file to GitHub using token"""
    if not GITHUB_TOKEN or not GITHUB_REPO:
        log(f"WARNING: No GitHub credentials found, skipping push of {filename}")
        return None

    log(f"Pushing {filename} to GitHub...")

    with open(filename, 'r', encoding='utf-8') as f:
        content = f.read()

    content_base64 = base64.b64encode(content.encode('utf-8')).decode('utf-8')

    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{filename}"
    headers = {
        'Authorization': f'token {GITHUB_TOKEN}',
        'Accept': 'application/vnd.github.v3+json'
    }

    sha = None
    try:
        response = requests.get(api_url, headers=headers)
        if response.status_code == 200:
            sha = response.json().get('sha')
    except Exception:
        pass

    payload = {
        'message': f'Update {filename} - {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
        'content': content_base64,
        'branch': 'main'
    }
    if sha:
        payload['sha'] = sha

    response = requests.put(api_url, headers=headers, json=payload)

    if response.status_code in [200, 201]:
        log(f"OK: Pushed to GitHub: {GITHUB_REPO}/{filename}")
        return response.json()
    else:
        log(f"ERROR: GitHub push failed for {filename}: {response.status_code}")
        if response.text:
            log(f"  Response: {response.text[:200]}")
        return None


# ================= MAIN FUNCTION =================

def main():
    log("=" * 60)
    log("WAPA Field59 Scraper - Playlist Generator")
    log("=" * 60)

    xml_content = fetch_xml()
    if not xml_content:
        log("ERROR: Failed to fetch XML. Exiting.")
        return

    log("")
    log("Extracting ALL instances from schedule...")
    events = extract_all_instances(xml_content)

    if not events:
        log("ERROR: No valid events found. Exiting.")
        return

    log(f"OK: Total events extracted: {len(events)}")

    log("")
    log("Generating playlists...")
    vlc_file = save_vlc_playlist(events, VLC_OUTPUT)
    tivimate_file = save_tivimate_playlist(events, TIVIMATE_OUTPUT)

    log("")
    log("Pushing to GitHub...")
    push_to_github(vlc_file)
    push_to_github(tivimate_file)

    log("")
    log("=" * 60)
    log(f"Complete!")
    log(f"   VLC: {VLC_OUTPUT} ({len(events)} streams)")
    log(f"   TiviMate: {TIVIMATE_OUTPUT} ({len(events)} streams)")
    log("=" * 60)


if __name__ == "__main__":
    main()
