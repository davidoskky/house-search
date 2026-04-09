from __future__ import annotations

import json
import re
from typing import Any, AsyncIterator

from playwright.async_api import Browser, Page

from ..models import Listing
from .base import BaseScraper, console, random_delay

# Santiago de Compostela rent URL
BASE_URL = "https://www.fotocasa.es/es/alquiler/viviendas/santiago-de-compostela/todas-las-zonas/l"

_BUILDING_TYPE_MAP = {
    "Flat": "flat",
    "House": "house",
    "Studio": "studio",
    "Duplex": "duplex",
}


def _extract_initial_props(html: str) -> dict | None:
    """Extract window.__INITIAL_PROPS__ JSON from page HTML."""
    scripts = re.findall(r'<script(?:[^>]*)>([\s\S]*?)</script>', html)
    for s in scripts:
        if "__INITIAL_PROPS__" in s:
            m = re.search(
                r'window\.__INITIAL_PROPS__\s*=\s*JSON\.parse\("((?:[^"\\]|\\.)*)"\)',
                s,
            )
            if m:
                try:
                    decoded = json.loads('"' + m.group(1) + '"')
                    return json.loads(decoded)
                except Exception:
                    pass
    return None


def _get_feature(features: list[dict], key: str) -> Any:
    for f in features:
        if f.get("key") == key:
            return f.get("value")
    return None


def _listing_from_raw(raw: dict) -> Listing | None:
    external_id = str(raw.get("id", ""))
    if not external_id:
        return None

    detail = raw.get("detail", {})
    path = detail.get("es-ES", "")
    url = f"https://www.fotocasa.es{path}" if path else ""
    if not url:
        return None

    price = raw.get("rawPrice")
    if not price:
        return None

    features = raw.get("features", [])
    rooms = _get_feature(features, "rooms")
    size_m2_raw = _get_feature(features, "surface")
    size_m2 = float(size_m2_raw) if size_m2_raw is not None else None
    bathrooms = _get_feature(features, "bathrooms")

    has_elevator_raw = _get_feature(features, "elevator")
    has_elevator = bool(has_elevator_raw) if has_elevator_raw is not None else None
    has_parking_raw = _get_feature(features, "parking")
    has_parking = bool(has_parking_raw) if has_parking_raw is not None else None
    has_terrace_raw = _get_feature(features, "terrace")
    has_terrace = bool(has_terrace_raw) if has_terrace_raw is not None else None
    has_garden_raw = _get_feature(features, "garden")
    has_garden = bool(has_garden_raw) if has_garden_raw is not None else None

    address_data = raw.get("address", {})
    district = address_data.get("district") or ""
    municipality = (address_data.get("municipality") or "").strip()
    address = f"{district}, {municipality}".strip(", ") if district or municipality else None
    neighborhood = district or None

    coords = raw.get("coordinates", {})
    latitude = coords.get("latitude")
    longitude = coords.get("longitude")
    if latitude == 0 and longitude == 0:
        latitude = longitude = None

    building_type = raw.get("buildingType", "")
    property_type = _BUILDING_TYPE_MAP.get(building_type, "flat")

    multimedia = raw.get("multimedia", [])
    image_urls = [
        m["src"] for m in multimedia if m.get("type") == "image" and m.get("src")
    ]

    # Build title
    building_subtype = raw.get("buildingSubtype") or building_type or "Piso"
    title = f"{building_subtype} en {address}" if address else f"{building_subtype} {external_id}"

    return Listing(
        source="fotocasa",
        external_id=external_id,
        url=url,
        title=title,
        price=float(price),
        size_m2=size_m2,
        rooms=int(rooms) if rooms is not None else None,
        bathrooms=int(bathrooms) if bathrooms is not None else None,
        address=address,
        neighborhood=neighborhood,
        latitude=latitude,
        longitude=longitude,
        image_urls=image_urls,
        has_elevator=has_elevator,
        has_parking=has_parking,
        has_terrace=has_terrace,
        has_garden=has_garden,
        property_type=property_type,
        description=raw.get("description"),
    )


class FotocasaScraper(BaseScraper):
    source = "fotocasa"

    def __init__(self, max_pages: int = 5, headless: bool = True):
        super().__init__(headless=headless)
        self.max_pages = max_pages

    async def scrape(self) -> AsyncIterator[Listing]:
        raise NotImplementedError("Use scrape_with_browser")

    async def scrape_with_browser(self, browser: Browser) -> AsyncIterator[Listing]:
        context = await self._new_context(browser)
        page = await self._new_page(context)

        try:
            # Load page 1 first to accept cookies
            console.print(f"[magenta]fotocasa[/magenta] Loading {BASE_URL}")
            await page.goto(BASE_URL, wait_until="networkidle", timeout=60000)
            await random_delay(2, 4)
            await self._accept_cookies(page)
            await random_delay(1, 2)

            for page_num in range(1, self.max_pages + 1):
                # Page 1 uses BASE_URL, subsequent pages append /N to the path
                if page_num > 1:
                    url = f"{BASE_URL}/{page_num}"
                    console.print(f"[magenta]fotocasa[/magenta] Loading page {page_num}")
                    await page.goto(url, wait_until="networkidle", timeout=60000)
                    await random_delay(2, 4)
                else:
                    console.print(f"[magenta]fotocasa[/magenta] Scraping page {page_num}")

                content = await page.content()
                listings = self._parse_page(content)

                if not listings:
                    console.print("[yellow]fotocasa[/yellow] No listings on this page, stopping.")
                    break

                for listing in listings:
                    yield listing

                await random_delay(1, 3)
        finally:
            await context.close()

    async def _accept_cookies(self, page: Page) -> None:
        for selector in [
            "#didomi-notice-agree-button",
            "button[aria-label*='Aceptar']",
            "button[id*='accept']",
            "[data-testid='cookiesAcceptAll']",
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
        props = _extract_initial_props(html)
        if not props:
            console.print("[yellow]fotocasa[/yellow] Could not extract __INITIAL_PROPS__")
            return []

        try:
            raw_listings = props["initialSearch"]["result"]["realEstates"]
        except (KeyError, TypeError):
            console.print("[yellow]fotocasa[/yellow] Could not find realEstates in data")
            return []

        listings = []
        for raw in raw_listings:
            try:
                listing = _listing_from_raw(raw)
                if listing:
                    listings.append(listing)
            except Exception as e:
                console.print(f"[yellow]fotocasa[/yellow] Error parsing listing: {e}")

        return listings
