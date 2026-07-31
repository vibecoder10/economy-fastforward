-- 153_machine_research_cards_roster_index_identity.sql
-- G5: roster-index keying for machine_research_cards.
--
-- The row identity was PRIMARY KEY (tenant_id, video_id, machine_key), where
-- machine_key = _normalized_unit_code(machine) (pipeline_executor.py). That
-- normalization is lossy: two DISTINCT locked roster entries can derive the
-- same code, e.g.
--   "Audacious class / Malta class"  -> CVA01
--   "CVA-01 class"                   -> CVA01
--   "Attacker class (US-built)"      -> LENDLEASEESCORTCARRIERS
--   "Ruler class (US-built)"         -> LENDLEASEESCORTCARRIERS
-- _upsert_machine_research_card's ON CONFLICT (tenant_id, video_id,
-- machine_key) DO UPDATE means the second colliding write silently
-- clobbers the first one's card/validation instead of erroring or
-- coexisting. Confirmed live damage on video
-- d2e37cd6-521a-43aa-a14d-ce096a783c1e: a 23-entry locked roster left only
-- 21 rows (21 distinct machine_key) in this table, though
-- research_payload->unit_research_cards still has all 23 (the JSONB
-- payload never used machine_key as a dict key, only this compact table
-- did) - see scripts/replay_research_cards.py for the recovery path.
--
-- roster_index is the correct identity: it is the locked roster's own 1:1
-- slot number, already UNIQUE (tenant_id, video_id, roster_index) since the
-- original 081_machine_research_cards.sql, and already passed into every
-- upsert call site as the loop's own `enumerate(roster, start=1)` index -
-- nothing downstream needs to change how it derives that number.
--
-- machine_key is demoted from PRIMARY KEY to a plain indexed informational
-- column: still populated on every write (readers/joins that only need a
-- quick machine_key lookup keep working when there is no collision, which
-- is the overwhelming majority of rows), just no longer required to be
-- unique per (tenant_id, video_id).
ALTER TABLE machine_research_cards DROP CONSTRAINT IF EXISTS machine_research_cards_pkey;
ALTER TABLE machine_research_cards DROP CONSTRAINT IF EXISTS machine_research_cards_tenant_id_video_id_roster_index_key;
ALTER TABLE machine_research_cards ADD PRIMARY KEY (tenant_id, video_id, roster_index);

-- The old UNIQUE(tenant_id, video_id, roster_index) index is now redundant
-- with the new PK's own index; machine_research_cards_video_order_idx was a
-- separate plain (non-unique) index over the same columns for ORDER BY -
-- also now redundant with the PK index. Drop both duplicates.
DROP INDEX IF EXISTS machine_research_cards_video_order_idx;

-- machine_key keeps a plain index for the lookups that only need it and
-- don't care about the (now possible) duplicate-key case.
CREATE INDEX IF NOT EXISTS machine_research_cards_machine_key_idx
  ON machine_research_cards(tenant_id, video_id, machine_key);
