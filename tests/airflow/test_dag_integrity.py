"""DAG integrity tests. Run inside the Airflow image (see CI / `make test-dags`)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Skip outside the Airflow image. (Guard on a real submodule: the repository's own airflow/
# directory is importable as a namespace package when pytest runs from the repo root.)
dagbag_module = pytest.importorskip("airflow.dag_processing.dagbag")
DagBag = dagbag_module.DagBag

DAGS_DIR = Path(
    os.environ.get("RDP_DAGS_DIR", Path(__file__).resolve().parents[2] / "airflow" / "dags")
)


@pytest.fixture(scope="module")
def dagbag() -> DagBag:
    return DagBag(dag_folder=str(DAGS_DIR))


def test_no_import_errors(dagbag: DagBag) -> None:
    assert dagbag.import_errors == {}


def test_pipeline_shape(dagbag: DagBag) -> None:
    dag = dagbag.dags["retail_pipeline"]
    assert set(dag.task_ids) == {
        "start",
        "ingest_api",
        "ingest_web",
        "ingest_dataset",
        "dbt_build",
        "quality_summary",
        "refresh_metrics",
        "end",
    }
    ingest = {"ingest_api", "ingest_web", "ingest_dataset"}
    assert dag.get_task("start").downstream_task_ids == ingest
    assert dag.get_task("dbt_build").upstream_task_ids == ingest
    assert dag.get_task("end").upstream_task_ids == {"refresh_metrics"}
    assert dag.catchup is False
    assert dag.max_active_runs == 1


def test_network_sources_retry_with_backoff(dagbag: DagBag) -> None:
    dag = dagbag.dags["retail_pipeline"]
    for task_id in ("ingest_api", "ingest_web"):
        task = dag.get_task(task_id)
        assert task.retries >= 3
        assert task.retry_exponential_backoff


def test_downstream_steps_run_after_failures(dagbag: DagBag) -> None:
    dag = dagbag.dags["retail_pipeline"]
    for task_id in ("dbt_build", "quality_summary", "refresh_metrics", "end"):
        assert dag.get_task(task_id).trigger_rule == "all_done"


def test_run_id_is_not_interpolated_into_shell(dagbag: DagBag) -> None:
    dag = dagbag.dags["retail_pipeline"]
    for task in dag.tasks:
        assert "{{" not in task.bash_command
        assert task.env["RDP_RUN_ID"] == "{{ run_id }}"
