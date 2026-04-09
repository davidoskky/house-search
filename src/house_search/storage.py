from __future__ import annotations

import json
from pathlib import Path

import sqlite_utils

from .models import Listing

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
    return db


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
