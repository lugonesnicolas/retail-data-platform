{{
    config(
        materialized='incremental',
        unique_key='observation_id',
        incremental_strategy='delete+insert',
        on_schema_change='append_new_columns'
    )
}}

-- Grain: one row per observed product state (product x source x observation).
-- Incremental: only raw rows loaded since the last build are processed.
select
    observation_id,
    product_key,
    source,
    observed_at,
    observed_date,
    price,
    currency,
    price_usd,
    availability,
    is_available,
    rating,
    stock_quantity,
    discount_pct,
    loaded_at,
    source_run_id,
    pipeline_run_id
from {{ ref('int_product_observations') }}
{% if is_incremental() %}
where loaded_at > (select coalesce(max(loaded_at), '1900-01-01'::timestamptz) from {{ this }})
{% endif %}
