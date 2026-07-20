-- C58 (checklist "Follow-up queue", the last P4.2 scout gap): early-warning
-- launch classifier. Classifies a freshly-launched platform video's early
-- trajectory (its ctr_48h write-once snapshot -- routes/youtube_sync.py's
-- _calculate_snapshots(), the SAME milestone every video's ctr_48h already
-- locks at) against the CHANNEL'S OWN historical ctr_48h distribution into
-- 'ok' | 'watch' | 'underperforming'. READ-ONLY signal -- never trips the
-- kill switch, never pauses anything, never touches spend (design
-- constraint 1). See backend/early_warning.py for the classifier + the
-- evidence shape written into early_signal_evidence.
--
-- early_signal            -- 'ok' | 'watch' | 'underperforming', NULL until
--                             classified (most videos, and every video
--                             created before this migration, start NULL).
-- early_signal_evidence   -- jsonb: the numbers behind the call --
--                             {"metric": "ctr_48h", "maturity": "48h",
--                             "video_ctr_48h": ..., "channel_median_ctr_48h":
--                             ..., "delta_pct": ..., "cohort_size": ...,
--                             "watch_threshold_pct": ..., "underperforming_
--                             threshold_pct": ...} -- same evidence-jsonb
--                             discipline as channel_patterns.evidence (C56).
-- early_signal_at         -- write-once marker (same convention as
--                             launch_pattern_analyzed_at, migration 110):
--                             NULL means "not yet classified" (either never
--                             reached the ctr_48h milestone yet, OR the
--                             channel doesn't have enough sibling launches
--                             yet to trust a median -- both cases retry on
--                             a later sync, never guessed). Once stamped,
--                             this video is never re-classified again.
--
-- Idempotent (ADD COLUMN IF NOT EXISTS) -- applied LIVE via Supabase MCP
-- against project wrromlupsmyzrrcqlucn, confirmed via
-- information_schema.columns (same pattern as migrations 103/107/108/109/110).

ALTER TABLE videos ADD COLUMN IF NOT EXISTS early_signal TEXT
  CHECK (early_signal IS NULL OR early_signal IN ('ok', 'watch', 'underperforming'));
ALTER TABLE videos ADD COLUMN IF NOT EXISTS early_signal_evidence JSONB;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS early_signal_at TIMESTAMPTZ;
