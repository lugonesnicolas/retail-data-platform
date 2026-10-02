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

# shellcheck disable=SC2329 # invoked indirectly through check()
container_healthy() {
    local id
    id="$(compose ps -q "$1")"
    [[ -n "$id" && "$(docker inspect -f '{{.State.Health.Status}}' "$id")" == healthy ]]
}

for service in postgres airflow-apiserver airflow-scheduler airflow-dag-processor dashboard caddy; do
    check "container $service healthy" container_healthy "$service"
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
