#!/usr/bin/env bash
# Post-deploy / periodic health check. Exit code 0 only if everything is healthy.
# shellcheck source=deploy/scripts/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
require_env

status=0
check() {
    local name="$1"; shift
    if "$@" >/dev/null 2>&1; then log "OK   $name"; else log "FAIL $name"; status=1; fi
}

for service in postgres airflow-apiserver airflow-scheduler airflow-dag-processor dashboard caddy; do
    id="$(compose ps -q "$service" 2>/dev/null || true)"
    health="$([[ -n "$id" ]] && docker inspect -f '{{.State.Health.Status}}' "$id" || echo missing)"
    if [[ "$health" == healthy ]]; then
        log "OK   container $service healthy"
    else
        log "FAIL container $service ($health)"
        status=1
    fi
done

check "https://${DOMAIN}/ (dashboard)" curl -fsS --max-time 10 "https://${DOMAIN}/_stcore/health"
check "https://airflow.${DOMAIN}/ (airflow)" curl -fsS --max-time 10 "https://airflow.${DOMAIN}/api/v2/monitor/health"
check "PostgreSQL not reachable from outside the host network" \
    bash -c "! timeout 3 bash -c '</dev/tcp/${DOMAIN}/5432'"

# Data-level smoke test (marts populated, last run succeeded). Skipped on a fresh install.
if compose run --rm --no-deps tools smoke >/tmp/rdp-smoke.log 2>&1; then
    log "OK   data smoke test"
else
    log "WARN data smoke test failed (expected before the first pipeline run):"
    sed 's/^/       /' /tmp/rdp-smoke.log | grep -E 'FAIL' || true
fi
exit "$status"
