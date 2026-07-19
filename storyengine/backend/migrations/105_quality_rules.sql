-- QUALITY_RULES (checklist C46b — per-channel quality-rules store).
--
-- C46a shipped the generic critic (script_quality.py::critique_script /
-- run_critique_and_edit) with a `rules_text` seam fed by a stopgap
-- (script_templates.structure, the channel's house FORMAT prose — never a
-- law/gate list). This table is the real thing: discrete, severity-tagged
-- LAW rows modeled on storyengine/notes/dvsu-quality-law.md's QL/QD row
-- shape (id / law text / evidence / severity), scoped per-video via
-- `applies_to`.
--
-- Row shape:
--   rule_id   -- a short id, e.g. "QL-12" (imported from a doc) or a
--               generated slug (chat/UI-authored rules). Unique per tenant.
--   law       -- the testable rule text (dvsu-quality-law.md's "Law
--               (testable)" column).
--   evidence  -- optional rationale/evidence text (the doc's "Evidence"
--               column) — nullable, purely explanatory, never graded.
--   severity  -- 'hard_gate' (block/reject) | 'warn' (flag, ships if
--               deliberate) | 'guidance' (a prior, never blocks) — same
--               three-tier severity dvsu-quality-law.md uses throughout.
--   source    -- 'doc_upload' (parsed from an uploaded/pasted rules doc) |
--               'chat' (authored inline via a chat op) | 'seed' (a
--               reference-tenant seed set, e.g. C46c's DvsU 74 laws).
--
-- applies_to (jsonb) — the SCOPE, resolved deterministically by
-- quality_rules.py::active_rules_for_video() against DATA the video already
-- carries (Ryan's 2026-07-19 scoping requirement: never LLM judgment about
-- WHICH gates apply — judgment lives inside gates, not about them). A rule
-- matches a video if ANY key below resolves true (OR across keys); a rule
-- with zero resolvable/recognized keys never matches (fails closed, logged,
-- never crashes). Vocabulary:
--
--   "all": true          -- universal craft gates (kill-phrase lists, closer
--                           novelty, etc.) — always true, every video.
--   "research": true      -- the video's research stage actually ran (not
--                           skipped) — resolved from videos.research_skipped
--                           (false/NULL = ran) AND videos.pipeline_stages
--                           (the per-video workflow plan; NULL plan = full
--                           pipeline = research included, else "research"
--                           must be a member). Citation/grounding/two-source
--                           laws (QL-18/19/37, QD-2/QD-4) belong here.
--   "story": true         -- narrative/documentary-arc laws (word floor,
--                           designed-vs-used twist, verdict-punch, act
--                           spine — QL-1..QL-15) — resolved from
--                           videos.render_mode = 'static_docu' today (the
--                           only channel format this signal set can identify
--                           as narrative-arc-driven; OR in more render_modes
--                           here as new arc-driven formats land — this is
--                           the one place that needs to change, not the
--                           resolver's contract).
--   "animated": true      -- videos.render_style = 'animated'.
--   "realistic": true     -- videos.render_style = 'realistic'.
--   "channel_format": "<value>" -- STRING-valued (not boolean): matches
--                           case-insensitively against this tenant's
--                           channel_profiles.channel_identity.visual_format.
--                           style. Forward-compatible stub for per-format
--                           rule sets ahead of a discrete format-id registry
--                           (channel_format.py's FORMAT_FIELDS today are
--                           free text, not an enum).
--
-- A hybrid research+narrative video (e.g. DvsU: render_mode='static_docu'
-- AND research ran) matches BOTH "research" and "story" rules — the union
-- of both scopes' laws, not either/or.
--
-- Idempotent (CREATE TABLE IF NOT EXISTS / IF NOT EXISTS index) — applied
-- LIVE via the Supabase MCP against project wrromlupsmyzrrcqlucn, confirmed
-- via information_schema.columns (same pattern as migrations 088-104).
--
-- RLS: enabled, NO policies (same playbook pattern as agent_tokens/
-- mcp_confirm_tokens/generation_claims above — the backend connects as the
-- `postgres` role, which bypasses RLS via rolbypassrls=true; this only
-- closes the public PostgREST/anon/authenticated path).

CREATE TABLE IF NOT EXISTS quality_rules (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  rule_id TEXT NOT NULL,
  law TEXT NOT NULL,
  evidence TEXT,
  severity TEXT NOT NULL CHECK (severity IN ('hard_gate', 'warn', 'guidance')),
  applies_to JSONB NOT NULL DEFAULT '{"all": true}'::jsonb,
  source TEXT NOT NULL CHECK (source IN ('doc_upload', 'chat', 'seed')),
  active BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, rule_id)
);

CREATE INDEX IF NOT EXISTS quality_rules_tenant_active_idx
  ON quality_rules (tenant_id, active);

ALTER TABLE quality_rules ENABLE ROW LEVEL SECURITY;
-- No policies (deny-all to anon/authenticated/PostgREST); backend bypasses
-- via table ownership + BYPASSRLS (see migration 083 for the proof).
