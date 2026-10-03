"""Static retail CSV dataset adapter.

The file is versioned in the repository (``data/sample/retail_products.csv``) so the platform
always has a deterministic third source. The ``source`` column of the file identifies the
originating retailer/channel and is preserved in the raw payload as such.
"""

from __future__ import annotations

import csv
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from pydantic import AwareDatetime, BaseModel, ConfigDict, field_validator

from retail_data_platform.ingestion.base import SourceRecord, SourceSchemaError
from retail_data_platform.models import Availability, ProductObservation, SourceName

REQUIRED_COLUMNS = frozenset(
    {
        "source_product_id",
        "product_name",
        "brand",
        "category",
        "price",
        "currency",
        "availability",
        "source",
        "observed_at",
    }
)


class DatasetRow(BaseModel):
    """File-level schema: every value arrives as text and is coerced explicitly."""

    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)

    source_product_id: str
    product_name: str
    brand: str | None = None
    category: str | None = None
    price: Decimal
    currency: str
    availability: str | None = None
    source: str
    observed_at: AwareDatetime
    product_url: str | None = None
    rating: Decimal | None = None

    @field_validator("brand", "category", "availability", "product_url", "rating", mode="before")
    @classmethod
    def _empty_is_null(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("price", mode="before")
    @classmethod
    def _decimal(cls, value: object) -> object:
        if isinstance(value, str):
            try:
                return Decimal(value.strip())
            except InvalidOperation as exc:
                raise ValueError(f"price {value!r} is not a number") from exc
        return value


class CsvDatasetAdapter:
    source = SourceName.DATASET

    def __init__(
        self, path: Path, *, clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    ) -> None:
        self._path = path
        self._clock = clock

    def extract(self) -> Iterator[SourceRecord]:
        if not self._path.is_file():
            raise SourceSchemaError(f"dataset file not found: {self._path}")
        extracted_at = self._clock()
        with self._path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
            if missing:
                raise SourceSchemaError(f"dataset is missing columns: {sorted(missing)}")
            for line_number, row in enumerate(reader, start=2):
                yield SourceRecord(
                    payload={key: value for key, value in row.items() if key is not None},
                    extracted_at=extracted_at,
                    source_url=None,
                    ref=f"{self._path.name}:{line_number}:{row.get('source_product_id') or ''}",
                )

    def normalize(self, record: SourceRecord) -> ProductObservation:
        row = DatasetRow.model_validate(record.payload)
        return ProductObservation(
            source=self.source,
            source_product_id=row.source_product_id,
            product_name=row.product_name,
            brand=row.brand,
            category=row.category,
            price=row.price,
            currency=row.currency,
            availability=Availability.parse(row.availability),
            rating=row.rating,
            product_url=row.product_url,
            observed_at=row.observed_at,
            raw_payload=record.payload,
        )
