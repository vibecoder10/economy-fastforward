-- Global application-level drain state.
--
-- This singleton is deliberately PostgreSQL-backed: production may run
-- without Redis and more than one backend process/operator can participate in
-- a deploy.  The state therefore has to survive process restarts and be seen
-- by every process before it starts new provider work.
CREATE TABLE IF NOT EXISTS application_drain_state (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    mode TEXT NOT NULL DEFAULT 'normal' CHECK (mode IN ('normal', 'draining')),
    reason TEXT,
    owner TEXT,
    changed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO application_drain_state (singleton, mode)
VALUES (TRUE, 'normal')
ON CONFLICT (singleton) DO NOTHING;

ALTER TABLE application_drain_state ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON application_drain_state FROM anon;
REVOKE ALL ON application_drain_state FROM authenticated;

COMMENT ON TABLE application_drain_state IS
    'Operator-controlled global generation drain. Only backend service credentials may read/write it.';

