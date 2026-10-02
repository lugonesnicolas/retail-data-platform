-- Quality check results across layers (ingestion, dbt, freshness) with run context.
select
    q.id                   as result_id,
    q.pipeline_run_id,
    p.started_at           as pipeline_started_at,
    q.check_name,
    q.layer,
    q.severity,
    q.status,
    q.source,
    q.observed_value,
    q.threshold,
    q.details,
    q.checked_at
from {{ source('ops', 'data_quality_results') }} as q
left join {{ source('ops', 'pipeline_runs') }} as p on p.run_id = q.pipeline_run_id
