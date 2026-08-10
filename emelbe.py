#!/usr/bin/env python3

import asyncio
import re
import json
from urllib.parse import urljoin, quote_plus

from playwright.async_api import (
    async_playwright,
    TimeoutError as PlaywrightTimeoutError,
)
from selectolax.lexbor import LexborHTMLParser as HTMLParser

# ============================================================
# CONFIG
# ============================================================

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:146.0) "
    "Gecko/20100101 Firefox/146.0"
)

HOMEPAGE = "https://mlbwebcast.com/"

OUTPUT_VLC = "emelbecast_VLC.m3u8"
OUTPUT_TIVI = "emelbecast_TiviMate.m3u8"

DEFAULT_LOGO = (
    "https://i.postimg.cc/7L220Lmn/baseball4k.png"
)

TVG_ID = "MLB.Baseball.Dummy.us"
GROUP_TITLE = "MLB TEAM GAME"

# How long to wait for the player to generate/request the stream.
STREAM_WAIT_SECONDS = 30

# Maximum number of concurrent browser pages.
MAX_CONCURRENT = 2

# ============================================================
# LOGGING
# ============================================================

def log(*args):
    print(*args, flush=True)

# ============================================================
# HELPERS
# ============================================================

def clean_text(value: str) -> str:
    value = re.sub(r"\s+", " ", value or "")
    return value.strip()

def fix_event(value: str) -> str:
    value = clean_text(value)
    # Normalize the site's "@" separator.
    value = re.sub(r"\s*@\s*", " vs ", value)
    return value

def team_name_from_title(title: str) -> str:
    title = clean_text(title)
    title = re.sub(
        r"\s+Live\s+Stream\s*$",
        "",
        title,
        flags=re.IGNORECASE,
    )
    return clean_text(title)

def is_m3u8(url: str) -> bool:
    if not url:
        return False
    return ".m3u8" in url.lower()

def clean_m3u8_url(url: str) -> str:
    if not url:
        return ""
    url = url.strip()
    url = url.strip("\"'")
    url = url.replace("&amp;", "&")
    url = re.sub(r"\s+", "", url)
    return url

# ============================================================
# HOMEPAGE EVENT DISCOVERY
# ============================================================

async def fetch_events_via_playwright(playwright):
    """Discover MLB team/game URLs."""
    browser = await playwright.firefox.launch(headless=True)
    context = await browser.new_context(
        user_agent=USER_AGENT,
        viewport={"width": 1920, "height": 1080},
        locale="en-US",
        timezone_id="America/New_York",
    )
    page = await context.new_page()
    events = {}

    log("Loading homepage...")

    try:
        try:
            await page.goto(HOMEPAGE, wait_until="domcontentloaded", timeout=30000)
        except PlaywrightTimeoutError:
            log("Homepage DOM load timed out; continuing...")

        await page.wait_for_timeout(5000)

        # METHOD 1: Team logos
        team_count = 0
        try:
            await page.wait_for_selector("li.team-logo a", timeout=10000)
        except PlaywrightTimeoutError:
            pass

        team_links = await page.locator("li.team-logo a").evaluate_all(
            """
            links => links.map(a => ({
                href: a.href || a.getAttribute('href') || '',
                title: a.getAttribute('title') || '',
                img: a.querySelector('img')?.src || ''
            }))
            """
        )

        for item in team_links:
            href = clean_text(item.get("href", ""))
            title = clean_text(item.get("title", ""))
            logo = clean_text(item.get("img", ""))

            if not href or "-live" not in href.lower():
                continue

            team_name = team_name_from_title(title)
            if not team_name:
                slug = href.rstrip("/").split("/")[-1]
                slug = re.sub(r"-live$", "", slug, flags=re.IGNORECASE)
                team_name = slug.replace("-", " ").title()

            if not logo:
                logo = DEFAULT_LOGO

            key = href.rstrip("/").lower()
            events[key] = {
                "url": urljoin(HOMEPAGE, href),
                "event": team_name,
                "team": team_name,
                "logo": logo,
            }
            team_count += 1

        log(f"Found {team_count} team links")

        # METHOD 2: Game rows
        game_count = 0
        rows = page.locator("tr.singele_match_date:not(.mdatetitle)")
        row_count = await rows.count()
        log(f"Found {row_count} match rows")

        for index in range(row_count):
            row = rows.nth(index)
            try:
                vs_link = row.locator("td.teamvs a").first
                if await vs_link.count() == 0:
                    continue

                href = await vs_link.get_attribute("href")
                if not href:
                    continue

                href = urljoin(HOMEPAGE, href)
                raw_event = await vs_link.inner_text()

                # Remove date
                date_nodes = vs_link.locator("span.mtdate")
                date_count = await date_nodes.count()
                event_name = raw_event
                for d in range(date_count):
                    date_text = await date_nodes.nth(d).inner_text()
                    if date_text:
                        event_name = event_name.replace(date_text, "")

                event_name = fix_event(event_name)
                if not event_name:
                    continue

                logo = DEFAULT_LOGO
                logo_img = row.locator("td.teamlogo img").first
                if await logo_img.count():
                    src = await logo_img.get_attribute("src")
                    if src:
                        logo = urljoin(HOMEPAGE, src)

                key = href.rstrip("/").lower()
                if key in events:
                    events[key]["event"] = event_name
                    events[key]["logo"] = logo
                else:
                    events[key] = {
                        "url": href,
                        "event": event_name,
                        "team": event_name,
                        "logo": logo,
                    }
                game_count += 1
            except Exception as exc:
                log(f"  Error reading match row {index + 1}: {exc}")

        log(f"Found {game_count} game rows")

    except Exception as exc:
        log(f"Homepage discovery error: {exc}")

    finally:
        try:
            await page.close()
        except Exception:
            pass
        try:
            await context.close()
        except Exception:
            pass
        try:
            await browser.close()
        except Exception:
            pass

    return list(events.values())

