from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from house_search.models import Listing


def make_listing(**overrides) -> Listing:
    defaults = dict(
        source="idealista",
        external_id="12345",
        url="https://www.idealista.com/inmueble/12345/",
        title="Piso en Calle Mayor",
        price=800.0,
    )
    defaults.update(overrides)
    return Listing(**defaults)


class TestComputedId:
    def test_id_is_source_colon_external_id(self):
        listing = make_listing(source="idealista", external_id="99999")
        assert listing.id == "idealista:99999"

    def test_id_fotocasa(self):
        listing = make_listing(source="fotocasa", external_id="185476027")
        assert listing.id == "fotocasa:185476027"

    def test_id_ignored_if_passed(self):
        # extra='ignore' means passing id= is silently discarded
        listing = make_listing(id="manual:override")
        assert listing.id == "idealista:12345"


class TestPriceComputed:
    def test_price_per_room_with_rooms(self):
        listing = make_listing(price=900.0, rooms=3)
        assert listing.price_per_room == 300.0

    def test_price_per_room_rounds(self):
        listing = make_listing(price=1000.0, rooms=3)
        assert listing.price_per_room == round(1000 / 3, 2)

    def test_price_per_room_none_when_no_rooms(self):
        listing = make_listing(price=900.0, rooms=None)
        assert listing.price_per_room is None

    def test_price_per_m2_with_size(self):
        listing = make_listing(price=900.0, size_m2=90.0)
        assert listing.price_per_m2 == 10.0

    def test_price_per_m2_none_when_no_size(self):
        listing = make_listing(price=900.0, size_m2=None)
        assert listing.price_per_m2 is None


class TestFieldValidation:
    def test_price_must_be_positive(self):
        with pytest.raises(ValidationError, match="price"):
            make_listing(price=0)

    def test_price_negative_rejected(self):
        with pytest.raises(ValidationError, match="price"):
            make_listing(price=-100)

    def test_rooms_must_be_at_least_1(self):
        with pytest.raises(ValidationError, match="rooms"):
            make_listing(rooms=0)

    def test_rooms_negative_rejected(self):
        with pytest.raises(ValidationError, match="rooms"):
            make_listing(rooms=-1)

    def test_size_m2_must_be_positive(self):
        with pytest.raises(ValidationError, match="size_m2"):
            make_listing(size_m2=0)

    def test_invalid_source_rejected(self):
        with pytest.raises(ValidationError, match="source"):
            make_listing(source="rightmove")

    def test_invalid_property_type_rejected(self):
        with pytest.raises(ValidationError, match="property_type"):
            make_listing(property_type="castle")

    def test_empty_external_id_rejected(self):
        with pytest.raises(ValidationError, match="external_id"):
            make_listing(external_id="  ")


class TestDefaults:
    def test_scraped_at_is_utc_aware(self):
        listing = make_listing()
        assert listing.scraped_at.tzinfo is not None
        assert listing.scraped_at.tzinfo == timezone.utc

    def test_image_urls_default_empty_list(self):
        listing = make_listing()
        assert listing.image_urls == []

    def test_property_type_default_flat(self):
        listing = make_listing()
        assert listing.property_type == "flat"

    def test_optional_fields_default_none(self):
        listing = make_listing()
        for field in ("size_m2", "rooms", "bathrooms", "floor", "address",
                      "neighborhood", "latitude", "longitude", "description",
                      "has_elevator", "has_parking", "has_terrace", "has_garden",
                      "pets_allowed"):
            assert getattr(listing, field) is None, f"{field} should be None"


class TestSerialisation:
    def test_model_dump_includes_computed_id(self):
        listing = make_listing()
        d = listing.model_dump()
        assert d["id"] == "idealista:12345"

    def test_model_dump_includes_price_per_room(self):
        listing = make_listing(price=900.0, rooms=3)
        d = listing.model_dump()
        assert d["price_per_room"] == 300.0

    def test_round_trip_via_model_validate(self):
        original = make_listing(
            price=750.0, rooms=1, size_m2=50.0,
            has_elevator=True, address="Calle Mayor 1",
        )
        data = original.model_dump()
        restored = Listing.model_validate(data)
        assert restored.price == original.price
        assert restored.rooms == original.rooms
        assert restored.id == original.id
        assert restored.price_per_room == original.price_per_room

    def test_extra_fields_ignored_on_construction(self):
        # Simulates loading a DB row that includes stored 'id' column
        listing = Listing(
            id="ignored:value",
            source="fotocasa",
            external_id="999",
            url="https://fotocasa.es/",
            title="Test",
            price=500.0,
        )
        assert listing.id == "fotocasa:999"
