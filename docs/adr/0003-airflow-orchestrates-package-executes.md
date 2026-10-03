# 0003 - Airflow orchestrates; the Python package executes

**Status:** Accepted

## Context
Airflow DAGs that embed scraping, validation or SQL become hard to test (they need an Airflow
runtime), hard to reuse outside Airflow, and tightly coupled to Airflow upgrades.

## Decision
All logic lives in the `retail_data_platform` package, exposed through the `rdp` CLI. The DAG
contains only scheduling concerns: dependencies, retries with exponential backoff, trigger rules
and timeouts. Each task is a `BashOperator` running one `rdp` command, with the run id passed
via environment variables. Airflow 3 runs with the **LocalExecutor** and PostgreSQL metadata.
The package and dbt are installed in an isolated virtualenv inside the Airflow image.

The final run status is derived from persisted ops metadata (`rdp pipeline finish`), not from
Airflow task states, so `rdp pipeline run` (CLI only) and the DAG reach the same verdict.

## Consequences
- The whole pipeline is testable with pytest and runnable without Airflow (CI does exactly that).
- Swapping the orchestrator (Dagster, Prefect, cron) means rewriting one small DAG file.
- The LocalExecutor runs tasks inside the scheduler container: there are no Celery or Redis
  services to operate, at the cost of horizontal scalability, which this workload does not need.
- BashOperator gives no Python-level XCom typing. That is fine here, because the tasks
  communicate through the database.
