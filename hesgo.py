#!/usr/bin/env python3
import json
import os
import base64
import requests
from datetime import datetime
from urllib.parse import quote_plus

# ================= CONFIG =================

API_URL = "https://hesgoaled.com/all_sports_combined.json"
OUTPUT_FILE = "hesgo_tivimate.m3u8"

# Headers for TiviMate format
REFERER = "https://hesgoaled.com/"
ORIGIN = "https://hesgoaled.com"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
ENCODED_UA = quote_plus(USER_AGENT)

TAG = "HESGO"

# Default logo for events without logo
DEFAULT_LOGO = "https://livelive24.com/fav.png"

# GitHub config
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
GITHUB_REPO = os.getenv('GITHUB_REPO')

# ================= HELPER FUNCTIONS =================

def log(msg):
    print(msg, flush=True)


def fetch_events():
    """Fetch events from the HesGoal API"""
    log(f"Fetching events from: {API_URL}")
    
    try:
        headers = {
            'User-Agent': USER_AGENT,
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://hesgoaled.com/',
            'Origin': 'https://hesgoaled.com',
        }
        
        response = requests.get(API_URL, timeout=30, headers=headers)
        response.raise_for_status()
        
        data = response.json()
        
        # Extract sports data
        sports_data = data.get('sports_data', {})
        
        # Count total events
        total_events = 0
        for sport, events in sports_data.items():
            if isinstance(events, list):
                total_events += len(events)
            elif isinstance(events, dict) and 'error' in events:
                log(f"  {sport}: {events['error']}")
        
        log(f"Found {total_events} events across {len(sports_data)} sports")
        return sports_data
        
    except requests.RequestException as e:
        log(f"Error fetching API: {e}")
        return {}
    except json.JSONDecodeError as e:
        log(f"Error parsing JSON: {e}")
        return {}


def extract_stream_url(stream_url):
    if not stream_url:
        return None
    
    # Check if URL has the dlhd.html?url= pattern
    if 'dlhd.html?url=' in stream_url:
        # Extract everything after dlhd.html?url=
        encoded_part = stream_url.split('dlhd.html?url=', 1)[1]
        
        # Check if it's a direct URL (not base64) or base64
        if encoded_part.startswith('http'):
            # It's a direct URL, encode it to base64
            encoded_part = base64.b64encode(encoded_part.encode('utf-8')).decode('utf-8')
        
        # Return with xmtv:// prefix
        return f"xmtv://{encoded_part}"
    
    # If no dlhd pattern, try to find the url parameter
    if 'url=' in stream_url:
        encoded_part = stream_url.split('url=', 1)[1]
        
        # If it looks like base64, use as is
        try:
            # Try to decode to check if valid base64
            decoded = base64.b64decode(encoded_part).decode('utf-8')
            if decoded.startswith('http'):
                return f"xmtv://{encoded_part}"
        except:
            # Not valid base64, encode it
            encoded_part = base64.b64encode(stream_url.encode('utf-8')).decode('utf-8')
            return f"xmtv://{encoded_part}"
    
    # If already has xmtv:// prefix, return as is
    if stream_url.startswith('xmtv://'):
        return stream_url
    
    return None


def generate_m3u_entry(event, sport, stream_index=0):
    """Generate a single M3U entry for an event stream"""
    # Extract event data
    name = event.get('name', 'Unknown Event')
    category = event.get('category', 'Sports Event')
    logo = event.get('image', DEFAULT_LOGO)
    league = event.get('playing', 'Live Events')
    streams = event.get('streams', [])
    
    # Check if we have streams
    if not streams or stream_index >= len(streams):
        return None
    
    # Get the stream
    stream = streams[stream_index]
    stream_url = stream.get('url', '')
    stream_quality = stream.get('quality', 'SD')
    stream_name = stream.get('name', 'Stream')
    
    # Convert stream URL to xmtv:// format
    xmtv_url = extract_stream_url(stream_url)
    if not xmtv_url:
        return None
    
    # Create display name
    display_name = f"{name} ({TAG})"
    if len(streams) > 1:
        display_name = f"{name} - {stream_quality} ({TAG})"
    
    # Use league as group title
    group_title = league if league else 'Live Events'
    
    # Build the EXTINF line
    extinf_line = (
        f'#EXTINF:-1 '
        f'tvg-id="Live.Event.us" '
        f'tvg-name="{display_name}" '
        f'tvg-logo="{logo}" '
        f'group-title="{group_title}",{display_name}'
    )
    
    return {
        'extinf': extinf_line,
        'url': xmtv_url,
        'name': name,
        'sport': sport,
        'league': league,
        'quality': stream_quality
    }


