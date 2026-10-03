# 0005 - Streamlit for the dashboard

**Status:** Accepted

## Context
The dashboard has to show the Gold layer and pipeline health with filters, be version-controlled
next to the code, and run as a lightweight container.

## Decision
Use Streamlit with Altair charts. It reads only `mart.*` through a read-only database role,
caches query results (TTL configurable), and shows an actionable message when the warehouse is
unavailable. Grafana is offered as an optional, provisioned ops dashboard on the same marts.

## Consequences
- Dashboards are Python code: reviewable and testable, with no BI server or metadata DB.
- About 50 MB of RAM idle. Concurrency is limited compared with a BI tool, which is acceptable
  for a demo and internal audience.
- A BI tool (Superset, Metabase) would be preferable for self-service exploration by
  non-engineers.
