"""Inspect the full structure of __INITIAL_PROPS__ to find all listings."""
import asyncio
import json
import re
from pathlib import Path
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async

BASE_URL = "https://www.fotocasa.es/es/alquiler/viviendas/espana/todas-las-zonas/l?text=Santiago+de+Compostela%2C+A+Coru%C3%B1a"

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

        print("Loading page...")
        await page.goto(BASE_URL, wait_until="networkidle", timeout=60000)
        await asyncio.sleep(2)

        for sel in ["#didomi-notice-agree-button"]:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=2000):
                    await btn.click()
                    await asyncio.sleep(1)
                    break
            except Exception:
                pass

        html = await page.content()

        scripts = re.findall(r'<script(?:[^>]*)>([\s\S]*?)</script>', html)
        for s in scripts:
            if "__INITIAL_PROPS__" in s:
                m = re.search(r'window\.__INITIAL_PROPS__\s*=\s*JSON\.parse\("((?:[^"\\]|\\.)*)"\)', s)
                if m:
                    decoded = json.loads('"' + m.group(1) + '"')
                    props = json.loads(decoded)
                    Path("data/fotocasa_props.json").write_text(json.dumps(props, indent=2))
                    print(f"Saved full props ({len(decoded)} chars)")

                    # Explore structure
                    def explore(obj, path="", depth=0):
                        if depth > 4:
                            return
                        if isinstance(obj, dict):
                            for k, v in obj.items():
                                full = f"{path}.{k}" if path else k
                                if isinstance(v, list):
                                    print(f"  {full}: list[{len(v)}]")
                                    if len(v) > 0 and isinstance(v[0], dict) and depth < 3:
                                        explore(v[0], full + "[0]", depth + 1)
                                elif isinstance(v, dict):
                                    explore(v, full, depth + 1)
                                else:
                                    if not isinstance(v, str) or len(str(v)) < 100:
                                        print(f"  {full}: {v!r}")

                    explore(props)
                    break

        await browser.close()

asyncio.run(main())
