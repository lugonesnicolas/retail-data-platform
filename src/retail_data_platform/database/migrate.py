"""Minimal, deterministic schema migrations.

Migrations are plain SQL files shipped inside the package (``database/migrations/NNNN_*.sql``)
and applied in lexical order, each in its own transaction. Applied versions are recorded in
``ops.schema_migrations`` together with a checksum so an edited, already-applied migration is
detected instead of silently diverging. A PostgreSQL advisory lock serialises concurrent
migrators (e.g. several containers starting at once).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from importlib import resources

import psycopg

from retail_data_platform.observability import get_logger

log = get_logger(__name__)

# Arbitrary, stable 64-bit key for pg_advisory_lock.
MIGRATION_LOCK_KEY = 7_311_942_001


@dataclass(frozen=True)
class Migration:
    version: str
    name: str
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode()).hexdigest()


class MigrationError(RuntimeError):
    pass


def discover_migrations() -> list[Migration]:
    package = resources.files("retail_data_platform.database") / "migrations"
    migrations = []
    for entry in sorted(package.iterdir(), key=lambda e: e.name):
        if entry.name.endswith(".sql"):
            version, _, rest = entry.name.partition("_")
            migrations.append(
                Migration(version=version, name=rest.removesuffix(".sql"), sql=entry.read_text())
            )
    return migrations


def apply_migrations(conn: psycopg.Connection) -> list[str]:
    """Apply pending migrations; return the versions applied in this call."""
    applied_now: list[str] = []
    conn.autocommit = True
    conn.execute("select pg_advisory_lock(%s)", (MIGRATION_LOCK_KEY,))
    try:
        conn.execute("create schema if not exists ops")
        conn.execute(
            """
            create table if not exists ops.schema_migrations (
                version    text primary key,
                name       text        not null,
                checksum   text        not null,
                applied_at timestamptz not null default now()
            )
            """
        )
        rows = conn.execute("select version, checksum from ops.schema_migrations").fetchall()
        applied: dict[str, str] = dict(rows)

        for migration in discover_migrations():
            if migration.version in applied:
                if applied[migration.version] != migration.checksum:
                    raise MigrationError(
                        f"migration {migration.version}_{migration.name} was modified after "
                        "being applied; add a new migration instead"
                    )
                continue
            with conn.transaction():
                conn.execute(migration.sql.encode())
                conn.execute(
                    "insert into ops.schema_migrations (version, name, checksum) "
                    "values (%s, %s, %s)",
                    (migration.version, migration.name, migration.checksum),
                )
            applied_now.append(migration.version)
            log.info("migration.applied", version=migration.version, name=migration.name)
    finally:
        conn.execute("select pg_advisory_unlock(%s)", (MIGRATION_LOCK_KEY,))
    return applied_now
