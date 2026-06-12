-- Extraction validation (Ryan's "bad crop" rules, 2026-06-12):
-- per-asset flags written by extract_grid's post-crop validation.
-- 'label_leak'   — a [KFn | SHOT | Ns] chip survived the crop
-- 'gutter_split' — the crop straddles two grid panels
-- UI renders a red "bad crop" badge + one-tap re-crop on flagged assets.
ALTER TABLE assets ADD COLUMN IF NOT EXISTS extraction_flags TEXT[];
