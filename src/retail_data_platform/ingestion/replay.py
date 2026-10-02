"""Replay transports: serve committed fixtures through the real HTTP client.

Used when ``RDP_SOURCE_MODE=replay`` (CI, offline demos, sandboxed environments). They emulate
the upstream behaviour the adapters depend on - DummyJSON's ``limit``/``skip`` pagination and
books.toscrape.com's static page tree - without any network access.
"""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath

import httpx


def dummyjson_transport(fixtures_dir: Path) -> httpx.MockTransport:
    catalogue = json.loads((fixtures_dir / "dummyjson" / "products.json").read_text("utf-8"))
    products: list[dict[str, object]] = catalogue["products"]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.rstrip("/") != "/products":
            return httpx.Response(404, json={"message": f"Route {request.url.path} not found"})
        limit = int(request.url.params.get("limit", 30))
        skip = int(request.url.params.get("skip", 0))
        page = products[skip : skip + limit] if limit else products[skip:]
        return httpx.Response(
            200,
            json={"products": page, "total": len(products), "skip": skip, "limit": len(page)},
        )

    return httpx.MockTransport(handler)


def books_toscrape_transport(fixtures_dir: Path) -> httpx.MockTransport:
    root = (fixtures_dir / "books_toscrape").resolve()

    def handler(request: httpx.Request) -> httpx.Response:
        relative = PurePosixPath(request.url.path.lstrip("/") or "index.html")
        candidate = (root / relative).resolve()
        if not candidate.is_relative_to(root) or not candidate.is_file():
            return httpx.Response(404, text="Not Found")
        return httpx.Response(
            200,
            content=candidate.read_bytes(),
            headers={"Content-Type": "text/html; charset=utf-8"},
        )

    return httpx.MockTransport(handler)
