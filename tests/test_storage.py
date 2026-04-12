from __future__ import annotations
from unittest.mock import MagicMock, patch

import sqlite_utils
import pytest

from house_search.models import Listing
from house_search.storage import geocode_missing, load_listings, save_listing, save_listings, update_listing_status


def _db() -> sqlite_utils.Database:
    """In-memory SQLite database for tests."""
    return sqlite_utils.Database(memory=True)


def _listing(**overrides) -> Listing:
    defaults = dict(
        source="idealista",
        external_id="10001",
        url="https://www.idealista.com/inmueble/10001/",
        title="Piso de prueba",
        price=700.0,
        rooms=2,
        size_m2=60.0,
    )
    defaults.update(overrides)
    return Listing(**defaults)


class TestSaveListing:
    def test_saves_to_db(self):
        db = _db()
        save_listing(_listing(), db)
        assert db["listings"].count == 1

    def test_upsert_overwrites_same_id(self):
        db = _db()
        save_listing(_listing(price=700.0), db)
        save_listing(_listing(price=800.0), db)  # same external_id
        assert db["listings"].count == 1
        row = list(db["listings"].rows)[0]
        assert row["price"] == 800.0

    def test_different_ids_both_saved(self):
        db = _db()
        save_listing(_listing(external_id="10001"), db)
        save_listing(_listing(external_id="10002"), db)
        assert db["listings"].count == 2

    def test_bool_fields_stored_as_int(self):
        db = _db()
        save_listing(_listing(has_elevator=True, has_parking=False), db)
        row = list(db["listings"].rows)[0]
        assert row["has_elevator"] == 1
        assert row["has_parking"] == 0

    def test_none_bool_stored_as_none(self):
        db = _db()
        save_listing(_listing(has_elevator=None), db)
        row = list(db["listings"].rows)[0]
        assert row["has_elevator"] is None

    def test_image_urls_stored_as_json(self):
        db = _db()
        save_listing(_listing(), db)
        row = list(db["listings"].rows)[0]
        import json
        assert json.loads(row["image_urls"]) == []

    def test_derived_computed_fields_not_stored(self):
        db = _db()
        save_listing(_listing(), db)
        row = list(db["listings"].rows)[0]
        assert "price_per_room" not in row
        assert "price_per_m2" not in row


class TestLoadListings:
    def test_load_returns_listings(self):
        db = _db()
        save_listing(_listing(), db)
        loaded = load_listings(db)
        assert len(loaded) == 1
        assert isinstance(loaded[0], Listing)

    def test_empty_db_returns_empty_list(self):
        db = _db()
        assert load_listings(db) == []

    def test_roundtrip_preserves_price(self):
        db = _db()
        save_listing(_listing(price=999.0), db)
        loaded = load_listings(db)
        assert loaded[0].price == 999.0

    def test_roundtrip_preserves_rooms(self):
        db = _db()
        save_listing(_listing(rooms=3), db)
        loaded = load_listings(db)
        assert loaded[0].rooms == 3

    def test_roundtrip_preserves_image_urls(self):
        db = _db()
        urls = ["https://example.com/a.jpg", "https://example.com/b.jpg"]
        save_listing(_listing(image_urls=urls), db)
        loaded = load_listings(db)
        assert loaded[0].image_urls == urls

    def test_roundtrip_restores_bool_fields(self):
        db = _db()
        save_listing(_listing(has_elevator=True, has_parking=False), db)
        loaded = load_listings(db)
        assert loaded[0].has_elevator is True
        assert loaded[0].has_parking is False

    def test_roundtrip_computed_id_correct(self):
        db = _db()
        listing = _listing(source="fotocasa", external_id="99999")
        save_listing(listing, db)
        loaded = load_listings(db)
        assert loaded[0].id == "fotocasa:99999"

    def test_roundtrip_computed_price_per_room(self):
        db = _db()
        save_listing(_listing(price=900.0, rooms=3), db)
        loaded = load_listings(db)
        assert loaded[0].price_per_room == 300.0

    def test_multiple_listings_roundtrip(self):
        db = _db()
        save_listings([
            _listing(external_id="A", price=500.0),
            _listing(external_id="B", price=800.0),
            _listing(source="fotocasa", external_id="C", price=1000.0),
        ], db)
        loaded = load_listings(db)
        assert len(loaded) == 3
        prices = {l.price for l in loaded}
        assert prices == {500.0, 800.0, 1000.0}


