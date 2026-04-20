-- Track accounts whose expired trial has been processed (plan downgraded + email sent).
-- Prevents the downgrade cron from repeatedly firing on the same account.

ALTER TABLE accounts
  ADD COLUMN IF NOT EXISTS trial_expired_handled BOOLEAN DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_accounts_trial_expired_unhandled
  ON accounts (trial_ends_at)
  WHERE trial_expired_handled IS NOT TRUE AND stripe_subscription_id IS NULL;
