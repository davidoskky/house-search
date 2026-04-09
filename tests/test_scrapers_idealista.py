from __future__ import annotations

from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from house_search.scrapers.idealista import (
    IdealistaScraper,
    _parse_float,
    _parse_int,
    _parse_price,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Parser helpers
# ---------------------------------------------------------------------------

class TestParsePrice:
    def test_standard_format(self):
        assert _parse_price("750€/mes") == 750.0

    def test_with_thousands_dot(self):
        assert _parse_price("1.200€/mes") == 1200.0

    def test_with_spaces(self):
        assert _parse_price("900 €/mes") == 900.0

    def test_empty_returns_none(self):
        assert _parse_price("") is None

    def test_no_digits_returns_none(self):
        assert _parse_price("precio a consultar") is None


class TestParseInt:
    def test_extracts_leading_number(self):
        assert _parse_int("3 hab.") == 3

    def test_single_digit(self):
        assert _parse_int("1 baño") == 1

    def test_no_digits_returns_none(self):
        assert _parse_int("sin hab.") is None


class TestParseFloat:
    def test_whole_number(self):
        assert _parse_float("70 m²") == 70.0

    def test_decimal_comma(self):
        assert _parse_float("85,5 m²") == 85.5

    def test_no_digits_returns_none(self):
        assert _parse_float("desconocido") is None


# ---------------------------------------------------------------------------
# Article parsing
# ---------------------------------------------------------------------------

def _load_fixture_article():
    html = (FIXTURE_DIR / "idealista_article.html").read_text()
    soup = BeautifulSoup(html, "html.parser")
    return soup.select_one("article")


class TestParseArticle:
    def setup_method(self):
        self.scraper = IdealistaScraper()
        self.article = _load_fixture_article()

    def test_external_id_from_data_attribute(self):
        listing = self.scraper._parse_article(self.article)
        assert listing is not None
        assert listing.external_id == "111147946"

    def test_id_is_computed(self):
        listing = self.scraper._parse_article(self.article)
        assert listing.id == "idealista:111147946"

    def test_price_parsed(self):
        listing = self.scraper._parse_article(self.article)
        assert listing.price == 750.0

    def test_rooms_parsed(self):
        listing = self.scraper._parse_article(self.article)
        assert listing.rooms == 1

    def test_size_m2_parsed(self):
        listing = self.scraper._parse_article(self.article)
        assert listing.size_m2 == 70.0

    def test_title_from_title_attribute(self):
        listing = self.scraper._parse_article(self.article)
        assert "Piso en Calle da República" in listing.title

    def test_url_is_absolute(self):
        listing = self.scraper._parse_article(self.article)
        assert listing.url.startswith("https://www.idealista.com")

    def test_floor_parsed(self):
        listing = self.scraper._parse_article(self.article)
        assert listing.floor is not None
        assert "2ª" in listing.floor or "Planta" in listing.floor

    def test_has_elevator_from_floor_text(self):
        listing = self.scraper._parse_article(self.article)
        assert listing.has_elevator is True

    def test_image_url_extracted(self):
        listing = self.scraper._parse_article(self.article)
        assert len(listing.image_urls) == 1
        assert listing.image_urls[0].startswith("https://")

    def test_source_is_idealista(self):
        listing = self.scraper._parse_article(self.article)
        assert listing.source == "idealista"

    def test_price_per_room_computed(self):
        listing = self.scraper._parse_article(self.article)
        assert listing.price_per_room == 750.0  # 750 / 1 room

    def test_article_without_price_returns_none(self):
        html = """<article class="item" data-element-id="999">
          <a class="item-link" href="/inmueble/999/" title="Sin precio">Sin precio</a>
        </article>"""
        soup = BeautifulSoup(html, "html.parser")
        article = soup.select_one("article")
        result = self.scraper._parse_article(article)
        assert result is None

    def test_article_without_link_returns_none(self):
        html = """<article class="item" data-element-id="999">
          <span class="item-price">500€/mes</span>
        </article>"""
        soup = BeautifulSoup(html, "html.parser")
        article = soup.select_one("article")
        result = self.scraper._parse_article(article)
        assert result is None


class TestParseListingsPage:
    def setup_method(self):
        self.scraper = IdealistaScraper()

    def test_parses_single_article(self):
        html = (FIXTURE_DIR / "idealista_article.html").read_text()
        listings = self.scraper._parse_listings_page(html)
        assert len(listings) == 1
        assert listings[0].external_id == "111147946"

    def test_empty_page_returns_empty_list(self):
        listings = self.scraper._parse_listings_page("<html><body></body></html>")
        assert listings == []

    def test_multiple_articles(self):
        article_html = (FIXTURE_DIR / "idealista_article.html").read_text()
        # Create a second article with a different id
        article2 = article_html.replace("111147946", "222222222").replace("750", "900")
        page_html = f"<html><body>{article_html}{article2}</body></html>"
        listings = self.scraper._parse_listings_page(page_html)
        assert len(listings) == 2
        ids = {l.external_id for l in listings}
        assert ids == {"111147946", "222222222"}
