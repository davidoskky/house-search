from __future__ import annotations

import json
from pathlib import Path

import pytest

from house_search.scrapers.fotocasa import (
    FotocasaScraper,
    _extract_initial_props,
    _get_feature,
    _listing_from_raw,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Minimal raw listing that mirrors the real Fotocasa JSON structure
# ---------------------------------------------------------------------------

def _raw_listing(**overrides) -> dict:
    base = {
        "id": 185476027,
        "buildingType": "Flat",
        "buildingSubtype": "Apartment",
        "rawPrice": 900,
        "price": "900 €",
        "detail": {"es-ES": "/es/alquiler/vivienda/santiago-de-compostela/calefaccion/185476027/d"},
        "address": {
            "district": "Ensanche - Sar",
            "municipality": "Santiago de Compostela ",
            "country": "España",
        },
        "coordinates": {"latitude": 42.875, "longitude": -8.549, "accuracy": 0},
        "features": [
            {"key": "rooms", "value": 3},
            {"key": "surface", "value": 80},
            {"key": "bathrooms", "value": 2},
            {"key": "elevator", "value": 13},
        ],
        "multimedia": [
            {"type": "image", "src": "https://static.fotocasa.es/images/ads/abc.jpg"},
            {"type": "youtube", "src": "https://youtu.be/xyz"},
        ],
        "description": "Apartamento luminoso en el centro.",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# _get_feature
# ---------------------------------------------------------------------------

class TestGetFeature:
    def test_returns_value_for_existing_key(self):
        features = [{"key": "rooms", "value": 3}, {"key": "surface", "value": 80}]
        assert _get_feature(features, "rooms") == 3

    def test_returns_none_for_missing_key(self):
        features = [{"key": "rooms", "value": 3}]
        assert _get_feature(features, "elevator") is None

    def test_empty_list_returns_none(self):
        assert _get_feature([], "rooms") is None


# ---------------------------------------------------------------------------
# _listing_from_raw
# ---------------------------------------------------------------------------

class TestListingFromRaw:
    def test_basic_fields_parsed(self):
        listing = _listing_from_raw(_raw_listing())
        assert listing is not None
        assert listing.source == "fotocasa"
        assert listing.external_id == "185476027"
        assert listing.price == 900.0

    def test_id_is_computed(self):
        listing = _listing_from_raw(_raw_listing())
        assert listing.id == "fotocasa:185476027"

    def test_rooms_parsed_from_features(self):
        listing = _listing_from_raw(_raw_listing())
        assert listing.rooms == 3

    def test_size_m2_parsed_from_surface_feature(self):
        listing = _listing_from_raw(_raw_listing())
        assert listing.size_m2 == 80.0

    def test_bathrooms_parsed(self):
        listing = _listing_from_raw(_raw_listing())
        assert listing.bathrooms == 2

    def test_elevator_truthy_feature(self):
        listing = _listing_from_raw(_raw_listing())
        assert listing.has_elevator is True

    def test_elevator_absent_feature_is_none(self):
        raw = _raw_listing()
        raw["features"] = [f for f in raw["features"] if f["key"] != "elevator"]
        listing = _listing_from_raw(raw)
        assert listing.has_elevator is None

    def test_url_is_absolute(self):
        listing = _listing_from_raw(_raw_listing())
        assert listing.url.startswith("https://www.fotocasa.es")

    def test_coordinates_extracted(self):
        listing = _listing_from_raw(_raw_listing())
        assert listing.latitude == pytest.approx(42.875)
        assert listing.longitude == pytest.approx(-8.549)

    def test_zero_coordinates_become_none(self):
        raw = _raw_listing(coordinates={"latitude": 0, "longitude": 0, "accuracy": 0})
        listing = _listing_from_raw(raw)
        assert listing.latitude is None
        assert listing.longitude is None

    def test_address_built_from_district_and_municipality(self):
        listing = _listing_from_raw(_raw_listing())
        assert "Ensanche" in listing.address
        assert "Santiago" in listing.address

    def test_only_image_urls_included(self):
        listing = _listing_from_raw(_raw_listing())
        assert len(listing.image_urls) == 1
        assert "youtube" not in listing.image_urls[0]

    def test_property_type_flat(self):
        listing = _listing_from_raw(_raw_listing(buildingType="Flat"))
        assert listing.property_type == "flat"

    def test_property_type_house(self):
        listing = _listing_from_raw(_raw_listing(buildingType="House"))
        assert listing.property_type == "house"

    def test_property_type_unknown_defaults_to_flat(self):
        listing = _listing_from_raw(_raw_listing(buildingType="Penthouse"))
        assert listing.property_type == "flat"

    def test_missing_id_returns_none(self):
        raw = _raw_listing()
        del raw["id"]
        assert _listing_from_raw(raw) is None

    def test_missing_price_returns_none(self):
        raw = _raw_listing(rawPrice=None)
        assert _listing_from_raw(raw) is None

    def test_missing_detail_returns_none(self):
        raw = _raw_listing()
        raw["detail"] = {}
        assert _listing_from_raw(raw) is None

    def test_price_per_room_computed(self):
        listing = _listing_from_raw(_raw_listing())
        assert listing.price_per_room == 300.0  # 900 / 3


# ---------------------------------------------------------------------------
# _extract_initial_props
# ---------------------------------------------------------------------------

def _wrap_in_page(props: dict) -> str:
    """Wrap a props dict in a minimal HTML page as Fotocasa would serve it."""
    raw = json.dumps(json.dumps(props, ensure_ascii=False))  # double-encode
    # Remove outer quotes that json.dumps adds, because we embed it as: JSON.parse("...")
    inner = raw[1:-1]  # strip surrounding double quotes
    return f"""<html><head></head><body>
<script>window.__INITIAL_PROPS__ = JSON.parse("{inner}");</script>
</body></html>"""


class TestExtractInitialProps:
    def test_extracts_props_from_page(self):
        props = {"initialSearch": {"result": {"realEstates": []}}}
        html = _wrap_in_page(props)
        result = _extract_initial_props(html)
        assert result is not None
        assert "initialSearch" in result

    def test_returns_none_when_absent(self):
        html = "<html><body><script>var x = 1;</script></body></html>"
        assert _extract_initial_props(html) is None

    def test_returns_none_on_invalid_json(self):
        html = '<script>window.__INITIAL_PROPS__ = JSON.parse("not valid json");</script>'
        assert _extract_initial_props(html) is None


class TestParsePage:
    def setup_method(self):
        self.scraper = FotocasaScraper()

    def test_parses_listings_from_page(self):
        props = {
            "initialSearch": {
                "result": {
                    "realEstates": [_raw_listing(), _raw_listing(id=999999, rawPrice=750)]
                }
            }
        }
        html = _wrap_in_page(props)
        listings = self.scraper._parse_page(html)
        assert len(listings) == 2

    def test_empty_real_estates_returns_empty_list(self):
        props = {"initialSearch": {"result": {"realEstates": []}}}
        html = _wrap_in_page(props)
        listings = self.scraper._parse_page(html)
        assert listings == []

    def test_missing_props_returns_empty_list(self):
        html = "<html><body></body></html>"
        listings = self.scraper._parse_page(html)
        assert listings == []

    def test_invalid_listing_skipped(self):
        # One valid listing and one missing rawPrice
        bad = _raw_listing(rawPrice=None)
        good = _raw_listing()
        props = {"initialSearch": {"result": {"realEstates": [bad, good]}}}
        html = _wrap_in_page(props)
        listings = self.scraper._parse_page(html)
        assert len(listings) == 1
        assert listings[0].price == 900.0
