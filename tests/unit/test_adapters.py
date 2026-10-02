from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from retail_data_platform.config import Settings
from retail_data_platform.ingestion.api.dummyjson import DummyJsonAdapter
from retail_data_platform.ingestion.base import SourceRecord, SourceSchemaError
from retail_data_platform.ingestion.dataset.csv_adapter import CsvDatasetAdapter
from retail_data_platform.ingestion.http import AcquisitionError, build_http_client
from retail_data_platform.ingestion.pipeline import validate_records
from retail_data_platform.ingestion.registry import open_adapter
from retail_data_platform.ingestion.web.books_toscrape import BooksToScrapeAdapter
from retail_data_platform.models import Availability, SourceName

from ..conftest import DATASET_PATH, FIXED_NOW


def fixed_clock() -> datetime:
    return FIXED_NOW


# ------------------------------------------------------------------------------- API adapter
def test_api_adapter_paginates_until_total(make_settings: Callable[..., Settings]) -> None:
    settings = make_settings(api_page_size=20)
    with open_adapter(SourceName.API, settings) as (adapter, http):
        records = list(adapter.extract())
        assert http is not None
        assert http.request_count == 3  # 20 + 20 + 5
    assert len(records) == 45
    assert len({r.payload["id"] for r in records}) == 45
    assert records[0].source_url is not None
    assert "skip=0" in records[0].source_url


def test_api_adapter_respects_max_pages(make_settings: Callable[..., Settings]) -> None:
    with open_adapter(SourceName.API, make_settings(api_page_size=10, api_max_pages=2)) as (
        adapter,
        _,
    ):
        assert len(list(adapter.extract())) == 20


def test_api_adapter_normalises_products(
    fixtures_dir: Path, make_settings: Callable[..., Settings]
) -> None:
    products = json.loads((fixtures_dir / "dummyjson" / "products.json").read_text())["products"]
    adapter = DummyJsonAdapter(
        build_http_client(
            make_settings(), replay_transport=httpx.MockTransport(lambda r: httpx.Response(500))
        ),
        base_url="https://dummyjson.com",
        page_size=10,
        max_pages=1,
    )
    by_id = {p["id"]: p for p in products}

    mascara = adapter.normalize(SourceRecord(payload=by_id[1], extracted_at=FIXED_NOW))
    assert mascara.source is SourceName.API
    assert mascara.currency == "USD"
    assert mascara.price == Decimal("9.99")
    assert mascara.brand == "Essence"
    assert mascara.product_url == "https://dummyjson.com/products/1"
    assert mascara.raw_payload == by_id[1]

    apple = adapter.normalize(SourceRecord(payload=by_id[16], extracted_at=FIXED_NOW))
    assert apple.brand is None  # groceries have no brand in DummyJSON
    assert apple.availability is Availability.LOW_STOCK

    sold_out = adapter.normalize(SourceRecord(payload=by_id[127], extracted_at=FIXED_NOW))
    assert sold_out.availability is Availability.OUT_OF_STOCK


def test_api_envelope_change_aborts_the_run(make_settings: Callable[..., Settings]) -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"items": []}))
    adapter = DummyJsonAdapter(
        build_http_client(make_settings(), replay_transport=transport),
        base_url="https://dummyjson.com",
        page_size=10,
        max_pages=5,
    )
    with pytest.raises(SourceSchemaError):
        list(adapter.extract())


# ------------------------------------------------------------------------------- web adapter
def test_web_adapter_extracts_configured_categories(make_settings: Callable[..., Settings]) -> None:
    settings = make_settings(web_categories=["travel", "Mystery", "Does Not Exist"])
    with open_adapter(SourceName.WEB, settings) as (adapter, _):
        records = list(adapter.extract())
    categories = {r.payload["category"] for r in records}
    assert categories == {"Travel", "Mystery"}
    assert len(records) == 11 + 24


def test_web_adapter_bounds_pages_per_category(make_settings: Callable[..., Settings]) -> None:
    settings = make_settings(web_categories=["Mystery"], web_max_pages_per_category=1)
    with open_adapter(SourceName.WEB, settings) as (adapter, _):
        assert len(list(adapter.extract())) == 20


def test_web_adapter_normalises_listing(make_settings: Callable[..., Settings]) -> None:
    with open_adapter(SourceName.WEB, make_settings(web_categories=["Poetry"])) as (adapter, _):
        record = next(iter(adapter.extract()))
        obs = adapter.normalize(record)
    assert obs.source is SourceName.WEB
    assert obs.product_name == "A Light in the Attic"
    assert obs.currency == "GBP"
    assert obs.price == Decimal("51.77")
    assert obs.rating == Decimal(3)
    assert obs.category == "Poetry"
    assert obs.availability is Availability.IN_STOCK
    assert obs.source_product_id.startswith("a-light-in-the-attic_")


def test_web_adapter_honours_robots_txt(make_settings: Callable[..., Settings]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /\n")
        return httpx.Response(200, text="<html></html>")

    settings = make_settings()
    adapter = BooksToScrapeAdapter(
        build_http_client(settings, replay_transport=httpx.MockTransport(handler)),
        base_url="https://books.toscrape.com/",
        categories=["Travel"],
        max_pages_per_category=1,
        request_delay_seconds=0,
        user_agent=settings.http_user_agent,
    )
    with pytest.raises(AcquisitionError, match=r"robots\.txt"):
        list(adapter.extract())


# --------------------------------------------------------------------------- dataset adapter
def test_dataset_adapter_reads_every_row() -> None:
    records = list(CsvDatasetAdapter(DATASET_PATH, clock=fixed_clock).extract())
    assert len(records) == 62
    assert records[0].ref is not None
    assert records[0].ref.startswith("retail_products.csv:2:")


def test_dataset_invalid_rows_are_rejected_not_dropped() -> None:
    adapter = CsvDatasetAdapter(DATASET_PATH, clock=fixed_clock)
    valid, rejected = validate_records(adapter, list(adapter.extract()))
    assert len(valid) == 59
    assert len(rejected) == 3
    refs = {r.source_record_ref.split(":")[-1] for r in rejected if r.source_record_ref}
    assert refs == {"HE-9001", "NM-9002", "GG-9003"}
    assert all(r.errors for r in rejected)
    obs, _ = valid[0]
    assert obs.observed_at == datetime(2026, 9, 1, 9, 0, tzinfo=UTC)
    assert obs.raw_payload["source"] == "harbor_electronics"


def test_dataset_schema_drift_aborts(tmp_path: Path) -> None:
    broken = tmp_path / "broken.csv"
    broken.write_text("sku,name\n1,thing\n")
    with pytest.raises(SourceSchemaError, match="missing columns"):
        list(CsvDatasetAdapter(broken).extract())
    with pytest.raises(SourceSchemaError, match="not found"):
        list(CsvDatasetAdapter(tmp_path / "absent.csv").extract())


def test_duplicate_records_in_one_batch_are_collapsed() -> None:
    adapter = CsvDatasetAdapter(DATASET_PATH, clock=fixed_clock)
    records = list(adapter.extract())[:3]
    valid, rejected = validate_records(adapter, records + records)
    assert len(valid) == 3
    assert rejected == []
