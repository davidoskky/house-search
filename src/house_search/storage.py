from __future__ import annotations

import json
import logging
from pathlib import Path

import sqlite_utils
from geopy.extra.rate_limiter import RateLimiter
from geopy.geocoders import Nominatim

from .models import Listing

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent.parent / "data" / "listings.db"


def get_db() -> sqlite_utils.Database:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite_utils.Database(DB_PATH)
    if "listings" not in db.table_names():
        db["listings"].create(
            {
                "id": str,
                "source": str,
                "external_id": str,
                "url": str,
                "title": str,
                "price": float,
                "size_m2": float,
                "rooms": int,
                "bathrooms": int,
                "floor": str,
                "address": str,
                "neighborhood": str,
                "latitude": float,
                "longitude": float,
                "description": str,
                "image_urls": str,  # JSON
                "has_elevator": int,
                "has_parking": int,
                "has_terrace": int,
                "has_garden": int,
                "pets_allowed": int,
                "property_type": str,
                "scraped_at": str,
            },
            pk="id",
        )
    ensure_indexes(db)
    return db


def ensure_indexes(db: sqlite_utils.Database) -> None:
    """Create indexes on frequently filtered columns (idempotent)."""
    if "listings" not in db.table_names():
        return
    existing = {idx.name for idx in db["listings"].indexes}
    wanted = {
        "idx_price": ["price"],
        "idx_rooms": ["rooms"],
        "idx_neighborhood": ["neighborhood"],
        "idx_coords": ["latitude", "longitude"],
        "idx_source": ["source"],
    }
    for name, cols in wanted.items():
        if name not in existing:
            db["listings"].create_index(cols, index_name=name, if_not_exists=True)


def save_listing(listing: Listing, db: sqlite_utils.Database | None = None) -> None:
    if db is None:
        db = get_db()
    # Exclude derived computed fields not persisted to DB
    row = listing.model_dump(exclude={"price_per_room", "price_per_m2"})
    row["image_urls"] = json.dumps(row["image_urls"])
    row["scraped_at"] = row["scraped_at"].isoformat()
    # bool -> int for SQLite
    for field in ("has_elevator", "has_parking", "has_terrace", "has_garden", "pets_allowed"):
        if row[field] is not None:
            row[field] = int(row[field])
    db["listings"].upsert(row, pk="id")


def save_listings(listings: list[Listing], db: sqlite_utils.Database | None = None) -> None:
    if db is None:
        db = get_db()
    for listing in listings:
        save_listing(listing, db)


def load_listings(db: sqlite_utils.Database | None = None) -> list[Listing]:
    if db is None:
        db = get_db()
    if "listings" not in db.table_names():
        return []
    rows = list(db["listings"].rows)
    listings = []
    for row in rows:
        row["image_urls"] = json.loads(row["image_urls"] or "[]")
        for field in ("has_elevator", "has_parking", "has_terrace", "has_garden", "pets_allowed"):
            if row[field] is not None:
                row[field] = bool(row[field])
        listings.append(Listing(**row))
    return listings


def geocode_missing(db: sqlite_utils.Database | None = None) -> int:
    """Geocode listings that have an address but no coordinates.

    Uses Nominatim (OpenStreetMap) with a 1 req/s rate limit.
    Returns the number of listings successfully geocoded.
    """
    if db is None:
        db = get_db()
    if "listings" not in db.table_names():
        return 0

    rows = list(db.execute(
        "SELECT id, address FROM listings WHERE latitude IS NULL AND address IS NOT NULL"
    ).fetchall())

    if not rows:
        return 0

    geolocator = Nominatim(user_agent="house-search/1.0")
    geocode = RateLimiter(geolocator.geocode, min_delay_seconds=1)

    geocoded = 0
    for row_id, address in rows:
        # Append city for better accuracy
        query = f"{address}, Santiago de Compostela, Spain"
        try:
            location = geocode(query)
        except Exception as exc:
            logger.warning("Geocoding error for %r: %s", address, exc)
            continue

        if location is None:
            logger.debug("No result for %r", address)
            continue

        db.execute(
            "UPDATE listings SET latitude = ?, longitude = ? WHERE id = ?",
            [location.latitude, location.longitude, row_id],
        )
        geocoded += 1
        logger.info("Geocoded %s → (%.4f, %.4f)", row_id, location.latitude, location.longitude)

    return geocoded
