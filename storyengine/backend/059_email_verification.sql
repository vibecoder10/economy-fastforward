-- Email verification. A new password-signup account must confirm its email (via
-- an emailed link) before it can generate — this stops fake-email trial abuse.
-- Existing accounts are grandfathered to verified=true (they predate this and are
-- real); Google signups are set verified=true in code (Google already verified
-- the address). New password signups default to false and must confirm.
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS email_verified BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS email_verification_token TEXT;
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS email_verification_expires TIMESTAMPTZ;

-- Grandfather everyone who already exists (real accounts from before this feature).
UPDATE accounts SET email_verified = true WHERE email_verified = false;

CREATE INDEX IF NOT EXISTS idx_accounts_email_verif_token ON accounts(email_verification_token);
