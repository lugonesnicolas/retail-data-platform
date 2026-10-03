from __future__ import annotations

import httpx
import pytest

from retail_data_platform import steps
from retail_data_platform.config import Settings
from retail_data_platform.database import WarehouseRepository, connection
from retail_data_platform.ingestion import registry
from retail_data_platform.ingestion.pipeline import IngestionFailedError
from retail_data_platform.models import SourceName

pytestmark = pytest.mark.integration


def scalar(settings: Settings, query: str, *params: object) -> object:
    with connection(settings) as conn:
        row = conn.execute(query.encode(), params or None).fetchone()  # type: ignore[arg-type]
    return row[0] if row else None


@pytest.mark.parametrize(
    ("source", "table", "expected_rows"),
    [
        (SourceName.API, "raw.api_products", 45),
        (SourceName.WEB, "raw.web_products", 51),
        (SourceName.DATASET, "raw.dataset_products", 59),
    ],
)
def test_ingestion_is_idempotent(
    clean_db: Settings, source: SourceName, table: str, expected_rows: int
) -> None:
    first = steps.ingest(clean_db, source, "it-run-1")
    assert first.status == "success"
    assert first.rows_loaded == expected_rows

    second = steps.ingest(clean_db, source, "it-run-2")
    assert second.rows_loaded == 0
    assert second.rows_duplicate == expected_rows
    assert scalar(clean_db, f"select count(*) from {table}") == expected_rows

    # Lineage: every raw row points to the source run and pipeline run that produced it.
    assert (
        scalar(
            clean_db,
            f"select count(*) from {table} t join ops.source_runs s using (source_run_id) "
            "where t.pipeline_run_id = 'it-run-1' and s.source = %s",
            source.value,
        )
        == expected_rows
    )


def test_source_run_metadata_and_rejects_are_persisted(clean_db: Settings) -> None:
    steps.ingest(clean_db, SourceName.DATASET, "it-meta")
    with connection(clean_db) as conn:
        run = conn.execute(
            "select status, rows_extracted, rows_valid, rows_loaded, rows_rejected, "
            "finished_at is not null, duration_seconds >= 0, source_mode "
            "from ops.source_runs where pipeline_run_id = 'it-meta'"
        ).fetchone()
        rejected = conn.execute(
            "select count(*), bool_and(jsonb_array_length(errors) > 0) "
            "from raw.rejected_records where pipeline_run_id = 'it-meta'"
        ).fetchone()
        checks = dict(
            conn.execute(
                "select check_name, status from ops.data_quality_results "
                "where pipeline_run_id = 'it-meta'"
            ).fetchall()
        )
    assert run == ("success", 62, 59, 59, 3, True, True, "replay")
    assert rejected == (3, True)
    assert checks["ingestion.reject_ratio"] == "pass"
    assert checks["ingestion.no_rejected_records"] == "fail"  # warning severity


def test_quality_gate_blocks_the_batch(db_settings_factory, clean_db: Settings) -> None:  # type: ignore[no-untyped-def]
    strict = db_settings_factory(max_reject_ratio=0.01)
    with pytest.raises(IngestionFailedError, match="critical checks failed"):
        steps.ingest(strict, SourceName.DATASET, "it-gate")
    assert scalar(clean_db, "select count(*) from raw.dataset_products") == 0
    assert scalar(clean_db, "select count(*) from raw.rejected_records") == 3
    assert (
        scalar(clean_db, "select error_type from ops.source_runs where pipeline_run_id = 'it-gate'")
        == "QualityGateFailed"
    )


def test_acquisition_failure_is_recorded(
    clean_db: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        registry,
        "dummyjson_transport",
        lambda _: httpx.MockTransport(lambda request: httpx.Response(503)),
    )
    flaky = clean_db.model_copy(update={"http_max_retries": 1})
    with pytest.raises(Exception, match="HTTP 503"):
        steps.ingest(flaky, SourceName.API, "it-down")
    with connection(clean_db) as conn:
        row = conn.execute(
            "select status, error_type, http_requests from ops.source_runs "
            "where pipeline_run_id = 'it-down'"
        ).fetchone()
    assert row == ("failed", "AcquisitionError", 2)


def test_pipeline_status_reflects_missing_and_failed_sources(clean_db: Settings) -> None:
    steps.start_pipeline(clean_db, "it-partial")
    steps.ingest(clean_db, SourceName.API, "it-partial")
    outcome = steps.finish_pipeline(clean_db, "it-partial")
    assert outcome.status == "failed"
    assert outcome.error_summary is not None
    assert "web: no source run recorded" in outcome.error_summary

    steps.start_pipeline(clean_db, "it-complete")
    for source in SourceName:
        steps.ingest(clean_db, source, "it-complete")
    outcome = steps.finish_pipeline(clean_db, "it-complete")
    assert outcome.status == "success"
    assert outcome.rows_extracted == 45 + 51 + 62
    assert outcome.rows_rejected == 3


def test_restarting_a_run_is_idempotent(clean_db: Settings) -> None:
    with connection(clean_db) as conn:
        repo = WarehouseRepository(conn)
        repo.start_pipeline_run("it-retry", pipeline="p", trigger="scheduled")
        repo.start_pipeline_run("it-retry", pipeline="p", trigger="scheduled")
        assert conn.execute("select count(*) from ops.pipeline_runs").fetchone() == (1,)