def process_events(sports_data):
    """Process all events and generate entries"""
    entries = []
    skipped = 0
    total = 0
    
    for sport, events in sports_data.items():
        if not isinstance(events, list):
            continue
        
        for event in events:
            total += 1
            streams = event.get('streams', [])
            
            if not streams:
                skipped += 1
                continue
            
            # Process each stream
            for i, stream in enumerate(streams):
                entry = generate_m3u_entry(event, sport, i)
                if entry:
                    entries.append(entry)
                else:
                    skipped += 1
    
    log(f"\nProcessed {total} events -> {len(entries)} stream entries")
    log(f"Skipped {skipped} entries (no stream or invalid URL)")
    return entries


def save_m3u_playlist(entries, output_file):
    """Save all entries to M3U file"""
    log(f"Saving {len(entries)} streams to {output_file}")
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("#EXTM3U\n")
        f.write(f"# Playlist generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"# Total streams: {len(entries)}\n\n")
        
        ch_no = 1
        for entry in entries:
            if entry:
                f.write(f'#EXTINF:-1 tvg-chno="{ch_no}" tvg-id="Live.Event.us" tvg-name="{entry["name"]} ({TAG})" tvg-logo="{entry.get("logo", DEFAULT_LOGO)}" group-title="{entry["league"]}",{entry["name"]} ({TAG})\n')
                f.write(f'{entry["url"]}\n\n')
                ch_no += 1
    
    log(f"✓ Playlist saved successfully")
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
            log("Found existing file, will update")
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
        log(f"Successfully pushed to GitHub")
        return response.json()
    else:
        log(f"GitHub push failed: {response.status_code}")
        if response.text:
            log(f"  Response: {response.text[:200]}")
        return None


def print_statistics(entries):
    """Print statistics about the streams"""
    if not entries:
        return
    
    leagues = {}
    for entry in entries:
        league = entry.get('league', 'Unknown')
        leagues[league] = leagues.get(league, 0) + 1
    
    log("\n" + "=" * 50)
    log("Stream Statistics by League:")
    log("=" * 50)
    for league, count in sorted(leagues.items(), key=lambda x: x[1], reverse=True):
        log(f"  {league}: {count} streams")
    log(f"\n  Total: {len(entries)} streams")
    log("=" * 50)


# ================= MAIN FUNCTION =================

def main():
    log("=" * 60)
    log("HesGoal TV Updater - xmtv:// Playlist Generator")
    log("=" * 60)
    
    # Fetch events from API
    sports_data = fetch_events()
    
    if not sports_data:
        log("No events found. Exiting.")
        return
    
    # Process all events
    log("\nProcessing events and converting stream URLs...")
    entries = process_events(sports_data)
    
    if not entries:
        log("No valid streams found to save")
        return
    
    # Print statistics
    print_statistics(entries)
    
    # Save M3U playlist
    log("\nSaving playlist...")
    output_file = save_m3u_playlist(entries, OUTPUT_FILE)
    
    # Push to GitHub if configured
    log("\nPushing to GitHub...")
    push_to_github(output_file)
    
    log("\n" + "=" * 60)
    log(f"Complete! Playlist saved to: {output_file}")
    log("=" * 60)


if __name__ == "__main__":
    main()
