-- Current state of every product: its most recent observation joined to its descriptors.
with latest as (
    select
        *,
        row_number() over (
            partition by product_key order by observed_at desc, loaded_at desc, observation_id
        ) as recency_rank
    from {{ ref('fct_price_observation') }}
)

select
    p.product_key,
    p.source_key            as source,
    s.display_name          as source_name,
    p.source_product_id,
    p.product_name,
    p.brand,
    p.category,
    p.retailer,
    l.price,
    l.currency,
    l.price_usd,
    l.availability,
    l.is_available,
    l.rating,
    l.stock_quantity,
    l.discount_pct,
    p.product_url,
    l.observed_at           as last_observed_at,
    p.first_observed_at,
    p.observation_count
from latest as l
inner join {{ ref('dim_product') }} as p on p.product_key = l.product_key
inner join {{ ref('dim_source') }} as s on s.source_key = p.source_key
where l.recency_rank = 1
