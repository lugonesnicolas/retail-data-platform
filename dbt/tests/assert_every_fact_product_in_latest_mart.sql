-- No product may disappear between the fact table and the gold "latest" mart.
select distinct f.product_key
from {{ ref('fct_price_observation') }} as f
left join {{ ref('mart_product_latest') }} as m on m.product_key = f.product_key
where m.product_key is null
