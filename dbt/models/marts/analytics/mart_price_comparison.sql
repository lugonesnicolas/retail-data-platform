-- Per-product price history summary and position against its category.
with history as (
    select
        product_key,
        observed_at,
        price,
        price_usd,
        lag(price) over (partition by product_key order by observed_at, loaded_at) as previous_price,
        row_number() over (
            partition by product_key order by observed_at desc, loaded_at desc
        ) as recency_rank
    from {{ ref('fct_price_observation') }}
),

stats as (
    select
        product_key,
        min(price)              as min_price,
        max(price)              as max_price,
        round(avg(price), 2)    as avg_price,
        count(*)                as observation_count
    from history
    group by product_key
),

category_median as (
    select category, median_price_usd from {{ ref('mart_category_metrics') }}
)

select
    l.product_key,
    l.source,
    l.product_name,
    l.brand,
    l.category,
    l.retailer,
    l.currency,
    h.price                                                        as latest_price,
    h.previous_price,
    round(100.0 * (h.price - h.previous_price) / nullif(h.previous_price, 0), 2)
                                                                   as price_change_pct,
    s.min_price,
    s.max_price,
    s.avg_price,
    s.observation_count,
    l.price_usd                                                    as latest_price_usd,
    cm.median_price_usd                                            as category_median_price_usd,
    round(l.price_usd / nullif(cm.median_price_usd, 0), 3)         as category_price_index,
    l.last_observed_at
from {{ ref('mart_product_latest') }} as l
inner join history as h on h.product_key = l.product_key and h.recency_rank = 1
inner join stats as s on s.product_key = l.product_key
left join category_median as cm on cm.category = l.category
