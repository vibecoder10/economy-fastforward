ALTER TABLE accounts ADD COLUMN IF NOT EXISTS trial_ends_at TIMESTAMPTZ;

-- Set trial for existing free accounts that don't have a Stripe subscription
UPDATE accounts
SET trial_ends_at = created_at + INTERVAL '14 days'
WHERE plan = 'free' AND stripe_subscription_id IS NULL AND trial_ends_at IS NULL;
