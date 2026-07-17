-- Records WHICH image model actually generated an asset's picture (may differ
-- from videos.image_model_override when a content-policy/failure fallback
-- fired — see shared/clients/image_model_router.py, the resolver checklist
-- item C02/§0.1 introduced so the Pictures model select stops lying).
--
-- One of: 'gpt-image-2' (default + fallback), 'nano-banana-2', 'z-image', or
-- NULL for assets generated before this column existed (their true model is
-- unknown — the app's badge simply shows nothing for those rows).
--
-- Idempotent (ADD COLUMN IF NOT EXISTS) — safe to run when already applied.

ALTER TABLE assets ADD COLUMN IF NOT EXISTS image_model TEXT;
