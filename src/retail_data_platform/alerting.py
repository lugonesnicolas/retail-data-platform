"""Failure alerts by email (SMTP).

When a pipeline run fails, one plain-text email is sent with what failed (sources, checks, error
summary) and links to Airflow and the dashboard. Design rules:

* **Optional** - disabled (a logged no-op) unless ``RDP_SMTP_HOST`` and ``RDP_ALERT_EMAIL_TO`` are
  set, so local development and CI are unaffected.
* **At most once per run** - the sender first claims ``ops.pipeline_runs.alerted_at``; the
  ``end`` task and the Airflow DAG failure callback can both call it safely. A failed send
  releases the claim so a retry can resend.
* **Never masks the pipeline result** - callers treat alerting errors as log events only.
"""

from __future__ import annotations

import smtplib
import ssl
from dataclasses import dataclass, field
from datetime import datetime
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Any
from urllib.parse import quote

import psycopg

from retail_data_platform.config import Settings
from retail_data_platform.database import WarehouseRepository, connection
from retail_data_platform.observability import get_logger

log = get_logger(__name__)

SUBJECT_PREFIX = "[retail-data-platform]"
MAX_CHECK_LINES = 20


class AlertingError(RuntimeError):
    """The alert could not be delivered (SMTP/network/authentication problem)."""


@dataclass(frozen=True)
class FailureReport:
    run_id: str
    pipeline: str = "retail_pipeline"
    status: str = "failed"
    trigger: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_seconds: float | None = None
    rows_extracted: int | None = None
    rows_loaded: int | None = None
    rows_rejected: int | None = None
    error_summary: str | None = None
    failed_sources: list[tuple[str, str | None, str | None]] = field(default_factory=list)
    failed_checks: list[tuple[str, str, str, str | None]] = field(default_factory=list)
    note: str | None = None


# --------------------------------------------------------------------------------- rendering
def _header_safe(value: str, limit: int = 150) -> str:
    """Strip control characters (no header injection via a crafted run id) and bound length."""
    return "".join(ch for ch in value if ch.isprintable())[:limit]


def _fmt_time(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S %Z").strip() if value else "-"


def _count(value: int | None) -> str:
    return "-" if value is None else str(value)


def _sender(settings: Settings) -> str:
    return settings.alert_email_from or settings.smtp_user or "retail-data-platform@localhost"


def _new_message(settings: Settings, subject: str, body: str) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = _header_safe(subject)
    message["From"] = _sender(settings)
    message["To"] = ", ".join(settings.alert_email_to)
    message["Date"] = formatdate(usegmt=True)
    message["Message-ID"] = make_msgid(domain="retail-data-platform")
    message.set_content(body)
    return message


def run_links(report: FailureReport, settings: Settings) -> list[str]:
    links = []
    if settings.airflow_url:
        run = quote(report.run_id, safe="")
        links.append(
            f"Airflow:   {settings.airflow_url.rstrip('/')}/dags/{report.pipeline}/runs/{run}"
        )
    if settings.dashboard_url:
        links.append(f"Dashboard: {settings.dashboard_url.rstrip('/')}/health")
    return links


def render_failure_email(report: FailureReport, settings: Settings) -> EmailMessage:
    duration = f"{report.duration_seconds:.1f} s" if report.duration_seconds is not None else "-"
    lines = [
        f"Pipeline run {report.status.upper()}",
        "",
        f"Pipeline:  {report.pipeline}",
        f"Run id:    {report.run_id}",
        f"Trigger:   {report.trigger or '-'}",
        f"Started:   {_fmt_time(report.started_at)}",
        f"Finished:  {_fmt_time(report.finished_at)}",
        f"Duration:  {duration}",
        f"Rows:      extracted {_count(report.rows_extracted)}"
        f" | loaded {_count(report.rows_loaded)} | rejected {_count(report.rows_rejected)}",
    ]
    if report.note:
        lines += ["", f"Note: {report.note}"]
    if report.error_summary:
        lines += ["", "What failed", "-----------"]
        lines += [f"- {part.strip()}" for part in report.error_summary.split(";") if part.strip()]
    if report.failed_sources:
        lines += ["", "Failed sources", "--------------"]
        lines += [
            f"- {source}: {error_type or 'unknown error'} - {summary or 'no details'}"
            for source, error_type, summary in report.failed_sources
        ]
    if report.failed_checks:
        lines += [
            "",
            "Failing quality checks (critical first)",
            "---------------------------------------",
        ]
        for severity, name, source, details in report.failed_checks[:MAX_CHECK_LINES]:
            lines.append(f"- [{severity.upper()}] {name} ({source}) {details or ''}".rstrip())
        hidden = len(report.failed_checks) - MAX_CHECK_LINES
        if hidden > 0:
            lines.append(f"- ... and {hidden} more")
    links = run_links(report, settings)
    if links:
        lines += ["", "Links", "-----", *links]
    lines += [
        "",
        f"Investigate: rdp quality summarize --run-id {report.run_id}",
        "Runbook: docs/operations.md (Failure scenarios)",
    ]
    subject = f"{SUBJECT_PREFIX} Pipeline {report.status.upper()}: {report.run_id}"
    return _new_message(settings, subject, "\n".join(lines) + "\n")


def render_test_email(settings: Settings) -> EmailMessage:
    body = (
        "This is a test alert from the Retail Data Platform.\n\n"
        "If you received it, failure alerts are configured correctly:\n"
        f"  SMTP server: {settings.smtp_host}:{settings.smtp_port} ({settings.smtp_security})\n"
        f"  Recipients:  {', '.join(settings.alert_email_to)}\n"
    )
    return _new_message(settings, f"{SUBJECT_PREFIX} Test alert", body)


# ----------------------------------------------------------------------------------- sending
def send_email(message: EmailMessage, settings: Settings) -> None:
    if not settings.smtp_host:
        raise AlertingError("RDP_SMTP_HOST is not configured")
    context = ssl.create_default_context()
    try:
        smtp: smtplib.SMTP
        if settings.smtp_security == "ssl":
            smtp = smtplib.SMTP_SSL(
                settings.smtp_host,
                settings.smtp_port,
                timeout=settings.smtp_timeout_seconds,
                context=context,
            )
        else:
            smtp = smtplib.SMTP(
                settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout_seconds
            )
        with smtp:
            if settings.smtp_security == "starttls":
                smtp.starttls(context=context)
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password.get_secret_value())
            smtp.send_message(message)
    except (smtplib.SMTPException, OSError) as exc:
        raise AlertingError(f"{type(exc).__name__}: {exc}") from exc


