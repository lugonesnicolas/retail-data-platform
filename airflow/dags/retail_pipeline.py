"""
### Retail data pipeline

Orchestrates the platform end-to-end. Every task is a thin call to the `rdp` CLI from the
`retail_data_platform` package - no acquisition or transformation logic lives in this file.

```
start -> [ingest_api, ingest_web, ingest_dataset] -> dbt_build -> quality_summary
      -> refresh_metrics -> end
```

* Ingestion tasks run in parallel and retry with exponential backoff (network sources).
* `dbt_build` runs even if one source failed (`all_done`), so healthy sources still reach
  the marts; the failure is recorded in `ops.source_runs` and fails the run at `end`.
* `quality_summary` fails on critical quality checks; `refresh_metrics` and `end` still run so
  the dashboard always reflects the outcome.
* `end` derives the final status from persisted metadata and fails the DAG run if needed.

Schedule: `RDP_PIPELINE_SCHEDULE` (cron or preset, default `@daily`; `none` = manual only).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG, TriggerRule

RDP = os.environ.get("RDP_CLI", "rdp")
_schedule = os.environ.get("RDP_PIPELINE_SCHEDULE", "@daily").strip()
SCHEDULE = None if _schedule.lower() in {"", "none", "manual"} else _schedule

# Templated values reach the command through environment variables, never by string
# interpolation into the shell command: a manually supplied run_id cannot inject shell code.
RUN_ENV = {"RDP_RUN_ID": "{{ run_id }}", "RDP_RUN_TYPE": "{{ dag_run.run_type }}"}


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
    ingest_api = rdp_task("ingest_api", "ingest api", **network_retry)
    ingest_web = rdp_task("ingest_web", "ingest web", **network_retry)
    ingest_dataset = rdp_task("ingest_dataset", "ingest dataset", retries=0)

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

    start >> [ingest_api, ingest_web, ingest_dataset] >> dbt_build
    dbt_build >> quality_summary >> refresh_metrics >> end
