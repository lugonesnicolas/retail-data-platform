# 0001 - PostgreSQL as the warehouse and metadata store

**Status:** Accepted

## Context
The platform ingests hundreds to low thousands of rows per day. It needs a SQL warehouse that
dbt supports, transactional writes for operational metadata, the Airflow metadata database, and
something that runs identically on a laptop, in CI and on a small VM.

## Decision
Use one PostgreSQL 16 instance with two databases: `retail` (raw/staging/intermediate/mart/ops
schemas) and `airflow` (Airflow metadata). Each has its own role, plus a read-only role for
consumers.

## Consequences
- One stateful service to run, back up (`pg_dump`) and secure. The same engine is used in CI
  (service container) and production.
- Real constraints (unique `record_hash`, foreign keys from raw to `ops.source_runs`), `COPY`
  for bulk loads, `jsonb` for raw payloads, and advisory locks for migrations.
- Row storage and a single node limit analytical scale. Beyond tens of millions of rows, or with
  heavy concurrent analytics, a columnar warehouse would be the right move. The dbt models are
  mostly portable.
- Sharing one instance between Airflow and the warehouse couples their resources. That is
  acceptable at this size, and they are split by database and role.
