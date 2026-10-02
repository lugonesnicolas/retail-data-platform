# 0002 - dbt Core for SQL transformations and tests

**Status:** Accepted

## Context
Transformations are relational (union, conform, dimension, aggregate) and must be testable,
documented and reviewable. Hand-written SQL scripts executed from Python would need their own
dependency ordering, testing and docs tooling.

## Decision
Use dbt Core with dbt-postgres. Raw and ops tables are dbt **sources** (with freshness). Models
are layered staging → intermediate → core → marts. Tests (generic, custom generic, singular)
live next to the models. No dbt Hub packages: the few generic tests needed are implemented
in-repo, which keeps builds offline-capable and dependency-light.

## Consequences
- `dbt build` gives dependency-ordered execution in which a failing test stops downstream models,
  plus a lineage graph and docs for free.
- Test outcomes are parsed from `run_results.json` into `ops.data_quality_results`, so dbt and
  Python checks share one quality picture.
- dbt runs in the Airflow image, in a separate virtualenv, to avoid dependency conflicts with
  Airflow.
