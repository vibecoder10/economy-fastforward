-- D5-A2: Frame Arbiter learning-ratchet memory (storyengine/FRAME-ARBITER-
-- PLAN.md, "Learning-ratchet mechanics" section — the law this table
-- implements). The arbiter judge (A3/A4, not built yet) will call a
-- vision check on every new frame and classify each finding into one of
-- three buckets (MODEL_DEFECT / AUTHORING_DEFECT / TASTE_QUESTION, DoC #2).
-- This table is its MEMORY: without it, a recurring model defect would get
-- redrawn forever (an unbounded spend loop — Ryan's explicit law this
-- mission exists to prevent).
--
-- Fingerprint law (verbatim from the plan, DO NOT reinterpret): fingerprint
-- = (rule_id or failure_class, stage, failure_class). Computed identically
-- every time, no free text in the key. `fingerprint_key` below is a STORED
-- generated column (COALESCE(rule_id, failure_class)) — Postgres computes
-- it the same way on every write, so the app layer (arbiter_fingerprints.py)
-- never has to keep a second, driftable copy of that logic in sync; its own
-- `fingerprint_key()` helper exists only so callers can compute the SAME
-- value for read-path filtering without an extra round trip, using the
-- identical expression.
--
--   rule_id        -- optional: the quality_rules.rule_id this finding is
--                     tied to, when an authored rule exists (e.g. a Ryan
--                     ruling entered via upsert_quality_rule). NULL when
--                     the finding has no authored rule yet (a raw
--                     failure_class is the whole identity in that case).
--                     Deliberately NOT a foreign key to quality_rules: a
--                     fingerprint must be recordable before any rule gets
--                     authored for it (that's the whole point of
--                     AUTHORING_DEFECT findings feeding a future rule), so
--                     coupling the two tables' write order would break the
--                     mission's own escalation path.
--   stage           -- pipeline stage the finding fired in (e.g. the new
--                     generation_ledger 'frame_qa' stage A1 is adding).
--                     Free TEXT, not an enum — new stages can appear
--                     without a migration, same latitude quality_rules.
--                     applies_to's string-valued keys get.
--   failure_class   -- the specific defect taxonomy tag (e.g.
--                     'continuity_drift', 'character_off_model') — distinct
--                     from `classification` below: this is WHAT went wrong,
--                     classification is WHICH of the three buckets it
--                     sorts into (and therefore what action, if any, may
--                     fire).
--   fingerprint_key -- GENERATED ALWAYS AS COALESCE(rule_id, failure_class)
--                     STORED. The actual uniqueness/lookup key together
--                     with stage + failure_class.
--   classification  -- MODEL_DEFECT | AUTHORING_DEFECT | TASTE_QUESTION
--                     (DoC #2's three-way bucket). Only MODEL_DEFECT may
--                     ever reach redraw_shot (A5, not built here) — an
--                     invalid value is rejected by both this CHECK and
--                     arbiter_fingerprints.py's own pre-flight raise
--                     (never silently coerced, unlike quality_rules.
--                     create_rule's severity fallback: a wrong bucket here
--                     can misdirect real spend, so this fails loud instead
--                     of soft).
--   violation_count -- how many times THIS exact fingerprint has fired.
--                     Starts at 1 on first insert, +1 on every repeat
--                     occurrence (ON CONFLICT DO UPDATE, mirrors
--                     quality_rules.py's create_rule upsert pattern
--                     exactly — same file's docstring names it as the
--                     precedent to follow).
--   frozen          -- true from the moment violation_count reaches 2
--                     onward (DoC #4: "the same fingerprint firing twice
--                     freezes auto-repair for that class and files a
--                     root-cause finding instead of a third redraw").
--                     Precedent this deliberately does NOT copy:
--                     migrations/118_motion_gate_status.sql's
--                     motion_gate_status freezes one SHOT after two
--                     attempts on that shot; this freezes one CLASS across
--                     every scene/video for the tenant, forever (no
--                     unfreeze path in this chunk — only a human editing
--                     the upstream rule, per the contract-triangle law,
--                     should ever move it back).
--   root_cause_finding_id -- pointer to the root-cause finding this
--                     fingerprint's freeze event filed (A5's job, not
--                     built here — this chunk only reserves the column).
--                     No FK: the findings table this will point at doesn't
--                     exist yet (A3/A5 build it), and a finding may live in
--                     a table shaped however that chunk decides.
--
-- RLS: enabled + REVOKE ALL FROM anon, authenticated (no policies) — the
-- exact pattern the NEWEST migration at the time of writing
-- (138_custom_film_scene_storyboards.sql) uses, not the older
-- enable-only style (105_quality_rules.sql). Backend bypasses via table
-- ownership + BYPASSRLS (migration 083's proof).
--
-- $0 to build. No paid calls. Nothing in the product calls this table yet
-- (A3/A5 will) — pure data-layer chunk.

BEGIN;

CREATE TABLE IF NOT EXISTS arbiter_fingerprints (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  rule_id TEXT,
  stage TEXT NOT NULL CHECK (length(stage) > 0),
  failure_class TEXT NOT NULL CHECK (length(failure_class) > 0),
  fingerprint_key TEXT GENERATED ALWAYS AS (COALESCE(rule_id, failure_class)) STORED,
  classification TEXT NOT NULL CHECK (classification IN ('MODEL_DEFECT', 'AUTHORING_DEFECT', 'TASTE_QUESTION')),
  violation_count INTEGER NOT NULL DEFAULT 1 CHECK (violation_count >= 1),
  frozen BOOLEAN NOT NULL DEFAULT false,
  root_cause_finding_id UUID,
  first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, fingerprint_key, stage, failure_class)
);

CREATE INDEX IF NOT EXISTS arbiter_fingerprints_tenant_frozen_idx
  ON arbiter_fingerprints (tenant_id, frozen);

ALTER TABLE arbiter_fingerprints ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON arbiter_fingerprints FROM anon, authenticated;

COMMIT;
