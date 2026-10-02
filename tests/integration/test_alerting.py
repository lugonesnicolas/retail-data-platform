"""Failure alerts end-to-end against PostgreSQL (SMTP replaced by a recorder)."""

from __future__ import annotations

from collections.abc import Callable
from email.message import EmailMessage

import pytest

from retail_data_platform import alerting, steps
from retail_data_platform.config import Settings
from retail_data_platform.database import connection
from retail_data_platform.models import SourceName

pytestmark = pytest.mark.integration


@pytest.fixture
def outbox(monkeypatch: pytest.MonkeyPatch) -> list[EmailMessage]:
    sent: list[EmailMessage] = []

    def fake_send(message: EmailMessage, settings: Settings) -> None:
        sent.append(message)

    monkeypatch.setattr(alerting, "send_email", fake_send)
    return sent


@pytest.fixture
def alert_settings(clean_db: Settings, db_settings_factory: Callable[..., Settings]) -> Settings:
    return db_settings_factory(smtp_host="smtp.example.com", alert_email_to="ops@example.com")


def alerted_at(settings: Settings, run_id: str) -> object:
    with connection(settings) as conn:
        row = conn.execute(
            "select alerted_at from ops.pipeline_runs where run_id = %s", (run_id,)
        ).fetchone()
    return row[0] if row else None


def failed_run(settings: Settings, run_id: str) -> None:
    """A run where only the API source ran: web and dataset are missing -> failed."""
    steps.start_pipeline(settings, run_id)
    steps.ingest(settings, SourceName.API, run_id)


def test_failed_run_sends_exactly_one_alert(
    alert_settings: Settings, outbox: list[EmailMessage]
) -> None:
    failed_run(alert_settings, "al-1")
    outcome = steps.finish_pipeline(alert_settings, "al-1")

    assert outcome.status == "failed"
    assert len(outbox) == 1
    body = outbox[0].get_content()
    assert "Pipeline FAILED: al-1" in outbox[0]["Subject"]
    assert "web: no source run recorded" in body
    assert alerted_at(alert_settings, "al-1") is not None

    # The Airflow failure callback (or an `end` retry) must not send a second email.
    assert alerting.notify_pipeline_failure(alert_settings, "al-1") is False
    assert steps.finish_pipeline(alert_settings, "al-1").status == "failed"
    assert len(outbox) == 1

    # An operator can still resend explicitly.
    assert alerting.notify_pipeline_failure(alert_settings, "al-1", force=True) is True
    assert len(outbox) == 2


def test_successful_run_sends_nothing(alert_settings: Settings, outbox: list[EmailMessage]) -> None:
    steps.start_pipeline(alert_settings, "al-ok")
    for source in SourceName:
        steps.ingest(alert_settings, source, "al-ok")
    assert steps.finish_pipeline(alert_settings, "al-ok").status == "success"
    assert alerting.notify_pipeline_failure(alert_settings, "al-ok") is False
    assert outbox == []


def test_run_that_never_finished_is_reported(
    alert_settings: Settings, outbox: list[EmailMessage]
) -> None:
    failed_run(alert_settings, "al-stuck")  # still 'running': end never executed
    assert alerting.notify_pipeline_failure(
        alert_settings, "al-stuck", reason="Airflow marked the run failed"
    )
    body = outbox[0].get_content()
    assert "Pipeline RUNNING: al-stuck" in outbox[0]["Subject"]
    assert "Note: Airflow marked the run failed" in body


def test_smtp_failure_does_not_change_outcome_and_allows_retry(
    alert_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken_send(message: EmailMessage, settings: Settings) -> None:
        raise alerting.AlertingError("SMTPServerDisconnected: gone")

    monkeypatch.setattr(alerting, "send_email", broken_send)
    failed_run(alert_settings, "al-smtp")
    outcome = steps.finish_pipeline(alert_settings, "al-smtp")

    assert outcome.status == "failed"  # unchanged by the alerting failure
    assert alerted_at(alert_settings, "al-smtp") is None  # claim released for a retry
