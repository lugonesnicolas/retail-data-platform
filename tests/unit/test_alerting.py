from __future__ import annotations

import smtplib
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, ClassVar

import pytest

from retail_data_platform import alerting
from retail_data_platform.alerting import AlertingError, FailureReport
from retail_data_platform.config import Settings


class FakeSMTP:
    """Records what the alerting code does with the SMTP connection."""

    instances: ClassVar[list[FakeSMTP]] = []
    fail_with: ClassVar[Exception | None] = None

    def __init__(self, host: str, port: int, timeout: float, **kwargs: Any) -> None:
        self.host, self.port, self.timeout, self.kwargs = host, port, timeout, kwargs
        self.calls: list[str] = []
        self.sent: list[Any] = []
        FakeSMTP.instances.append(self)
        if FakeSMTP.fail_with is not None:
            raise FakeSMTP.fail_with

    def __enter__(self) -> FakeSMTP:
        return self

    def __exit__(self, *_: object) -> None:
        self.calls.append("quit")

    def starttls(self, context: Any) -> None:
        self.calls.append("starttls")

    def login(self, user: str, password: str) -> None:
        self.calls.append(f"login:{user}:{password}")

    def send_message(self, message: Any) -> None:
        self.sent.append(message)


@pytest.fixture(autouse=True)
def fake_smtp(monkeypatch: pytest.MonkeyPatch) -> type[FakeSMTP]:
    FakeSMTP.instances = []
    FakeSMTP.fail_with = None
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    return FakeSMTP


@pytest.fixture
def smtp_settings(make_settings: Callable[..., Settings]) -> Callable[..., Settings]:
    def factory(**overrides: Any) -> Settings:
        values: dict[str, Any] = {
            "smtp_host": "smtp.example.com",
            "smtp_user": "bot@example.com",
            "smtp_password": "app-password",
            "alert_email_to": "ops@example.com, data@example.com",
            "airflow_url": "https://airflow.example.com/",
            "dashboard_url": "https://example.com",
        }
        values.update(overrides)
        return make_settings(**values)

    return factory


REPORT = FailureReport(
    run_id="manual__2026-10-02T03:16:13+00:00",
    status="failed",
    trigger="manual",
    started_at=datetime(2026, 10, 2, 3, 16, tzinfo=UTC),
    finished_at=datetime(2026, 10, 2, 3, 17, tzinfo=UTC),
    duration_seconds=61.5,
    rows_extracted=158,
    rows_loaded=0,
    rows_rejected=3,
    error_summary="dataset: failed (batch not loaded); critical check failed: reject_ratio",
    failed_sources=[("dataset", "QualityGateFailed", "batch not loaded")],
    failed_checks=[("critical", "ingestion.reject_ratio", "dataset", "share of bad records")],
)


def test_alerting_is_disabled_without_host_or_recipients(
    make_settings: Callable[..., Settings],
) -> None:
    assert not make_settings().alerting_enabled
    assert not make_settings(smtp_host="smtp.example.com").alerting_enabled
    assert not make_settings(smtp_host="", alert_email_to="ops@example.com").alerting_enabled
    # Disabled alerting is a no-op, not an error, and never touches the database.
    assert alerting.notify_pipeline_failure(make_settings(), "any-run") is False


def test_recipients_are_parsed_from_a_comma_separated_list(
    smtp_settings: Callable[..., Settings],
) -> None:
    assert smtp_settings().alert_email_to == ["ops@example.com", "data@example.com"]


def test_failure_email_content(smtp_settings: Callable[..., Settings]) -> None:
    message = alerting.render_failure_email(REPORT, smtp_settings())
    body = message.get_content()

    assert message["Subject"] == (
        "[retail-data-platform] Pipeline FAILED: manual__2026-10-02T03:16:13+00:00"
    )
    assert message["To"] == "ops@example.com, data@example.com"
    assert message["From"] == "bot@example.com"
    assert "Rows:      extracted 158 | loaded 0 | rejected 3" in body
    assert "- dataset: failed (batch not loaded)" in body
    assert "- dataset: QualityGateFailed - batch not loaded" in body
    assert "[CRITICAL] ingestion.reject_ratio (dataset)" in body
    # The run id is URL-encoded in the Airflow link.
    assert (
        "https://airflow.example.com/dags/retail_pipeline/runs/"
        "manual__2026-10-02T03%3A16%3A13%2B00%3A00"
    ) in body
    assert "https://example.com/health" in body


def test_header_injection_is_neutralised(smtp_settings: Callable[..., Settings]) -> None:
    report = FailureReport(run_id="evil\r\nBcc: attacker@example.com")
    message = alerting.render_failure_email(report, smtp_settings())
    assert "\n" not in message["Subject"]
    assert message["Bcc"] is None


def test_long_check_lists_are_truncated(smtp_settings: Callable[..., Settings]) -> None:
    checks = [("warning", f"check_{i}", "-", None) for i in range(25)]
    report = FailureReport(run_id="r", failed_checks=checks)
    body = alerting.render_failure_email(report, smtp_settings()).get_content()
    assert "check_19" in body
    assert "check_20" not in body
    assert "... and 5 more" in body


def test_starttls_login_and_send(
    smtp_settings: Callable[..., Settings], fake_smtp: type[FakeSMTP]
) -> None:
    settings = smtp_settings()
    alerting.send_email(alerting.render_test_email(settings), settings)
    (smtp,) = fake_smtp.instances
    assert (smtp.host, smtp.port, smtp.timeout) == ("smtp.example.com", 587, 15.0)
    assert smtp.calls[:2] == ["starttls", "login:bot@example.com:app-password"]
    assert len(smtp.sent) == 1


def test_implicit_tls_and_unauthenticated_modes(
    smtp_settings: Callable[..., Settings], fake_smtp: type[FakeSMTP]
) -> None:
    ssl_settings = smtp_settings(smtp_security="ssl", smtp_port=465)
    alerting.send_email(alerting.render_test_email(ssl_settings), ssl_settings)
    assert "context" in fake_smtp.instances[-1].kwargs
    assert "starttls" not in fake_smtp.instances[-1].calls

    plain = smtp_settings(smtp_security="none", smtp_user="", smtp_port=1025)
    alerting.send_email(alerting.render_test_email(plain), plain)
    assert fake_smtp.instances[-1].calls == ["quit"]  # no STARTTLS, no login


def test_smtp_errors_become_alerting_errors(
    smtp_settings: Callable[..., Settings], fake_smtp: type[FakeSMTP]
) -> None:
    fake_smtp.fail_with = smtplib.SMTPAuthenticationError(535, b"bad credentials")
    settings = smtp_settings()
    with pytest.raises(AlertingError, match="SMTPAuthenticationError"):
        alerting.send_email(alerting.render_test_email(settings), settings)
    fake_smtp.fail_with = ConnectionRefusedError("refused")
    with pytest.raises(AlertingError, match="ConnectionRefusedError"):
        alerting.send_email(alerting.render_test_email(settings), settings)


def test_password_never_appears_in_messages(smtp_settings: Callable[..., Settings]) -> None:
    settings = smtp_settings()
    for message in (
        alerting.render_test_email(settings),
        alerting.render_failure_email(REPORT, settings),
    ):
        assert "app-password" not in message.as_string()
