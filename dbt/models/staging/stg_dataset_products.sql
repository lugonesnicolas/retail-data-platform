-- CSV dataset: the file's "source" column names the originating retailer.
with source as (
    select * from {{ source('raw', 'dataset_products') }}
)

select
    record_hash                                    as observation_id,
    'dataset'::text                                as source,
    source_product_id,
    product_name,
    brand,
    lower(trim(category))                          as source_category,
    raw_payload ->> 'source'                       as retailer,
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
