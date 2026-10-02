-- All sources in one conformed shape: surrogate product key, canonical category, USD price.
with unioned as (
    select * from {{ ref('stg_api_products') }}
    union all
    select * from {{ ref('stg_web_products') }}
    union all
    select * from {{ ref('stg_dataset_products') }}
),

categories as (
    select source, source_category, canonical_category from {{ ref('category_mapping') }}
),

rates as (
    select currency, usd_rate from {{ ref('currency_rates') }}
)

select
    u.observation_id,
    {{ product_key('u.source', 'u.source_product_id') }} as product_key,
    u.source,
    u.source_product_id,
    u.product_name,
    u.brand,
    u.source_category,
    coalesce(c.canonical_category, initcap(u.source_category), 'Uncategorised') as category,
    u.retailer,
    u.price,
    u.currency,
    round(u.price * r.usd_rate, 2)                  as price_usd,
    u.availability,
    u.availability in ('in_stock', 'low_stock')     as is_available,
    u.rating,
    u.stock_quantity,
    u.discount_pct,
    u.product_url,
    u.observed_at,
    (u.observed_at at time zone 'UTC')::date        as observed_date,
    u.loaded_at,
    u.source_run_id,
    u.pipeline_run_id
from unioned as u
left join categories as c
    on c.source = u.source and c.source_category = u.source_category
left join rates as r
    on r.currency = u.currency
