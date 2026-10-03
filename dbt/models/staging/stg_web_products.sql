-- books.toscrape.com listings. Books have no brand; stock levels are not exposed on listings.
with source as (
    select * from {{ source('raw', 'web_products') }}
)

select
    record_hash                                    as observation_id,
    'web'::text                                    as source,
    source_product_id,
    product_name,
    brand,
    lower(trim(category))                          as source_category,
    'books.toscrape.com'::text                     as retailer,
    price,
    currency::text                                 as currency,
    availability,
    rating,
    null::integer                                  as stock_quantity,
    null::numeric(5, 2)                            as discount_pct,
    null::text                                     as sku,
    product_url,
    observed_at,
    loaded_at,
    source_run_id,
    pipeline_run_id
from source
