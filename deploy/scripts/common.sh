#!/usr/bin/env bash
# Shared helpers for the deployment scripts. Sourced, not executed.
set -euo pipefail

APP_DIR="${APP_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
cd "$APP_DIR"

COMPOSE_FILES=(-f docker-compose.yml -f deploy/docker-compose.prod.yml)
compose() { docker compose "${COMPOSE_FILES[@]}" "$@"; }

log() { printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }
die() { log "ERROR: $*" >&2; exit 1; }

require_env() {
    [[ -f .env ]] || die ".env missing in $APP_DIR (copy .env.example or run scripts/generate-env.sh)"
    if grep -qE '=CHANGE_ME' .env; then
        die ".env still contains CHANGE_ME placeholders"
    fi
    # shellcheck disable=SC1091
    set -a && source .env && set +a
    [[ "${DOMAIN:-example.com}" != "example.com" ]] || die "set DOMAIN in .env"
}
