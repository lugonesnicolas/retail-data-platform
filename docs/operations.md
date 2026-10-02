# Operations runbook

Commands assume the repository root. In production, prefix compose commands with the overlay:
`docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml …` (the scripts in
`deploy/scripts/` already do this).

## Daily operation

| Task | Command |
|---|---|
| Start / stop | `make up` / `make down` (data kept) |
| Status | `make ps`, `deploy/scripts/healthcheck.sh` (prod) |
| Trigger the pipeline and wait | `make pipeline` (or **Trigger** in the Airflow UI) |
| Run without Airflow | `make pipeline-local` |
| Smoke test | `make smoke` |
| Follow logs | `make logs` or `docker compose logs -f airflow-scheduler` |
| Ad-hoc CLI | `docker compose run --rm tools <args>` e.g. `tools quality summarize --run-id <id>` |
| Backup | `deploy/scripts/backup.sh` |

The schedule comes from `RDP_PIPELINE_SCHEDULE` (default `@daily`, UTC). After changing it, run
`docker compose up -d` so the Airflow services pick up the new environment.

## Re-running safely

Every step is idempotent for a given run id:

- Re-running an ingestion task appends only unseen `record_hash`es, so a same-day re-run adds 0
  rows. Each attempt creates a new `ops.source_runs` row, and the latest attempt per source
  decides the run's status.
- `dbt build` is deterministic. The incremental fact uses `delete+insert` on `observation_id`.
  To rebuild everything, run `docker compose run --rm tools transform --full-refresh`.
- `pipeline start` on an existing run id resets it to `running`, and `pipeline finish`
  recomputes the status.

To re-run a failed DAG run, use **Clear** on the failed task in the Airflow UI ("downstream"
selected), or trigger a new run.

**Backfills.** The API and web sources are point-in-time snapshots of the current state, so a
historical date cannot be re-fetched. `catchup=False` is intentional. History accumulates one
observation per day going forward. The CSV dataset carries its own `observed_at` values.

## Failure scenarios

### A source is down or slow (`ingest_api` / `ingest_web` failed)
1. The HTTP client already retried with backoff (`http.retry` log lines), and Airflow retried the
   task 3 times with exponential backoff.
2. `select * from mart.mart_source_run_history where status='failed' order by started_at desc limit 5;`
   shows `error_type` (e.g. `AcquisitionError`, `ConnectTimeout`) and the message.
3. The other sources still loaded, and dbt still built (`all_done`). The run ends `failed`, and
   the dashboard shows the source as stale after 26 h.
4. Remedy: wait and re-run. If the outage persists, remove the source from `RDP_ENABLED_SOURCES`
   temporarily.

### Quality gate blocked a batch (`QualityGateFailed`)
1. `rdp quality summarize --run-id <id>` lists `ingestion.reject_ratio` or
   `ingestion.min_rows_extracted`.
2. Inspect the rejects:
   `select errors, raw_payload from raw.rejected_records where pipeline_run_id='<id>' limit 20;`
3. If the source changed its format, adapt the adapter/contract and add a fixture plus a test.
   If the rejects are genuinely bad data, the gate did its job: nothing was loaded.

### Source structure changed (`SourceSchemaError`)
The API envelope, the HTML layout or the CSV header no longer matches. Capture a new fixture
(`data/fixtures/…`), update the parser or schema, and extend the parser tests.

### dbt test failure (`quality_summary` failed)
1. `select check_name, details from mart.mart_data_quality where pipeline_run_id='<id>' and severity='critical' and status in ('fail','error');`
2. Reproduce: `docker compose run --rm tools transform --select <model>+`
3. Inspect the failing rows with `dbt test --select <test> --store-failures` from a dev
   environment.

### Run stuck in `running` / health `abandoned`
The scheduler container died mid-run. Restart it (`docker compose up -d airflow-scheduler`),
mark the Airflow run failed, and trigger a new one. The abandoned row stays in `ops` as history.

### Database unavailable
The dashboard shows "warehouse is not reachable". Check `docker compose ps postgres` and
`docker compose logs postgres`, then disk space (`df -h`, `docker system df`).

### Disk filling up
- Logs are bounded (json-file, 5 × 20 MB per container in prod).
- `docker image prune -f` removes old images (deploy does this for images older than 7 days).
- Airflow task logs live in the `airflow-logs` volume. Prune them with
  `docker compose exec airflow-scheduler find /opt/airflow/logs -mtime +30 -delete`.
- Backups older than `BACKUP_RETENTION_DAYS` are pruned by `backup.sh`.

## Backup and restore

```bash
deploy/scripts/backup.sh                         # pg_dump -Fc of warehouse + airflow DBs → backups/
deploy/scripts/restore.sh backups/retail-20261002T021500Z.dump retail --yes
```

Schedule backups with cron on the VM:

```
15 2 * * * cd /opt/retail-data-platform && deploy/scripts/backup.sh >> backups/backup.log 2>&1
```

Copy `backups/` off the VM (Azure Blob, S3, rsync). A backup on the same disk does not protect
against losing the VM. The warehouse can also be rebuilt from scratch: migrations plus a pipeline
run reconstruct everything except the observation history.

## Secret rotation

1. Generate a new value: `od -An -N24 -tx1 /dev/urandom | tr -d ' \n'`.
2. Database roles: `docker compose exec postgres psql -U postgres -c "alter role retail password '<new>'"`,
   then update `.env`.
3. Update `.env` and run `docker compose up -d` (and `deploy/scripts/deploy.sh` in prod).
4. Do not change `AIRFLOW_FERNET_KEY` casually: it encrypts Airflow connections. Rotate it with
   `airflow rotate-fernet-key` using a comma-separated new,old key.

Note: the PostgreSQL init script runs only on an empty volume. Changing passwords in `.env`
later requires the `alter role` above.

## Known limitations

- No push alerting. Failures are visible in Airflow and on the dashboard, but nothing notifies
  anyone.
- Single VM: no high availability. Recovery is restore-from-backup or rebuild-and-re-run.
- Static FX rates for cross-currency comparisons.
- Live scraping depends on books.toscrape.com and dummyjson.com staying up and stable. Replay
  mode exists for deterministic demos.
- Changing the CSV dataset content re-inserts the changed rows as new observations, which is the
  append-only, by-design behaviour.
