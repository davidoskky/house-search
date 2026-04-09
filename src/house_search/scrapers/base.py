from __future__ import annotations

import asyncio
import random
from abc import ABC, abstractmethod
from typing import AsyncIterator

from playwright.async_api import Browser, BrowserContext, Page, async_playwright
from playwright_stealth import stealth_async
from rich.console import Console

from ..models import Listing

console = Console()

USER_AGENTS = [
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]


async def random_delay(min_s: float = 1.5, max_s: float = 4.0) -> None:
    await asyncio.sleep(random.uniform(min_s, max_s))


class BaseScraper(ABC):
    source: str

    def __init__(self, headless: bool = True):
        self.headless = headless

    async def _new_context(self, browser: Browser) -> BrowserContext:
        ua = random.choice(USER_AGENTS)
        context = await browser.new_context(
            user_agent=ua,
            viewport={"width": 1366, "height": 768},
            locale="es-ES",
            timezone_id="Europe/Madrid",
            extra_http_headers={
                "Accept-Language": "es-ES,es;q=0.9",
            },
        )
        return context

    async def _new_page(self, context: BrowserContext) -> Page:
        page = await context.new_page()
        await stealth_async(page)
        return page

    @abstractmethod
    async def scrape(self) -> AsyncIterator[Listing]:
        """Yield listings one by one."""
        ...

    async def scrape_all(self) -> list[Listing]:
        listings: list[Listing] = []
        async with async_playwright() as pw:
            browser = await pw.firefox.launch(headless=self.headless)
            try:
                async for listing in self.scrape_with_browser(browser):
                    listings.append(listing)
                    console.print(
                        f"[green]{self.source}[/green] {listing.title[:60]} "
                        f"— [bold]{listing.price}€[/bold]"
                        + (f" ({listing.rooms}h)" if listing.rooms else "")
                    )
            finally:
                await browser.close()
        return listings

    @abstractmethod
    async def scrape_with_browser(self, browser: Browser) -> AsyncIterator[Listing]:
        ...
