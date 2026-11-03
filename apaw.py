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


def clean_cdata(text):
    """Remove CDATA wrapper and clean whitespace"""
    if not text:
        return ""
    # Remove CDATA wrappers
    text = re.sub(r'<!\[CDATA\[', '', text)
    text = re.sub(r'\]\]>', '', text)
    # Clean whitespace
    text = text.strip()
    # Remove any leftover angle brackets
    text = text.replace('<', '').replace('>', '')
    return text.strip()


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


def extract_all_events(xml_content):
    """Extract ALL events from XML, ignoring begin/end times"""
    if not xml_content:
        return []
    
    events = []
    
    # Strategy 1: Find all <item> blocks (common RSS/XML structure)
    item_blocks = re.findall(r'<item>(.*?)</item>', xml_content, re.DOTALL | re.IGNORECASE)
    
    # Strategy 2: If no <item> blocks, try <program> blocks
    if not item_blocks:
        item_blocks = re.findall(r'<program>(.*?)</program>', xml_content, re.DOTALL | re.IGNORECASE)
    
    # Strategy 3: Try <entry> blocks
    if not item_blocks:
        item_blocks = re.findall(r'<entry>(.*?)</entry>', xml_content, re.DOTALL | re.IGNORECASE)
    
    # Strategy 4: If no blocks found, treat entire XML as one block
    if not item_blocks:
        item_blocks = [xml_content]
    
    log(f"  Found {len(item_blocks)} event block(s)")
    
    for i, block in enumerate(item_blocks):
        # Extract title (handles both plain and CDATA)
        title = None
        title_patterns = [
            r'<title>\s*<!\[CDATA\[(.*?)\]\]>\s*</title>',
            r'<title>(.*?)</title>',
            r'<title\s+[^>]*>(.*?)</title>',
        ]
        for pattern in title_patterns:
            match = re.search(pattern, block, re.DOTALL | re.IGNORECASE)
            if match:
                title = clean_cdata(match.group(1))
                if title:
                    break
        
        # Skip if no title or title is generic
        if not title or title.lower() in ['wapa en vivo', 'wapa', 'live']:
            # Try to find title near <key> tag as fallback
            key_match = re.search(r'<key>(.*?)</key>', block, re.DOTALL | re.IGNORECASE)
            if key_match:
                fallback_title = clean_cdata(key_match.group(1))
                if fallback_title and fallback_title.lower() not in ['wapa en vivo', 'wapa', 'live']:
                    title = fallback_title
        
        # If still no title, use default with index
        if not title:
            title = f"WAPA Event {i + 1}"
        
        # Extract stream URL - look for m3u8 links specifically
        stream_url = None
        url_patterns = [
            r'<url>\s*<!\[CDATA\[(https?://[^\]]+\.m3u8[^\]]*)\]\]>\s*</url>',
            r'<url>\s*(https?://[^<]+\.m3u8[^<]*)\s*</url>',
            r'<url>(.*?)</url>',
            r'<stream_url>(.*?)</stream_url>',
            r'<stream>(.*?)</stream>',
            r'<link>(.*?)</link>',
        ]
        
        for pattern in url_patterns:
            match = re.search(pattern, block, re.DOTALL | re.IGNORECASE)
            if match:
                potential_url = clean_cdata(match.group(1))
                if '.m3u8' in potential_url and 'http' in potential_url:
                    stream_url = potential_url
                    break
        
        # Fallback: search for any m3u8 URL in the block
        if not stream_url:
            m3u8_match = re.search(r'(https?://[^\s<>"\']+\.m3u8[^\s<>"\']*)', block)
            if m3u8_match:
                stream_url = m3u8_match.group(1)
        
        # Skip if no valid stream URL
        if not stream_url:
            log(f"  Event '{title}' has no valid m3u8 stream")
            continue
        
        # Skip if URL is actually an image (logo)
        if any(ext in stream_url.lower() for ext in ['.png', '.jpg', '.jpeg', '.gif', '.svg']):
            log(f"  Event '{title}' URL is an image, skipping: {stream_url[:60]}")
            continue
        
        events.append({
            'title': title,
            'stream_url': stream_url,
            'logo': LOGO,
            'tvg_id': TVG_ID,
            'tag': TAG,
            'group': GROUP_TITLE,
        })
        
        log(f"  Event {i + 1}: {title}")
        log(f"    Stream: {stream_url[:80]}...")
    
    return events


def save_vlc_playlist(events, output_file):
    """Save VLC playlist with EXTVLCOPT headers"""
    log(f"Saving VLC playlist: {output_file}")
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("#EXTM3U\n")
        
        ch_no = 1
        for event in events:
            f.write(f'#EXTINF:-1 tvg-chno="{ch_no}" tvg-id="{event["tvg_id"]}" '
                    f'tvg-name="{event["title"]} ({event["tag"]})" '
                    f'tvg-logo="{event["logo"]}" '
                    f'group-title="{event["group"]}",{event["title"]}\n')
            f.write(f'#EXTVLCOPT:http-referrer={REFERER}\n')
            f.write(f'#EXTVLCOPT:http-origin={ORIGIN}\n')
            f.write(f'#EXTVLCOPT:http-user-agent={USER_AGENT}\n')
            f.write(f'{event["stream_url"]}\n\n')
            ch_no += 1
    
    log(f"VLC playlist saved with {ch_no - 1} stream(s)")
    return output_file


def save_tivimate_playlist(events, output_file):
    """Save TiviMate playlist with pipe headers and encoded user agent"""
    log(f"Saving TiviMate playlist: {output_file}")
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("#EXTM3U\n")
        
        ch_no = 1
        for event in events:
            # Build URL with TiviMate headers
            url_with_headers = (
                f'{event["stream_url"]}'
                f'|referer={REFERER}'
                f'|origin={ORIGIN}'
                f'|user-agent={ENCODED_UA}'
            )
            
            f.write(f'#EXTINF:-1 tvg-chno="{ch_no}" tvg-id="{event["tvg_id"]}" '
                    f'tvg-name="{event["title"]} ({event["tag"]})" '
                    f'tvg-logo="{event["logo"]}" '
                    f'group-title="{event["group"]}",{event["title"]}\n')
            f.write(f'{url_with_headers}\n\n')
            ch_no += 1
    
    log(f"TiviMate playlist saved with {ch_no - 1} stream(s)")
    return output_file


def push_to_github(filename):
    """Push file to GitHub using token"""
    if not GITHUB_TOKEN or not GITHUB_REPO:
        log("⚠ No GitHub credentials found, skipping push")
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
        log(f"Pushed to GitHub: {GITHUB_REPO}/{filename}")
        return response.json()
    else:
        log(f"GitHub push failed: {response.status_code}")
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
        log("Failed to fetch XML. Exiting.")
        return
    
    log("\nExtracting all events...")
    events = extract_all_events(xml_content)
    
    if not events:
        log("No valid events found. Exiting.")
        return
    
    log(f"\nTotal events extracted: {len(events)}")
    
    log("\nGenerating playlists...")
    vlc_file = save_vlc_playlist(events, VLC_OUTPUT)
    tivimate_file = save_tivimate_playlist(events, TIVIMATE_OUTPUT)
    
    log("\nPushing to GitHub...")
    push_to_github(vlc_file)
    push_to_github(tivimate_file)
    
    log("\n" + "=" * 60)
    log(f"Complete!")
    log(f"   VLC: {VLC_OUTPUT} ({len(events)} streams)")
    log(f"   TiviMate: {TIVIMATE_OUTPUT} ({len(events)} streams)")
    log("=" * 60)


if __name__ == "__main__":
    main()
