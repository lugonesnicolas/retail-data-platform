"""Builds configured adapters by source name."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from retail_data_platform.config import Settings, SourceMode
from retail_data_platform.ingestion.api.dummyjson import DummyJsonAdapter
from retail_data_platform.ingestion.base import SourceAdapter
from retail_data_platform.ingestion.dataset.csv_adapter import CsvDatasetAdapter
from retail_data_platform.ingestion.http import RetryingHttpClient, build_http_client
from retail_data_platform.ingestion.replay import books_toscrape_transport, dummyjson_transport
from retail_data_platform.ingestion.web.books_toscrape import BooksToScrapeAdapter
from retail_data_platform.models import SourceName


@contextmanager
def open_adapter(
    source: SourceName, settings: Settings
) -> Iterator[tuple[SourceAdapter, RetryingHttpClient | None]]:
    """Yield ``(adapter, http_client)``; the HTTP client (if any) is closed afterwards."""
    if source is SourceName.DATASET:
        yield CsvDatasetAdapter(settings.dataset_path), None
        return

    if source is SourceName.API:
        http = build_http_client(
            settings, replay_transport=dummyjson_transport(settings.fixtures_dir)
        )
        adapter: SourceAdapter = DummyJsonAdapter(
            http,
            base_url=settings.api_base_url,
            page_size=settings.api_page_size,
            max_pages=settings.api_max_pages,
        )
    else:
        http = build_http_client(
            settings, replay_transport=books_toscrape_transport(settings.fixtures_dir)
        )
        adapter = BooksToScrapeAdapter(
            http,
            base_url=settings.web_base_url,
            categories=settings.web_categories,
            max_pages_per_category=settings.web_max_pages_per_category,
            # No point being polite to a local fixture server.
            request_delay_seconds=0.0
            if settings.source_mode is SourceMode.REPLAY
            else settings.web_request_delay_seconds,
            user_agent=settings.http_user_agent,
        )
    with http:
        yield adapter, http
