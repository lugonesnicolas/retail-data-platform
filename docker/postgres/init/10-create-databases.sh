#!/usr/bin/env bash
# Runs once, on first start of an empty data volume (postgres docker-entrypoint convention).
# Creates the Airflow metadata database, the warehouse database and a read-only role for the
# dashboard/Grafana. Schema objects are created by `rdp db migrate` and dbt, not here.
set -euo pipefail

: "${AIRFLOW_DB_NAME:?}" "${AIRFLOW_DB_USER:?}" "${AIRFLOW_DB_PASSWORD:?}"
: "${WAREHOUSE_DB_NAME:?}" "${WAREHOUSE_DB_USER:?}" "${WAREHOUSE_DB_PASSWORD:?}"
: "${DASHBOARD_DB_USER:?}" "${DASHBOARD_DB_PASSWORD:?}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
    -v airflow_db="$AIRFLOW_DB_NAME" -v airflow_user="$AIRFLOW_DB_USER" \
    -v airflow_password="$AIRFLOW_DB_PASSWORD" \
    -v warehouse_db="$WAREHOUSE_DB_NAME" -v warehouse_user="$WAREHOUSE_DB_USER" \
    -v warehouse_password="$WAREHOUSE_DB_PASSWORD" \
    -v reader_user="$DASHBOARD_DB_USER" -v reader_password="$DASHBOARD_DB_PASSWORD" <<'SQL'
create role :"airflow_user" login password :'airflow_password';
create database :"airflow_db" owner :"airflow_user";
revoke all on database :"airflow_db" from public;

create role :"warehouse_user" login password :'warehouse_password';
create database :"warehouse_db" owner :"warehouse_user";
revoke all on database :"warehouse_db" from public;

-- Read-only consumer (dashboard, Grafana). dbt grants it SELECT on the mart schema only.
create role :"reader_user" login password :'reader_password';
grant connect on database :"warehouse_db" to :"reader_user";
SQL

# Nobody but the owner may create objects in the warehouse's public schema.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$WAREHOUSE_DB_NAME" \
    -c "revoke create on schema public from public;"
