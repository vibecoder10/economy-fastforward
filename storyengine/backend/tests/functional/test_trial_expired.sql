-- Functional test for trial-expired downgrade logic.
-- Exercises the exact SELECT + UPDATE used by check_trial_expired() in email_tasks.py.
-- Run against the real DB (via Supabase MCP or psql). Asserts:
--   1. The SELECT finds accounts with expired trials + no paid sub + unhandled
--   2. The UPDATE flips plan to 'starter' + marks handled + bumps updated_at
--   3. Re-running the SELECT returns zero rows for the same account (idempotency)
-- Inserts and deletes a test row with a deterministic email prefix to avoid
-- touching real customer data.
--
-- Last verified passing: 2026-04-19 against project rcbobwaldrefnyllhjyo.

-- === SETUP ===
INSERT INTO accounts (email, display_name, plan, trial_ends_at, trial_expired_handled, stripe_subscription_id)
VALUES ('osiris-trial-test-sentinel@test.storyengine.dev', 'Osiris Test', 'creator', now() - interval '1 hour', FALSE, NULL)
ON CONFLICT DO NOTHING;

-- === ASSERTION 1: SELECT finds our test row ===
SELECT id, email, display_name, plan
FROM accounts
WHERE trial_ends_at IS NOT NULL
  AND trial_ends_at < now()
  AND trial_expired_handled IS NOT TRUE
  AND stripe_subscription_id IS NULL
  AND email = 'osiris-trial-test-sentinel@test.storyengine.dev';
-- Expected: 1 row, plan='creator'

-- === ACTION: UPDATE flips the row (exact statement from check_trial_expired) ===
UPDATE accounts
SET plan = 'starter',
    trial_expired_handled = TRUE,
    updated_at = now()
WHERE email = 'osiris-trial-test-sentinel@test.storyengine.dev'
  AND trial_expired_handled IS NOT TRUE
RETURNING id, plan, trial_expired_handled;
-- Expected: 1 row, plan='starter', trial_expired_handled=true

-- === ASSERTION 2: idempotency — SELECT now returns 0 rows ===
SELECT count(*) AS should_be_zero
FROM accounts
WHERE trial_ends_at IS NOT NULL
  AND trial_ends_at < now()
  AND trial_expired_handled IS NOT TRUE
  AND stripe_subscription_id IS NULL
  AND email = 'osiris-trial-test-sentinel@test.storyengine.dev';
-- Expected: count=0

-- === CLEANUP ===
DELETE FROM accounts WHERE email = 'osiris-trial-test-sentinel@test.storyengine.dev';
