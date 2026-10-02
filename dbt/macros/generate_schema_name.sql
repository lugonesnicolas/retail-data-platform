{#- Use the configured schema verbatim (staging, intermediate, mart, reference) instead of
    dbt's default "<target_schema>_<custom_schema>" so the warehouse layout is predictable. -#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}{{ target.schema }}{%- else -%}{{ custom_schema_name | trim }}{%- endif -%}
{%- endmacro %}
