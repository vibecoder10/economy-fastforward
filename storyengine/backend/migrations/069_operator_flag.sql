-- Channel Manager Command Center (operator-only). Flags the account(s) allowed to
-- hold multiple client workspaces and see the Slack-style channel switcher.
-- Default FALSE so every existing/normal user is unaffected (single-channel app).
-- The real authorization boundary is still the memberships table, checked on every
-- request in auth.get_tenant_id; this flag only gates who sees the switcher UI.
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS is_operator BOOLEAN DEFAULT FALSE;

-- Enable for Ryan (the sole operator for now).
UPDATE accounts SET is_operator = TRUE WHERE lower(email) = 'ryan.ayler@gmail.com';
