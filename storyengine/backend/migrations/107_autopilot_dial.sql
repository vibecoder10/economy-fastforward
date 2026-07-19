-- AUTOPILOT DIAL (checklist C50, P4.2-a — schema-only groundwork for the
-- tenant autopilot P4.2 will build, C51-C56).
--
-- This chunk adds ONLY the columns + accessor; NO behavior anywhere reads
-- dial_level yet, so every existing row and every existing caller keeps
-- behaving exactly as before. The default 'propose_only' is chosen
-- specifically to be a no-op alongside today's code: nothing currently
-- gates on dial_level, so its value has zero effect until C51+ wires a
-- reader. This is the same "additive column, default preserves current
-- behavior" discipline as migration 103 (videos.max_spend).
--
-- Row shape (new columns on autopilot_config):
--   dial_level              -- the tenant's autopilot autonomy level:
--       'propose_only' (default) -- autopilot only proposes candidates; a
--                                    human launches (today's actual
--                                    behavior via POST /launch/{id}).
--       'auto_draft'              -- autopilot may create a video/draft
--                                    unattended (not built until C5x).
--       'full_auto'               -- autopilot may carry a video all the
--                                    way to publish unattended (not built
--                                    until C5x).
--   weekly_budget_cap       -- optional per-tenant weekly spend ceiling in
--                               dollars. NULL = no cap set (today's
--                               behavior for every existing row). Mirrors
--                               migration 103's videos.max_spend pattern:
--                               additive, opt-in, no ceiling until a human
--                               sets one.
--   weekly_spend_reset_at   -- when the CURRENT weekly spend window began.
--                               NULL until C54 starts maintaining it (no
--                               reader exists yet in this chunk).
--   kill_switch_tripped_at  -- stamped ONLY by the system (e.g. a budget
--                               breach or repeated pipeline failures,
--                               C5x), never by a human toggle. NULL means
--                               "not tripped" — the only state possible
--                               today, since nothing trips it yet.
--   kill_switch_reason      -- free-text explaining why the kill switch
--                               tripped (paired with kill_switch_tripped_at).
--
-- Kill switch vs. `enabled` — DISTINCT concepts, do not conflate:
--   `enabled` (pre-existing column) is the HUMAN on/off switch — a creator
--   flips it via POST /api/autopilot/toggle. The kill switch is an
--   AUTOMATIC trip recorded BY THE SYSTEM and requires an EXPLICIT human
--   RE-ENABLE (clearing kill_switch_tripped_at) before autopilot may act
--   again — tripping the kill switch never mutates `enabled`, and toggling
--   `enabled` never clears the kill switch. Two independent gates, both
--   must be "go" for autopilot to act (once a caller is built that checks
--   the kill switch at all — not this chunk).
--
-- dial_level's CHECK constraint uses the DO $$ idempotent pattern (ALTER
-- TABLE ADD CONSTRAINT has no IF NOT EXISTS form) — same house style as
-- migration 018 (competitor_videos_tenant_id_video_id_key).
--
-- Idempotent (ADD COLUMN IF NOT EXISTS / DO $$ constraint guard) — applied
-- LIVE via the Supabase MCP against project wrromlupsmyzrrcqlucn, confirmed
-- via information_schema.columns and pg_constraint (same pattern as
-- migrations 088-106).
--
-- RLS: autopilot_config already has RLS enabled with a real tenant-isolation
-- policy (see schema.sql) — these are just new columns on an existing
-- policy-covered table, no RLS change needed here.

ALTER TABLE autopilot_config ADD COLUMN IF NOT EXISTS dial_level TEXT NOT NULL DEFAULT 'propose_only';
ALTER TABLE autopilot_config ADD COLUMN IF NOT EXISTS weekly_budget_cap NUMERIC;
ALTER TABLE autopilot_config ADD COLUMN IF NOT EXISTS weekly_spend_reset_at TIMESTAMPTZ;
ALTER TABLE autopilot_config ADD COLUMN IF NOT EXISTS kill_switch_tripped_at TIMESTAMPTZ;
ALTER TABLE autopilot_config ADD COLUMN IF NOT EXISTS kill_switch_reason TEXT;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'autopilot_config_dial_level_check'
  ) THEN
    ALTER TABLE autopilot_config
      ADD CONSTRAINT autopilot_config_dial_level_check
      CHECK (dial_level IN ('propose_only', 'auto_draft', 'full_auto'));
  END IF;
END $$;
