-- One row per pipeline run with its quality outcome. A view, so it is always current.
with quality as (
    select
        pipeline_run_id,
        count(*)                                                                as checks_total,
        count(*) filter (where severity = 'critical' and status in ('fail', 'error'))
                                                                                as critical_failures,
        count(*) filter (where severity = 'warning' and status in ('fail', 'error'))
                                                                                as warnings
    from {{ source('ops', 'data_quality_results') }}
    group by pipeline_run_id
),

sources as (
    select
        pipeline_run_id,
        count(*)                                     as source_runs,
        count(*) filter (where status = 'failed')    as failed_source_runs
    from {{ source('ops', 'source_runs') }}
    group by pipeline_run_id
)

select
    p.run_id,
    p.pipeline,
    p.trigger,
    p.status,
    p.started_at,
    p.finished_at,
    p.duration_seconds,
    coalesce(p.rows_extracted, 0)       as rows_extracted,
    coalesce(p.rows_loaded, 0)          as rows_loaded,
    coalesce(p.rows_rejected, 0)        as rows_rejected,
    coalesce(s.source_runs, 0)          as source_runs,
    coalesce(s.failed_source_runs, 0)   as failed_source_runs,
    coalesce(q.checks_total, 0)         as checks_total,
    coalesce(q.critical_failures, 0)    as critical_failures,
    coalesce(q.warnings, 0)             as warnings,
    case
        -- A run still 'running' long after it started was killed without reaching its end task.
        when p.status = 'running' and p.started_at < now() - interval '6 hours' then 'abandoned'
        when p.status = 'running' then 'running'
        when p.status = 'failed' or coalesce(q.critical_failures, 0) > 0 then 'critical'
        when coalesce(q.warnings, 0) > 0 then 'warning'
        else 'healthy'
    end                                 as health,
    p.error_summary
from {{ source('ops', 'pipeline_runs') }} as p
left join quality as q on q.pipeline_run_id = p.run_id
left join sources as s on s.pipeline_run_id = p.run_id
