"""``rdp`` command-line interface - the single entry point used by Airflow, Docker and humans."""

from __future__ import annotations

from typing import Annotated

import typer

from retail_data_platform import steps
from retail_data_platform.config import get_settings
from retail_data_platform.database import wait_for_database
from retail_data_platform.ingestion.pipeline import IngestionFailedError
from retail_data_platform.models import SourceName
from retail_data_platform.observability import configure_logging, get_logger
from retail_data_platform.smoke import run_smoke_checks

app = typer.Typer(help="Retail Data Platform CLI", no_args_is_help=True, add_completion=False)
db_app = typer.Typer(help="Database administration", no_args_is_help=True)
pipeline_app = typer.Typer(help="Pipeline run lifecycle", no_args_is_help=True)
quality_app = typer.Typer(help="Data quality", no_args_is_help=True)
app.add_typer(db_app, name="db")
app.add_typer(pipeline_app, name="pipeline")
app.add_typer(quality_app, name="quality")

log = get_logger("rdp.cli")

RunIdOption = Annotated[
    str | None,
    typer.Option(
        "--run-id", help="Pipeline run id (Airflow passes its run_id). Default: manual__<ts>"
    ),
]


@app.callback()
def _setup() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)


def _run_id(value: str | None) -> str:
    return value or steps.default_run_id()


# ------------------------------------------------------------------------------------------ db
@db_app.command("wait")
def db_wait(timeout: Annotated[float, typer.Option(help="Seconds to wait")] = 60.0) -> None:
    """Block until the warehouse database accepts connections."""
    wait_for_database(get_settings(), timeout)


@db_app.command("migrate")
def db_migrate(
    wait: Annotated[float, typer.Option(help="Wait up to N seconds for the database")] = 60.0,
) -> None:
    """Apply pending SQL migrations (idempotent, safe to run concurrently)."""
    settings = get_settings()
    wait_for_database(settings, wait)
    applied = steps.migrate(settings)
    typer.echo(f"applied migrations: {applied or 'none (up to date)'}")


# -------------------------------------------------------------------------------------- ingest
@app.command()
def ingest(
    sources: Annotated[
        list[str], typer.Argument(help="api, web, dataset or 'all' (enabled sources)")
    ],
    run_id: RunIdOption = None,
) -> None:
    """Ingest one or more sources into the raw layer."""
    settings = get_settings()
    rid = _run_id(run_id)
    selected = settings.enabled_sources if sources == ["all"] else sources
    failed: list[str] = []
    for name in selected:
        try:
            source = SourceName(name)
        except ValueError as exc:
            raise typer.BadParameter(f"unknown source {name!r}") from exc
        try:
            result = steps.ingest(settings, source, rid)
            typer.echo(
                f"{name}: extracted={result.rows_extracted} loaded={result.rows_loaded} "
                f"duplicates={result.rows_duplicate} rejected={result.rows_rejected}"
            )
        except IngestionFailedError as exc:
            typer.echo(f"{name}: FAILED - {exc}", err=True)
            failed.append(name)
        except Exception as exc:
            typer.echo(f"{name}: FAILED - {type(exc).__name__}: {exc}", err=True)
            failed.append(name)
    if failed:
        raise typer.Exit(code=1)


# ----------------------------------------------------------------------------------- transform
@app.command()
def transform(
    run_id: RunIdOption = None,
    select: Annotated[str | None, typer.Option(help="dbt node selection")] = None,
    freshness: Annotated[bool, typer.Option(help="Also run dbt source freshness")] = False,
    full_refresh: Annotated[bool, typer.Option(help="Rebuild incremental models")] = False,
) -> None:
    """Run dbt build and record test outcomes in ops.data_quality_results."""
    outcome = steps.transform(
        get_settings(),
        _run_id(run_id),
        select=select,
        freshness=freshness,
        full_refresh=full_refresh,
    )
    if outcome.exit_code != 0:
        raise typer.Exit(code=outcome.exit_code)


# ------------------------------------------------------------------------------------- quality
@quality_app.command("summarize")
def quality_summarize(
    run_id: Annotated[str, typer.Option("--run-id", help="Pipeline run id")],
) -> None:
    """Print the run's failing checks; exit 1 if any critical check failed."""
    failed = steps.summarize_quality(get_settings(), run_id)
    if not failed:
        typer.echo("all quality checks passed")
    for severity, name, source, details in failed:
        typer.echo(f"[{severity.upper():8}] {name} ({source}) {details or ''}".rstrip())
    if any(severity == "critical" for severity, *_ in failed):
        raise typer.Exit(code=1)


# ------------------------------------------------------------------------------------ pipeline
@pipeline_app.command("start")
def pipeline_start(
    run_id: RunIdOption = None,
    trigger: Annotated[str, typer.Option(help="scheduled | manual | cli")] = "manual",
) -> None:
    """Register a pipeline run in ops.pipeline_runs."""
    rid = _run_id(run_id)
    steps.start_pipeline(get_settings(), rid, trigger)
    typer.echo(rid)


@pipeline_app.command("finish")
def pipeline_finish(run_id: Annotated[str, typer.Option("--run-id")]) -> None:
    """Derive and persist the final run status; exit 1 if the run failed."""
    outcome = steps.finish_pipeline(get_settings(), run_id)
    typer.echo(f"{outcome.run_id}: {outcome.status}")
    if outcome.status != "success":
        typer.echo(outcome.error_summary or "", err=True)
        raise typer.Exit(code=1)


@pipeline_app.command("run")
def pipeline_run(run_id: RunIdOption = None) -> None:
    """Run the whole pipeline locally, in the same order as the Airflow DAG."""
    outcome = steps.run_all(get_settings(), _run_id(run_id))
    typer.echo(
        f"{outcome.run_id}: {outcome.status} (extracted={outcome.rows_extracted} "
        f"loaded={outcome.rows_loaded} rejected={outcome.rows_rejected})"
    )
    if outcome.status != "success":
        typer.echo(outcome.error_summary or "", err=True)
        raise typer.Exit(code=1)


# --------------------------------------------------------------------------------------- smoke
@app.command()
def smoke(
    dashboard_url: Annotated[str | None, typer.Option(help="e.g. http://localhost:8501")] = None,
    airflow_url: Annotated[str | None, typer.Option(help="e.g. http://localhost:8080")] = None,
) -> None:
    """End-to-end smoke checks against the marts (and optionally the web UIs)."""
    failures = 0
    for check in run_smoke_checks(
        get_settings(), dashboard_url=dashboard_url, airflow_url=airflow_url
    ):
        typer.echo(f"[{'PASS' if check.ok else 'FAIL'}] {check.name}: {check.detail}")
        failures += not check.ok
    if failures:
        raise typer.Exit(code=1)


if __name__ == "__main__":  # pragma: no cover
    app()
