-- Authoritative YouTube delivery receipt for durable title-list completion.
ALTER TABLE videos
  ADD COLUMN IF NOT EXISTS queue_delivery_receipt JSONB;

ALTER TABLE videos
  DROP CONSTRAINT IF EXISTS videos_queue_delivery_receipt_object_ck;
ALTER TABLE videos
  ADD CONSTRAINT videos_queue_delivery_receipt_object_ck
  CHECK (
    queue_delivery_receipt IS NULL
    OR jsonb_typeof(queue_delivery_receipt) = 'object'
  );
