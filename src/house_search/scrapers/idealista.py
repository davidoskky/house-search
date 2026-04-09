from __future__ import annotations

import re
from typing import AsyncIterator

from bs4 import BeautifulSoup
from playwright.async_api import Browser, Page

from ..models import Listing
from .base import BaseScraper, console, random_delay

# Santiago de Compostela rent URL
BASE_URL = "https://www.idealista.com/alquiler-viviendas/santiago-de-compostela-a-coruna/"


def _parse_price(text: str) -> float | None:
    # "750€/mes" -> 750.0
    m = re.search(r"([\d\.]+)", text.replace(".", "").replace(",", "."))
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None


def _parse_int(text: str) -> int | None:
    m = re.search(r"\d+", text)
    return int(m.group()) if m else None


def _parse_float(text: str) -> float | None:
    m = re.search(r"[\d,]+", text)
    if m:
        try:
            return float(m.group().replace(",", "."))
        except ValueError:
            return None
    return None


class IdealistaScraper(BaseScraper):
    source = "idealista"

    def __init__(self, max_pages: int = 5, headless: bool = True):
        super().__init__(headless=headless)
        self.max_pages = max_pages

    async def scrape(self) -> AsyncIterator[Listing]:
        raise NotImplementedError("Use scrape_with_browser")

    async def scrape_with_browser(self, browser: Browser) -> AsyncIterator[Listing]:
        context = await self._new_context(browser)
        page = await self._new_page(context)

        try:
            console.print(f"[blue]idealista[/blue] Loading {BASE_URL}")
            await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)
            await random_delay(3, 5)
            await self._accept_cookies(page)
            await random_delay(1, 2)

            page_num = 1
            while page_num <= self.max_pages:
                console.print(f"[blue]idealista[/blue] Scraping page {page_num}")
                # Wait for listing articles to appear
                try:
                    await page.wait_for_selector("article.item", timeout=15000)
                except Exception:
                    pass
                content = await page.content()
                listings = self._parse_listings_page(content)
                for listing in listings:
                    yield listing

                next_url = await self._get_next_page_url(page)
                if not next_url:
                    break
                await random_delay(2, 5)
                await page.goto(next_url, wait_until="domcontentloaded", timeout=30000)
                await random_delay(2, 3)
                page_num += 1
        finally:
            await context.close()

    async def _accept_cookies(self, page: Page) -> None:
        for selector in [
            "#didomi-notice-agree-button",
            "button[id*='accept']",
            "button[class*='accept']",
            "#acceptAllButton",
        ]:
            try:
                btn = page.locator(selector).first
                if await btn.is_visible(timeout=3000):
                    await btn.click()
                    await random_delay(0.5, 1.5)
                    return
            except Exception:
                continue

    async def _get_next_page_url(self, page: Page) -> str | None:
        try:
            next_btn = page.locator("a.icon-arrow-right-after").first
            if await next_btn.is_visible(timeout=3000):
                href = await next_btn.get_attribute("href")
                if href:
                    return f"https://www.idealista.com{href}"
        except Exception:
            pass
        return None

    def _parse_listings_page(self, html: str) -> list[Listing]:
        soup = BeautifulSoup(html, "html.parser")
        listings = []

        articles = soup.select("article.item")
        for article in articles:
            try:
                listing = self._parse_article(article)
                if listing:
                    listings.append(listing)
            except Exception as e:
                console.print(f"[yellow]idealista[/yellow] Error parsing article: {e}")

        return listings

    def _parse_article(self, article) -> Listing | None:
        # External ID from data attribute (more reliable than URL parsing)
        external_id = article.get("data-element-id")
        if not external_id:
            link_el = article.select_one("a.item-link")
            if not link_el:
                return None
            m = re.search(r"/inmueble/(\d+)/", link_el.get("href", ""))
            external_id = m.group(1) if m else None
        if not external_id:
            return None

        link_el = article.select_one("a.item-link")
        if not link_el:
            return None
        href = link_el.get("href", "")
        url = f"https://www.idealista.com{href}" if href.startswith("/") else href
        title = link_el.get("title") or link_el.get_text(strip=True) or f"Listing {external_id}"

        # Price: span.item-price contains "750€/mes"
        price_el = article.select_one(".item-price")
        price = None
        if price_el:
            price = _parse_price(price_el.get_text())
        if price is None:
            return None

        # Details: .item-detail-char span gives "1 hab.", "70 m²", "Planta 2ª..."
        size_m2 = None
        rooms = None
        bathrooms = None
        floor = None
        has_elevator = None

        for detail in article.select(".item-detail-char span"):
            text = detail.get_text(strip=True)
            tl = text.lower()
            if "m²" in text or "m2" in tl:
                size_m2 = _parse_float(text)
            elif "hab" in tl:
                rooms = _parse_int(text)
            elif "baño" in tl:
                bathrooms = _parse_int(text)
            elif "planta" in tl or "bajo" in tl or "ático" in tl or "sótano" in tl:
                floor = text
                has_elevator = "ascensor" in tl

        # Image
        image_urls: list[str] = []
        img = article.select_one("img[src]")
        if img:
            src = img.get("src", "")
            if src.startswith("http"):
                image_urls.append(src)

        # Tags for features
        has_parking = None
        has_terrace = None
        has_garden = None

        tags_text = " ".join(
            t.get_text(strip=True).lower()
            for t in article.select(".item-detail-char span, .tag-list span")
        )
        if tags_text:
            if has_elevator is None:
                has_elevator = "ascensor" in tags_text
            has_parking = "garaje" in tags_text or "parking" in tags_text
            has_terrace = "terraza" in tags_text
            has_garden = "jardín" in tags_text or "jardin" in tags_text

        return Listing(
            source="idealista",
            external_id=str(external_id),
            url=url,
            title=title,
            price=price,
            size_m2=size_m2,
            rooms=rooms,
            bathrooms=bathrooms,
            floor=floor,
            image_urls=image_urls,
            has_elevator=has_elevator,
            has_parking=has_parking,
            has_terrace=has_terrace,
            has_garden=has_garden,
        )
