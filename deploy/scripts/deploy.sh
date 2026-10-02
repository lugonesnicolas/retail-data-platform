#!/usr/bin/env bash
# Deploy or update the platform on the VM. Safe to re-run.
#   deploy/scripts/deploy.sh [git-ref]      (default: current branch, fast-forward only)
# Steps: update code -> validate config -> build images -> migrate (one-shot service) ->
#        rolling restart via compose -> health checks.
# shellcheck source=deploy/scripts/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

ref="${1:-}"
require_env

log "Updating code"
if [[ -n "$ref" ]]; then
    git fetch --quiet origin "$ref"
    git checkout --quiet --detach FETCH_HEAD
else
    git pull --ff-only --quiet
fi
log "Deploying commit $(git rev-parse --short HEAD)"

log "Validating compose configuration"
compose config --quiet

log "Building images"
compose build --pull

log "Starting services (migrations run in the one-shot 'migrate' service)"
compose up -d --wait --remove-orphans

"$(dirname "${BASH_SOURCE[0]}")/healthcheck.sh"
docker image prune -f --filter "until=168h" >/dev/null
log "Deployment of $(git rev-parse --short HEAD) complete"
