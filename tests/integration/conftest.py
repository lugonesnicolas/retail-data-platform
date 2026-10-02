"""Integration fixtures: a throw-away PostgreSQL database per test session.

Connection parameters come from ``RDP_TEST_DB_*`` (falling back to ``RDP_DB_*``); the user needs
CREATEDB. Tests are skipped - not failed - when no server is reachable, so ``pytest`` stays
usable without Docker. CI always provides a PostgreSQL service.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import psycopg
import pytest
from psycopg import sql

from retail_data_platform.config import Settings
from retail_data_platform.database import apply_migrations, connection

pytestmark = pytest.mark.integration


def _env(name: str, default: str) -> str:
    return os.environ.get(f"RDP_TEST_DB_{name}") or os.environ.get(f"RDP_DB_{name}") or default


@pytest.fixture(scope="session")
def database_params() -> Iterator[dict[str, Any]]:
    params: dict[str, Any] = {
        "host": _env("HOST", "localhost"),
        "port": int(_env("PORT", "5432")),
        "user": _env("USER", "postgres"),
        "password": _env("PASSWORD", ""),
    }
    admin_db = os.environ.get("RDP_TEST_DB_ADMIN_DBNAME", "postgres")
    try:
        admin = psycopg.connect(dbname=admin_db, autocommit=True, connect_timeout=3, **params)
    except psycopg.OperationalError as exc:
        pytest.skip(f"PostgreSQL not reachable for integration tests: {exc}")
    name = f"rdp_test_{uuid.uuid4().hex[:8]}"
    admin.execute(sql.SQL("create database {}").format(sql.Identifier(name)))
    try:
        yield {**params, "dbname": name}
    finally:
        admin.execute(
            sql.SQL("drop database if exists {} with (force)").format(sql.Identifier(name))
        )
        admin.close()


@pytest.fixture(scope="session")
def db_settings_factory(
    database_params: dict[str, Any], make_settings_session: Callable[..., Settings]
) -> Callable[..., Settings]:
    def factory(**overrides: Any) -> Settings:
        return make_settings_session(
            db_host=database_params["host"],
            db_port=database_params["port"],
            db_user=database_params["user"],
            db_password=database_params["password"],
            db_name=database_params["dbname"],
            **overrides,
        )

    return factory


@pytest.fixture(scope="session")
def make_settings_session() -> Callable[..., Settings]:
    from ..conftest import DATASET_PATH, FIXTURES_DIR, REPO_ROOT

    def factory(**overrides: Any) -> Settings:
        values: dict[str, Any] = {
            "source_mode": "replay",
            "fixtures_dir": FIXTURES_DIR,
            "dataset_path": DATASET_PATH,
            "dbt_project_dir": REPO_ROOT / "dbt",
            "dbt_profiles_dir": REPO_ROOT / "dbt",
            "http_backoff_base_seconds": 0,
            "web_request_delay_seconds": 0,
        }
        values.update(overrides)
        return Settings(_env_file=None, **values)  # type: ignore[call-arg]

    return factory


@pytest.fixture(scope="session")
def migrated(db_settings_factory: Callable[..., Settings]) -> Settings:
    settings = db_settings_factory()
    with connection(settings) as conn:
        apply_migrations(conn)
    return settings


@pytest.fixture
def clean_db(migrated: Settings) -> Settings:
    """Empty raw/ops tables between tests (schema stays migrated)."""
    with connection(migrated) as conn:
        conn.execute(
            "truncate raw.api_products, raw.web_products, raw.dataset_products, "
            "raw.rejected_records, ops.data_quality_results, ops.source_runs, "
            "ops.pipeline_runs restart identity cascade"
        )
    return migrated
