"""Environment-driven configuration.

Every setting can be supplied through an ``RDP_``-prefixed environment variable (or a local
``.env`` file). Nothing secret has a default: the database password must be provided.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class SourceMode(StrEnum):
    """How acquisition adapters reach their upstream.

    ``live`` talks to the real public endpoints. ``replay`` serves committed fixtures through the
    same HTTP client and parsing code, which keeps CI and offline demos deterministic.
    """

    LIVE = "live"
    REPLAY = "replay"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RDP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- warehouse connection -------------------------------------------------------------
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "retail"
    db_user: str = "retail"
    db_password: SecretStr = SecretStr("")
    db_connect_timeout_seconds: int = 10
    db_statement_timeout_ms: int = 300_000

    # --- runtime behaviour ----------------------------------------------------------------
    source_mode: SourceMode = SourceMode.LIVE
    enabled_sources: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["api", "web", "dataset"]
    )
    log_level: str = "INFO"
    log_format: str = Field(default="json", pattern="^(json|console)$")

    # --- data quality thresholds ------------------------------------------------------------
    max_reject_ratio: float = Field(default=0.2, ge=0, le=1)
    min_rows_per_source: int = Field(default=1, ge=0)

    # --- HTTP acquisition -------------------------------------------------------------------
    http_connect_timeout_seconds: float = 5.0
    http_read_timeout_seconds: float = 20.0
    http_max_retries: int = Field(default=4, ge=0)
    http_backoff_base_seconds: float = Field(default=1.0, ge=0)
    http_backoff_max_seconds: float = Field(default=30.0, ge=0)
    http_user_agent: str = (
        "retail-data-platform/0.1 (+https://github.com/lugonesnicolas/retail-data-platform)"
    )

    # --- API source (DummyJSON) -------------------------------------------------------------
    api_base_url: str = "https://dummyjson.com"
    api_page_size: int = Field(default=50, ge=1, le=100)
    api_max_pages: int = Field(default=20, ge=1)

    # --- web source (books.toscrape.com) ----------------------------------------------------
    web_base_url: str = "https://books.toscrape.com/"
    web_categories: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["Travel", "Mystery", "Poetry", "Science", "Business"]
    )
    web_max_pages_per_category: int = Field(default=3, ge=1)
    web_request_delay_seconds: float = Field(default=0.5, ge=0)

    # --- dataset source ---------------------------------------------------------------------
    dataset_path: Path = Path("data/sample/retail_products.csv")

    # --- failure alerts (email via SMTP; disabled unless host and recipients are set) --------
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: SecretStr = SecretStr("")
    smtp_security: str = Field(default="starttls", pattern="^(starttls|ssl|none)$")
    smtp_timeout_seconds: float = Field(default=15.0, gt=0)
    alert_email_from: str | None = None
    alert_email_to: Annotated[list[str], NoDecode] = Field(default_factory=list)
    # Public URLs used only to build links in alert emails.
    airflow_url: str | None = None
    dashboard_url: str | None = None

    # --- paths ------------------------------------------------------------------------------
    fixtures_dir: Path = Path("data/fixtures")
    dbt_project_dir: Path = Path("dbt")
    dbt_profiles_dir: Path = Path("dbt")
    dbt_target: str = "dev"
    dbt_target_path: Path = Path("dbt/target")
    dbt_log_path: Path = Path("dbt/logs")

    @field_validator("enabled_sources", "web_categories", "alert_email_to", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("enabled_sources")
    @classmethod
    def _known_sources(cls, value: list[str]) -> list[str]:
        unknown = set(value) - {"api", "web", "dataset"}
        if unknown:
            raise ValueError(f"unknown sources in RDP_ENABLED_SOURCES: {sorted(unknown)}")
        return value

    @field_validator("smtp_host", "smtp_user", "alert_email_from", "airflow_url", "dashboard_url")
    @classmethod
    def _blank_is_unset(cls, value: str | None) -> str | None:
        # Compose passes unset optional variables as empty strings.
        if value is None:
            return None
        return value.strip() or None

    @property
    def alerting_enabled(self) -> bool:
        return bool(self.smtp_host and self.alert_email_to)

    @property
    def conninfo(self) -> str:
        """libpq keyword/value connection string (password passed separately, never logged)."""
        return (
            f"host={self.db_host} port={self.db_port} dbname={self.db_name} "
            f"user={self.db_user} connect_timeout={self.db_connect_timeout_seconds} "
            f"application_name=retail-data-platform"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
