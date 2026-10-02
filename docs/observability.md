# Observability

Lightweight on purpose: no metrics stack to operate. Everything needed to answer *"did it run,
how long did it take, how much data moved, what failed, and is the data fresh?"* is persisted in
PostgreSQL and surfaced through the marts.

| Signal | Where |
|---|---|
| Structured logs | stdout/stderr of every container (JSON); Airflow task logs |
| Pipeline run metadata | `ops.pipeline_runs` → `mart.mart_pipeline_health` |
| Source run metadata (row counts, duration, HTTP requests, errors) | `ops.source_runs` → `mart.mart_source_run_history`, `mart.mart_source_metrics` |
| Quality status | `ops.data_quality_results` → `mart.mart_data_quality`, `mart_pipeline_health.health` |
| Freshness | `dbt source freshness` results + `mart_source_metrics.hours_since_last_success` / `is_stale` |
| Service health | Docker healthchecks on every long-running service; `rdp smoke`; `deploy/scripts/healthcheck.sh` |
| Orchestration | Airflow UI (grid, durations, retries, task logs) |
| Dashboards | Streamlit **Pipeline Health** page; optional Grafana "Retail Data Platform - Operations" |

## Structured logs

All application logging goes through `structlog` (`observability/logging.py`), one JSON object
per line, never `print()`. Context is bound once and attached to every event: `run_id`,
`source`, `source_run_id`, `operation`. Operations log `started`, then `finished` or `failed`,
with a duration:

```json
{"source_mode": "replay", "run_id": "manual__20261002T031813Z", "source": "dataset",
 "source_run_id": "32d8...", "operation": "ingest", "event": "operation.finished",
 "duration_seconds": 0.025, "status": "success", "rows_extracted": 62, "rows_loaded": 59,
 "rows_duplicate": 0, "rows_rejected": 3, "level": "info", "timestamp": "2026-10-02T03:18:30Z"}
```

Failures add `exception_type` and a truncated `error`. HTTP retries log `http.retry` with the
attempt number, status code or exception, and the delay. Set `RDP_LOG_FORMAT=console` for
human-readable local output. Secrets never appear in logs: the DB password is a `SecretStr`
and is not part of the connection string.

```bash
docker compose logs airflow-scheduler | grep operation.failed     # task-level failures
docker compose exec airflow-scheduler ls /opt/airflow/logs        # Airflow task log files
```

## Useful queries

```sql
-- last 10 runs with outcome
select run_id, status, health, duration_seconds, rows_loaded, critical_failures, warnings
from mart.mart_pipeline_health order by started_at desc limit 10;

-- slowest / failing source runs this week
select source, status, duration_seconds, rows_extracted, rows_rejected, error_type, error_summary
from mart.mart_source_run_history
where started_at > now() - interval '7 days'
order by status desc, duration_seconds desc;

-- freshness
select source, last_success_at, hours_since_last_success, is_stale from mart.mart_source_metrics;
```

## Health states

`mart_pipeline_health.health`:

| Value | Meaning |
|---|---|
| `healthy` | succeeded, no failing checks |
| `warning` | succeeded with warning-level findings (e.g. rejected CSV rows) |
| `critical` | failed, or a critical check failed |
| `running` | in progress |
| `abandoned` | still `running` more than 6 h after start: the worker died before the `end` task |

## Grafana (optional)

```bash
make grafana     # docker compose --profile observability up -d grafana
```

Grafana is provisioned from `observability/grafana/`. It gets a PostgreSQL datasource using the
read-only role, and an "Operations" dashboard: last run health, stale sources, products in Gold,
critical checks (7 d), run durations, rows loaded and rejected per source run, freshness table,
and failing checks. It reads the same marts as the Streamlit dashboard, so it needs no extra
instrumentation, and it can be left disabled to save about 100 MB of RAM.

Prometheus is intentionally absent. The platform emits batch-run facts, not continuous
time-series, and those already live in PostgreSQL with full context. Prometheus would be
justified for host and container metrics at a larger scale (node-exporter or cAdvisor), or for
alerting rules.

## Alerting (not implemented)

Failures are visible (failed DAG run, `critical` health, dashboard), but nothing is pushed. The
cheapest next step is an Airflow `on_failure_callback` on the `end` task that posts
`ops.pipeline_runs.error_summary` to Slack or e-mail.
