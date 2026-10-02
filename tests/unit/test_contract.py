from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from retail_data_platform.models import Availability, ProductObservation, SourceName

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def observation(**overrides: Any) -> ProductObservation:
    values: dict[str, Any] = {
        "source": SourceName.API,
        "source_product_id": "1",
        "product_name": "Mascara",
        "brand": "Essence",
        "category": "beauty",
        "price": Decimal("9.99"),
        "currency": "usd",
        "availability": Availability.IN_STOCK,
        "observed_at": NOW,
        "ingested_at": NOW,
        "raw_payload": {"id": 1},
    }
    values.update(overrides)
    return ProductObservation(**values)


def test_valid_observation_is_normalised() -> None:
    obs = observation(brand="  ", category="")
    assert obs.currency == "USD"
    assert obs.brand is None
    assert obs.category is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("price", Decimal("-0.01")),
        ("price", Decimal("1.001")),
        ("currency", "EURO"),
        ("product_name", ""),
        ("rating", Decimal("5.5")),
        ("product_url", "ftp://example.com/x"),
        ("observed_at", datetime(2026, 10, 1, 12, 0)),  # noqa: DTZ001 - naive is the point
    ],
)
def test_contract_violations_are_rejected(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        observation(**{field: value})


def test_observation_in_the_future_is_rejected() -> None:
    with pytest.raises(ValidationError, match="in the future"):
        observation(observed_at=NOW + timedelta(hours=2))
    # Small clock skew is tolerated.
    observation(observed_at=NOW + timedelta(minutes=30))


def test_unknown_fields_are_not_silently_accepted() -> None:
    with pytest.raises(ValidationError):
        observation(colour="red")


def test_record_hash_is_stable_within_a_day_and_changes_with_state() -> None:
    base = observation()
    same_day_later = observation(
        observed_at=NOW + timedelta(minutes=45), ingested_at=NOW + timedelta(hours=1)
    )
    next_day = observation(observed_at=NOW + timedelta(days=1), ingested_at=NOW + timedelta(days=1))
    new_price = observation(price=Decimal("8.99"))

    assert base.record_hash == same_day_later.record_hash
    assert base.record_hash != next_day.record_hash
    assert base.record_hash != new_price.record_hash
    assert len(base.record_hash) == 64


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("In Stock", Availability.IN_STOCK),
        ("in stock (22 available)", Availability.IN_STOCK),
        ("Low Stock", Availability.LOW_STOCK),
        ("Out of Stock", Availability.OUT_OF_STOCK),
        ("out_of_stock", Availability.OUT_OF_STOCK),
        ("", Availability.UNKNOWN),
        (None, Availability.UNKNOWN),
        ("backorder", Availability.UNKNOWN),
    ],
)
def test_availability_parsing(label: str | None, expected: Availability) -> None:
    assert Availability.parse(label) is expected
