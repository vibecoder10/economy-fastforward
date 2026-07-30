-- C8 (2026-07-29): backfill the ad-hoc `static_reference_misses` table
-- (created via in-process `CREATE TABLE IF NOT EXISTS` in static_docu.py's
-- _ensure_ref_cache_schema, alongside static_reference_cache) into the
-- tracked migration lineage, plus close its RLS gap up front — same
-- pattern migrations/082_untracked_ad_hoc_tables.sql +
-- 083_enable_rls_ad_hoc_tables.sql already applied to static_reference_cache,
-- just landed in ONE migration this time instead of two, since this table
-- is new rather than already-untracked-in-prod.
--
-- Real tenant_id (+ video_id) column, so it needs the SAME RLS treatment
-- 083 already proved safe for static_reference_cache: enable RLS with NO
-- policies (closes the public PostgREST/anon/authenticated access path),
-- relying on the backend's own DB connection (postgres role, BYPASSRLS)
-- to keep the app working — see 083's docstring for the verified proof.
--
-- Matches the exact shape _ensure_ref_cache_schema creates, so on a real
-- deploy (table already exists via the in-process guard) this is a pure
-- no-op; it only matters for a from-scratch rebuild.

CREATE TABLE IF NOT EXISTS static_reference_misses (
    tenant_id UUID NOT NULL,
    video_id UUID NOT NULL,
    machine_key TEXT NOT NULL,
    machine TEXT,
    reason_code TEXT NOT NULL,
    reason_detail TEXT,
    checked_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (tenant_id, video_id, machine_key)
);

ALTER TABLE static_reference_misses ENABLE ROW LEVEL SECURITY;
