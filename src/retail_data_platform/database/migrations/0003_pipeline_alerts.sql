-- When a failure alert was sent for a run. Doubles as an idempotency claim: an alert is only
-- sent by whoever sets this column from NULL, so a run is never alerted twice.
alter table ops.pipeline_runs add column if not exists alerted_at timestamptz;
