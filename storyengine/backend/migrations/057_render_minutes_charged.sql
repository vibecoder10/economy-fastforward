-- Idempotent render billing. Before this, every successful render incremented
-- tenant_usage.render_minutes — so re-rendering one video (a normal part of
-- editing/retrying) charged the customer's monthly allowance again and again
-- for a single deliverable. This column is the high-water mark of minutes
-- already charged for the video; the executor only charges the delta above it.
ALTER TABLE videos
    ADD COLUMN IF NOT EXISTS render_minutes_charged NUMERIC(10,2) NOT NULL DEFAULT 0;
