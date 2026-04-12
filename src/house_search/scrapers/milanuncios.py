from __future__ import annotations

import re
from typing import AsyncIterator

from bs4 import BeautifulSoup
from playwright.async_api import Browser, Page

from ..models import Listing
from .base import BaseScraper, console, random_delay

# Santiago de Compostela rent URL
BASE_URL = "https://www.milanuncios.com/alquiler-de-pisos-en-santiago-de-compostela-la_coruna/"


def _parse_price(text: str) -> float | None:
    # "750 €/mes" or "750€" -> 750.0
    m = re.search(r"([\d\.\,]+)", text.replace(".", "").replace(",", "."))
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None



class MilanunciosScraper(BaseScraper):
    source = "milanuncios"

    def __init__(self, max_pages: int = 5, headless: bool = True):
        super().__init__(headless=headless)
        self.max_pages = max_pages

    async def scrape(self) -> AsyncIterator[Listing]:
        raise NotImplementedError("Use scrape_with_browser")

    async def scrape_with_browser(self, browser: Browser) -> AsyncIterator[Listing]:
        context = await self._new_context(browser)
        page = await self._new_page(context)

        try:
            console.print(f"[cyan]milanuncios[/cyan] Loading {BASE_URL}")
            await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)
            await random_delay(3, 5)
            await self._accept_cookies(page)
            await random_delay(1, 2)

            for page_num in range(1, self.max_pages + 1):
                if page_num > 1:
                    url = f"{BASE_URL}?pagina={page_num}"
                    console.print(f"[cyan]milanuncios[/cyan] Loading page {page_num}")
                    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    await random_delay(2, 4)
                else:
                    console.print(f"[cyan]milanuncios[/cyan] Scraping page {page_num}")

                try:
                    await page.wait_for_selector("article", timeout=10000)
                except Exception:
                    pass

                content = await page.content()
                listings = self._parse_page(content)

                if not listings:
                    console.print("[yellow]milanuncios[/yellow] No listings on this page, stopping.")
                    break

                for listing in listings:
                    yield listing

                await random_delay(2, 4)
        finally:
            await context.close()

    async def _accept_cookies(self, page: Page) -> None:
        for selector in [
            "#didomi-notice-agree-button",
            "button[id*='accept']",
            "button[id*='Accept']",
            "[data-testid='accept-all']",
            "button[class*='accept']",
            "#onetrust-accept-btn-handler",
        ]:
            try:
                btn = page.locator(selector).first
                if await btn.is_visible(timeout=3000):
                    await btn.click()
                    await random_delay(0.5, 1.5)
                    return
            except Exception:
                continue

    def _parse_page(self, html: str) -> list[Listing]:
        soup = BeautifulSoup(html, "html.parser")
        listings = []

        # Milanuncios uses article tags with data-id or similar
        articles = soup.select("article[data-id], article.ma-AdCardV2, article[class*='AdCard']")
        if not articles:
            # Fallback: any article with a link
            articles = soup.select("article")

        for article in articles:
            try:
                listing = self._parse_article(article)
                if listing:
                    listings.append(listing)
            except Exception as e:
                console.print(f"[yellow]milanuncios[/yellow] Error parsing article: {e}")

        return listings

    def _parse_article(self, article) -> Listing | None:
        # External ID
        external_id = (
            article.get("data-id")
            or article.get("data-ad-id")
            or article.get("id", "").lstrip("ad-")
        )

        # Title and URL from the main link
        link_el = (
            article.select_one("a.ma-AdCardV2-titleLink")
            or article.select_one("h2 a")
            or article.select_one("a[class*='title']")
            or article.select_one("a[href*='/']")
        )
        if not link_el:
            return None

        href = link_el.get("href", "")
        if not href:
            return None
        url = f"https://www.milanuncios.com{href}" if href.startswith("/") else href

        # Extract external_id from URL if not found on article
        if not external_id:
            m = re.search(r"-(\d+)\.htm", href)
            external_id = m.group(1) if m else None
        if not external_id:
            return None

        title = link_el.get_text(strip=True) or f"Listing {external_id}"

        # Price
        price_el = (
            article.select_one(".ma-AdPrice-value")
            or article.select_one("[class*='price']")
            or article.select_one(".ad-price")
        )
        price = None
        if price_el:
            price = _parse_price(price_el.get_text())
        if price is None:
            return None

        # Description (used to extract features)
        desc_el = article.select_one(".ma-AdCardV2-description, [class*='description'], .ad-description")
        description = desc_el.get_text(strip=True) if desc_el else None

        # Features: look for tag/detail spans
        size_m2 = None
        rooms = None

        all_text = article.get_text(" ", strip=True).lower()

        # Size: e.g. "80 m²" or "80m2"
        m2_match = re.search(r"(\d+)\s*m[²2]", all_text)
        if m2_match:
            size_m2 = float(m2_match.group(1))

        # Rooms: e.g. "3 habitaciones" or "3 hab"
        rooms_match = re.search(r"(\d+)\s*hab", all_text)
        if rooms_match:
            rooms = int(rooms_match.group(1))

        # Images
        image_urls: list[str] = []
        for img in article.select("img[src]"):
            src = img.get("src", "")
            if src.startswith("http") and not src.endswith(".svg"):
                image_urls.append(src)
                break  # one thumbnail is enough

        # Boolean features from text
        has_elevator = "ascensor" in all_text or "elevator" in all_text or None
        has_parking = ("garaje" in all_text or "parking" in all_text) or None
        has_terrace = "terraza" in all_text or None
        has_garden = ("jardín" in all_text or "jardin" in all_text) or None

        # Normalise booleans: False positives from "sin ascensor" etc.
        if has_elevator and ("sin ascensor" in all_text or "no ascensor" in all_text):
            has_elevator = False
        if has_parking and ("sin garaje" in all_text or "sin parking" in all_text):
            has_parking = False
        if has_terrace and "sin terraza" in all_text:
            has_terrace = False

        return Listing(
            source="milanuncios",
            external_id=str(external_id),
            url=url,
            title=title,
            price=price,
            size_m2=size_m2,
            rooms=rooms,
            description=description,
            image_urls=image_urls,
            has_elevator=has_elevator if has_elevator else None,
            has_parking=has_parking if has_parking else None,
            has_terrace=has_terrace if has_terrace else None,
            has_garden=has_garden if has_garden else None,
        )
