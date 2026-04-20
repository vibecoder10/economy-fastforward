-- Migration 042: index background_tasks.created_at
-- Stage 2.3 fix. Enables:
--   1. Ordering by recency (ORDER BY created_at DESC LIMIT N) for ops/debug queries
--   2. Future cleanup/TTL job (DELETE WHERE created_at < NOW() - INTERVAL 'N days')
--   3. Activity-feed-style queries that join on the task row
-- DESC because cleanup scans oldest-first but range-prunes with < comparisons on
-- created_at, and activity feeds read newest-first. Bidirectional index scans
-- work on either direction but DESC matches the hot path.
--
-- Safe to re-run. Small table (< 50k rows in prod today), so index build is
-- instant.
--
-- Note on tenant_usage.period_start (also flagged by Stage 2.3): already
-- covered by idx_tenant_usage_tenant_period from migration 024 — the
-- composite (tenant_id, period_start) serves every real query, all of
-- which are tenant-scoped.

CREATE INDEX IF NOT EXISTS idx_bg_tasks_created_at
    ON background_tasks (created_at DESC);
