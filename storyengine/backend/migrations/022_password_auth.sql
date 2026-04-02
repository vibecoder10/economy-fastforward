-- Add password_hash column to accounts for email/password auth
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS password_hash TEXT;

-- Make email unique for password-based login lookups
CREATE UNIQUE INDEX IF NOT EXISTS accounts_email_unique ON accounts (email) WHERE email IS NOT NULL;
