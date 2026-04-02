-- Add Stripe billing columns to accounts table
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS stripe_customer_id TEXT UNIQUE;
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS stripe_subscription_id TEXT;
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS stripe_plan TEXT;
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS stripe_status TEXT;
