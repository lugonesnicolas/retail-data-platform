#!/usr/bin/env bash
# Restore one database from a backup produced by backup.sh.
#   deploy/scripts/restore.sh <dump-file> <database> --yes
# Stops the services that write to the database, restores (drop + recreate objects), restarts.
# shellcheck source=deploy/scripts/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
require_env

file="${1:?usage: restore.sh <dump-file> <database> --yes}"
db="${2:?usage: restore.sh <dump-file> <database> --yes}"
[[ "${3:-}" == "--yes" ]] || die "restoring overwrites $db; re-run with --yes to confirm"
[[ -f "$file" ]] || die "no such file: $file"
case "$db" in
    "$WAREHOUSE_DB_NAME") owner="$WAREHOUSE_DB_USER" ;;
    "$AIRFLOW_DB_NAME") owner="$AIRFLOW_DB_USER" ;;
    *) die "unknown database $db" ;;
esac

log "Stopping writers"
compose stop airflow-scheduler airflow-dag-processor airflow-apiserver dashboard

log "Restoring $file into $db"
compose exec -T postgres pg_restore --username "$POSTGRES_SUPERUSER" --dbname "$db" \
    --clean --if-exists --no-owner --role "$owner" --exit-on-error < "$file"

log "Restarting services"
compose up -d --wait
log "Restore complete - run deploy/scripts/healthcheck.sh"
