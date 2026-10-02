"""Data access for the raw (bronze) and ops schemas.

All values are bound as query parameters. Table names are never taken from user input: they are
resolved from the closed :class:`SourceName` enum and composed with :mod:`psycopg.sql`.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from retail_data_platform.models import ProductObservation, RejectedRecord, SourceName
from retail_data_platform.quality import QualityResult

RAW_TABLES: dict[SourceName, str] = {
    SourceName.API: "api_products",
    SourceName.WEB: "web_products",
    SourceName.DATASET: "dataset_products",
}

_RAW_COLUMNS = (
    "record_hash",
    "source_run_id",
    "pipeline_run_id",
    "source_product_id",
    "product_name",
    "brand",
    "category",
    "price",
    "currency",
    "availability",
    "rating",
    "product_url",
    "observed_at",
    "ingested_at",
    "source_url",
    "raw_payload",
)


def _json_default(value: object) -> str:
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"not JSON serialisable: {type(value).__name__}")


def _jsonb(value: Any) -> Jsonb:
    return Jsonb(value, dumps=lambda obj: json.dumps(obj, default=_json_default))


@dataclass(frozen=True, slots=True)
class PipelineOutcome:
    run_id: str
    status: str
    rows_extracted: int
    rows_loaded: int
    rows_rejected: int
    error_summary: str | None


class WarehouseRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn

    # ------------------------------------------------------------------ pipeline runs
    def start_pipeline_run(self, run_id: str, *, pipeline: str, trigger: str) -> None:
        """Idempotent: re-starting the same run (e.g. an Airflow task retry) resets it."""
        with self.conn.transaction():
            self.conn.execute(
                """
                insert into ops.pipeline_runs (run_id, pipeline, trigger, status)
                values (%s, %s, %s, 'running')
                on conflict (run_id) do update
                   set status = 'running', finished_at = null, error_summary = null
                """,
                (run_id, pipeline, trigger),
            )

    def ensure_pipeline_run(self, run_id: str, *, pipeline: str, trigger: str) -> None:
        """Create the run row if a step is executed standalone (no explicit ``pipeline start``)."""
        with self.conn.transaction():
            self.conn.execute(
                """
                insert into ops.pipeline_runs (run_id, pipeline, trigger, status)
                values (%s, %s, %s, 'running')
                on conflict (run_id) do nothing
                """,
                (run_id, pipeline, trigger),
            )

    def finish_pipeline_run(self, run_id: str, expected_sources: Sequence[str]) -> PipelineOutcome:
        """Derive the final run status from what actually happened, then persist it.

        A run fails when an expected source has no successful source run, or when any critical
        quality check failed. Using the persisted metadata (not orchestrator state) keeps the
        verdict identical whether the run was driven by Airflow or by ``rdp pipeline run``.
        """
        latest = self.conn.execute(
            """
            select distinct on (source) source, status, rows_extracted, rows_loaded,
                   rows_rejected, error_summary
              from ops.source_runs
             where pipeline_run_id = %s
             order by source, started_at desc
            """,
            (run_id,),
        ).fetchall()
        by_source = {row[0]: row for row in latest}
        problems: list[str] = []
        for source in expected_sources:
            row = by_source.get(source)
            if row is None:
                problems.append(f"{source}: no source run recorded")
            elif row[1] != "success":
                problems.append(f"{source}: {row[1]} ({row[5] or 'no error summary'})")

        critical = self.conn.execute(
            """
            select check_name, coalesce(source, '-')
              from ops.data_quality_results
             where pipeline_run_id = %s and severity = 'critical' and status in ('fail', 'error')
             order by id
            """,
            (run_id,),
        ).fetchall()
        problems.extend(f"critical check failed: {name} [{source}]" for name, source in critical)

        rows_extracted = sum(row[2] for row in latest)
        rows_loaded = sum(row[3] for row in latest)
        rows_rejected = sum(row[4] for row in latest)
        status = "failed" if problems else "success"
        error_summary = "; ".join(problems)[:4000] or None
        with self.conn.transaction():
            self.conn.execute(
                """
                update ops.pipeline_runs
                   set status = %s, finished_at = now(), rows_extracted = %s,
                       rows_loaded = %s, rows_rejected = %s, error_summary = %s
                 where run_id = %s
                """,
                (status, rows_extracted, rows_loaded, rows_rejected, error_summary, run_id),
            )
        return PipelineOutcome(
            run_id, status, rows_extracted, rows_loaded, rows_rejected, error_summary
        )

    # ------------------------------------------------------------------ source runs
    def start_source_run(
        self, *, source: SourceName, pipeline_run_id: str | None, source_mode: str
    ) -> uuid.UUID:
        with self.conn.transaction():
            row = self.conn.execute(
                """
                insert into ops.source_runs (pipeline_run_id, source, source_mode, status)
                values (%s, %s, %s, 'running')
                returning source_run_id
                """,
                (pipeline_run_id, source.value, source_mode),
            ).fetchone()
        if row is None:  # pragma: no cover - INSERT ... RETURNING always yields a row
            raise RuntimeError("could not create source run")
        source_run_id: uuid.UUID = row[0]
        return source_run_id

    def finish_source_run(
        self,
        source_run_id: uuid.UUID,
        *,
        status: str,
        rows_extracted: int = 0,
        rows_valid: int = 0,
        rows_loaded: int = 0,
        rows_duplicate: int = 0,
        rows_rejected: int = 0,
        http_requests: int | None = None,
        error_type: str | None = None,
        error_summary: str | None = None,
    ) -> None:
        self.conn.execute(
            """
            update ops.source_runs
               set status = %s, finished_at = now(), rows_extracted = %s, rows_valid = %s,
                   rows_loaded = %s, rows_duplicate = %s, rows_rejected = %s,
                   http_requests = %s, error_type = %s, error_summary = %s
             where source_run_id = %s
            """,
            (
                status,
                rows_extracted,
                rows_valid,
                rows_loaded,
                rows_duplicate,
                rows_rejected,
                http_requests,
                error_type,
                (error_summary or None) and error_summary[:4000],
                source_run_id,
            ),
        )

    # ------------------------------------------------------------------ raw layer
    def insert_observations(
        self,
        source: SourceName,
        observations: Sequence[ProductObservation],
        *,
        source_run_id: uuid.UUID,
        pipeline_run_id: str | None,
        source_urls: Sequence[str | None],
    ) -> int:
        """Bulk-load via COPY into a temp table, then append only unseen record hashes.

        Returns the number of genuinely new rows (duplicates are skipped, not overwritten).
        """
        if not observations:
            return 0
        table = sql.Identifier("raw", RAW_TABLES[source])
        columns = sql.SQL(", ").join(map(sql.Identifier, _RAW_COLUMNS))
        self.conn.execute(
            sql.SQL(
                "create temp table _incoming on commit drop as "
                "select {columns} from {table} with no data"
            ).format(table=table, columns=columns)
        )
        with self.conn.cursor().copy(
            sql.SQL("copy _incoming ({columns}) from stdin").format(columns=columns)
        ) as copy:
            for obs, url in zip(observations, source_urls, strict=True):
                copy.write_row(
                    (
                        obs.record_hash,
                        source_run_id,
                        pipeline_run_id,
                        obs.source_product_id,
                        obs.product_name,
                        obs.brand,
                        obs.category,
                        obs.price,
                        obs.currency,
                        obs.availability.value,
                        obs.rating,
                        obs.product_url,
                        obs.observed_at,
                        obs.ingested_at,
                        url,
                        json.dumps(obs.raw_payload, default=_json_default),
                    )
                )
        cursor = self.conn.execute(
            sql.SQL(
                "insert into {table} ({columns}) "
                "select {columns} from _incoming "
                "on conflict (record_hash) do nothing"
            ).format(table=table, columns=columns)
        )
        return cursor.rowcount

    def insert_rejected(
        self,
        rejected: Sequence[RejectedRecord],
        *,
        source_run_id: uuid.UUID,
        pipeline_run_id: str | None,
    ) -> None:
        if not rejected:
            return
        with self.conn.cursor() as cur:
            cur.executemany(
                """
                insert into raw.rejected_records
                    (source, source_run_id, pipeline_run_id, source_record_ref, source_url,
                     errors, raw_payload)
                values (%s, %s, %s, %s, %s, %s, %s)
                """,
                [
                    (
                        rec.source.value,
                        source_run_id,
                        pipeline_run_id,
                        rec.source_record_ref,
                        rec.source_url,
                        _jsonb(rec.errors),
                        _jsonb(rec.raw_payload),
                    )
                    for rec in rejected
                ],
            )

    # ------------------------------------------------------------------ quality results
    def record_quality_results(
        self,
        results: Sequence[QualityResult],
        *,
        pipeline_run_id: str | None,
        source_run_id: uuid.UUID | None = None,
    ) -> None:
        if not results:
            return
        with self.conn.cursor() as cur:
            cur.executemany(
                """
                insert into ops.data_quality_results
                    (pipeline_run_id, source_run_id, check_name, layer, severity, status,
                     source, observed_value, threshold, details)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                [
                    (
                        pipeline_run_id,
                        source_run_id,
                        r.check_name,
                        r.layer,
                        r.severity.value,
                        r.status.value,
                        r.source,
                        r.observed_value,
                        r.threshold,
                        r.details,
                    )
                    for r in results
                ],
            )

    def quality_summary(self, pipeline_run_id: str) -> list[tuple[str, str, int]]:
        """``(severity, status, count)`` for one pipeline run."""
        rows = self.conn.execute(
            """
            select severity, status, count(*)::int
              from ops.data_quality_results
             where pipeline_run_id = %s
             group by severity, status
             order by severity, status
            """,
            (pipeline_run_id,),
        ).fetchall()
        return [(severity, status, count) for severity, status, count in rows]

    def failed_checks(self, pipeline_run_id: str) -> list[tuple[str, str, str, str | None]]:
        """``(severity, check_name, source, details)`` of failing checks for one run."""
        rows = self.conn.execute(
            """
            select severity, check_name, coalesce(source, '-'), details
              from ops.data_quality_results
             where pipeline_run_id = %s and status in ('fail', 'error')
             order by case severity when 'critical' then 0 when 'warning' then 1 else 2 end, id
            """,
            (pipeline_run_id,),
        ).fetchall()
        return [(severity, name, source, details) for severity, name, source, details in rows]
