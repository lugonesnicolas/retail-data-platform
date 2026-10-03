{% macro grant_read_access(schemas, role) %}
    {%- if role and execute -%}
        {%- set role_ident = adapter.quote(role) -%}
        do $grant$
        begin
            if exists (select 1 from pg_roles where rolname = {{ dbt.string_literal(role) }}) then
            {%- for schema in schemas %}
                execute 'grant usage on schema {{ schema }} to {{ role_ident }}';
                execute 'grant select on all tables in schema {{ schema }} to {{ role_ident }}';
            {%- endfor %}
            end if;
        end
        $grant$;
    {%- else -%}
        select 1
    {%- endif -%}
{% endmacro %}
