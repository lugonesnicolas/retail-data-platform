# 0006 - Append-only raw layer with content hashes

**Status:** Accepted

## Context
Sources are re-fetched daily and retried on failure. The raw layer must preserve what was
observed, support price history, and make reloads safe without duplicates.

## Decision
Raw tables are append-only, one per source. Each row stores the contract-validated columns, the
full source payload (`jsonb`) and lineage metadata (`source_run_id`, `pipeline_run_id`,
`observed_at`, `ingested_at`, `loaded_at`, `source_url`). A deterministic `record_hash` (source,
product id, observation date, business attributes) is unique. Loads use `COPY` into a temp table
plus `INSERT … ON CONFLICT (record_hash) DO NOTHING` in one transaction together with the
run metadata.

## Consequences
- Re-runs and Airflow retries are idempotent: a same-day re-run adds 0 rows. Each day, or each
  change of state, adds a new observation, giving history without SCD logic in raw.
- Nothing is ever updated or deleted in raw, so downstream bugs can be fixed by rebuilding
  marts from raw.
- Observation grain is one per product per day per state. Intra-day changes back to a previous
  state are not distinguished.
- Raw grows linearly. At this volume that is negligible, and partitioning by `loaded_at` would be
  the first step at scale.
