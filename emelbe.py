#!/usr/bin/env python3
import asyncio
import re
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

STREAM_IFRAME = "https://mlbwebcast.com/stream/mlbhd.html"

OUTPUT_VLC = "emelbecast_VLC.m3u8"
OUTPUT_TIVI = "emelbecast_TiviMate.m3u8"

DEFAULT_LOGO = (
    "https://i.postimg.cc/7L220Lmn/baseball4k.png"
)

TVG_ID = "MLB.Baseball.Dummy.us"
GROUP_TITLE = "MLB TEAM GAME"

# How long to wait for the player to generate/request the stream.
STREAM_WAIT_SECONDS = 45

# Delay between teams.
TEAM_DELAY_SECONDS = 1.0

# Maximum number of concurrent browser pages.
MAX_CONCURRENT = 4

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
    """
    Example:
    Arizona Diamondbacks Live Stream
    ->
    Arizona Diamondbacks
    """
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
    """
    Normalize whitespace/HTML escaping without removing
    query-string authentication parameters.
    """
    if not url:
        return ""

    url = url.strip()
    # Remove accidental surrounding quotes.
    url = url.strip("\"'")
    # HTML entities sometimes appear in source.
    url = url.replace("&amp;", "&")
    # Remove whitespace that should never exist inside URL.
    url = re.sub(r"\s+", "", url)

    return url

def looks_like_stream(url: str) -> bool:
    if not is_m3u8(url):
        return False

    lowered = url.lower()
    # Prefer the actual HLS stream rather than unrelated resources.
    stream_hosts = (
        "b-cdn.net",
        "cloudfront.net",
        ".m3u8",
    )

    return any(x in lowered for x in stream_hosts)

# ============================================================
# HOMEPAGE EVENT DISCOVERY
# ============================================================

