# 0007 - Replay mode for deterministic runs

**Status:** Accepted

## Context
CI, demos and tests must not depend on third-party websites being up, unchanged or reachable
(some build environments block them). At the same time, mocking whole adapters would leave the
HTTP, pagination and parsing code untested in end-to-end runs.

## Decision
Add `RDP_SOURCE_MODE=replay`. The adapters are unchanged. The shared HTTP client is built with
an `httpx.MockTransport` that serves committed fixtures and emulates upstream behaviour
(DummyJSON `limit`/`skip`, static HTML tree, robots.txt 404). The default is `live`. Opt-in
`live`-marked tests check the real sites for contract drift.

## Consequences
- CI exercises the real retry, pagination, parsing, validation and loading code end to end,
  deterministically.
- Fixtures can drift from the live sites. The live tests and `SourceSchemaError` monitoring make
  that drift visible, and refreshing a fixture is a documented step.
- `source_mode` is recorded per source run, so replayed data is always distinguishable in ops
  metadata and on the dashboard.
