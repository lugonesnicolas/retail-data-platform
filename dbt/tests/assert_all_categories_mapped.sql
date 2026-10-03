{{ config(severity='warn') }}
-- Unmapped categories still flow (initcap fallback) but signal the mapping seed needs updating.
select distinct o.source, o.source_category
from {{ ref('int_product_observations') }} as o
left join {{ ref('category_mapping') }} as m
    on m.source = o.source and m.source_category = o.source_category
where m.canonical_category is null