def send_test_email(settings: Settings) -> None:
    send_email(render_test_email(settings), settings)
    log.info("alert.test_sent", recipients=len(settings.alert_email_to))


# ------------------------------------------------------------------------------ orchestration
def _report_from_run(
    repo: WarehouseRepository, run: dict[str, Any], note: str | None
) -> FailureReport:
    duration = run.get("duration_seconds")
    return FailureReport(
        run_id=run["run_id"],
        pipeline=run["pipeline"],
        status=run["status"],
        trigger=run["trigger"],
        started_at=run["started_at"],
        finished_at=run["finished_at"],
        duration_seconds=float(duration) if duration is not None else None,
        rows_extracted=run["rows_extracted"],
        rows_loaded=run["rows_loaded"],
        rows_rejected=run["rows_rejected"],
        error_summary=run["error_summary"],
        failed_sources=repo.failed_source_runs(run["run_id"]),
        failed_checks=repo.failed_checks(run["run_id"]),
        note=note,
    )


def notify_pipeline_failure(
    settings: Settings, run_id: str, *, force: bool = False, reason: str | None = None
) -> bool:
    """Email a failure report for ``run_id`` once. Returns True if an email was sent.

    Skips runs recorded as successful and runs already alerted (unless ``force``). A run still
    marked ``running`` is reported too: it means the orchestrator failed it before the ``end``
    task could finish it. If the ops metadata cannot be read, a minimal alert is still sent.
    """
    if not settings.alerting_enabled:
        log.info("alert.disabled", run_id=run_id)
        return False

    claimed = False
    try:
        with connection(settings) as conn:
            repo = WarehouseRepository(conn)
            run = repo.pipeline_run(run_id)
            if run is not None and run["status"] == "success" and not force:
                log.info("alert.skipped", run_id=run_id, reason="run succeeded")
                return False
            if run is not None and not force:
                claimed = repo.claim_alert(run_id)
                if not claimed:
                    log.info("alert.skipped", run_id=run_id, reason="already sent")
                    return False
            if run is None:
                report = FailureReport(run_id=run_id, note="run not found in ops.pipeline_runs")
            else:
                if run["status"] == "running":
                    reason = reason or "the run was stopped before its end task completed"
                report = _report_from_run(repo, run, reason)
    except psycopg.Error as exc:
        detail = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
        report = FailureReport(run_id=run_id, note=f"could not read ops metadata: {detail}")

    try:
        send_email(render_failure_email(report, settings), settings)
    except AlertingError:
        if claimed:
            _release_claim(settings, run_id)
        raise
    log.info("alert.sent", run_id=run_id, recipients=len(settings.alert_email_to))
    return True


def _release_claim(settings: Settings, run_id: str) -> None:
    try:
        with connection(settings) as conn:
            WarehouseRepository(conn).release_alert(run_id)
    except psycopg.Error:
        log.warning("alert.release_failed", run_id=run_id)
