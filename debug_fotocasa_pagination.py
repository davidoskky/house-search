"""Debug Fotocasa pagination — check if __INITIAL_PROPS__ updates and intercept API calls."""
import asyncio
import json
import re
from pathlib import Path
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async

BASE_URL = "https://www.fotocasa.es/es/alquiler/viviendas/espana/todas-las-zonas/l?text=Santiago+de+Compostela%2C+A+Coru%C3%B1a"

captured_api = []

async def main():
    async with async_playwright() as pw:
        browser = await pw.firefox.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0",
            viewport={"width": 1366, "height": 768},
            locale="es-ES",
            timezone_id="Europe/Madrid",
            extra_http_headers={"Accept-Language": "es-ES,es;q=0.9"},
        )
        page = await context.new_page()
        await stealth_async(page)

        # Intercept all JSON responses
        async def on_response(response):
            url = response.url
            ct = response.headers.get("content-type", "")
            if "json" in ct and "fotocasa" in url:
                try:
                    body = await response.json()
                    captured_api.append({"url": url, "size": len(json.dumps(body))})
                    if "realEstates" in json.dumps(body)[:200]:
                        Path("data/fotocasa_api_p2.json").write_text(json.dumps(body, indent=2))
                        print(f"  [API HIT] {url[:100]}")
                except Exception:
                    pass

        page.on("response", on_response)

        print("Loading page 1...")
        await page.goto(BASE_URL, wait_until="networkidle", timeout=60000)
        await asyncio.sleep(2)

        # Accept cookies
        for sel in ["#didomi-notice-agree-button"]:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=2000):
                    await btn.click()
                    await asyncio.sleep(2)
                    break
            except Exception:
                pass

        html1 = await page.content()
        ids1 = _extract_ids(html1)
        print(f"Page 1 URL: {page.url}")
        print(f"Page 1 listing IDs (first 5): {ids1[:5]}")
        print(f"Page 1 __INITIAL_PROPS__ size: {_props_size(html1)}")

        # Click Siguiente
        print("\nClicking Siguiente...")
        captured_api.clear()
        btn = page.locator("button[aria-label='Siguiente']").first
        if await btn.is_visible(timeout=5000):
            await btn.click()
            await page.wait_for_load_state("networkidle", timeout=30000)
            await asyncio.sleep(2)
        else:
            print("Siguiente button NOT found!")

        html2 = await page.content()
        ids2 = _extract_ids(html2)
        print(f"\nPage 2 URL: {page.url}")
        print(f"Page 2 listing IDs (first 5): {ids2[:5]}")
        print(f"Page 2 __INITIAL_PROPS__ size: {_props_size(html2)}")
        print(f"IDs changed: {ids1[:5] != ids2[:5]}")

        print(f"\nCaptured API calls: {len(captured_api)}")
        for c in captured_api[:10]:
            print(f"  {c['url'][:100]}  ({c['size']} bytes)")

        await browser.close()

def _extract_ids(html: str) -> list[str]:
    scripts = re.findall(r'<script(?:[^>]*)>([\s\S]*?)</script>', html)
    for s in scripts:
        if "__INITIAL_PROPS__" in s:
            m = re.search(r'window\.__INITIAL_PROPS__\s*=\s*JSON\.parse\("((?:[^"\\]|\\.)*)"\)', s)
            if m:
                try:
                    decoded = json.loads('"' + m.group(1) + '"')
                    props = json.loads(decoded)
                    listings = props["initialSearch"]["result"]["realEstates"]
                    return [str(l["id"]) for l in listings]
                except Exception:
                    pass
    return []

def _props_size(html: str) -> int:
    scripts = re.findall(r'<script(?:[^>]*)>([\s\S]*?)</script>', html)
    for s in scripts:
        if "__INITIAL_PROPS__" in s:
            return len(s)
    return 0

asyncio.run(main())
