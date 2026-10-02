"""Opt-in checks against the real third-party sites (excluded by default).

    uv run pytest -m live tests/live

They detect upstream contract drift (API envelope, HTML structure) that fixtures cannot. They are
not part of CI so builds never depend on someone else's uptime.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from retail_data_platform.config import Settings, SourceMode
from retail_data_platform.ingestion.pipeline import validate_records
from retail_data_platform.ingestion.registry import open_adapter
from retail_data_platform.models import SourceName

pytestmark = pytest.mark.live


@pytest.mark.parametrize("source", [SourceName.API, SourceName.WEB])
def test_live_source_still_matches_contract(
    make_settings: Callable[..., Settings], source: SourceName
) -> None:
    settings = make_settings(
        source_mode=SourceMode.LIVE,
        api_page_size=10,
        api_max_pages=1,
        web_categories=["Travel"],
        web_max_pages_per_category=1,
        web_request_delay_seconds=1.0,
    )
    with open_adapter(source, settings) as (adapter, _):
        records = list(adapter.extract())
        valid, rejected = validate_records(adapter, records)
    assert records, "source returned no records"
    assert len(rejected) / len(records) <= settings.max_reject_ratio, rejected[:3]
    assert valid
