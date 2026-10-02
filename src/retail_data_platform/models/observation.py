"""Canonical data contract for a single product observation.

Every acquisition adapter, regardless of where the data comes from, must produce
:class:`ProductObservation` instances. Anything that cannot be expressed in this contract is
rejected (and persisted to ``raw.rejected_records``) rather than silently dropped.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

#: Observations dated further than this into the future are considered clock/parsing errors.
FUTURE_TOLERANCE = timedelta(hours=1)


class SourceName(StrEnum):
    API = "api"
    WEB = "web"
    DATASET = "dataset"


class Availability(StrEnum):
    IN_STOCK = "in_stock"
    LOW_STOCK = "low_stock"
    OUT_OF_STOCK = "out_of_stock"
    UNKNOWN = "unknown"

    @classmethod
    def parse(cls, value: str | None) -> Availability:
        """Map free-text availability labels from any source onto the canonical enum."""
        if value is None:
            return cls.UNKNOWN
        text = " ".join(value.lower().replace("_", " ").replace("-", " ").split())
        if not text:
            return cls.UNKNOWN
        if text.startswith(("out of stock", "sold out", "unavailable")):
            return cls.OUT_OF_STOCK
        if text.startswith(("low stock", "limited")):
            return cls.LOW_STOCK
        if text.startswith(("in stock", "available")):
            return cls.IN_STOCK
        return cls.UNKNOWN


class ProductObservation(BaseModel):
    """One observation of one product's attributes at one point in time, from one source."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True, extra="forbid")

    source: SourceName
    source_product_id: str = Field(min_length=1, max_length=200)
    product_name: str = Field(min_length=1, max_length=500)
    brand: str | None = Field(default=None, max_length=200)
    category: str | None = Field(default=None, max_length=200)
    price: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    availability: Availability = Availability.UNKNOWN
    rating: Decimal | None = Field(default=None, ge=0, le=5, max_digits=3, decimal_places=2)
    product_url: str | None = Field(default=None, max_length=2000)
    observed_at: AwareDatetime
    ingested_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    raw_payload: dict[str, Any]

    @field_validator("brand", "category", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("currency", mode="before")
    @classmethod
    def _upper_currency(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("product_url")
    @classmethod
    def _http_url(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith(("http://", "https://")):
            raise ValueError("product_url must be an absolute http(s) URL")
        return value

    @model_validator(mode="after")
    def _not_in_future(self) -> ProductObservation:
        if self.observed_at > self.ingested_at + FUTURE_TOLERANCE:
            raise ValueError(
                f"observed_at {self.observed_at.isoformat()} is in the future "
                f"(ingested_at {self.ingested_at.isoformat()})"
            )
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def record_hash(self) -> str:
        """Deterministic identity of this observation, used for idempotent loading.

        The hash covers the business attributes plus the *calendar day* of observation, so:

        * re-running ingestion on the same day does not create duplicates;
        * a new day (or a changed price/availability) produces a new append-only observation.
        """
        identity = {
            "source": self.source.value,
            "source_product_id": self.source_product_id,
            "observed_date": self.observed_at.astimezone(UTC).date().isoformat(),
            "product_name": self.product_name,
            "brand": self.brand,
            "category": self.category,
            "price": str(self.price),
            "currency": self.currency,
            "availability": self.availability.value,
            "rating": None if self.rating is None else str(self.rating),
        }
        encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


class RejectedRecord(BaseModel):
    """A source record that failed the contract, kept for inspection instead of being dropped."""

    model_config = ConfigDict(frozen=True)

    source: SourceName
    source_record_ref: str | None
    raw_payload: dict[str, Any]
    errors: list[dict[str, Any]]
    source_url: str | None = None
