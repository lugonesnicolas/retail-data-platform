-- Gold consistency: mart_product_latest must reflect the most recent fact row per product.
with latest_fact as (
    select product_key, max(observed_at) as max_observed_at
    from {{ ref('fct_price_observation') }}
    group by product_key
)

select m.product_key, m.last_observed_at, f.max_observed_at
from {{ ref('mart_product_latest') }} as m
inner join latest_fact as f on f.product_key = m.product_key
where m.last_observed_at <> f.max_observed_at
