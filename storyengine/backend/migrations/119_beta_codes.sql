-- Beta access codes — launch beta wiring: submitting a valid code on
-- email/password signup (POST /api/auth/register) grants a longer free
-- trial instead of the default TRIAL_DAYS (7). See
-- backend/routes/google_auth.py::register() for the redeem call site.
--
-- Design: redemption is ONE atomic
--   UPDATE beta_codes SET redemptions_used = redemptions_used + 1
--     WHERE code = $1 AND active = TRUE
--       AND (max_redemptions IS NULL OR redemptions_used < max_redemptions)
--   RETURNING trial_days
-- — the same "row-count/returned-row IS the check" pattern as
-- confirm_tokens.redeem() and agent_tokens' revoke: no read-then-write race
-- between two signups hitting the same code at once, and no separate cap
-- check that could disagree with the increment. A missing row (bad code,
-- inactive, or cap already hit) falls back to the normal TRIAL_DAYS grant —
-- signup itself is NEVER blocked by a bad/dead/exhausted code.
--
-- active: instant kill switch — flip to FALSE and the code stops granting
-- with no redeploy.
-- max_redemptions: NULL = unlimited. Set a number to cap a promo; the
-- redeem UPDATE's WHERE clause enforces the cap atomically (no redeploy
-- needed to add/lower a cap either).
-- code: stored lowercased; register() lowercases+trims the submitted code
-- before matching, so casing/whitespace from the user never misses a match.
--
-- accounts.beta_code: which code (if any) an account redeemed at signup.
-- NULL for every account that didn't submit one — the default, so every
-- existing row is untouched.
--
-- Idempotent (CREATE TABLE IF NOT EXISTS / ADD COLUMN IF NOT EXISTS / ON
-- CONFLICT DO NOTHING seed) — same convention as migrations 090/097/118.
--
-- RLS: enabled, NO policies (deny-all to anon/authenticated/PostgREST) —
-- same pattern as agent_tokens/mcp_confirm_tokens/feature_requests above;
-- the backend connects as the `postgres` role, which bypasses RLS via
-- rolbypassrls=true.

CREATE TABLE IF NOT EXISTS beta_codes (
  code TEXT PRIMARY KEY,              -- stored lowercased
  trial_days INT NOT NULL DEFAULT 60,
  max_redemptions INT,                -- NULL = unlimited
  redemptions_used INT NOT NULL DEFAULT 0,
  active BOOLEAN NOT NULL DEFAULT TRUE,
  note TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE beta_codes ENABLE ROW LEVEL SECURITY;
-- No policies (deny-all to anon/authenticated/PostgREST); backend bypasses
-- via table ownership + BYPASSRLS (see migration 083 for the proof).

ALTER TABLE accounts ADD COLUMN IF NOT EXISTS beta_code TEXT;

INSERT INTO beta_codes (code, trial_days, max_redemptions, active, note)
VALUES ('beta26', 60, NULL, TRUE, 'launch beta - 2 months free')
ON CONFLICT (code) DO NOTHING;
