# Deployment

Production runs the base `docker-compose.yml` plus the overlay in this directory on one Ubuntu
VM. Full guide: [docs/cloud-deployment.md](../docs/cloud-deployment.md).

| File | Purpose |
|---|---|
| `docker-compose.prod.yml` | Overlay: only Caddy publishes ports (80/443), `restart: always`, log rotation, memory limits |
| `Caddyfile` | Automatic HTTPS; `DOMAIN` → dashboard, `airflow.DOMAIN` → Airflow; security headers |
| `scripts/bootstrap.sh` | One-time VM preparation (Docker, ufw, swap, deploy user, clone). Idempotent, run with sudo |
| `scripts/deploy.sh [ref]` | Update code → validate → build → `up -d --wait` (runs migrations) → health check |
| `scripts/healthcheck.sh` | Container health, HTTPS endpoints, PostgreSQL not exposed, data smoke test |
| `scripts/backup.sh` | `pg_dump -Fc` of the warehouse and Airflow DBs into `backups/`, with retention |
| `scripts/restore.sh <dump> <db> --yes` | Stops writers, restores, restarts |

```bash
# on the VM, as the deploy user
cd /opt/retail-data-platform
scripts/generate-env.sh && nano .env     # set DOMAIN and ACME_EMAIL
deploy/scripts/deploy.sh
```

Requires Docker Compose v2.24+ (the overlay uses `!reset` to drop the development port bindings).
