import asyncio
import re
from urllib.parse import quote

from playwright.async_api import async_playwright

TARGET_URL = "https://rojadirectablog.com/en-vivo/capo-deportes.php"

HEADERS = {
    "referer": "https://capo7play.com/",
    "origin": "https://capo7play.com"
}


async def extract_m3u8():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox"]
        )

        context = await browser.new_context()
        page = await context.new_page()

        m3u8_url = None

        def handle_response(response):
            nonlocal m3u8_url

            url = response.url

            if ".m3u8" in url or ".ts" in url:
                if "token" in url or ".m3u8" in url:
                    print(f"🎯 FOUND STREAM: {url}")
                    m3u8_url = url

        page.on("response", handle_response)

        print(f"Loading: {TARGET_URL}")
        await page.goto(TARGET_URL, timeout=60000)

        # Wait for iframe
        try:
            iframe = await page.wait_for_selector("iframe", timeout=15000)
            src = await iframe.get_attribute("src")

            if src:
                print(f"Found iframe: {src}")
                await page.goto(src, timeout=60000)
        except:
            print("No iframe found, continuing...")

        # Wait for player/network activity
        await page.wait_for_timeout(15000)

        await browser.close()

        return m3u8_url


def write_outputs(stream_url):
    if not stream_url:
        print("No stream found")
        return

    name = "Capo Deportes"

    # VLC format
    vlc = f'#EXTM3U\n#EXTINF:-1,{name}\n{stream_url}\n'

    # Tivimate format (headers encoded)
    headers = "|referer=" + quote(HEADERS["referer"]) + "&origin=" + quote(HEADERS["origin"])
    tivimate = f'#EXTM3U\n#EXTINF:-1,{name}\n{stream_url}{headers}\n'

    with open("rojadirecta_vlc.m3u8", "w", encoding="utf-8") as f:
        f.write(vlc)

    with open("rojadirecta_tivimate.m3u8", "w", encoding="utf-8") as f:
        f.write(tivimate)

    print("Files written successfully")


async def main():
    stream = await extract_m3u8()
    write_outputs(stream)


if __name__ == "__main__":
    asyncio.run(main())
