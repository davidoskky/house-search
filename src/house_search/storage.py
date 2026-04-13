from __future__ import annotations

import json
import logging
import math
from pathlib import Path

import sqlite_utils
from geopy.extra.rate_limiter import RateLimiter
from geopy.geocoders import Nominatim

from .models import Listing

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent.parent / "data" / "listings.db"


def get_db() -> sqlite_utils.Database:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite_utils.Database(DB_PATH, timeout=30)
    db.conn.execute("PRAGMA journal_mode=WAL")
    db.conn.execute("PRAGMA synchronous=NORMAL")
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
                "phone": str,
                "image_urls": str,  # JSON
                "has_elevator": int,
                "has_parking": int,
                "has_terrace": int,
                "has_garden": int,
                "pets_allowed": int,
                "property_type": str,
                "status": str,
                "favorite": int,
                "comments": str,
                "scraped_at": str,
                "duplicate_of": str,
            },
            pk="id",
        )
    # Migrate existing DBs: add columns introduced after initial schema
    if "listings" in db.table_names():
        existing_cols = {c.name for c in db["listings"].columns}
        migrations = [
            ("phone",        "TEXT"),
            ("status",       "TEXT DEFAULT 'new'"),
            ("duplicate_of", "TEXT"),
            ("favorite",     "INTEGER DEFAULT 0"),
            ("comments",     "TEXT"),
        ]
        for col, col_def in migrations:
            if col not in existing_cols:
                db.execute(f"ALTER TABLE listings ADD COLUMN {col} {col_def}")

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
        "idx_status": ["status"],
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
    # Preserve user-set fields across re-scrapes
    if "listings" in db.table_names():
        existing = db.execute(
            "SELECT status, duplicate_of, favorite, comments FROM listings WHERE id = ?",
            [row["id"]],
        ).fetchone()
        if existing:
            if existing[0] and existing[0] != "new":
                row["status"] = existing[0]
            if existing[1]:
                row["duplicate_of"] = existing[1]
            if existing[2]:
                row["favorite"] = existing[2]
            if existing[3]:
                row["comments"] = existing[3]
    db["listings"].upsert(row, pk="id", alter=True)


def save_listings(listings: list[Listing], db: sqlite_utils.Database | None = None) -> None:
    if db is None:
        db = get_db()
    for listing in listings:
        save_listing(listing, db)


def update_listing_status(
    listing_id: str,
    status: str,
    db: sqlite_utils.Database | None = None,
) -> None:
    """Update status for a listing and all members of its duplicate group."""
    if db is None:
        db = get_db()

    # Find the canonical ID for this listing
    row = db.execute(
        "SELECT duplicate_of FROM listings WHERE id = ?", [listing_id]
    ).fetchone()
    canonical_id = row[0] if row and row[0] else listing_id

    # Update the canonical and every listing that points to it
    db.execute("UPDATE listings SET status = ? WHERE id = ?", [status, canonical_id])
    db.execute("UPDATE listings SET status = ? WHERE duplicate_of = ?", [status, canonical_id])
    db.conn.commit()


def toggle_favorite(
    listing_id: str,
    db: sqlite_utils.Database | None = None,
) -> bool:
    """Toggle the favorite flag. Returns the new value."""
    if db is None:
        db = get_db()
    row = db.execute("SELECT favorite FROM listings WHERE id = ?", [listing_id]).fetchone()
    new_value = 0 if (row and row[0]) else 1
    db.execute("UPDATE listings SET favorite = ? WHERE id = ?", [new_value, listing_id])
    db.conn.commit()
    return bool(new_value)


def update_comments(
    listing_id: str,
    comments: str,
    db: sqlite_utils.Database | None = None,
) -> None:
    """Save free-text comments for a listing."""
    if db is None:
        db = get_db()
    db.execute("UPDATE listings SET comments = ? WHERE id = ?", [comments or None, listing_id])
    db.conn.commit()


