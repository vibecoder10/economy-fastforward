-- Extends generation_claims (migration 092, checklist C16a) to also support
-- CHANNEL-LEVEL claims — a claim with no video_id at all — for checklist C41
-- (channel_dna.py::learn_channel, the unified DNA-ingestion orchestrator).
--
-- Why: learn_channel doesn't operate on a single video (it rebuilds
-- channel_profiles.channel_identity from the tenant's whole channel), so the
-- existing acquire()/release()/is_blocked() trio — keyed on (tenant_id,
-- video_id, stage) with video_id NOT NULL — has no video to key on. Rather
-- than invent a parallel table (tasks/decisions.md C41 note: "reuse
-- generation_claims"), this migration:
--   1. Drops the NOT NULL on video_id so a claim row can represent a
--      tenant-wide operation (video_id IS NULL). The FK to videos(id) is
--      untouched and still enforced for every non-NULL row — this is purely
--      additive, no existing row's video_id can become NULL retroactively.
--   2. Adds a SEPARATE partial unique index scoped to (tenant_id, stage)
--      WHERE video_id IS NULL. The original generation_claims_unique index
--      (tenant_id, video_id, stage) never fires for NULL video_id rows
--      (Postgres treats NULLs as distinct in a plain unique index), so
--      without this second index two concurrent tenant-level claims for the
--      same stage could both insert — this index is what makes
--      generation_claims.acquire_channel()'s "ON CONFLICT ... WHERE video_id
--      IS NULL DO NOTHING" actually a no-op on the second attempt.
--
-- The existing per-video acquire()/release()/is_blocked() functions and
-- their SQL are UNTOUCHED by this migration (they always pass a real
-- video_id, so their behavior — including the S7-1 CRITICAL money-safety
-- guarantee they encode — is byte-identical before and after). New
-- generation_claims.py functions acquire_channel()/release_channel() are the
-- only callers that ever write/read a NULL video_id row.

ALTER TABLE generation_claims ALTER COLUMN video_id DROP NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS generation_claims_tenant_stage_unique
  ON generation_claims (tenant_id, stage)
  WHERE video_id IS NULL;
