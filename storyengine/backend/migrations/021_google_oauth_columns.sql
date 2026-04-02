-- Add Google OAuth columns to accounts table
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS google_id TEXT UNIQUE;
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS avatar_url TEXT;

-- Index for fast Google ID lookups during login
CREATE INDEX IF NOT EXISTS idx_accounts_google_id ON accounts(google_id);