def _deserialise_row(row: dict) -> Listing:
    row["image_urls"] = json.loads(row["image_urls"] or "[]")
    for field in ("has_elevator", "has_parking", "has_terrace", "has_garden", "pets_allowed", "favorite"):
        if row.get(field) is not None:
            row[field] = bool(row[field])
    return Listing(**row)


def load_listings(
    db: sqlite_utils.Database | None = None,
    include_duplicates: bool = False,
) -> list[Listing]:
    if db is None:
        db = get_db()
    if "listings" not in db.table_names():
        return []
    rows = list(db["listings"].rows)
    listings = []
    for row in rows:
        if not include_duplicates and row.get("duplicate_of"):
            continue
        listings.append(_deserialise_row(row))
    return listings


def _coord_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Approximate distance in metres between two points (flat-earth, good for <1 km)."""
    dlat = (lat2 - lat1) * 111_000
    dlon = (lon2 - lon1) * 111_000 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.sqrt(dlat ** 2 + dlon ** 2)


def _is_duplicate(candidate: Listing, canonical: Listing) -> bool:
    """Return True if *candidate* looks like the same property as *canonical*."""
    # Strong signal: same non-empty phone number
    if candidate.phone and canonical.phone and candidate.phone == canonical.phone:
        return True

    # Weaker signal: matching key features
    price_ok = (
        candidate.price is not None
        and canonical.price is not None
        and abs(candidate.price - canonical.price) / canonical.price <= 0.03
    )
    rooms_ok = candidate.rooms is not None and candidate.rooms == canonical.rooms
    size_ok = (
        candidate.size_m2 is not None
        and canonical.size_m2 is not None
        and abs(candidate.size_m2 - canonical.size_m2) / canonical.size_m2 <= 0.05
    )

    if not (price_ok and rooms_ok and size_ok):
        return False

    # Need at least one location signal to avoid false positives
    coords_ok = (
        candidate.latitude is not None
        and candidate.longitude is not None
        and canonical.latitude is not None
        and canonical.longitude is not None
        and _coord_distance_m(
            candidate.latitude, candidate.longitude,
            canonical.latitude, canonical.longitude,
        ) <= 200
    )
    neighborhood_ok = (
        candidate.neighborhood
        and canonical.neighborhood
        and candidate.neighborhood.lower() == canonical.neighborhood.lower()
    )
    return bool(coords_ok or neighborhood_ok)


def deduplicate_listings(db: sqlite_utils.Database | None = None) -> int:
    """Mark duplicate listings in the database.

    A listing is a duplicate if it matches an earlier listing by phone number,
    or by (price ±3%, rooms, size ±5%) plus location proximity / same neighbourhood.

    The canonical listing is the earliest-scraped one among a group.
    Returns the number of listings newly marked as duplicates.
    """
    if db is None:
        db = get_db()
    if "listings" not in db.table_names():
        return 0

    # Reset all duplicate marks so we recompute from scratch each run
    db.execute("UPDATE listings SET duplicate_of = NULL")
    db.conn.commit()

    # Load all listings ordered by scraped_at so the earliest becomes canonical
    rows = list(db.execute(
        "SELECT * FROM listings ORDER BY scraped_at ASC"
    ).fetchall())
    columns = [desc[0] for desc in db.execute("SELECT * FROM listings LIMIT 0").description]

    canonical: list[Listing] = []
    newly_marked = 0

    for raw in rows:
        row = dict(zip(columns, raw))
        listing = _deserialise_row(row)

        matched_id: str | None = None
        for canon in canonical:
            if listing.id == canon.id:
                break  # same listing, skip
            if _is_duplicate(listing, canon):
                matched_id = canon.id
                break

        if matched_id:
            db.execute(
                "UPDATE listings SET duplicate_of = ? WHERE id = ?",
                [matched_id, listing.id],
            )
            newly_marked += 1
        else:
            canonical.append(listing)

    db.conn.commit()
    return newly_marked


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
        db.conn.commit()
        geocoded += 1
        logger.info("Geocoded %s → (%.4f, %.4f)", row_id, location.latitude, location.longitude)

    return geocoded
