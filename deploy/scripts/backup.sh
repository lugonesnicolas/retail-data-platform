#!/usr/bin/env bash
# Logical backups of the warehouse and Airflow metadata databases (pg_dump custom format).
#   deploy/scripts/backup.sh            -> backups/<db>-<UTC timestamp>.dump
# Retention: BACKUP_RETENTION_DAYS (default 14). Schedule via cron, e.g.:
#   15 2 * * * cd /opt/retail-data-platform && deploy/scripts/backup.sh >> backups/backup.log 2>&1
# Copy backups off the VM (e.g. az storage blob upload-batch) - a backup on the same disk is
# not disaster recovery.
# shellcheck source=deploy/scripts/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
require_env

dir="${BACKUP_DIR:-$APP_DIR/backups}"
retention="${BACKUP_RETENTION_DAYS:-14}"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$dir"
chmod 700 "$dir"

for db in "$WAREHOUSE_DB_NAME" "$AIRFLOW_DB_NAME"; do
    file="$dir/${db}-${stamp}.dump"
    log "Dumping $db -> $file"
    compose exec -T postgres pg_dump --username "$POSTGRES_SUPERUSER" --format=custom \
        --no-owner --dbname "$db" > "$file.partial"
    mv "$file.partial" "$file"
done

find "$dir" -name '*.dump' -mtime +"$retention" -print -delete | sed 's/^/pruned /'
log "Backup complete"
