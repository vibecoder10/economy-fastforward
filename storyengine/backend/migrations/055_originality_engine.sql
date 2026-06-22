-- 055: originality engine — slop-proofing plumbing (anti-demonetization).
--
-- Foundation for making AI slop structurally impossible to produce, so YouTube's
-- inauthentic-content policy can't demonetize a channel. Design rule: NO
-- user-facing gates or warnings — the engine just diverges by construction and
-- silently re-rolls anything too close to past work (see backend/originality.py
-- and ../MONETIZATION-SAFETY-PLAN.md).
--
-- Columns we REUSE (already on videos, no change here):
--   * monetization_risk (TEXT)  — may carry the internal verdict for our own
--     debugging; never surfaced to the creator.
--   * agent_paper_trail (JSONB) — appends internal originality notes / re-rolls.
--
-- Columns this migration ADDS:
--   * slop_fingerprint     — the compact per-video record (title/hook/script
--     excerpt/thumbnail/look) that future generations diverge from.
--   * ai_disclosure_required / ai_disclosure_text — set automatically (and
--     invisibly) only when a video depicts a real person, a cloned real voice,
--     or altered real footage; auto-prepended to the YouTube description at
--     upload. NULL/false for the normal fictional/animated case.
--
-- All idempotent. Existing videos get NULL/false and behave exactly as before.
ALTER TABLE videos ADD COLUMN IF NOT EXISTS slop_fingerprint JSONB;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS ai_disclosure_required BOOLEAN DEFAULT false;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS ai_disclosure_text TEXT;
