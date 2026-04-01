-- Normalize asset status and video_status to lowercase
-- Fixes case sensitivity mismatch: 'Pending'/'Done' → 'pending'/'done'

UPDATE assets SET status = LOWER(status) WHERE status != LOWER(status);
UPDATE assets SET video_status = LOWER(video_status) WHERE video_status IS NOT NULL AND video_status != LOWER(video_status);