class TestListingStatus:
    def test_default_status_is_new(self):
        db = _db()
        save_listing(_listing(), db)
        row = list(db["listings"].rows)[0]
        assert row["status"] == "new"

    def test_update_status(self):
        db = _db()
        save_listing(_listing(), db)
        update_listing_status("idealista:10001", "to_call", db)
        row = list(db["listings"].rows)[0]
        assert row["status"] == "to_call"

    def test_status_preserved_on_rescrape(self):
        db = _db()
        save_listing(_listing(price=700.0), db)
        update_listing_status("idealista:10001", "discarded", db)
        # Re-scrape with updated price
        save_listing(_listing(price=750.0), db)
        row = list(db["listings"].rows)[0]
        assert row["status"] == "discarded"
        assert row["price"] == 750.0

    def test_new_status_overwritten_on_rescrape(self):
        """status='new' (default) should not block fresh saves."""
        db = _db()
        save_listing(_listing(price=700.0), db)
        save_listing(_listing(price=750.0), db)
        row = list(db["listings"].rows)[0]
        assert row["status"] == "new"
        assert row["price"] == 750.0

    def test_roundtrip_preserves_status(self):
        db = _db()
        save_listing(_listing(), db)
        update_listing_status("idealista:10001", "called", db)
        loaded = load_listings(db)
        assert loaded[0].status == "called"


class TestGeocodeEnsureIndexes:
    def test_ensure_indexes_creates_indexes(self):
        from house_search.storage import ensure_indexes, get_db
        db = _db()
        # Create schema first
        save_listing(_listing(), db)
        ensure_indexes(db)
        index_names = {idx.name for idx in db["listings"].indexes}
        assert "idx_price" in index_names
        assert "idx_rooms" in index_names
        assert "idx_coords" in index_names

    def test_ensure_indexes_idempotent(self):
        from house_search.storage import ensure_indexes
        db = _db()
        save_listing(_listing(), db)
        ensure_indexes(db)
        ensure_indexes(db)  # second call must not raise


class TestGeocodeMissing:
    def test_returns_zero_when_no_missing(self):
        db = _db()
        # Listing already has coordinates
        save_listing(_listing(), db)
        db.execute("UPDATE listings SET latitude = 42.88, longitude = -8.54 WHERE id = 'idealista:10001'")
        result = geocode_missing(db)
        assert result == 0

    def test_geocodes_listing_with_address_and_no_coords(self):
        from unittest.mock import MagicMock, patch
        db = _db()
        save_listing(_listing(address="Calle Mayor 1"), db)
        # latitude IS NULL (no coords saved) — confirm
        row = list(db.execute("SELECT latitude FROM listings").fetchall())
        assert row[0][0] is None

        mock_location = MagicMock()
        mock_location.latitude = 42.8805
        mock_location.longitude = -8.5457

        with patch("house_search.storage.RateLimiter") as mock_rl_cls:
            mock_geocode_fn = MagicMock(return_value=mock_location)
            mock_rl_cls.return_value = mock_geocode_fn
            result = geocode_missing(db)

        assert result == 1
        row = list(db.execute("SELECT latitude, longitude FROM listings").fetchall())
        # Column may be stored without type affinity in in-memory DB; cast to float
        assert float(row[0][0]) == pytest.approx(42.8805)
        assert float(row[0][1]) == pytest.approx(-8.5457)

    def test_skips_listing_without_address(self):
        db = _db()
        # No address field — should skip entirely
        save_listing(_listing(address=None), db)
        with patch("house_search.storage.RateLimiter") as mock_rl_cls:
            mock_rl_cls.return_value = MagicMock()
            result = geocode_missing(db)
        assert result == 0

    def test_skips_when_geocoder_returns_none(self):
        from unittest.mock import MagicMock, patch
        db = _db()
        save_listing(_listing(address="Lugar Inexistente 999"), db)
        with patch("house_search.storage.RateLimiter") as mock_rl_cls:
            mock_rl_cls.return_value = MagicMock(return_value=None)
            result = geocode_missing(db)
        assert result == 0
