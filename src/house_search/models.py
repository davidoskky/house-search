from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator


class Listing(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source: Literal["idealista", "fotocasa"]
    external_id: str
    url: str
    title: str
    price: float = Field(gt=0, description="Monthly rent in EUR")
    size_m2: float | None = Field(default=None, gt=0)
    rooms: int | None = Field(default=None, ge=1)
    bathrooms: int | None = Field(default=None, ge=0)
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
    scraped_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @field_validator("external_id")
    @classmethod
    def external_id_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("external_id must not be empty")
        return v

    @computed_field  # type: ignore[prop-decorator]
    @property
    def id(self) -> str:
        """Stable unique key: source:external_id."""
        return f"{self.source}:{self.external_id}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def price_per_room(self) -> float | None:
        if self.rooms and self.rooms > 0:
            return round(self.price / self.rooms, 2)
        return None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def price_per_m2(self) -> float | None:
        if self.size_m2 and self.size_m2 > 0:
            return round(self.price / self.size_m2, 2)
        return None
