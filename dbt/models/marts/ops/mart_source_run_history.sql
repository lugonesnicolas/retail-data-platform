-- Every source run (latest first on the dashboard). A view over ops.source_runs.
select
    source_run_id,
    pipeline_run_id,
    source,
    source_mode,
    status,
    started_at,
    finished_at,
    duration_seconds,
    rows_extracted,
    rows_valid,
    rows_loaded,
    rows_duplicate,
    rows_rejected,
    http_requests,
    error_type,
    error_summary
from {{ source('ops', 'source_runs') }}
