{#- Surrogate key of a product within a source. Products are not matched across sources:
    the sources describe disjoint catalogues, so cross-source identity would be invented. -#}
{% macro product_key(source_col, id_col) -%}
    md5({{ source_col }} || '|' || {{ id_col }})
{%- endmacro %}
