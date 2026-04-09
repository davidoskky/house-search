"""Debug Idealista pagination — inspect page 2 HTML."""
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async
from bs4 import BeautifulSoup

BASE_URL = "https://www.idealista.com/alquiler-viviendas/santiago-de-compostela-a-coruna/"

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

        print("Loading page 1...")
        await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(4)

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

        await asyncio.sleep(2)
        try:
            await page.wait_for_selector("article.item", timeout=15000)
        except Exception:
            print(f"WARNING: article.item not found on page 1 (title: {await page.title()})")
            await page.content()  # keep going anyway

        # Find next page button
        html = await page.content()
        soup = BeautifulSoup(html, "html.parser")
        print(f"Page 1 articles: {len(soup.select('article.item'))}")

        # Look for pagination
        print("\n--- Pagination links ---")
        for a in soup.select("a[class*='arrow'], a[class*='next'], a[class*='icon-arrow']"):
            print(f"  class={a.get('class')} href={a.get('href','')[:80]}")

        # Try the specific selector
        next_btn = soup.select_one("a.icon-arrow-right-after")
        print(f"\nnext button (a.icon-arrow-right-after): {next_btn}")

        # Also look for any link with page-2
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            if "pagina-2" in href or "page=2" in href:
                print(f"  page-2 link: {href}")

        # Check via playwright locator
        try:
            loc = page.locator("a.icon-arrow-right-after").first
            visible = await loc.is_visible(timeout=3000)
            href = await loc.get_attribute("href") if visible else None
            print(f"\nPlaywright: visible={visible}, href={href}")
        except Exception as e:
            print(f"Playwright locator error: {e}")

        # Navigate to page 2
        next_url = None
        try:
            loc = page.locator("a.icon-arrow-right-after").first
            if await loc.is_visible(timeout=3000):
                href = await loc.get_attribute("href")
                if href:
                    next_url = f"https://www.idealista.com{href}"
        except Exception:
            pass

        # Try clicking the button instead of goto
        print("\nClicking next page button...")
        try:
            loc = page.locator("a.icon-arrow-right-after").first
            if await loc.is_visible(timeout=3000):
                await loc.scroll_into_view_if_needed()
                await asyncio.sleep(1)
                await loc.click()
                await page.wait_for_load_state("domcontentloaded", timeout=30000)
                await asyncio.sleep(3)

                try:
                    await page.wait_for_selector("article.item", timeout=10000)
                    print("Found article.item on page 2!")
                except Exception:
                    print("No article.item found on page 2 within 10s")

                html2 = await page.content()
                soup2 = BeautifulSoup(html2, "html.parser")
                print(f"Page 2 URL: {page.url}")
                print(f"Page 2 articles: {len(soup2.select('article.item'))}")
                title = soup2.find("title")
                print(f"Page 2 title: {title.text if title else 'none'}")
                Path("data/idealista_p2.html").write_text(html2)
                print(f"Saved {len(html2)} chars to data/idealista_p2.html")
            else:
                print("Next button not visible!")
        except Exception as e:
            print(f"Click failed: {e}")

        await browser.close()

asyncio.run(main())