async def fetch_events_via_playwright(playwright):
    """
    Discover MLB team/game URLs.

    Primary source:
        li.team-logo > a

    Secondary source:
        tr.singele_match_date

    The homepage supplied by the user confirms both structures.
    """
    browser = await playwright.firefox.launch(
        headless=True
    )

    context = await browser.new_context(
        user_agent=USER_AGENT,
        viewport={
            "width": 1920,
            "height": 1080,
        },
        locale="en-US",
        timezone_id="America/New_York",
    )

    page = await context.new_page()

    events = {}

    log("Loading homepage...")

    try:
        try:
            await page.goto(
                HOMEPAGE,
                wait_until="domcontentloaded",
                timeout=30000,
            )
        except PlaywrightTimeoutError:
            log("Homepage DOM load timed out; continuing...")

        # Give WordPress/LiteSpeed/Cloudflare/player JS time to settle.
        await page.wait_for_timeout(5000)

        # ----------------------------------------------------
        # METHOD 1:
        # Read actual team-logo links directly from DOM.
        # ----------------------------------------------------

        team_count = 0

        try:
            await page.wait_for_selector(
                "li.team-logo a",
                timeout=10000,
            )
        except PlaywrightTimeoutError:
            pass

        team_links = await page.locator(
            "li.team-logo a"
        ).evaluate_all(
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

            if not href:
                continue

            # Ignore navigation links that are not team/live pages.
            if "-live" not in href.lower():
                continue

            team_name = team_name_from_title(title)

            if not team_name:
                # Fallback from URL.
                slug = href.rstrip("/").split("/")[-1]
                slug = re.sub(
                    r"-live$",
                    "",
                    slug,
                    flags=re.IGNORECASE,
                )
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

        # ----------------------------------------------------
        # METHOD 2:
        # Extract today's actual games.
        # ----------------------------------------------------

        game_count = 0

        rows = page.locator(
            "tr.singele_match_date:not(.mdatetitle)"
        )

        row_count = await rows.count()

        log(f"Found {row_count} match rows")

        for index in range(row_count):
            row = rows.nth(index)

            try:
                vs_link = row.locator(
                    "td.teamvs a"
                ).first

                if await vs_link.count() == 0:
                    continue

                href = await vs_link.get_attribute("href")

                if not href:
                    continue

                href = urljoin(HOMEPAGE, href)

                raw_event = await vs_link.inner_text()

                # Remove date from event.
                date_nodes = vs_link.locator(
                    "span.mtdate"
                )

                date_count = await date_nodes.count()

                event_name = raw_event

                for d in range(date_count):
                    date_text = await date_nodes.nth(d).inner_text()

                    if date_text:
                        event_name = event_name.replace(
                            date_text,
                            "",
                        )

                event_name = fix_event(event_name)

                if not event_name:
                    continue

                logo = DEFAULT_LOGO

                logo_img = row.locator(
                    "td.teamlogo img"
                ).first

                if await logo_img.count():
                    src = await logo_img.get_attribute("src")

                    if src:
                        logo = urljoin(HOMEPAGE, src)

                key = href.rstrip("/").lower()

                if key in events:
                    # Keep the better event name from the game table.
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
                log(
                    f"  Error reading match row "
                    f"{index + 1}: {exc}"
                )

        log(f"Found {game_count} game rows")

        # ----------------------------------------------------
        # FALLBACK:
        # Parse raw HTML if Playwright selectors returned nothing.
        # ----------------------------------------------------

        if not events:
            log(
                "No events found through Playwright DOM. "
                "Trying raw HTML..."
            )

            html = await page.content()

            soup = HTMLParser(html)

            # Team logos.
            for link in soup.css(
                "li.team-logo a"
            ):
                href = link.attributes.get("href", "")
                title = link.attributes.get("title", "")

                if not href:
                    continue

                if "-live" not in href.lower():
                    continue

                team_name = team_name_from_title(title)

                if not team_name:
                    slug = href.rstrip("/").split("/")[-1]
                    slug = re.sub(
                        r"-live$",
                        "",
                        slug,
                        flags=re.IGNORECASE,
                    )
                    team_name = slug.replace(
                        "-",
                        " ",
                    ).title()

                img = link.css_first("img")

                logo = DEFAULT_LOGO

                if img:
                    src = img.attributes.get("src")

                    if src:
                        logo = urljoin(
                            HOMEPAGE,
                            src,
                        )

                key = urljoin(
                    HOMEPAGE,
                    href,
                ).rstrip("/").lower()

                events[key] = {
                    "url": urljoin(HOMEPAGE, href),
                    "event": team_name,
                    "team": team_name,
                    "logo": logo,
                }

        log(
            f"Total unique team/event URLs: "
            f"{len(events)}"
        )

    except Exception as exc:
        log(
            f"Homepage discovery error: {exc}"
        )

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
# M3U8 EXTRACTION
# ============================================================

async def capture_m3u8_from_page(
    playwright,
    event,
    timeout_seconds=STREAM_WAIT_SECONDS,
):
    """
    Open the actual team URL and capture the HLS URL.

    IMPORTANT:
    We do NOT navigate page.goto() to the iframe URL.

    The team page remains open and the iframe is allowed to
    load normally. This preserves the browser/page/frame context
    and lets Playwright observe requests generated by the player.
    """
    url = event["url"]

    browser = await playwright.firefox.launch(
        headless=True
    )

    context = await browser.new_context(
        user_agent=USER_AGENT,
        viewport={
            "width": 1920,
            "height": 1080,
        },
        locale="en-US",
        timezone_id="America/New_York",
        extra_http_headers={
            "Accept-Language": "en-US,en;q=0.9",
        },
    )

    page = await context.new_page()

    captured = None
    seen = set()

    def accept_stream(candidate, source="network"):
        nonlocal captured

        candidate = clean_m3u8_url(candidate)

        if not candidate:
            return

        if not looks_like_stream(candidate):
            return

        if candidate in seen:
            return

        seen.add(candidate)

        if captured is None:
            captured = candidate

            log(
                f"  ✓ CAPTURED via {source}: "
                f"{candidate[:180]}"
            )

    # --------------------------------------------------------
    # REQUEST listener
    # --------------------------------------------------------

    def on_request(request):
        try:
            request_url = request.url

            if is_m3u8(request_url):
                accept_stream(
                    request_url,
                    "REQUEST",
                )
        except Exception:
            pass

    # --------------------------------------------------------
    # RESPONSE listener
    # --------------------------------------------------------

    def on_response(response):
        try:
            response_url = response.url

            if is_m3u8(response_url):
                accept_stream(
                    response_url,
                    "RESPONSE",
                )
        except Exception:
            pass

    page.on("request", on_request)
    page.on("response", on_response)

    try:
        log(f"  Opening team page: {url}")

        # ----------------------------------------------------
        # Load team page.
        # ----------------------------------------------------

        try:
            await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=30000,
            )
        except PlaywrightTimeoutError:
            log(
                "  Team page DOM load timed out; "
                "continuing..."
            )

        # Allow iframe/player initialization.
        await page.wait_for_timeout(5000)

        # ----------------------------------------------------
        # Print all frames.
        # ----------------------------------------------------

        log(
            f"  Frames currently loaded: "
            f"{len(page.frames)}"
        )

        for frame in page.frames:
            try:
                log(
                    f"    FRAME: {frame.url}"
                )
            except Exception:
                pass

        # ----------------------------------------------------
        # Make sure the MLB player iframe exists.
        # ----------------------------------------------------

        iframe_locator = page.locator(
            "iframe[src*='/stream/mlbhd.html']"
        )

        iframe_count = await iframe_locator.count()

        log(
            f"  MLB player iframes: "
            f"{iframe_count}"
        )

        if iframe_count == 0:
            # Generic fallback.
            iframe_locator = page.locator(
                "iframe"
            )

            iframe_count = await iframe_locator.count()

            log(
                f"  Generic iframe count: "
                f"{iframe_count}"
            )

        # ----------------------------------------------------
        # Locate the player frame.
        # ----------------------------------------------------

        player_frame = None

        for frame in page.frames:
            frame_url = frame.url or ""

            if (
                "mlbhd.html" in frame_url.lower()
                or "/stream/" in frame_url.lower()
            ):
                player_frame = frame

                log(
                    f"  ✓ Player frame found: "
                    f"{frame_url}"
                )

                break

        # ----------------------------------------------------
        # If iframe exists but frame isn't available yet,
        # wait for it.
        # ----------------------------------------------------

        if player_frame is None and iframe_count:
            log(
                "  Waiting for player frame..."
            )

            for _ in range(10):
                await page.wait_for_timeout(1000)

                for frame in page.frames:
                    frame_url = frame.url or ""

                    if (
                        "mlbhd.html"
                        in frame_url.lower()
                        or "/stream/"
                        in frame_url.lower()
                    ):
                        player_frame = frame

                        log(
                            f"  ✓ Player frame loaded: "
                            f"{frame_url}"
                        )

                        break

                if player_frame:
                    break

        # ----------------------------------------------------
        # Inspect iframe content.
        # ----------------------------------------------------

        if player_frame:
            try:
                await player_frame.wait_for_load_state(
                    "domcontentloaded",
                    timeout=10000,
                )
            except Exception:
                pass

            await page.wait_for_timeout(3000)

            try:
                player_html = await player_frame.content()

                log(
                    f"  Player HTML size: "
                    f"{len(player_html)} bytes"
                )

                # Search static HTML for HLS URLs.
                static_patterns = [
                    r"https?://[^\"'<>\s]+\.m3u8[^\"'<>\s]*",
                    r"https?://[^\"'<>\s]*b-cdn\.net[^\"'<>\s]*\.m3u8[^\"'<>\s]*",
                    r"https?://[^\"'<>\s]*cloudfront\.net[^\"'<>\s]*\.m3u8[^\"'<>\s]*",
                ]

                for pattern in static_patterns:
                    matches = re.findall(
                        pattern,
                        player_html,
                        re.IGNORECASE,
                    )

                    for match in matches:
                        accept_stream(
                            match,
                            "PLAYER HTML",
                        )

                        if captured:
                            break

                    if captured:
                        break

            except Exception as exc:
                log(
                    f"  Player HTML error: {exc}"
                )

        # ----------------------------------------------------
        # Browser interaction.
        #
        # The site autoloads the stream, but some players do
        # not begin the HLS request until the video/player is
        # interacted with.
        # ----------------------------------------------------

        if player_frame and not captured:
            log(
                "  Starting browser player interaction..."
            )

            # Try video element.
            try:
                videos = player_frame.locator(
                    "video"
                )

                video_count = await videos.count()

                log(
                    f"  Video elements: "
                    f"{video_count}"
                )

                for i in range(video_count):
                    video = videos.nth(i)

                    try:
                        await video.scroll_into_view_if_needed(
                            timeout=3000
                        )
                    except Exception:
                        pass

                    try:
                        await video.click(
                            position={
                                "x": 20,
                                "y": 20,
                            },
                            timeout=3000,
                            force=True,
                        )

                        log(
                            "  ✓ Video clicked"
                        )

                    except Exception:
                        pass

                    # Ask the HTML5 video element to play.
                    try:
                        await video.evaluate(
                            """
                            async video => {
                                try {
                                    video.muted = true;
                                    await video.play();
                                    return true;
                                } catch (e) {
                                    return false;
                                }
                            }
                            """
                        )

                        log(
                            "  ✓ video.play() requested"
                        )

                    except Exception:
                        pass

            except Exception as exc:
                log(
                    f"  Video interaction error: "
                    f"{exc}"
                )

            # Try clicking common player elements.
            selectors = [
                "button",
                ".play",
                ".play-button",
                ".vjs-big-play-button",
                ".clappr-big-play-button",
                ".media-control",
                "[aria-label*='Play']",
                "[title*='Play']",
            ]

            for selector in selectors:
                if captured:
                    break

                try:
                    locator = player_frame.locator(
                        selector
                    )

                    count = await locator.count()

                    for i in range(
                        min(count, 5)
                    ):
                        try:
                            await locator.nth(i).click(
                                timeout=1500,
                                force=True,
                            )

                            log(
                                f"  ✓ Clicked player "
                                f"element: {selector}"
                            )

                            await page.wait_for_timeout(
                                1000
                            )

                            if captured:
                                break

                        except Exception:
                            pass

                except Exception:
                    pass

        # ----------------------------------------------------
        # Execute player-side JS.
        #
        # This is useful for players which create the media
        # element only after initialization.
        # ----------------------------------------------------

        if player_frame and not captured:
            try:
                await player_frame.evaluate(
                    """
                    () => {
                        const videos =
                            document.querySelectorAll("video");

                        for (const video of videos) {
                            try {
                                video.muted = true;
                                const p = video.play();

                                if (p && p.catch) {
                                    p.catch(() => {});
                                }
                            } catch (e) {}

                            // Try to find the source URL
                            if (video.src && video.src.includes('.m3u8')) {
                                return video.src;
                            }
                        }

                        return videos.length;
                    }
                    """
                )

                log(
                    "  ✓ Player-side video play "
                    "attempt completed"
                )

            except Exception:
                pass

        # ----------------------------------------------------
        # Wait and monitor network.
        #
        # This is the most important part.
        # ----------------------------------------------------

        log(
            f"  Waiting up to "
            f"{timeout_seconds}s for HLS stream..."
        )

        elapsed = 0

        while (
            elapsed < timeout_seconds
            and not captured
        ):
            await page.wait_for_timeout(2000)

            elapsed += 2

            # ------------------------------------------------
            # Check every frame for newly injected URLs.
            # ------------------------------------------------

            for frame in page.frames:
                if captured:
                    break

                try:
                    frame_html = await frame.content()

                    patterns = [
                        r"https?://[^\"'<>\s]+\.m3u8[^\"'<>\s]*",
                        r"https?://[^\"'<>\s]*b-cdn\.net[^\"'<>\s]*\.m3u8[^\"'<>\s]*",
                        r"https?://[^\"'<>\s]*cloudfront\.net[^\"'<>\s]*\.m3u8[^\"'<>\s]*",
                    ]

                    for pattern in patterns:
                        matches = re.findall(
                            pattern,
                            frame_html,
                            re.IGNORECASE,
                        )

                        for match in matches:
                            accept_stream(
                                match,
                                "FRAME HTML",
                            )

                            if captured:
                                break

                        if captured:
                            break

                except Exception:
                    pass

            if elapsed % 5 == 0:
                log(
                    f"  Still waiting... "
                    f"{elapsed}/{timeout_seconds}s"
                )

        # ----------------------------------------------------
        # Last browser-side search.
        # ----------------------------------------------------

        if not captured:
            try:
                all_frames = page.frames

                for frame in all_frames:
                    try:
                        entries = await frame.evaluate(
                            """
                            () => {
                                const result = [];

                                document
                                    .querySelectorAll("*")
                                    .forEach(el => {
                                        for (const attr of el.attributes || []) {
                                            if (
                                                attr.value &&
                                                attr.value.includes(".m3u8")
                                            ) {
                                                result.push(
                                                    attr.value
                                                );
                                            }
                                        }
                                    });

                                return result;
                            }
                            """
                        )

                        for value in entries:
                            matches = re.findall(
                                r"https?://[^\"'<>\s]+\.m3u8[^\"'<>\s]*",
                                value,
                                re.IGNORECASE,
                            )

                            for match in matches:
                                accept_stream(
                                    match,
                                    "DOM",
                                )

                                if captured:
                                    break

                            if captured:
                                break

                    except Exception:
                        pass

                    if captured:
                        break

            except Exception:
                pass

    except Exception as exc:
        log(
            f"  Stream capture error: "
            f"{str(exc)[:300]}"
        )

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

    # --------------------------------------------------------
    # VLC
    # --------------------------------------------------------

    with open(
        OUTPUT_VLC,
        "w",
        encoding="utf-8",
    ) as f:

        f.write("#EXTM3U\n")

        for i, entry in enumerate(
            entries,
            1,
        ):

            safe_name = (
                clean_text(entry["event"])
                .replace(",", "")
            )

            logo = entry.get(
                "logo",
                DEFAULT_LOGO,
            )

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
                f"#EXTVLCOPT:http-referrer="
                f"{HOMEPAGE}\n"
            )

            f.write(
                f"#EXTVLCOPT:http-origin="
                f"{HOMEPAGE}\n"
            )

            f.write(
                f"#EXTVLCOPT:http-user-agent="
                f"{USER_AGENT}\n"
            )

            f.write(
                f"{entry['m3u8']}\n\n"
            )

    # --------------------------------------------------------
    # TiviMate
    # --------------------------------------------------------

    ua_encoded = quote_plus(
        USER_AGENT
    )

    with open(
        OUTPUT_TIVI,
        "w",
        encoding="utf-8",
    ) as f:

        f.write("#EXTM3U\n")

        for i, entry in enumerate(
            entries,
            1,
        ):

            safe_name = (
                clean_text(entry["event"])
                .replace(",", "")
            )

            logo = entry.get(
                "logo",
                DEFAULT_LOGO,
            )

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

    log(
        "\nPlaylists saved:"
    )

    log(
        f"  {OUTPUT_VLC}"
    )

    log(
        f"  {OUTPUT_TIVI}"
    )

