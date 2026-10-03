{{ config(materialized='table') }}

-- Health and freshness per source. Rebuilt by the pipeline's refresh_metrics step after
-- ingestion, transformation and quality results for the run have been recorded.
with runs as (
    select * from {{ source('ops', 'source_runs') }}
),

last_run as (
    select distinct on (source) *
    from runs
    order by source, started_at desc
),

last_success as (
    select source, max(finished_at) as last_success_at
    from runs
    where status = 'success'
    group by source
),

recent as (
    select
        source,
        count(*)                                     as runs_7d,
        count(*) filter (where status = 'failed')    as failed_runs_7d,
        coalesce(sum(rows_rejected), 0)              as rows_rejected_7d
    from runs
    where started_at >= now() - interval '7 days'
    group by source
),

checks as (
    select source, count(*) as failed_checks_7d
    from {{ source('ops', 'data_quality_results') }}
    where status in ('fail', 'error')
      and severity in ('critical', 'warning')
      and checked_at >= now() - interval '7 days'
      and source is not null
    group by source
),

observations as (
    select source, count(*) as observation_count, max(loaded_at) as last_loaded_at
    from {{ ref('fct_price_observation') }}
    group by source
)

select
    s.source_key                                                   as source,
    s.display_name,
    s.acquisition_method,
    s.product_count,
    coalesce(o.observation_count, 0)                               as observation_count,
    s.last_observed_at,
    o.last_loaded_at,
    lr.status                                                      as last_run_status,
    lr.source_mode                                                 as last_run_mode,
    lr.started_at                                                  as last_run_started_at,
    lr.duration_seconds                                            as last_run_duration_seconds,
    lr.rows_extracted                                              as last_run_rows_extracted,
    lr.rows_loaded                                                 as last_run_rows_loaded,
    lr.rows_rejected                                               as last_run_rows_rejected,
    lr.error_summary                                               as last_run_error,
    ls.last_success_at,
    round((extract(epoch from (now() - ls.last_success_at)) / 3600)::numeric, 2)
                                                                   as hours_since_last_success,
    coalesce(
        ls.last_success_at < now() - interval '{{ var("stale_after_hours") }} hours', true
    )                                                              as is_stale,
    coalesce(r.runs_7d, 0)                                         as runs_7d,
    coalesce(r.failed_runs_7d, 0)                                  as failed_runs_7d,
    coalesce(r.rows_rejected_7d, 0)                                as rows_rejected_7d,
    coalesce(c.failed_checks_7d, 0)                                as failed_checks_7d
from {{ ref('dim_source') }} as s
left join last_run as lr on lr.source = s.source_key
left join last_success as ls on ls.source = s.source_key
left join recent as r on r.source = s.source_key
left join checks as c on c.source = s.source_key
left join observations as o on o.source = s.source_key
