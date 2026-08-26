-- Distinguish verified historical photographs from verified design drawings.
-- Existing cache rows are photographs and retain the existing primary key.
ALTER TABLE static_reference_cache
    ADD COLUMN IF NOT EXISTS reference_kind TEXT NOT NULL DEFAULT 'photo';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'static_reference_cache_reference_kind_check'
    ) THEN
        ALTER TABLE static_reference_cache
            ADD CONSTRAINT static_reference_cache_reference_kind_check
            CHECK (reference_kind IN ('photo', 'design'));
    END IF;
END $$;
