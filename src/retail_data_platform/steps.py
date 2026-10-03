"""Pipeline steps: the unit of work Airflow (or the CLI) orchestrates.

Each step is independently runnable and idempotent for a given ``run_id`` so that orchestrator
retries are safe. Airflow tasks call these through the ``rdp`` CLI; they contain no Airflow code.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from retail_data_platform import alerting
from retail_data_platform.config import Settings
from retail_data_platform.database import (
    PipelineOutcome,
    WarehouseRepository,
    apply_migrations,
    connection,
)
from retail_data_platform.ingestion.pipeline import IngestionResult, run_source_ingestion
from retail_data_platform.ingestion.registry import open_adapter
from retail_data_platform.models import SourceName
from retail_data_platform.observability import bind_context, get_logger
from retail_data_platform.quality import CheckStatus, QualityResult, Severity
from retail_data_platform.transform.artifacts import results_from_freshness, results_from_run
from retail_data_platform.transform.dbt_runner import run_dbt

log = get_logger(__name__)

PIPELINE_NAME = "retail_pipeline"


def default_run_id() -> str:
    return f"manual__{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"


def migrate(settings: Settings) -> list[str]:
    with connection(settings) as conn:
        return apply_migrations(conn)


def start_pipeline(settings: Settings, run_id: str, trigger: str = "manual") -> None:
    with bind_context(run_id=run_id), connection(settings) as conn:
        WarehouseRepository(conn).start_pipeline_run(
            run_id, pipeline=PIPELINE_NAME, trigger=trigger
        )
        log.info("pipeline.started", trigger=trigger)


def ingest(settings: Settings, source: SourceName, run_id: str) -> IngestionResult:
    with connection(settings) as conn, open_adapter(source, settings) as (adapter, http):
        repo = WarehouseRepository(conn)
        repo.ensure_pipeline_run(run_id, pipeline=PIPELINE_NAME, trigger="manual")
        return run_source_ingestion(
            adapter, repo, settings, pipeline_run_id=run_id, http_client=http
        )


@dataclass(frozen=True)
class TransformOutcome:
    exit_code: int
    critical_failures: int
    warnings: int


def _record(settings: Settings, run_id: str, results: list[QualityResult]) -> None:
    with connection(settings) as conn:
        repo = WarehouseRepository(conn)
        repo.ensure_pipeline_run(run_id, pipeline=PIPELINE_NAME, trigger="manual")
        with conn.transaction():
            repo.record_quality_results(results, pipeline_run_id=run_id)


def transform(
    settings: Settings,
    run_id: str,
    *,
    select: str | None = None,
    freshness: bool = False,
    full_refresh: bool = False,
) -> TransformOutcome:
    """``dbt build`` (models + tests, in DAG order), then persist the outcome as quality results."""
    target = settings.dbt_target_path.resolve()
    if freshness:
        # Freshness first, so models built below (mart_source_metrics) can include its results.
        (target / "sources.json").unlink(missing_ok=True)
        run_dbt(["source", "freshness"], settings)
        if (target / "sources.json").exists():
            _record(settings, run_id, results_from_freshness(target))

    (target / "run_results.json").unlink(missing_ok=True)
    extra: list[str] = []
    if select:
        extra += ["--select", select]
    if full_refresh:
        extra.append("--full-refresh")
    exit_code = run_dbt(["build"], settings, extra_args=extra)

    results: list[QualityResult] = []
    if (target / "run_results.json").exists():
        results.extend(results_from_run(target))
    if exit_code != 0 and not any(r.is_critical_failure for r in results):
        # dbt failed before producing node results (profile, connection, compilation...).
        results.append(
            QualityResult(
                check_name="dbt.invocation",
                layer="dbt",
                severity=Severity.CRITICAL,
                status=CheckStatus.ERROR,
                details=f"dbt build exited with code {exit_code}",
            )
        )

    _record(settings, run_id, results)
    outcome = TransformOutcome(
        exit_code=exit_code,
        critical_failures=sum(r.is_critical_failure for r in results),
        warnings=sum(
            r.severity is Severity.WARNING and r.status is not CheckStatus.PASS for r in results
        ),
    )
    log.info(
        "transform.finished",
        run_id=run_id,
        exit_code=outcome.exit_code,
        critical_failures=outcome.critical_failures,
        warnings=outcome.warnings,
    )
    return outcome


def summarize_quality(settings: Settings, run_id: str) -> list[tuple[str, str, str, str | None]]:
    """Log the run's quality picture; return its failing checks (critical first)."""
    with connection(settings) as conn:
        repo = WarehouseRepository(conn)
        counts = repo.quality_summary(run_id)
        failed = repo.failed_checks(run_id)
    log.info(
        "quality.summary",
        run_id=run_id,
        counts={f"{severity}.{status}": count for severity, status, count in counts},
        critical_failures=[name for sev, name, *_ in failed if sev == "critical"],
        warnings=[name for sev, name, *_ in failed if sev == "warning"],
    )
    return failed


def finish_pipeline(settings: Settings, run_id: str) -> PipelineOutcome:
    with bind_context(run_id=run_id), connection(settings) as conn:
        outcome = WarehouseRepository(conn).finish_pipeline_run(run_id, settings.enabled_sources)
        log.info(
            "pipeline.finished",
            status=outcome.status,
            rows_extracted=outcome.rows_extracted,
            rows_loaded=outcome.rows_loaded,
            rows_rejected=outcome.rows_rejected,
            error_summary=outcome.error_summary,
        )
    if outcome.status == "failed":
        try:
            alerting.notify_pipeline_failure(settings, run_id)
        except Exception as exc:
            # Alerting must never change or hide the pipeline's own outcome.
            log.error(
                "alert.failed",
                run_id=run_id,
                exception_type=type(exc).__name__,
                error=str(exc)[:300],
            )
    return outcome


def run_all(settings: Settings, run_id: str) -> PipelineOutcome:
    """Local equivalent of the Airflow DAG (used by CI, smoke tests and the tools container)."""
    start_pipeline(settings, run_id, trigger="cli")
    for source_name in settings.enabled_sources:
        try:
            ingest(settings, SourceName(source_name), run_id)
        except Exception as exc:
            # Mirror Airflow semantics: one failing source does not block the others.
            log.error(
                "pipeline.source_failed", source=source_name, exception_type=type(exc).__name__
            )
    transform(settings, run_id)
    summarize_quality(settings, run_id)
    transform(settings, run_id, select="tag:ops_metrics", freshness=True)
    return finish_pipeline(settings, run_id)
