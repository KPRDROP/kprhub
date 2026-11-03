#!/usr/bin/env python3
"""
WAPA Field59 Scraper - Fetches schedule XML from Field59 and generates VLC/TiviMate playlists
"""

import os
import re
import base64
import requests
from datetime import datetime
from urllib.parse import quote_plus

# ================= CONFIG =================

# Base URL
APAW_BASE_URL = os.getenv('APAW_BASE_URL')

# Output files
VLC_OUTPUT = "apaw_vlc.m3u8"
TIVIMATE_OUTPUT = "apaw_tivimate.m3u8"

# Headers
REFERER = "https://wapa.tv/"
ORIGIN = "https://wapa.tv"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
ENCODED_UA = quote_plus(USER_AGENT)

# Metadata
TAG = "WAPA-DT1"
TVG_ID = "WAPADT1.pr"
LOGO = "https://i.imgur.com/m5L6pyj.png"
GROUP_TITLE = "Live Events"

# GitHub config
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
GITHUB_REPO = os.getenv('GITHUB_REPO')

# ================= HELPER FUNCTIONS =================

def log(msg):
    print(msg, flush=True)


def fetch_xml():
    """Fetch the schedule XML from Field59"""
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
        
        log(f"Fetched XML ({len(response.text)} bytes)")
        return response.text
        
    except requests.RequestException as e:
        log(f"Error fetching XML: {e}")
        return None


def extract_metadata(xml_content):
    """Extract metadata from the XML content"""
    if not xml_content:
        return None
    
    # Extract title from <title>...</title>
    title_match = re.search(r'<title>(.*?)</title>', xml_content, re.DOTALL)
    title = title_match.group(1).strip() if title_match else None
    
    # Extract stream URL from <url>...</url>
    url_match = re.search(r'<url>(.*?)</url>', xml_content, re.DOTALL)
    stream_url = url_match.group(1).strip() if url_match else None
    
    # If not found, try CDATA wrapped patterns
    if not title:
        title_match = re.search(r'<title><!\[CDATA\[(.*?)\]\]></title>', xml_content, re.DOTALL)
        title = title_match.group(1).strip() if title_match else None
    
    if not stream_url:
        url_match = re.search(r'<url><!\[CDATA\[(.*?)\]\]></url>', xml_content, re.DOTALL)
        stream_url = url_match.group(1).strip() if url_match else None
    
    # Also try to find m3u8 directly as fallback
    if not stream_url:
        m3u8_match = re.search(r'(https?://[^\s<>"\']+\.m3u8[^\s<>"\']*)', xml_content)
        if m3u8_match:
            stream_url = m3u8_match.group(1)
    
    if not title:
        log("No title found, using default")
        title = "WAPA En Vivo"
    
    if not stream_url:
        log("No stream URL found in XML")
        return None
    
    return {
        'title': title,
        'stream_url': stream_url,
        'logo': LOGO,
        'tvg_id': TVG_ID,
        'tag': TAG,
        'group': GROUP_TITLE,
    }


def save_vlc_playlist(entry, output_file):
    """Save VLC playlist with EXTVLCOPT headers"""
    log(f"Saving VLC playlist: {output_file}")
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("#EXTM3U\n")
        f.write(f'#EXTINF:-1 tvg-chno="1" tvg-id="{entry["tvg_id"]}" '
                f'tvg-name="{entry["title"]} ({entry["tag"]})" '
                f'tvg-logo="{entry["logo"]}" '
                f'group-title="{entry["group"]}",{entry["title"]}\n')
        f.write(f'#EXTVLCOPT:http-referrer={REFERER}\n')
        f.write(f'#EXTVLCOPT:http-origin={ORIGIN}\n')
        f.write(f'#EXTVLCOPT:http-user-agent={USER_AGENT}\n')
        f.write(f'{entry["stream_url"]}\n')
    
    log(f"✓ VLC playlist saved")
    return output_file


def save_tivimate_playlist(entry, output_file):
    """Save TiviMate playlist with pipe headers and encoded user agent"""
    log(f"Saving TiviMate playlist: {output_file}")
    
    # Build URL with TiviMate headers
    url_with_headers = (
        f'{entry["stream_url"]}'
        f'|referer={REFERER}'
        f'|origin={ORIGIN}'
        f'|user-agent={ENCODED_UA}'
    )
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("#EXTM3U\n")
        f.write(f'#EXTINF:-1 tvg-chno="1" tvg-id="{entry["tvg_id"]}" '
                f'tvg-name="{entry["title"]} ({entry["tag"]})" '
                f'tvg-logo="{entry["logo"]}" '
                f'group-title="{entry["group"]}",{entry["title"]}\n')
        f.write(f'{url_with_headers}\n')
    
    log(f"✓ TiviMate playlist saved")
    return output_file


def push_to_github(filename):
    """Push file to GitHub using token"""
    if not GITHUB_TOKEN or not GITHUB_REPO:
        log("No GitHub credentials found, skipping push")
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
    
    # Get existing file SHA
    sha = None
    try:
        response = requests.get(api_url, headers=headers)
        if response.status_code == 200:
            sha = response.json().get('sha')
    except:
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
        log(f"✓ Pushed to GitHub: {GITHUB_REPO}/{filename}")
        return response.json()
    else:
        log(f"✗ GitHub push failed: {response.status_code}")
        if response.text:
            log(f"  Response: {response.text[:200]}")
        return None


# ================= MAIN FUNCTION =================

def main():
    log("=" * 60)
    log("WAPA Field59 Updater - Playlist Generator")
    log("=" * 60)
    
    # Fetch XML
    xml_content = fetch_xml()
    if not xml_content:
        log("Failed to fetch XML. Exiting.")
        return
    
    # Extract metadata
    log("\nExtracting metadata...")
    entry = extract_metadata(xml_content)
    
    if not entry:
        log("No valid metadata found. Exiting.")
        return
    
    log(f"✓ Event name: {entry['title']}")
    log(f"✓ Stream URL: {entry['stream_url'][:80]}...")
    log(f"✓ Logo: {entry['logo']}")
    log(f"✓ TVG-ID: {entry['tvg_id']}")
    
    # Generate playlists
    log("\nGenerating playlists...")
    vlc_file = save_vlc_playlist(entry, VLC_OUTPUT)
    tivimate_file = save_tivimate_playlist(entry, TIVIMATE_OUTPUT)
    
    # Push to GitHub
    log("\nPushing to GitHub...")
    push_to_github(vlc_file)
    push_to_github(tivimate_file)
    
    log("\n" + "=" * 60)
    log(f"Complete!")
    log(f"   VLC: {VLC_OUTPUT}")
    log(f"   TiviMate: {TIVIMATE_OUTPUT}")
    log("=" * 60)


if __name__ == "__main__":
    main()
