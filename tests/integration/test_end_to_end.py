"""Full pipeline including dbt: ingestion -> raw -> dbt build/tests -> marts -> smoke checks."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from retail_data_platform import steps
from retail_data_platform.config import Settings
from retail_data_platform.database import connection
from retail_data_platform.smoke import run_smoke_checks
from retail_data_platform.transform.dbt_runner import dbt_executable

pytestmark = pytest.mark.integration


@pytest.fixture
def dbt_settings(
    clean_db: Settings, db_settings_factory: Callable[..., Settings], tmp_path: Path
) -> Settings:
    try:
        dbt_executable()
    except FileNotFoundError:
        pytest.skip("dbt not installed")
    with connection(clean_db) as conn:
        conn.execute("drop schema if exists staging, intermediate, mart, reference cascade")
    return db_settings_factory(dbt_target_path=tmp_path / "target", dbt_log_path=tmp_path / "logs")


def test_full_pipeline_produces_tested_gold_data(dbt_settings: Settings) -> None:
    outcome = steps.run_all(dbt_settings, "it-e2e")
    assert outcome.status == "success", outcome.error_summary

    with connection(dbt_settings) as conn:
        products = conn.execute("select count(*) from mart.mart_product_latest").fetchone()
        sources = conn.execute(
            "select source, last_run_status, is_stale from mart.mart_source_metrics order by 1"
        ).fetchall()
        dbt_failures = conn.execute(
            "select count(*) from ops.data_quality_results where layer = 'dbt' "
            "and severity = 'critical' and status in ('fail', 'error')"
        ).fetchone()
        dbt_tests = conn.execute(
            "select count(*) from ops.data_quality_results where check_name like 'dbt.test.%'"
        ).fetchone()
    assert products == (121,)
    assert sources == [
        ("api", "success", False),
        ("dataset", "success", False),
        ("web", "success", False),
    ]
    assert dbt_failures == (0,)
    assert dbt_tests is not None
    assert dbt_tests[0] > 100

    failed_smoke = [check for check in run_smoke_checks(dbt_settings) if not check.ok]
    assert failed_smoke == []

    # A second run appends nothing new to raw, and the incremental fact stays consistent.
    assert steps.run_all(dbt_settings, "it-e2e-2").status == "success"
    with connection(dbt_settings) as conn:
        assert conn.execute("select count(*) from mart.fct_price_observation").fetchone() == (155,)
    shutil.rmtree(dbt_settings.dbt_target_path, ignore_errors=True)