# ============================================================
# M3U8 EXTRACTION - FIXED
# ============================================================

async def capture_m3u8_from_page(
    playwright,
    event,
    timeout_seconds=STREAM_WAIT_SECONDS,
):
    """Capture m3u8 stream URL from team page using the player's API call."""
    url = event["url"]

    browser = await playwright.firefox.launch(headless=True)
    context = await browser.new_context(
        user_agent=USER_AGENT,
        viewport={"width": 1920, "height": 1080},
        locale="en-US",
        timezone_id="America/New_York",
        extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
    )
    page = await context.new_page()

    captured = None
    seen = set()

    def accept_stream(candidate, source="network"):
        nonlocal captured
        candidate = clean_m3u8_url(candidate)
        if not candidate or not is_m3u8(candidate):
            return
        if candidate in seen:
            return
        seen.add(candidate)
        if captured is None:
            captured = candidate
            log(f"  ✓ CAPTURED via {source}: {candidate[:100]}...")

    # Network listeners
    def on_response(response):
        try:
            url = response.url
            if is_m3u8(url):
                accept_stream(url, "RESPONSE")
            # Check if this is the API response
            if "check_stream.php" in url:
                try:
                    data = response.json()
                    if data and data.get("url"):
                        accept_stream(data["url"], "API")
                except Exception:
                    pass
        except Exception:
            pass

    page.on("response", on_response)

    try:
        log(f"  Opening team page: {url}")

        # Load the team page
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except PlaywrightTimeoutError:
            log("  Team page DOM load timed out; continuing...")

        await page.wait_for_timeout(5000)

        # Find the player iframe
        iframe_locator = page.locator("iframe[src*='/stream/']")
        iframe_count = await iframe_locator.count()
        log(f"  Player iframes: {iframe_count}")

        # Get the iframe src
        iframe_src = None
        if iframe_count > 0:
            iframe_src = await iframe_locator.first.get_attribute("src")
            log(f"  Iframe src: {iframe_src}")

        # Navigate to the iframe if found
        if iframe_src and "mlbhd.html" in iframe_src:
            log(f"  Navigating to player iframe: {iframe_src}")
            try:
                await page.goto(iframe_src, wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_timeout(3000)

                # Get the player HTML content
                player_html = await page.content()
                log(f"  Player HTML size: {len(player_html)} bytes")

                # Look for the fetch call in the player HTML
                # Pattern: fetch('check_stream.php?id=XXX&ts=XXX&pt=XXX')
                fetch_pattern = r"fetch\s*\(\s*['\"]([^'\"]+)['\"]\s*\)"
                fetch_matches = re.findall(fetch_pattern, player_html)

                for fetch_url in fetch_matches:
                    if "check_stream.php" in fetch_url:
                        log(f"  Found fetch URL: {fetch_url}")
                        # Extract parameters
                        params = {}
                        for part in fetch_url.split("&"):
                            if "=" in part:
                                key, val = part.split("=", 1)
                                params[key] = val

                        if "id" in params and "ts" in params and "pt" in params:
                            # Make the API call directly
                            api_url = f"https://mlbwebcast.com/stream/check_stream.php?id={params['id']}&ts={params['ts']}&pt={params['pt']}"
                            log(f"  Calling API: {api_url}")

                            try:
                                # Use page.evaluate to make the fetch call
                                result = await page.evaluate(f'''
                                    async () => {{
                                        try {{
                                            const response = await fetch('{api_url}', {{
                                                headers: {{
                                                    'Referer': '{iframe_src}',
                                                    'User-Agent': '{USER_AGENT}'
                                                }}
                                            }});
                                            const data = await response.json();
                                            return data;
                                        }} catch(e) {{
                                            return null;
                                        }}
                                    }}
                                ''')

                                if result and result.get("url"):
                                    captured = result["url"]
                                    log(f"  ✓ CAPTURED via direct API call: {captured[:100]}...")
                            except Exception as e:
                                log(f"  API call failed: {e}")

                # Try to find the _d array (id, ts, pt)
                d_pattern = r'var\s+_d\s*=\s*\[([^\]]+)\]'
                d_match = re.search(d_pattern, player_html)
                if d_match and not captured:
                    try:
                        values = eval(d_match.group(1))
                        if len(values) >= 3:
                            ev_id, ev_ts, ev_pt = values[:3]
                            log(f"  Found _d array: id={ev_id}, ts={ev_ts}, pt={ev_pt}")

                            api_url = f"https://mlbwebcast.com/stream/check_stream.php?id={ev_id}&ts={ev_ts}&pt={ev_pt}"
                            result = await page.evaluate(f'''
                                async () => {{
                                    try {{
                                        const response = await fetch('{api_url}', {{
                                            headers: {{
                                                'Referer': '{iframe_src}',
                                                'User-Agent': '{USER_AGENT}'
                                            }}
                                        }});
                                        const data = await response.json();
                                        return data;
                                    }} catch(e) {{
                                        return null;
                                    }}
                                }}
                            ''')
                            if result and result.get("url"):
                                captured = result["url"]
                                log(f"  ✓ CAPTURED via _d array: {captured[:100]}...")
                    except Exception as e:
                        log(f"  _d parsing failed: {e}")

                # Search for m3u8 in the HTML
                if not captured:
                    patterns = [
                        r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*',
                        r'https?://[^\s"\'<>]*b-cdn\.net[^\s"\'<>]*\.m3u8[^\s"\'<>]*',
                    ]
                    for pattern in patterns:
                        matches = re.findall(pattern, player_html, re.IGNORECASE)
                        for match in matches:
                            if not captured:
                                captured = match
                                log(f"  ✓ CAPTURED via HTML: {captured[:100]}...")
                                break
                        if captured:
                            break

            except Exception as e:
                log(f"  Iframe navigation error: {e}")

        # If still not captured, monitor for network responses
        if not captured:
            log(f"  Monitoring for stream (max {timeout_seconds}s)...")
            elapsed = 0
            while elapsed < timeout_seconds and not captured:
                await page.wait_for_timeout(2000)
                elapsed += 2

                # Check for m3u8 in all frames
                for frame in page.frames:
                    if captured:
                        break
                    try:
                        frame_html = await frame.content()
                        patterns = [
                            r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*',
                            r'https?://[^\s"\'<>]*b-cdn\.net[^\s"\'<>]*\.m3u8[^\s"\'<>]*',
                        ]
                        for pattern in patterns:
                            matches = re.findall(pattern, frame_html, re.IGNORECASE)
                            for match in matches:
                                if not captured:
                                    captured = match
                                    log(f"  ✓ CAPTURED via frame HTML: {captured[:100]}...")
                                    break
                            if captured:
                                break
                    except Exception:
                        pass

                if elapsed % 5 == 0:
                    log(f"  Still waiting... {elapsed}/{timeout_seconds}s")

    except Exception as exc:
        log(f"  Stream capture error: {str(exc)[:300]}")

    finally:
        try:
            await page.close()
        except Exception:
            pass
        try:
            await context.close()
        except Exception:
            pass
        try:
            await browser.close()
        except Exception:
            pass

    return captured

# ============================================================
# PLAYLIST WRITER
# ============================================================

def write_playlists(entries):
    if not entries:
        log("No entries to write")
        return

    # VLC
    with open(OUTPUT_VLC, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for i, entry in enumerate(entries, 1):
            safe_name = clean_text(entry["event"]).replace(",", "")
            logo = entry.get("logo", DEFAULT_LOGO)
            f.write(
                f'#EXTINF:-1 '
                f'tvg-chno="{i}" '
                f'tvg-id="{TVG_ID}" '
                f'tvg-name="{safe_name}" '
                f'tvg-logo="{logo}" '
                f'group-title="{GROUP_TITLE}",'
                f'{safe_name}\n'
            )
            f.write(f"#EXTVLCOPT:http-referrer={HOMEPAGE}\n")
            f.write(f"#EXTVLCOPT:http-origin={HOMEPAGE}\n")
            f.write(f"#EXTVLCOPT:http-user-agent={USER_AGENT}\n")
            f.write(f"{entry['m3u8']}\n\n")

    # TiviMate
    ua_encoded = quote_plus(USER_AGENT)
    with open(OUTPUT_TIVI, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for i, entry in enumerate(entries, 1):
            safe_name = clean_text(entry["event"]).replace(",", "")
            logo = entry.get("logo", DEFAULT_LOGO)
            f.write(
                f'#EXTINF:-1 '
                f'tvg-chno="{i}" '
                f'tvg-id="{TVG_ID}" '
                f'tvg-name="{safe_name}" '
                f'tvg-logo="{logo}" '
                f'group-title="{GROUP_TITLE}",'
                f'{safe_name}\n'
            )
            f.write(
                f"{entry['m3u8']}"
                f"|referer={HOMEPAGE}"
                f"|origin={HOMEPAGE}"
                f"|user-agent={ua_encoded}\n\n"
            )

    log(f"\nPlaylists saved:")
    log(f"  {OUTPUT_VLC}")
    log(f"  {OUTPUT_TIVI}")

# ============================================================
# PROCESS ONE TEAM
# ============================================================

async def process_event(playwright, event, semaphore):
    async with semaphore:
        log("")
        log("=" * 70)
        log(f"PROCESSING: {event['event']}")
        log(f"URL: {event['url']}")

        m3u8 = await capture_m3u8_from_page(playwright, event, STREAM_WAIT_SECONDS)

        if m3u8:
            event["m3u8"] = m3u8
            log(f"✓ STREAM CAPTURED: {event['event']}")
            return event

        log(f"✗ NO STREAM: {event['event']}")
        return None

# ============================================================
# MAIN
# ============================================================

async def main():
    log("Starting MLB Webcast Updater...")

    async with async_playwright() as p:
        events = await fetch_events_via_playwright(p)
        log(f"Found {len(events)} total events")

        if not events:
            log("No events detected.")
            return

        log("")
        log("Discovered team/event URLs:")
        for i, event in enumerate(events, 1):
            log(f"  {i:02d}. {event['event']} -> {event['url']}")

        semaphore = asyncio.Semaphore(MAX_CONCURRENT)
        tasks = [process_event(p, event, semaphore) for event in events]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        collected = []
        for result in results:
            if isinstance(result, Exception):
                log(f"Worker error: {result}")
                continue
            if result:
                collected.append(result)

        collected.sort(key=lambda x: x.get("event", "").lower())

        log("")
        log("=" * 70)
        log(f"Captured {len(collected)}/{len(events)} streams")

        if not collected:
            log("No streams captured.")
            return

        write_playlists(collected)

# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    asyncio.run(main())
