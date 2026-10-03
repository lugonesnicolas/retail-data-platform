# Architecture Decision Records

Short records of decisions that shape the platform: context, decision, consequences.

| # | Decision | Status |
|---|---|---|
| [0001](0001-postgresql-as-warehouse.md) | PostgreSQL as the warehouse and metadata store | Accepted |
| [0002](0002-dbt-for-transformations.md) | dbt Core for SQL transformations and tests | Accepted |
| [0003](0003-airflow-orchestrates-package-executes.md) | Airflow orchestrates; the Python package executes | Accepted |
| [0004](0004-single-vm-docker-compose.md) | Single VM with Docker Compose instead of Kubernetes | Accepted |
| [0005](0005-streamlit-dashboard.md) | Streamlit for the dashboard | Accepted |
| [0006](0006-append-only-raw-layer.md) | Append-only raw layer with content hashes | Accepted |
| [0007](0007-replay-mode-for-deterministic-runs.md) | Replay mode for deterministic runs | Accepted |
