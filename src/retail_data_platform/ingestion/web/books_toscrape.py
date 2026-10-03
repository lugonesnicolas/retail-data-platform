"""books.toscrape.com adapter.

books.toscrape.com is a sandbox explicitly built for scraping practice. The scraper still behaves
politely: it identifies itself, honours robots.txt when present, rate-limits itself and only
walks a bounded number of category listing pages.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from dataclasses import asdict
from datetime import UTC, datetime
from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser

from retail_data_platform.ingestion.base import SourceRecord, SourceSchemaError
from retail_data_platform.ingestion.http import AcquisitionError, RetryingHttpClient
from retail_data_platform.ingestion.web.parser import (
    PageStructureError,
    parse_category_links,
    parse_category_page,
    parse_price,
    parse_rating,
    product_slug,
)
from retail_data_platform.models import Availability, ProductObservation, SourceName
from retail_data_platform.observability import get_logger

log = get_logger(__name__)


class BooksToScrapeAdapter:
    source = SourceName.WEB

    def __init__(
        self,
        http: RetryingHttpClient,
        *,
        base_url: str,
        categories: list[str],
        max_pages_per_category: int,
        request_delay_seconds: float,
        user_agent: str,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._http = http
        self._base_url = base_url if base_url.endswith("/") else f"{base_url}/"
        self._categories = categories
        self._max_pages = max_pages_per_category
        self._delay = request_delay_seconds
        self._user_agent = user_agent
        self._clock = clock
        self._sleep = sleep
        self._robots: RobotFileParser | None = None

    # ----------------------------------------------------------------------------- helpers
    def _load_robots(self) -> RobotFileParser:
        parser = RobotFileParser()
        try:
            response = self._http.get(urljoin(self._base_url, "robots.txt"))
            parser.parse(response.text.splitlines())
        except AcquisitionError as exc:
            if exc.status_code not in (404, 410):
                raise
            # No robots.txt means the site published no restrictions.
            parser.parse([])
        return parser

    def _fetch(self, url: str) -> str:
        if self._robots is None:
            self._robots = self._load_robots()
        if not self._robots.can_fetch(self._user_agent, url):
            raise AcquisitionError(f"robots.txt disallows {url}")
        response = self._http.get(url)
        if self._delay:
            self._sleep(self._delay)
        return response.text

    # ------------------------------------------------------------------------------ adapter
    def extract(self) -> Iterator[SourceRecord]:
        home_url = urljoin(self._base_url, "index.html")
        try:
            available = parse_category_links(self._fetch(home_url), home_url)
        except PageStructureError as exc:
            raise SourceSchemaError(f"home page structure changed: {exc}") from exc

        by_lower = {name.lower(): (name, url) for name, url in available.items()}
        for wanted in self._categories:
            match = by_lower.get(wanted.lower())
            if match is None:
                log.warning("web.category_missing", category=wanted)
                continue
            category, url = match
            yield from self._extract_category(category, url)

    def _extract_category(self, category: str, first_page_url: str) -> Iterator[SourceRecord]:
        page_url: str | None = first_page_url
        pages = 0
        while page_url is not None and pages < self._max_pages:
            pages += 1
            try:
                page = parse_category_page(self._fetch(page_url), page_url)
            except PageStructureError as exc:
                raise SourceSchemaError(f"category page {page_url} changed: {exc}") from exc
            extracted_at = self._clock()
            for book in page.books:
                yield SourceRecord(
                    payload={**asdict(book), "category": page.category},
                    extracted_at=extracted_at,
                    source_url=page_url,
                    ref=book.product_url,
                )
            log.debug("web.page", category=category, page=pages, books=len(page.books))
            page_url = page.next_page_url

    def normalize(self, record: SourceRecord) -> ProductObservation:
        payload = record.payload
        price, currency = parse_price(str(payload.get("price_text", "")))
        product_url = str(payload["product_url"])
        return ProductObservation(
            source=self.source,
            source_product_id=product_slug(product_url),
            product_name=payload.get("title", ""),
            brand=None,  # books.toscrape listings have no brand/publisher attribute
            category=payload.get("category"),
            price=price,
            currency=currency,
            availability=Availability.parse(payload.get("availability_text")),
            rating=parse_rating(payload.get("rating_text")),
            product_url=product_url,
            observed_at=record.extracted_at,
            raw_payload=payload,
        )
