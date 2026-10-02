-- A product cannot have two different prices at exactly the same observation instant.
select product_key, observed_at, count(distinct price) as distinct_prices
from {{ ref('fct_price_observation') }}
group by product_key, observed_at
having count(distinct price) > 1
