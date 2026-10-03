"""
### Retail data pipeline

Orchestrates the platform end-to-end. Every task is a thin call to the `rdp` CLI from the
`retail_data_platform` package - no acquisition or transformation logic lives in this file.

```
start -> [ingest_api, ingest_web, ingest_dataset] -> dbt_build -> quality_summary
      -> refresh_metrics -> end
```

* One ingestion task per source in `RDP_ENABLED_SOURCES`; they run in parallel and network
  sources retry with exponential backoff.
* `dbt_build` runs even if one source failed (`all_done`), so healthy sources still reach
  the marts; the failure is recorded in `ops.source_runs` and fails the run at `end`.
* `quality_summary` fails on critical quality checks; `refresh_metrics` and `end` still run so
  the dashboard always reflects the outcome.
* `end` derives the final status from persisted metadata and fails the DAG run if needed;
  for a failed run it also emails an alert (when SMTP is configured).
* Safety net: if the DAG run fails without `end` completing (e.g. `dagrun_timeout`), the DAG
  failure callback sends the alert. A run is never emailed twice (`ops.pipeline_runs.alerted_at`).

Schedule: `RDP_PIPELINE_SCHEDULE` (cron or preset, default `@daily`; `none` = manual only).
"""

from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime, timedelta
from typing import Any

from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG, TriggerRule

RDP = os.environ.get("RDP_CLI", "rdp")
KNOWN_SOURCES = ("api", "web", "dataset")
# Same variable the CLI uses, so the DAG and `rdp pipeline finish` agree on what is expected.
SOURCES = [
    source
    for source in (
        s.strip() for s in os.environ.get("RDP_ENABLED_SOURCES", "api,web,dataset").split(",")
    )
    if source in KNOWN_SOURCES
]
_schedule = os.environ.get("RDP_PIPELINE_SCHEDULE", "@daily").strip()
SCHEDULE = None if _schedule.lower() in {"", "none", "manual"} else _schedule

# Templated values reach the command through environment variables, never by string
# interpolation into the shell command: a manually supplied run_id cannot inject shell code.
RUN_ENV = {
    "RDP_RUN_ID": "{{ run_id }}",
    # Airflow 3 renders the enum as "DagRunType.MANUAL"; store just "manual"/"scheduled".
    "RDP_RUN_TYPE": "{{ dag_run.run_type | string | replace('DagRunType.', '') | lower }}",
}


def alert_on_failure(context: dict[str, Any]) -> None:
    """DAG failure callback: ask the CLI to email the failure report (deduplicated there)."""
    run_id = str(context["dag_run"].run_id)
    # Argument list, no shell: the run id is passed verbatim and cannot inject commands.
    subprocess.run(  # noqa: S603
        [RDP, "alert", "send", "--run-id", run_id, "--reason", "Airflow marked the run failed"],
        check=False,
        timeout=120,
    )


def rdp_task(task_id: str, args: str, **kwargs: object) -> BashOperator:
    return BashOperator(
        task_id=task_id,
        bash_command=f'{RDP} {args} --run-id "$RDP_RUN_ID"',
        env=RUN_ENV,
        append_env=True,
        **kwargs,  # type: ignore[arg-type]
    )


with DAG(
    dag_id="retail_pipeline",
    description="Ingest API/web/dataset, transform with dbt, check quality, refresh ops metrics",
    schedule=SCHEDULE,
    start_date=datetime(2026, 1, 1, tzinfo=UTC),
    catchup=False,
    max_active_runs=1,
    dagrun_timeout=timedelta(hours=2),
    on_failure_callback=alert_on_failure,
    default_args={
        "owner": "data-platform",
        "retries": 1,
        "retry_delay": timedelta(minutes=1),
        "execution_timeout": timedelta(minutes=30),
    },
    tags=["retail", "ingestion", "dbt"],
    doc_md=__doc__,
) as dag:
    start = BashOperator(
        task_id="start",
        bash_command=f'{RDP} pipeline start --run-id "$RDP_RUN_ID" --trigger "$RDP_RUN_TYPE"',
        env=RUN_ENV,
        append_env=True,
    )

    network_retry = {
        "retries": 3,
        "retry_delay": timedelta(seconds=30),
        "retry_exponential_backoff": True,
        "max_retry_delay": timedelta(minutes=10),
    }
    # Network sources retry with backoff; the local file source fails fast.
    ingest_tasks = [
        rdp_task(f"ingest_{source}", f"ingest {source}", **network_retry)
        if source != "dataset"
        else rdp_task("ingest_dataset", "ingest dataset", retries=0)
        for source in SOURCES
    ]

    dbt_build = rdp_task("dbt_build", "transform", trigger_rule=TriggerRule.ALL_DONE, retries=0)
    quality_summary = rdp_task(
        "quality_summary", "quality summarize", trigger_rule=TriggerRule.ALL_DONE, retries=0
    )
    refresh_metrics = rdp_task(
        "refresh_metrics",
        "transform --select tag:ops_metrics --freshness",
        trigger_rule=TriggerRule.ALL_DONE,
    )
    end = rdp_task("end", "pipeline finish", trigger_rule=TriggerRule.ALL_DONE, retries=0)

    start >> ingest_tasks >> dbt_build
    dbt_build >> quality_summary >> refresh_metrics >> end
