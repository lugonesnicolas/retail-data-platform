from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from retail_data_platform.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = REPO_ROOT / "data" / "fixtures"
DATASET_PATH = REPO_ROOT / "data" / "sample" / "retail_products.csv"
FIXED_NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def make_settings() -> Callable[..., Settings]:
    """Settings isolated from the developer's .env, in replay mode with zero backoff."""

    # Imported lazily so the Airflow DAG tests can run in the Airflow image without the package.
    from retail_data_platform.config import Settings, SourceMode

    def factory(**overrides: Any) -> Settings:
        values: dict[str, Any] = {
            "source_mode": SourceMode.REPLAY,
            "fixtures_dir": FIXTURES_DIR,
            "dataset_path": DATASET_PATH,
            "dbt_project_dir": REPO_ROOT / "dbt",
            "dbt_profiles_dir": REPO_ROOT / "dbt",
            "http_backoff_base_seconds": 0,
            "web_request_delay_seconds": 0,
            "api_page_size": 20,
        }
        values.update(overrides)
        return Settings(_env_file=None, **values)  # type: ignore[call-arg]

    return factory
