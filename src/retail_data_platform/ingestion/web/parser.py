"""Pure HTML parsing for books.toscrape.com pages (no I/O, fully fixture-testable)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

RATING_WORDS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
CURRENCY_SYMBOLS = {"£": "GBP", "$": "USD", "€": "EUR"}
_PRICE_RE = re.compile(r"(?P<symbol>[£$€])\s*(?P<amount>\d+(?:[.,]\d{1,2})?)")


class PageStructureError(ValueError):
    """The page does not have the structure the scraper relies on."""


@dataclass(frozen=True, slots=True)
class BookListing:
    title: str
    product_url: str
    price_text: str
    availability_text: str
    rating_text: str | None
    image_url: str | None


@dataclass(frozen=True, slots=True)
class CategoryPage:
    category: str
    books: list[BookListing]
    next_page_url: str | None


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def parse_category_links(html: str, page_url: str) -> dict[str, str]:
    """Return ``{category name: absolute url}`` from the sidebar of the home page."""
    nav = _soup(html).select_one("div.side_categories ul.nav-list ul")
    if nav is None:
        raise PageStructureError("category navigation not found")
    links: dict[str, str] = {}
    for anchor in nav.select("li > a[href]"):
        name = " ".join(anchor.get_text().split())
        if name:
            links[name] = urljoin(page_url, str(anchor["href"]))
    return links


def _text(node: Tag | None) -> str:
    return " ".join(node.get_text().split()) if node is not None else ""


def parse_category_page(html: str, page_url: str) -> CategoryPage:
    soup = _soup(html)
    header = soup.select_one("div.page-header h1")
    if header is None:
        raise PageStructureError("category header not found")

    books: list[BookListing] = []
    for pod in soup.select("article.product_pod"):
        anchor = pod.select_one("h3 > a[href]")
        if anchor is None:
            raise PageStructureError("product_pod without title link")
        rating_node = pod.select_one("p.star-rating")
        rating_classes = (
            [c for c in (rating_node.get("class") or []) if c != "star-rating"]
            if rating_node
            else []
        )
        image = pod.select_one("img[src]")
        books.append(
            BookListing(
                # The visible text is truncated; the title attribute holds the full name.
                title=str(anchor.get("title") or _text(anchor)),
                product_url=urljoin(page_url, str(anchor["href"])),
                price_text=_text(pod.select_one("p.price_color")),
                availability_text=_text(pod.select_one("p.availability")),
                rating_text=rating_classes[0] if rating_classes else None,
                image_url=urljoin(page_url, str(image["src"])) if image is not None else None,
            )
        )

    next_link = soup.select_one("li.next > a[href]")
    return CategoryPage(
        category=_text(header),
        books=books,
        next_page_url=urljoin(page_url, str(next_link["href"])) if next_link else None,
    )


def parse_price(text: str) -> tuple[Decimal, str]:
    """``"£51.77"`` -> ``(Decimal("51.77"), "GBP")``. Tolerates mis-decoded prefixes (``Â£``)."""
    match = _PRICE_RE.search(text)
    if match is None:
        raise ValueError(f"unparseable price: {text!r}")
    try:
        amount = Decimal(match["amount"].replace(",", "."))
    except InvalidOperation as exc:  # pragma: no cover - regex already guarantees digits
        raise ValueError(f"unparseable price: {text!r}") from exc
    return amount, CURRENCY_SYMBOLS[match["symbol"]]


def parse_rating(word: str | None) -> Decimal | None:
    if word is None:
        return None
    value = RATING_WORDS.get(word.lower())
    if value is None:
        raise ValueError(f"unknown star rating: {word!r}")
    return Decimal(value)


def product_slug(product_url: str) -> str:
    """``.../catalogue/a-light-in-the-attic_1000/index.html`` -> ``a-light-in-the-attic_1000``."""
    parts = [p for p in urlparse(product_url).path.split("/") if p and p != "index.html"]
    if not parts:
        raise ValueError(f"cannot derive product id from {product_url!r}")
    return parts[-1]
