"""PostgreSQL connectivity (psycopg 3)."""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg

from retail_data_platform.config import Settings
from retail_data_platform.observability import get_logger

log = get_logger(__name__)


def connect(settings: Settings, *, autocommit: bool = False) -> psycopg.Connection:
    """Open a connection. Credentials are passed as parameters, never interpolated into logs."""
    return psycopg.connect(
        settings.conninfo,
        password=settings.db_password.get_secret_value() or None,
        options=f"-c statement_timeout={settings.db_statement_timeout_ms}",
        autocommit=autocommit,
    )


@contextmanager
def connection(settings: Settings) -> Iterator[psycopg.Connection]:
    """Autocommit connection: every multi-statement unit of work uses an explicit
    ``with conn.transaction():`` block, so commit boundaries are visible in the code."""
    conn = connect(settings, autocommit=True)
    try:
        yield conn
    finally:
        conn.close()


def wait_for_database(settings: Settings, timeout_seconds: float = 60.0) -> None:
    """Block until the warehouse accepts connections (container start-up ordering helper)."""
    deadline = time.monotonic() + timeout_seconds
    attempt = 0
    while True:
        attempt += 1
        try:
            with connect(settings, autocommit=True) as conn:
                conn.execute("select 1")
            log.info("database.ready", attempts=attempt, host=settings.db_host)
            return
        except psycopg.OperationalError as exc:
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"database {settings.db_host}:{settings.db_port} not reachable "
                    f"after {timeout_seconds}s"
                ) from exc
            log.info("database.waiting", attempt=attempt, error=str(exc).splitlines()[0])
            time.sleep(min(2.0, 0.25 * attempt))
