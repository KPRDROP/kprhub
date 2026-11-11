#!/usr/bin/env python3
import os
import re
import base64
import requests
from datetime import datetime
from urllib.parse import quote_plus

# ================= CONFIG =================

XOR_BASE_URL = os.getenv('xor_base_url')

OUTPUT_FILE = "xor_tivimate.m3u8"

TAG = "XOR"

# Fixed encoded user-agent (as required)
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/111.0.0.0 Safari/537.36"
ENCODED_UA = "Mozilla%2F5.0%20(Windows%20NT%2010.0%3B%20Win64%3B%20x64)%20AppleWebKit%2F537.36%20(KHTML%2C%20like%20Gecko)%20Chrome%2F111.0.0.0%20Safari%2F537.36"

# Headers
REFERER = "https://roxiestreams.info/"
ORIGIN = "https://roxiestreams.info"

GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
GITHUB_REPO = os.getenv('GITHUB_REPO')

# ================= HELPER FUNCTIONS =================

def log(msg):
    print(msg, flush=True)


def fetch_playlist():
    """Fetch the playlist from the base URL"""
    if not XOR_BASE_URL:
        log("ERROR: xor_base_url environment variable is not set")
        return None

    log(f"Fetching: {XOR_BASE_URL}")

    try:
        headers = {
            'User-Agent': USER_AGENT,
            'Accept': 'text/plain, */*',
        }

        response = requests.get(XOR_BASE_URL, timeout=30, headers=headers)
        response.raise_for_status()

        log(f"OK: Fetched playlist ({len(response.text)} bytes)")
        return response.text

    except requests.RequestException as e:
        log(f"ERROR: Failed to fetch playlist: {e}")
        return None


def clean_name(name):
    """Remove date/time patterns and append (XOR)"""
    if not name:
        return ""
    
    name = re.sub(r'\s*-\s*(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d+.*?$', '', name, flags=re.IGNORECASE)
    
    name = re.sub(r'\s+EST\s*$', '', name, flags=re.IGNORECASE)
    
    name = re.sub(r'\s+', ' ', name).strip()
    
    return name


def clean_group(group):
    """Remove ' RS' from group-title"""
    if not group:
        return "Live Events"
    
    group = re.sub(r'\s*RS\s*$', '', group, flags=re.IGNORECASE)
    group = re.sub(r'^RS\s*', '', group, flags=re.IGNORECASE)
    
    return group.strip() if group.strip() else "Live Events"


def clean_url(url):
    """Clean URL by removing unwanted headers and keeping only referer/origin/user-agent"""
    if not url:
        return ""
    
    # Split URL and headers
    if '|' in url:
        parts = url.split('|')
        base_url = parts[0]
        
        cleaned_url = (
            f"{base_url}"
            f"|referer={REFERER}"
            f"|origin={ORIGIN}"
            f"|user-agent={ENCODED_UA}"
        )
        return cleaned_url
    
    # If no headers, add standard ones
    return (
        f"{url}"
        f"|referer={REFERER}"
        f"|origin={ORIGIN}"
        f"|user-agent={ENCODED_UA}"
    )


def is_valid_channel(extinf_line, url_line):
    """Check if this is a valid channel (not a placeholder/ad)"""
    if 'Brought to you by' in extinf_line or '1 Pix Media' in extinf_line:
        return False
    
    if 'tvg-id=""' in extinf_line:
        return False
    
    if '.mp4' in url_line and 'video.mp4' in url_line:
        return False
    
    return True


def parse_playlist(content):
    """Parse the playlist and extract channels"""
    lines = content.split('\n')
    
    channels = []
    current_extinf = None
    
    for line in lines:
        line = line.strip()
        
        if not line:
            continue
        
        # Skip header comments
        if line.startswith('#PLAYLIST:'):
            continue
        if line.startswith('# Total'):
            continue
        if line.startswith('# Working'):
            continue
        if line.startswith('#EXTM3U'):
            continue
        
        # Handle #EXTINF lines
        if line.startswith('#EXTINF'):
            current_extinf = line
            continue
        
        # Handle stream URLs
        if line and not line.startswith('#') and current_extinf:
            # Check if valid channel
            if not is_valid_channel(current_extinf, line):
                current_extinf = None
                continue
            
            # Extract metadata from EXTINF
            tvg_id_match = re.search(r'tvg-id="([^"]*)"', current_extinf)
            tvg_name_match = re.search(r'tvg-name="([^"]*)"', current_extinf)
            group_match = re.search(r'group-title="([^"]*)"', current_extinf)
            
            # Get name from after the last comma
            last_comma = current_extinf.rfind(',')
            display_name = current_extinf[last_comma + 1:].strip() if last_comma != -1 else ""
            
            tvg_id = tvg_id_match.group(1) if tvg_id_match else ""
            tvg_name = tvg_name_match.group(1) if tvg_name_match else display_name
            group = group_match.group(1) if group_match else "Live Events"
            
            # If tvg_name is empty, use display_name
            if not tvg_name:
                tvg_name = display_name
            
            # Clean name and group
            clean_title = clean_name(display_name)
            clean_grp = clean_group(group)
            clean_stream = clean_url(line)
            
            channels.append({
                'tvg_id': tvg_id,
                'tvg_name': tvg_name,
                'title': clean_title,
                'group': clean_grp,
                'url': clean_stream,
            })
            
            current_extinf = None
    
    log(f"OK: Parsed {len(channels)} valid channel(s)")
    return channels


def save_tivimate_playlist(channels, output_file):
    """Save TiviMate playlist with proper formatting"""
    log(f"Saving TiviMate playlist: {output_file}")

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("#EXTM3U\n\n")

        ch_no = 1
        for ch in channels:
            f.write(
                f'#EXTINF:-1 tvg-chno="{ch_no}" '
                f'tvg-id="{ch["tvg_id"]}" '
                f'tvg-name="{ch["title"]} ({TAG})" '
                f'group-title="{ch["group"]}", '
                f'{ch["title"]} - ({TAG})\n'
            )
            f.write(f'{ch["url"]}\n\n')
            ch_no += 1

    log(f"OK: Saved {ch_no - 1} channel(s) to {output_file}")
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
    log("XOR Playlist Transformer - TiviMate Generator")
    log("=" * 60)

    content = fetch_playlist()
    if not content:
        log("ERROR: Failed to fetch playlist. Exiting.")
        return

    log("")
    log("Parsing playlist...")
    channels = parse_playlist(content)

    if not channels:
        log("ERROR: No valid channels found. Exiting.")
        return

    log("")
    log("Generating TiviMate playlist...")
    output_file = save_tivimate_playlist(channels, OUTPUT_FILE)

    log("")
    log("Pushing to GitHub...")
    push_to_github(output_file)

    log("")
    log("=" * 60)
    log(f"Complete!")
    log(f"   Output: {OUTPUT_FILE} ({len(channels)} channels)")
    log("=" * 60)


if __name__ == "__main__":
    main()