# ============================================================
# PROCESS ONE TEAM
# ============================================================

async def process_event(
    playwright,
    event,
    semaphore,
):
    async with semaphore:
        log("")
        log(
            "=" * 70
        )

        log(
            f"PROCESSING: {event['event']}"
        )

        log(
            f"URL: {event['url']}"
        )

        m3u8 = await capture_m3u8_from_page(
            playwright,
            event,
            STREAM_WAIT_SECONDS,
        )

        if m3u8:
            event["m3u8"] = m3u8

            log(
                f"✓ STREAM CAPTURED: "
                f"{event['event']}"
            )

            return event

        log(
            f"✗ NO STREAM: "
            f"{event['event']}"
        )

        return None

# ============================================================
# MAIN
# ============================================================

async def main():
    log(
        "Starting MLB Webcast Updater..."
    )

    async with async_playwright() as p:
        # ----------------------------------------------------
        # Discover teams/events.
        # ----------------------------------------------------

        events = await fetch_events_via_playwright(
            p
        )

        log(
            f"Found {len(events)} total events"
        )

        if not events:
            log(
                "No events detected."
            )

            return

        # ----------------------------------------------------
        # Display discovered events.
        # ----------------------------------------------------

        log("")
        log(
            "Discovered team/event URLs:"
        )

        for i, event in enumerate(
            events,
            1,
        ):
            log(
                f"  {i:02d}. "
                f"{event['event']} -> "
                f"{event['url']}"
            )

        # ----------------------------------------------------
        # Process browser pages concurrently.
        # ----------------------------------------------------

        semaphore = asyncio.Semaphore(
            MAX_CONCURRENT
        )

        tasks = [
            process_event(
                p,
                event,
                semaphore,
            )
            for event in events
        ]

        results = await asyncio.gather(
            *tasks,
            return_exceptions=True,
        )

        collected = []

        for result in results:
            if isinstance(
                result,
                Exception,
            ):
                log(
                    f"Worker error: {result}"
                )

                continue

            if result:
                collected.append(
                    result
                )

        # ----------------------------------------------------
        # Sort consistently.
        # ----------------------------------------------------

        collected.sort(
            key=lambda x: (
                x.get("event", "")
                .lower()
            )
        )

        # ----------------------------------------------------
        # Results.
        # ----------------------------------------------------

        log("")
        log(
            "=" * 70
        )

        log(
            f"Captured "
            f"{len(collected)}/{len(events)} "
            f"streams"
        )

        if not collected:
            log(
                "No streams captured."
            )

            return

        # ----------------------------------------------------
        # Write playlists.
        # ----------------------------------------------------

        write_playlists(
            collected
        )

# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    asyncio.run(main())
