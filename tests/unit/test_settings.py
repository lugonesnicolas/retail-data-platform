from __future__ import annotations

import pytest
from pydantic import ValidationError

from retail_data_platform.config import Settings, SourceMode


def test_comma_separated_lists_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RDP_ENABLED_SOURCES", "api, dataset")
    monkeypatch.setenv("RDP_WEB_CATEGORIES", "Travel,Poetry")
    monkeypatch.setenv("RDP_SOURCE_MODE", "replay")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.enabled_sources == ["api", "dataset"]
    assert settings.web_categories == ["Travel", "Poetry"]
    assert settings.source_mode is SourceMode.REPLAY


def test_unknown_source_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RDP_ENABLED_SOURCES", "api,ftp")
    with pytest.raises(ValidationError, match="unknown sources"):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_password_is_not_part_of_conninfo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RDP_DB_PASSWORD", "s3cret")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert "s3cret" not in settings.conninfo
    assert "s3cret" not in repr(settings)
