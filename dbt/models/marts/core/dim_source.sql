-- One row per acquisition source, enriched with observation coverage.
with catalog as (
    select * from {{ ref('source_catalog') }}
),

coverage as (
    select
        source,
        count(distinct product_key) as product_count,
        min(observed_at)            as first_observed_at,
        max(observed_at)            as last_observed_at
    from {{ ref('int_product_observations') }}
    group by source
)

select
    c.source                             as source_key,
    c.display_name,
    c.acquisition_method,
    c.base_url,
    nullif(c.default_currency, '')       as default_currency,
    c.description,
    coalesce(cov.product_count, 0)       as product_count,
    cov.first_observed_at,
    cov.last_observed_at
from catalog as c
left join coverage as cov on cov.source = c.source
