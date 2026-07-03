-- The storyboard step now runs the REAL coverage planner and previews that
-- exact plan; the pictures step executes the SAME saved plan (Ryan's gate:
-- one cheap sheet showing every shot BEFORE the per-shot image spend).
-- The hash pins the plan to the scene text it was made from — editing the
-- script invalidates the preview and forces a re-plan.
ALTER TABLE scripts
  ADD COLUMN IF NOT EXISTS coverage_directive TEXT,
  ADD COLUMN IF NOT EXISTS coverage_directive_hash TEXT;
