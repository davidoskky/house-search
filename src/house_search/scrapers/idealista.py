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

                has_next = await self._click_next_page(page)
                if not has_next:
                    break
                await random_delay(3, 6)
                page_num += 1
        finally:
            await context.close()

    async def scrape_detail_url(self, url: str, browser: Browser) -> Listing | None:
        """Scrape a single Idealista listing from its detail page URL."""
        m = re.search(r"/inmueble/(\d+)/", url)
        if not m:
            console.print(f"[yellow]idealista[/yellow] Could not extract ID from URL: {url}")
            return None
        external_id = m.group(1)

        context = await self._new_context(browser)
        page = await self._new_page(context)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await random_delay(2, 4)
            await self._accept_cookies(page)
            await random_delay(1, 2)

            soup = BeautifulSoup(await page.content(), "html.parser")

            title_el = soup.select_one("h1.main-info__title-main, h1.main-info__title, h1")
            title = title_el.get_text(strip=True) if title_el else f"Idealista {external_id}"

            price_el = soup.select_one(".info-data-price, .price-features__current")
            price = _parse_price(price_el.get_text()) if price_el else None
            if not price:
                return None

            size_m2 = rooms = bathrooms = None
            floor: str | None = None
            for li in soup.select(".details-property_features li, .stats-text"):
                text = li.get_text(strip=True)
                tl = text.lower()
                if "m²" in text:
                    size_m2 = _parse_float(text)
                elif "hab" in tl:
                    rooms = _parse_int(text)
                elif "baño" in tl:
                    bathrooms = _parse_int(text)
                elif any(k in tl for k in ("planta", "bajo", "ático")):
                    floor = text

            images: list[str] = []
            for img in soup.select(".main-slider img[src], .slider img[src], img[data-src]"):
                src = str(img.get("src") or img.get("data-src") or "")
                if src.startswith("http"):
                    images.append(src)

            all_text = soup.get_text(" ").lower()
            has_elevator = "ascensor" in all_text or None
            has_parking = ("garaje" in all_text or "parking" in all_text) or None
            has_terrace = "terraza" in all_text or None

            return Listing(
                source="idealista",
                external_id=external_id,
                url=url,
                title=title,
                price=price,
                size_m2=size_m2,
                rooms=rooms,
                bathrooms=bathrooms,
                floor=floor,
                image_urls=images[:3],
                has_elevator=has_elevator if has_elevator else None,
                has_parking=has_parking if has_parking else None,
                has_terrace=has_terrace if has_terrace else None,
            )
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

    async def _click_next_page(self, page: Page) -> bool:
        """Click the next-page button in place. Returns True if clicked."""
        try:
            next_btn = page.locator("a.icon-arrow-right-after").first
            if not await next_btn.is_visible(timeout=3000):
                return False
            # Scroll the button into view and click (human-like)
            await next_btn.scroll_into_view_if_needed()
            await random_delay(0.5, 1.5)
            await next_btn.click()
            await page.wait_for_load_state("domcontentloaded", timeout=30000)
            return True
        except Exception:
            return False

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
