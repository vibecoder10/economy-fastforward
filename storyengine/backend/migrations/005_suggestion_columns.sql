-- 005_suggestion_columns.sql
-- Adds agent quality + suggestion overwrite columns to videos table
-- All statements idempotent (safe to re-run)

-- =============================================
-- AGENT QUALITY COLUMNS (written by /api/agents/ routes)
-- =============================================

ALTER TABLE videos ADD COLUMN IF NOT EXISTS agent_paper_trail JSONB;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS agent_hook_score NUMERIC;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS agent_body_score NUMERIC;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS agent_tier TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS agent_cost NUMERIC;

-- =============================================
-- SUGGESTION COLUMNS (agent proposes, human approves)
-- =============================================

ALTER TABLE videos ADD COLUMN IF NOT EXISTS suggested_script TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS suggested_title TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS suggested_thumbnail_prompt TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS suggested_thumbnail_urls JSONB;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS suggestion_source TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS suggestion_scores JSONB;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS suggestion_status TEXT;
