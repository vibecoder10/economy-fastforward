-- 072: per-asset display caption for static-documentary segments.
-- {"title": "Super Heavy Tank T28", "sub": "Super-heavy assault tank • U.S. Army • 1944–1947"}
-- Rendered as a FIXED Remotion text overlay (real typography, stays in frame
-- while the Ken Burns pan moves the image) — captions are no longer baked
-- into the generated image, which also removes the invented-text risk.
ALTER TABLE assets ADD COLUMN IF NOT EXISTS caption JSONB;
