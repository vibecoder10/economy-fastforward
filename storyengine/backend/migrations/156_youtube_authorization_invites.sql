CREATE TABLE IF NOT EXISTS youtube_authorization_invites (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    expected_channel_id TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS youtube_invite_oauth_states (
    state_hash TEXT PRIMARY KEY,
    invite_id UUID NOT NULL REFERENCES youtube_authorization_invites(id) ON DELETE CASCADE,
    browser_hash TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ
);
ALTER TABLE youtube_authorization_invites ENABLE ROW LEVEL SECURITY;
ALTER TABLE youtube_invite_oauth_states ENABLE ROW LEVEL SECURITY;
