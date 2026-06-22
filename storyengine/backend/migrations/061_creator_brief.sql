-- 061: durable per-tenant creator brief captured during chat onboarding.
--
-- intent / goals / niche_angle / channel / competitors are collected in the
-- "Start Here" flow but currently live ONLY in the chat conversation's state JSON.
-- Each page load starts a fresh conversation, so the producer forgets all of it on
-- the next visit. Persisting the brief on channel_profiles (the durable, per-tenant
-- row, UNIQUE on tenant_id) lets every new conversation hydrate it back, so the
-- producer stays channel-aware across sessions.
--
-- One JSONB column mirrors exactly what _creator_brief(state) already reads, so the
-- write (during onboarding) and the read (hydrate at conversation load) are trivial.
ALTER TABLE channel_profiles
  ADD COLUMN IF NOT EXISTS creator_brief JSONB DEFAULT '{}'::jsonb;
