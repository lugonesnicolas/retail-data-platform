from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from retail_data_platform.ingestion.web.parser import (
    PageStructureError,
    parse_category_links,
    parse_category_page,
    parse_price,
    parse_rating,
    product_slug,
)

BASE = "https://books.toscrape.com/"
CATEGORY_DIR = "catalogue/category/books"


def read(fixtures_dir: Path, relative: str) -> str:
    return (fixtures_dir / "books_toscrape" / relative).read_text("utf-8")


def test_parses_category_navigation(fixtures_dir: Path) -> None:
    links = parse_category_links(read(fixtures_dir, "index.html"), BASE + "index.html")
    assert "Books" not in links  # the parent "Books" entry is not a category
    assert links["Travel"] == f"{BASE}{CATEGORY_DIR}/travel_2/index.html"
    assert {"Mystery", "Poetry", "Science", "Business"} <= links.keys()


def test_parses_listing_page(fixtures_dir: Path) -> None:
    url = f"{BASE}{CATEGORY_DIR}/travel_2/index.html"
    page = parse_category_page(read(fixtures_dir, f"{CATEGORY_DIR}/travel_2/index.html"), url)

    assert page.category == "Travel"
    assert len(page.books) == 11
    assert page.next_page_url is None
    first = page.books[0]
    assert first.title == "It's Only the Himalayas"
    assert first.price_text == "£45.17"
    assert first.availability_text == "In stock"
    assert first.rating_text == "Two"
    assert first.product_url.startswith(f"{BASE}catalogue/it-s-only-the-himalayas_")
    # Long titles are truncated in the link text; the full title comes from the attribute.
    assert any(b.title.startswith("Full Moon over Noah") and len(b.title) > 40 for b in page.books)


def test_follows_pagination(fixtures_dir: Path) -> None:
    url = f"{BASE}{CATEGORY_DIR}/mystery_3/index.html"
    first = parse_category_page(read(fixtures_dir, f"{CATEGORY_DIR}/mystery_3/index.html"), url)
    assert len(first.books) == 20
    assert first.next_page_url == f"{BASE}{CATEGORY_DIR}/mystery_3/page-2.html"

    second = parse_category_page(
        read(fixtures_dir, f"{CATEGORY_DIR}/mystery_3/page-2.html"), first.next_page_url
    )
    assert len(second.books) == 4
    assert second.next_page_url is None


def test_structure_change_is_detected() -> None:
    with pytest.raises(PageStructureError):
        parse_category_page("<html><body><p>Maintenance</p></body></html>", BASE)
    with pytest.raises(PageStructureError):
        parse_category_links("<html></html>", BASE)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("£51.77", (Decimal("51.77"), "GBP")),
        ("Â£51.77", (Decimal("51.77"), "GBP")),  # mis-decoded UTF-8 seen in the wild
        ("$ 10", (Decimal("10"), "USD")),
        ("€9,50", (Decimal("9.50"), "EUR")),
    ],
)
def test_price_parsing(text: str, expected: tuple[Decimal, str]) -> None:
    assert parse_price(text) == expected


def test_unparseable_values_raise() -> None:
    with pytest.raises(ValueError, match="price"):
        parse_price("call for price")
    with pytest.raises(ValueError, match="rating"):
        parse_rating("Eleven")


def test_rating_and_slug() -> None:
    assert parse_rating("Four") == Decimal(4)
    assert parse_rating(None) is None
    assert product_slug(f"{BASE}catalogue/a-light-in-the-attic_1000/index.html") == (
        "a-light-in-the-attic_1000"
    )
