from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from retail_data_platform.models import SourceName
from retail_data_platform.quality import CheckStatus, Severity, ingestion_checks
from retail_data_platform.transform.artifacts import results_from_freshness, results_from_run

DBT_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "dbt"


def by_name(results: list, name: str):  # type: ignore[no-untyped-def]
    return next(r for r in results if r.check_name == name)


def test_clean_batch_passes_all_gates() -> None:
    checks = ingestion_checks(
        SourceName.API, rows_extracted=100, rows_rejected=0, max_reject_ratio=0.2, min_rows=1
    )
    assert not any(c.is_critical_failure for c in checks)
    assert all(c.status is CheckStatus.PASS for c in checks)


def test_some_rejects_is_a_warning_not_a_failure() -> None:
    checks = ingestion_checks(
        SourceName.DATASET, rows_extracted=62, rows_rejected=3, max_reject_ratio=0.2, min_rows=1
    )
    assert not any(c.is_critical_failure for c in checks)
    warning = by_name(checks, "ingestion.no_rejected_records")
    assert warning.severity is Severity.WARNING
    assert warning.status is CheckStatus.FAIL
    assert by_name(checks, "ingestion.reject_ratio").observed_value == Decimal("0.0484")


def test_reject_ratio_above_threshold_is_critical() -> None:
    checks = ingestion_checks(
        SourceName.WEB, rows_extracted=10, rows_rejected=5, max_reject_ratio=0.2, min_rows=1
    )
    assert by_name(checks, "ingestion.reject_ratio").is_critical_failure


def test_empty_source_is_critical() -> None:
    checks = ingestion_checks(
        SourceName.API, rows_extracted=0, rows_rejected=0, max_reject_ratio=0.2, min_rows=1
    )
    assert by_name(checks, "ingestion.min_rows_extracted").is_critical_failure


def test_dbt_run_results_are_mapped_by_configured_severity() -> None:
    results = results_from_run(DBT_FIXTURES)
    names = {r.check_name: r for r in results}

    assert names["dbt.test.unique_dim_product_product_key"].status is CheckStatus.PASS
    failing = names["dbt.test.non_negative_fct_price_observation_price"]
    assert failing.is_critical_failure
    assert failing.observed_value == Decimal(2)
    warn = names["dbt.test.value_between_mart_price_comparison_price_change_pct__50___50"]
    assert warn.severity is Severity.WARNING
    assert warn.status is CheckStatus.FAIL
    assert not warn.is_critical_failure
    # Successful models are not recorded; errored ones are critical.
    assert "dbt.model.dim_product" not in names
    assert names["dbt.model.mart_product_latest"].is_critical_failure


def test_freshness_results() -> None:
    results = {r.check_name: r for r in results_from_freshness(DBT_FIXTURES)}
    assert results["freshness.raw.api_products"].status is CheckStatus.PASS
    stale = results["freshness.raw.web_products"]
    assert stale.status is CheckStatus.FAIL
    assert stale.severity is Severity.WARNING
    assert stale.observed_value == Decimal("30.0")
