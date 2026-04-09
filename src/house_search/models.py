from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class Listing(BaseModel):
    id: str  # source:external_id e.g. "idealista:12345"
    source: Literal["idealista", "fotocasa"]
    external_id: str
    url: str
    title: str
    price: float  # monthly rent in EUR
    size_m2: float | None = None
    rooms: int | None = None
    bathrooms: int | None = None
    floor: str | None = None  # "1", "bajo", "ático", etc.
    address: str | None = None
    neighborhood: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    description: str | None = None
    image_urls: list[str] = Field(default_factory=list)
    has_elevator: bool | None = None
    has_parking: bool | None = None
    has_terrace: bool | None = None
    has_garden: bool | None = None
    pets_allowed: bool | None = None
    property_type: Literal["flat", "house", "studio", "duplex", "other"] = "flat"
    scraped_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def price_per_room(self) -> float | None:
        if self.rooms and self.rooms > 0:
            return self.price / self.rooms
        return None

    @property
    def price_per_m2(self) -> float | None:
        if self.size_m2 and self.size_m2 > 0:
            return self.price / self.size_m2
        return None
