"""Post-deployment smoke checks: is the platform producing usable gold data?"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import httpx
import psycopg

from retail_data_platform.config import Settings
from retail_data_platform.database import connection


@dataclass(frozen=True)
class SmokeCheck:
    name: str
    ok: bool
    detail: str


def _scalar(conn: psycopg.Connection, query: bytes) -> object:
    row = conn.execute(query).fetchone()
    return row[0] if row else None


def run_smoke_checks(
    settings: Settings, *, dashboard_url: str | None = None, airflow_url: str | None = None
) -> Iterator[SmokeCheck]:
    try:
        with connection(settings) as conn:
            yield SmokeCheck(
                "database", True, f"connected to {settings.db_host}/{settings.db_name}"
            )

            products = _scalar(conn, b"select count(*) from mart.mart_product_latest")
            yield SmokeCheck("mart_product_latest", bool(products), f"{products} products")

            sources = _scalar(
                conn, b"select count(distinct source) from mart.fct_price_observation"
            )
            expected = len(settings.enabled_sources)
            yield SmokeCheck(
                "sources_in_gold",
                sources == expected,
                f"{sources} of {expected} enabled sources present in fct_price_observation",
            )

            last = conn.execute(
                b"select run_id, status from mart.mart_pipeline_health "
                b"where status <> 'running' order by started_at desc limit 1"
            ).fetchone()
            yield SmokeCheck(
                "last_pipeline_run",
                last is not None and last[1] == "success",
                f"{last[0]} -> {last[1]}" if last else "no finished pipeline run",
            )
    except psycopg.Error as exc:
        yield SmokeCheck("database", False, f"{type(exc).__name__}: {str(exc).strip()[:200]}")

    for name, url in (
        ("dashboard", f"{dashboard_url.rstrip('/')}/_stcore/health" if dashboard_url else None),
        ("airflow", f"{airflow_url.rstrip('/')}/api/v2/monitor/health" if airflow_url else None),
    ):
        if url is None:
            continue
        try:
            response = httpx.get(url, timeout=10)
            yield SmokeCheck(
                name, response.status_code == 200, f"GET {url} -> {response.status_code}"
            )
        except httpx.HTTPError as exc:
            yield SmokeCheck(name, False, f"GET {url} -> {type(exc).__name__}")
