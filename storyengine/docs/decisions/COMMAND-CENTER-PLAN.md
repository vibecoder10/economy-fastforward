# Channel Manager Command Center — Plan

**Owner:** Ryan (operator-only for now). **Status:** planning → build.
**Created:** 2026-07-01.

## Goal

Let Ryan run many client YouTube channels from one StoryEngine login, Slack-style:
a sidebar list of client channels; click one and the whole app re-scopes to that
channel's workspace (chat, videos, pipeline, analytics, brand). Isolated to Ryan's
account for now; when there's a market, ungate it into a product — no rebuild.

First real client: **DesignedUsed** (client adds Ryan as YouTube channel manager).

## Core insight (why this is mostly wiring, not a new data model)

StoryEngine is already multi-tenant. A "client channel" maps 1:1 onto a **tenant**,
which already has isolated keys, brand, videos, competitors, chat, and one connected
YouTube channel. The `memberships` table already lets one user belong to many
tenants. So the command center is three things on top of what exists:

1. Ryan's user gets a membership in each client tenant.
2. A sidebar switcher that sets an **active tenant** and re-scopes the app.
3. An **operator gate** so only Ryan sees any of this.

## Decisions locked

- **Client = tenant.** Reuse tenant isolation; do NOT invent a sub-channel concept.
- **Client's own keys.** Each workspace holds that client's Kie/Claude keys; the
  client pays AI usage, Ryan bills a management fee. Reuses the encrypted secure
  key box (vault encryption-at-rest, shipped 2026-06-30).
- **Full context swap** on switch (not a lightweight post panel): the whole system
  opens for that channel.
- **Operator-only.** Gated behind an `is_operator` flag on the account. Everyone
  else sees the unchanged single-channel app.
- **Out of scope for v1:** client login / client-facing read views, billing
  automation, public release. All future.

## Architecture

- **Auth today:** `get_tenant_id` (backend/auth.py) returns the JWT's `tenant_id`,
  else the user's first `memberships` row.
- **Switch mechanism:** frontend sends an `X-Active-Tenant` header. `get_tenant_id`
  honors it **only after verifying** `SELECT 1 FROM memberships WHERE user_id=$1
  AND tenant_id=$2`. No match → 403, fall back to home tenant. JWT is untouched.
- **THE SECURITY RULE (non-negotiable):** the active-tenant override is authorized
  against memberships on EVERY request. This is the one thing that, done wrong, is a
  cross-client data breach. It gets the most careful build + the hardest tests.
- **Operator gate:** `accounts.is_operator` (new column, default false; true for
  Ryan). Switcher UI + multi-workspace behavior only render/apply when true.

## Phases

### Phase 1 — Secure active-tenant switching (the core, no UI)
- Migration: `ALTER TABLE accounts ADD COLUMN is_operator boolean DEFAULT false;`
  set true for Ryan.
- `get_tenant_id`: accept `X-Active-Tenant`; validate membership; 403 on non-member.
- Helper `user_has_membership(user_id, tenant_id)`.
- Frontend api client: attach `X-Active-Tenant` from the stored active workspace.
- **VERIFY (hard):** member switches to their tenant → data scopes correctly;
  attempt to switch to a NON-member tenant → 403, no data leak. This is the gate.

### Phase 2 — Slack-style switcher + Add client channel
- `GET /api/workspaces` → the operator's tenants (name, connected channel, status).
- Sidebar switcher component: lists workspaces, highlights active, click = set active
  tenant + re-scope (invalidate queries).
- "Add client channel" flow: create tenant + operator membership → name it → connect
  the client's YouTube via Ryan's manager OAuth → paste the client's Kie key (secure
  box) → optional Claude key. Reuses the onboarding key box + OAuth connect.

### Phase 3 — Operator gate + safety polish
- Gate everything behind `is_operator`.
- Prominent ACTIVE-WORKSPACE indicator so Ryan always knows which channel he's in.
- Upload/publish confirm shows the target channel name (guard against posting to the
  wrong client). Optional per-channel status/unread dots.

### Phase 4 — Onboard DesignedUsed
- Create the DesignedUsed workspace, connect via manager OAuth, add client's key,
  run the pipeline. First real client live.

## Risks & mitigations

- **Cross-tenant data leak via the switch** → membership auth check every request
  (Phase 1), adversarial tests.
- **Posting to the wrong client channel** → prominent active-workspace badge + a
  publish confirm that names the target channel (Phase 3).
- **YouTube manager access needs a Brand Account** → verify DesignedUsed is a brand
  account before onboarding; owner adds Ryan as Manager.
- **OAuth consent screen in "testing" mode** → Ryan connects (as manager) and his
  Google account is already a test user, so it works; flag if "not verified" appears.
