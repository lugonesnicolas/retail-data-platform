from __future__ import annotations

import pytest

from retail_data_platform.config import Settings
from retail_data_platform.database import apply_migrations, connection
from retail_data_platform.database.migrate import MigrationError

pytestmark = pytest.mark.integration


def test_migrations_are_idempotent(migrated: Settings) -> None:
    with connection(migrated) as conn:
        assert apply_migrations(conn) == []
        tables = {
            f"{schema}.{name}"
            for schema, name in conn.execute(
                "select table_schema, table_name from information_schema.tables "
                "where table_schema in ('raw', 'ops')"
            ).fetchall()
        }
    assert {
        "raw.api_products",
        "raw.web_products",
        "raw.dataset_products",
        "raw.rejected_records",
        "ops.pipeline_runs",
        "ops.source_runs",
        "ops.data_quality_results",
        "ops.schema_migrations",
    } <= tables


def test_modified_migration_is_detected(migrated: Settings) -> None:
    with connection(migrated) as conn:
        conn.execute(
            "update ops.schema_migrations set checksum = 'tampered' where version = '0001'"
        )
        try:
            with pytest.raises(MigrationError, match="modified"):
                apply_migrations(conn)
        finally:
            from retail_data_platform.database.migrate import discover_migrations

            original = discover_migrations()[0].checksum
            conn.execute(
                "update ops.schema_migrations set checksum = %s where version = '0001'",
                (original,),
            )
