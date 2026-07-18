-- BACKGROUND_TASKS job_id uniqueness backstop (checklist C16d — S7-8 LOW fix,
-- queue/idempotency sweep, docs/reports/2026-07-17-storyengine-agent-audit-
-- findings.md §S7). db_persist_task()'s "pending" branch was a plain
-- check-then-insert (SELECT ... WHERE job_id = $1 AND status = 'pending',
-- then INSERT if not found) with no DB-level constraint behind it — two
-- concurrent calls that both pass the SELECT before either INSERTs land two
-- rows for the SAME arq job_id (the classic TOCTOU race).
--
-- Live duplicate-scan BEFORE creating this index (required by chunk spec,
-- run via Supabase MCP against wrromlupsmyzrrcqlucn):
--   SELECT job_id, count(*) FROM background_tasks
--   WHERE job_id IS NOT NULL GROUP BY job_id HAVING count(*) > 1;
-- Result: zero rows (468 total rows in background_tasks today, 0 of them
-- carry a job_id at all — arq/Redis has never actually been in the loop in
-- prod; every stage so far ran via the in-process BackgroundTasks fallback).
-- Safe to create the index with no backfill/cleanup needed.
--
-- Partial unique index (job_id IS NOT NULL) — rows from the in-process
-- fallback path never set job_id, so they're correctly never deduped by
-- this index (NULL <> NULL for uniqueness purposes). Only arq-enqueued rows,
-- which always carry a real job_id, get the protection.
--
-- Idempotent (CREATE UNIQUE INDEX IF NOT EXISTS) — safe to re-apply.

CREATE UNIQUE INDEX IF NOT EXISTS background_tasks_job_id_uidx
  ON background_tasks (job_id)
  WHERE job_id IS NOT NULL;
