-- Category-level price and availability profile across all sources (USD-normalised).
select
    category,
    count(*)                                                     as product_count,
    count(distinct source)                                       as source_count,
    string_agg(distinct source, ', ' order by source)            as sources,
    count(distinct brand)                                        as brand_count,
    round(avg(price_usd), 2)                                     as avg_price_usd,
    round((percentile_cont(0.5) within group (order by price_usd))::numeric, 2)
                                                                 as median_price_usd,
    min(price_usd)                                               as min_price_usd,
    max(price_usd)                                               as max_price_usd,
    round(avg(case when is_available then 1.0 else 0.0 end), 4) as availability_ratio,
    round(avg(rating), 2)                                        as avg_rating,
    max(last_observed_at)                                        as last_observed_at
from {{ ref('mart_product_latest') }}
group by category
