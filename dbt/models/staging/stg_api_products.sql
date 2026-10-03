-- DummyJSON products: canonical columns plus API-specific attributes from the raw payload.
with source as (
    select * from {{ source('raw', 'api_products') }}
)

select
    record_hash                                    as observation_id,
    'api'::text                                    as source,
    source_product_id,
    product_name,
    brand,
    lower(trim(category))                          as source_category,
    'dummyjson.com'::text                          as retailer,
    price,
    currency::text                                 as currency,
    availability,
    rating,
    (raw_payload ->> 'stock')::integer             as stock_quantity,
    (raw_payload ->> 'discountPercentage')::numeric(5, 2) as discount_pct,
    raw_payload ->> 'sku'                          as sku,
    product_url,
    observed_at,
    loaded_at,
    source_run_id,
    pipeline_run_id
from source
