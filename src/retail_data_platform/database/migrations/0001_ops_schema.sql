-- Operational metadata: one row per pipeline run, per source run and per quality check.
create schema if not exists ops;

create table if not exists ops.pipeline_runs (
    run_id            text primary key,
    pipeline          text        not null,
    trigger           text        not null default 'manual',
    status            text        not null check (status in ('running', 'success', 'failed')),
    started_at        timestamptz not null default now(),
    finished_at       timestamptz,
    duration_seconds  numeric(12, 3) generated always as
                          (extract(epoch from (finished_at - started_at))) stored,
    rows_extracted    integer,
    rows_loaded       integer,
    rows_rejected     integer,
    error_summary     text,
    metadata          jsonb       not null default '{}'::jsonb
);

create index if not exists pipeline_runs_started_at_idx on ops.pipeline_runs (started_at desc);

create table if not exists ops.source_runs (
    source_run_id     uuid primary key default gen_random_uuid(),
    pipeline_run_id   text references ops.pipeline_runs (run_id) on delete set null,
    source            text        not null check (source in ('api', 'web', 'dataset')),
    source_mode       text        not null check (source_mode in ('live', 'replay')),
    status            text        not null check (status in ('running', 'success', 'failed')),
    started_at        timestamptz not null default now(),
    finished_at       timestamptz,
    duration_seconds  numeric(12, 3) generated always as
                          (extract(epoch from (finished_at - started_at))) stored,
    rows_extracted    integer     not null default 0,
    rows_valid        integer     not null default 0,
    rows_loaded       integer     not null default 0,
    rows_duplicate    integer     not null default 0,
    rows_rejected     integer     not null default 0,
    http_requests     integer,
    error_type        text,
    error_summary     text
);

create index if not exists source_runs_source_started_idx on ops.source_runs (source, started_at desc);
create index if not exists source_runs_pipeline_run_idx on ops.source_runs (pipeline_run_id);

create table if not exists ops.data_quality_results (
    id                bigint generated always as identity primary key,
    pipeline_run_id   text references ops.pipeline_runs (run_id) on delete set null,
    source_run_id     uuid references ops.source_runs (source_run_id) on delete set null,
    check_name        text        not null,
    layer             text        not null check (layer in ('ingestion', 'dbt', 'freshness', 'pipeline')),
    severity          text        not null check (severity in ('critical', 'warning', 'info')),
    status            text        not null check (status in ('pass', 'fail', 'error', 'skipped')),
    source            text,
    observed_value    numeric,
    threshold         numeric,
    details           text,
    checked_at        timestamptz not null default now()
);

create index if not exists dq_results_run_idx on ops.data_quality_results (pipeline_run_id);
create index if not exists dq_results_checked_at_idx on ops.data_quality_results (checked_at desc);
