"""DummyJSON Products API adapter (https://dummyjson.com/docs/products).

Public, unauthenticated, paginated with ``limit``/``skip``. Prices are in USD.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from retail_data_platform.ingestion.base import SourceRecord, SourceSchemaError
from retail_data_platform.ingestion.http import RetryingHttpClient
from retail_data_platform.models import Availability, ProductObservation, SourceName
from retail_data_platform.observability import get_logger

log = get_logger(__name__)

API_CURRENCY = "USD"


class DummyJsonPage(BaseModel):
    """Envelope of ``GET /products``. A mismatch here means the API contract changed."""

    model_config = ConfigDict(extra="allow")

    products: list[dict[str, Any]]
    total: int = Field(ge=0)
    skip: int = Field(ge=0)
    limit: int = Field(ge=0)


class DummyJsonProduct(BaseModel):
    """The subset of a DummyJSON product the platform relies on (extra fields are kept raw)."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: int
    title: str
    category: str
    price: Decimal
    brand: str | None = None
    rating: Decimal | None = None
    stock: int | None = None
    availability_status: str | None = Field(default=None, alias="availabilityStatus")


class DummyJsonAdapter:
    source = SourceName.API

    def __init__(
        self,
        http: RetryingHttpClient,
        *,
        base_url: str,
        page_size: int,
        max_pages: int,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._http = http
        self._base_url = base_url.rstrip("/")
        self._page_size = page_size
        self._max_pages = max_pages
        self._clock = clock

    def extract(self) -> Iterator[SourceRecord]:
        skip = 0
        for page_number in range(1, self._max_pages + 1):
            response = self._http.get(
                f"{self._base_url}/products", params={"limit": self._page_size, "skip": skip}
            )
            try:
                page = DummyJsonPage.model_validate(response.json())
            except (ValueError, ValidationError) as exc:
                raise SourceSchemaError(f"unexpected /products envelope: {exc}") from exc

            extracted_at = self._clock()
            for product in page.products:
                yield SourceRecord(
                    payload=product,
                    extracted_at=extracted_at,
                    source_url=str(response.url),
                    ref=str(product.get("id")),
                )
            log.debug("api.page", page=page_number, skip=skip, received=len(page.products))
            skip += len(page.products)
            if not page.products or skip >= page.total:
                return
        log.warning("api.max_pages_reached", max_pages=self._max_pages, next_skip=skip)

    def normalize(self, record: SourceRecord) -> ProductObservation:
        product = DummyJsonProduct.model_validate(record.payload)
        availability = Availability.parse(product.availability_status)
        if availability is Availability.UNKNOWN and product.stock is not None:
            availability = Availability.IN_STOCK if product.stock > 0 else Availability.OUT_OF_STOCK
        rating = (
            product.rating.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if product.rating is not None
            else None
        )
        return ProductObservation(
            source=self.source,
            source_product_id=str(product.id),
            product_name=product.title,
            brand=product.brand,
            category=product.category,
            price=product.price,
            currency=API_CURRENCY,
            availability=availability,
            rating=rating,
            product_url=f"{self._base_url}/products/{product.id}",
            observed_at=record.extracted_at,
            raw_payload=record.payload,
        )
