-- Durable, idempotent title-list production on the existing production_queue.
ALTER TABLE production_queue ADD COLUMN IF NOT EXISTS item_key TEXT;
ALTER TABLE production_queue ADD COLUMN IF NOT EXISTS continuous BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE production_queue ADD COLUMN IF NOT EXISTS required_render_mode TEXT;
ALTER TABLE production_queue ADD COLUMN IF NOT EXISTS attempt_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE production_queue ADD COLUMN IF NOT EXISTS last_error TEXT;
ALTER TABLE production_queue ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;
ALTER TABLE production_queue ADD COLUMN IF NOT EXISTS delivery_mode TEXT NOT NULL DEFAULT 'render_only';
ALTER TABLE production_queue ADD COLUMN IF NOT EXISTS delivery_channel_id TEXT;

DO $$ BEGIN
    ALTER TABLE production_queue ADD CONSTRAINT production_queue_delivery_mode_check
        CHECK (delivery_mode IN ('render_only', 'youtube_unlisted'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- Preserve historical duplicates. The oldest row owns the key; later legacy
-- duplicates stay NULL. Every new intake supplies a non-NULL deterministic key.
WITH ranked AS (
    SELECT id,
           row_number() OVER (
               PARTITION BY tenant_id, lower(regexp_replace(trim(title), '[[:space:]]+', ' ', 'g'))
               ORDER BY created_at, id
           ) AS rn,
           lower(regexp_replace(trim(title), '[[:space:]]+', ' ', 'g')) AS normalized_key
    FROM production_queue
    WHERE item_key IS NULL
)
UPDATE production_queue q
SET item_key = CASE WHEN ranked.rn = 1 THEN ranked.normalized_key ELSE NULL END
FROM ranked
WHERE q.id = ranked.id;

CREATE UNIQUE INDEX IF NOT EXISTS production_queue_tenant_item_key_uidx
    ON production_queue (tenant_id, item_key)
    WHERE item_key IS NOT NULL;
