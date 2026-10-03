"""The CLI is the contract Airflow depends on: exit codes must reflect outcomes."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from typer.testing import CliRunner

from retail_data_platform.cli.main import app
from retail_data_platform.config import Settings, get_settings

from ..conftest import DATASET_PATH, FIXTURES_DIR

pytestmark = pytest.mark.integration
runner = CliRunner()


@pytest.fixture
def cli_env(clean_db: Settings, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    env = {
        "RDP_DB_HOST": clean_db.db_host,
        "RDP_DB_PORT": str(clean_db.db_port),
        "RDP_DB_NAME": clean_db.db_name,
        "RDP_DB_USER": clean_db.db_user,
        "RDP_DB_PASSWORD": clean_db.db_password.get_secret_value(),
        "RDP_SOURCE_MODE": "replay",
        "RDP_FIXTURES_DIR": str(FIXTURES_DIR),
        "RDP_DATASET_PATH": str(DATASET_PATH),
        "RDP_LOG_FORMAT": "console",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_ingest_and_lifecycle_exit_codes(cli_env: None) -> None:
    assert runner.invoke(app, ["db", "migrate", "--wait", "5"]).exit_code == 0
    started = runner.invoke(app, ["pipeline", "start", "--run-id", "cli-1"])
    assert started.exit_code == 0
    assert "cli-1" in started.output

    ingested = runner.invoke(app, ["ingest", "dataset", "--run-id", "cli-1"])
    assert ingested.exit_code == 0, ingested.output
    assert "loaded=59" in ingested.output

    # Warnings only (3 rejected rows) -> summary succeeds.
    assert runner.invoke(app, ["quality", "summarize", "--run-id", "cli-1"]).exit_code == 0
    # api/web never ran -> the run must be reported as failed.
    assert runner.invoke(app, ["pipeline", "finish", "--run-id", "cli-1"]).exit_code == 1


def test_failures_produce_non_zero_exit(cli_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RDP_MAX_REJECT_RATIO", "0.01")
    get_settings.cache_clear()
    result = runner.invoke(app, ["ingest", "dataset", "--run-id", "cli-2"])
    assert result.exit_code == 1
    assert runner.invoke(app, ["quality", "summarize", "--run-id", "cli-2"]).exit_code == 1
    assert runner.invoke(app, ["ingest", "ftp", "--run-id", "cli-2"]).exit_code != 0
