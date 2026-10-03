# 0004 - Single VM with Docker Compose instead of Kubernetes

**Status:** Accepted

## Context
The deployment must be cheap, reproducible, provider-independent and operable by one person. The
workload fits comfortably in 4-8 GB of RAM.

## Decision
Deploy with Docker Compose on one Ubuntu VM: the same `docker-compose.yml` as local development,
plus a production overlay (`deploy/docker-compose.prod.yml`) that removes host ports, adds
restart policies, log limits, memory limits and Caddy for TLS. Terraform provisions the Azure VM
and network only. Idempotent shell scripts handle bootstrap, deploy, health checks and backups.
CD is a manual GitHub Actions workflow over SSH.

## Consequences
- Low cost (one small VM) and a short path from laptop to production, with identical images.
- No high availability or rolling deploys. A deploy restarts the changed containers, typically
  in under a minute. Recovery is restore from backup or rebuild and re-run.
- Kubernetes (or managed Airflow and a managed database) becomes justified with multiple
  environments and teams, an HA requirement, or workloads that need per-task resource isolation.
