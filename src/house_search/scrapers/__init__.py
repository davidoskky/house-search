from __future__ import annotations

import asyncio

from playwright.async_api import async_playwright

from ..models import Listing
from .fotocasa import FotocasaScraper
from .idealista import IdealistaScraper
from .milanuncios import MilanunciosScraper


def _detect_source(url: str) -> str | None:
    if "idealista.com" in url:
        return "idealista"
    if "fotocasa.es" in url:
        return "fotocasa"
    if "milanuncios.com" in url:
        return "milanuncios"
    return None


async def _scrape_single(url: str) -> Listing | None:
    source = _detect_source(url)
    if source is None:
        return None

    scraper: IdealistaScraper | FotocasaScraper | MilanunciosScraper
    if source == "idealista":
        scraper = IdealistaScraper()
    elif source == "fotocasa":
        scraper = FotocasaScraper()
    else:
        scraper = MilanunciosScraper()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--disable-dev-shm-usage", "--no-sandbox"],
        )
        try:
            return await scraper.scrape_detail_url(url, browser)
        finally:
            await browser.close()


def scrape_single_listing(url: str) -> Listing | None:
    """Synchronous wrapper — detects source from URL and scrapes the detail page."""
    return asyncio.run(_scrape_single(url))
