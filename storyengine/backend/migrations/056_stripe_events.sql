-- Stripe webhook idempotency: dedup table.
-- Stripe delivers each event at-least-once (retries on any non-2xx or timeout,
-- and occasionally even after a 200). Without a dedup record, a duplicate
-- checkout.session.completed re-sends the receipt email and re-applies side
-- effects. The webhook INSERTs the event id here (ON CONFLICT DO NOTHING) and
-- skips processing if it was already seen.
CREATE TABLE IF NOT EXISTS stripe_events (
    event_id     TEXT PRIMARY KEY,
    event_type   TEXT,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
