-- Product dimension (type 1): latest known descriptive attributes per product and source.
with ranked as (
    select
        *,
        row_number() over (
            partition by product_key order by observed_at desc, loaded_at desc, observation_id
        ) as recency_rank,
        min(observed_at) over (partition by product_key) as first_observed_at,
        count(*) over (partition by product_key)         as observation_count
    from {{ ref('int_product_observations') }}
)

select
    product_key,
    source                  as source_key,
    source_product_id,
    product_name,
    brand,
    category,
    source_category,
    retailer,
    product_url,
    first_observed_at,
    observed_at             as last_observed_at,
    observation_count
from ranked
where recency_rank = 1
