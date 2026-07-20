"""Tests for C57 ("the agent token IS the paywall" — decisions.md
2026-07-19 MCP-monetization entry + its CORRECTION, wiring MCP into the
EXISTING Stripe billing system rather than building a new one).

Covers:
  1. `routes.billing._good_standing_from_fields` — the ONE decision
     function, pinned per stripe_status value + the active-trial override.
  2. `routes.billing.is_account_in_good_standing` (tenant_id-keyed) — used
     by the mint route. DB-faked (accounts JOIN memberships).
  3. `agent_tokens.authenticate_with_standing` (token-keyed) — used by the
     per-request MCP verify gate. DB-faked (agent_tokens JOIN memberships
     JOIN accounts), proving the piggybacked single-query design actually
     returns the right (tenant_id, ok, reason) for a good and a lapsed
     account, and (None, False, "") for a bad/revoked token — same
     contract as the pre-existing `authenticate()`.
  4. `routes.agent_access.create_token` (the mint route): 402 refused when
     lapsed, allowed when good standing.
  5. `auth_agent.get_agent_tenant_id`: 402 with a renew-here message when
     the resolved tenant is not in good standing (a VALID, non-revoked
     token — distinct from the pre-existing 401 for a bad/revoked token,
     covered by test_c26).
  6. ONE-definition lock: `_good_standing_from_fields` is defined exactly
     once (in billing.py), and agent_tokens.authenticate_with_standing
     calls it rather than re-deriving the decision inline.

No live DB, no network.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c57_mcp_billing_gate.py -q
"""
from __future__ import annotations

import ast
import asyncio
import os
import re
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

import agent_tokens  # noqa: E402
import auth_agent  # noqa: E402
import routes.billing as billing  # noqa: E402
from fastapi import HTTPException  # noqa: E402


def _backend() -> Path:
    return Path(_BACKEND)


def _run(coro):
    return asyncio.run(coro)


# =============================================================================
# 1. _good_standing_from_fields — the pure decision function
# =============================================================================

def test_no_subscription_is_good_standing():
    """Never been through checkout at all — free tier from day one. This
    function only answers "has a subscription lapsed", not "is the plan
    high enough" (that's the parked, not-yet-built tier gate)."""
    ok, reason = billing._good_standing_from_fields(
        trial_ends_at=None, stripe_subscription_id=None, stripe_status=None,
    )
    assert ok is True
    assert "free tier" in reason
    print("✅ test_no_subscription_is_good_standing")


def test_active_subscription_is_good_standing():
    ok, reason = billing._good_standing_from_fields(
        trial_ends_at=None, stripe_subscription_id="sub_123", stripe_status="active",
    )
    assert ok is True
    assert "active subscription" in reason
    print("✅ test_active_subscription_is_good_standing")


def test_active_free_trial_is_good_standing_even_with_no_stripe_status():
    """Mirrors email_tasks.check_trial_expired's OWN safety filter
    (stripe_subscription_id IS NULL) for "is this a genuine trial" — not an
    invented rule."""
    future = datetime.now(timezone.utc) + timedelta(days=5)
    ok, reason = billing._good_standing_from_fields(
        trial_ends_at=future, stripe_subscription_id=None, stripe_status=None,
    )
    assert ok is True
    assert "trial" in reason
    print("✅ test_active_free_trial_is_good_standing_even_with_no_stripe_status")


def test_expired_trial_falls_through_to_stripe_status():
    """An expired trial with no subscription just IS a free-tier account —
    good standing, not "lapsed" (they were never charged)."""
    past = datetime.now(timezone.utc) - timedelta(days=5)
    ok, reason = billing._good_standing_from_fields(
        trial_ends_at=past, stripe_subscription_id=None, stripe_status=None,
    )
    assert ok is True
    print("✅ test_expired_trial_falls_through_to_stripe_status")


def test_canceled_subscription_is_not_good_standing():
    ok, reason = billing._good_standing_from_fields(
        trial_ends_at=None, stripe_subscription_id="sub_123", stripe_status="canceled",
    )
    assert ok is False
    assert "canceled" in reason
    print("✅ test_canceled_subscription_is_not_good_standing")


def test_past_due_subscription_is_not_good_standing():
    ok, reason = billing._good_standing_from_fields(
        trial_ends_at=None, stripe_subscription_id="sub_123", stripe_status="past_due",
    )
    assert ok is False
    assert "past_due" in reason
    print("✅ test_past_due_subscription_is_not_good_standing")


def test_unpaid_subscription_is_not_good_standing():
    ok, reason = billing._good_standing_from_fields(
        trial_ends_at=None, stripe_subscription_id="sub_123", stripe_status="unpaid",
    )
    assert ok is False
    print("✅ test_unpaid_subscription_is_not_good_standing")


def test_trial_end_in_past_but_has_stripe_subscription_does_not_override_bad_status():
    """A tenant with a REAL stripe_subscription_id (so the trial-safety
    filter's `stripe_subscription_id IS NULL` doesn't apply) and a
    non-active stripe_status is lapsed, even if some stale trial_ends_at
    from before they ever subscribed is still sitting on the row."""
    future = datetime.now(timezone.utc) + timedelta(days=5)
    ok, reason = billing._good_standing_from_fields(
        trial_ends_at=future, stripe_subscription_id="sub_123", stripe_status="canceled",
    )
    assert ok is False, (
        "a real (non-null) stripe_subscription_id means the trial-safety "
        "filter doesn't apply — trial_ends_at must not override a canceled "
        "paid subscription"
    )
    print("✅ test_trial_end_in_past_but_has_stripe_subscription_does_not_override_bad_status")


# =============================================================================
# 2. is_account_in_good_standing (tenant_id-keyed, mint route's gate)
# =============================================================================

def _patch_billing_fetch_one(row):
    async def _fetch_one(query, *args):
        assert "FROM accounts a" in query and "JOIN memberships m" in query
        return row
    return patch.object(billing, "fetch_one", _fetch_one)


def test_is_account_in_good_standing_true_for_active():
    row = {"trial_ends_at": None, "stripe_subscription_id": "sub_1", "stripe_status": "active"}
    with _patch_billing_fetch_one(row):
        ok, reason = _run(billing.is_account_in_good_standing(uuid.uuid4()))
    assert ok is True
    print("✅ test_is_account_in_good_standing_true_for_active")


def test_is_account_in_good_standing_false_for_canceled():
    row = {"trial_ends_at": None, "stripe_subscription_id": "sub_1", "stripe_status": "canceled"}
    with _patch_billing_fetch_one(row):
        ok, reason = _run(billing.is_account_in_good_standing(uuid.uuid4()))
    assert ok is False
    print("✅ test_is_account_in_good_standing_false_for_canceled")


def test_is_account_in_good_standing_no_account_row_fails_closed():
    with _patch_billing_fetch_one(None):
        ok, reason = _run(billing.is_account_in_good_standing(uuid.uuid4()))
    assert ok is False
    assert "no account" in reason
    print("✅ test_is_account_in_good_standing_no_account_row_fails_closed")


# =============================================================================
# 3. agent_tokens.authenticate_with_standing (token-keyed, per-request gate)
# =============================================================================

class _FakeAccountStore:
    """agent_tokens rows joined (in Python) to a per-tenant account row —
    same shape the real JOIN through memberships -> accounts would return
    in one query."""
    def __init__(self):
        self.tokens: dict[uuid.UUID, dict] = {}
        self.accounts: dict = {}  # tenant_id -> account fields

    def add_token(self, tenant_id, token_hash, revoked=False):
        row_id = uuid.uuid4()
        self.tokens[row_id] = {
            "id": row_id, "tenant_id": tenant_id, "token_hash": token_hash,
            "revoked_at": ("now" if revoked else None),
        }
        return row_id

    def set_account(self, tenant_id, *, trial_ends_at=None, stripe_subscription_id=None, stripe_status=None,
                     plan=None, is_operator=False):
        self.accounts[tenant_id] = {
            "trial_ends_at": trial_ends_at,
            "stripe_subscription_id": stripe_subscription_id,
            "stripe_status": stripe_status,
            "plan": plan,
            "is_operator": is_operator,
        }


def _patch_agent_tokens_with_standing(store: _FakeAccountStore):
    async def _fetch_one(query, *args):
        if "JOIN memberships m ON m.tenant_id = t.tenant_id" in query:
            (token_hash,) = args
            for row in store.tokens.values():
                if row["token_hash"] == token_hash and row["revoked_at"] is None:
                    acct = store.accounts.get(row["tenant_id"], {})
                    return {
                        "token_id": row["id"], "tenant_id": row["tenant_id"],
                        "trial_ends_at": acct.get("trial_ends_at"),
                        "stripe_subscription_id": acct.get("stripe_subscription_id"),
                        "stripe_status": acct.get("stripe_status"),
                        "plan": acct.get("plan"),
                        "is_operator": acct.get("is_operator", False),
                    }
            return None
        raise AssertionError(f"unexpected query: {query!r}")

    async def _execute(query, *args):
        if "SET last_used_at = now()" in query:
            return "UPDATE 1"
        raise AssertionError(f"unexpected query: {query!r}")

    return patch.object(agent_tokens, "fetch_one", _fetch_one), \
        patch.object(agent_tokens, "execute", _execute)


def test_authenticate_with_standing_good_account():
    store = _FakeAccountStore()
    tenant = uuid.uuid4()
    token_hash = agent_tokens._hash_token("se_agent_good")
    store.add_token(tenant, token_hash)
    # plan="pro" isolates this test to the standing dimension only — see the
    # C62 tier-gate tests below for plan-dependent behavior.
    store.set_account(tenant, stripe_status="active", stripe_subscription_id="sub_1", plan="pro")
    p1, p2 = _patch_agent_tokens_with_standing(store)
    with p1, p2:
        tenant_id, ok, reason, plan, is_operator = _run(agent_tokens.authenticate_with_standing("se_agent_good"))
    assert tenant_id == tenant
    assert ok is True
    assert plan == "pro"
    assert is_operator is False
    print("✅ test_authenticate_with_standing_good_account")


def test_authenticate_with_standing_lapsed_account():
    store = _FakeAccountStore()
    tenant = uuid.uuid4()
    token_hash = agent_tokens._hash_token("se_agent_lapsed")
    store.add_token(tenant, token_hash)
    store.set_account(tenant, stripe_status="past_due", stripe_subscription_id="sub_1", plan="pro")
    p1, p2 = _patch_agent_tokens_with_standing(store)
    with p1, p2:
        tenant_id, ok, reason, plan, is_operator = _run(agent_tokens.authenticate_with_standing("se_agent_lapsed"))
    assert tenant_id == tenant, "the token is still valid — only the standing check should fail"
    assert ok is False
    assert "past_due" in reason
    print("✅ test_authenticate_with_standing_lapsed_account")


def test_authenticate_with_standing_revoked_token_returns_none_tenant():
    store = _FakeAccountStore()
    tenant = uuid.uuid4()
    token_hash = agent_tokens._hash_token("se_agent_revoked")
    store.add_token(tenant, token_hash, revoked=True)
    store.set_account(tenant, stripe_status="active", stripe_subscription_id="sub_1", plan="pro")
    p1, p2 = _patch_agent_tokens_with_standing(store)
    with p1, p2:
        tenant_id, ok, reason, plan, is_operator = _run(agent_tokens.authenticate_with_standing("se_agent_revoked"))
    assert tenant_id is None, "a revoked token must not resolve a tenant, regardless of standing"
    print("✅ test_authenticate_with_standing_revoked_token_returns_none_tenant")


def test_authenticate_with_standing_wrong_prefix_short_circuits():
    tenant_id, ok, reason, plan, is_operator = _run(agent_tokens.authenticate_with_standing("not-a-real-token"))
    assert tenant_id is None
    print("✅ test_authenticate_with_standing_wrong_prefix_short_circuits")


# =============================================================================
# 3b. C62: MCP tier gate (plan/is_operator piggybacked onto the same query)
# =============================================================================

def test_authenticate_with_standing_starter_plan_surfaced():
    store = _FakeAccountStore()
    tenant = uuid.uuid4()
    token_hash = agent_tokens._hash_token("se_agent_starter")
    store.add_token(tenant, token_hash)
    store.set_account(tenant, stripe_status="active", stripe_subscription_id="sub_1", plan="starter")
    p1, p2 = _patch_agent_tokens_with_standing(store)
    with p1, p2:
        tenant_id, ok, reason, plan, is_operator = _run(agent_tokens.authenticate_with_standing("se_agent_starter"))
    assert ok is True, "standing is fine — starter is a tier problem, not a standing problem"
    assert plan == "starter"
    assert is_operator is False
    print("✅ test_authenticate_with_standing_starter_plan_surfaced")


def test_authenticate_with_standing_operator_flag_surfaced():
    store = _FakeAccountStore()
    tenant = uuid.uuid4()
    token_hash = agent_tokens._hash_token("se_agent_operator")
    store.add_token(tenant, token_hash)
    store.set_account(tenant, stripe_status=None, stripe_subscription_id=None, plan="free", is_operator=True)
    p1, p2 = _patch_agent_tokens_with_standing(store)
    with p1, p2:
        tenant_id, ok, reason, plan, is_operator = _run(agent_tokens.authenticate_with_standing("se_agent_operator"))
    assert ok is True, "no stripe_status at all (free tier) is good standing"
    assert plan == "free"
    assert is_operator is True
    print("✅ test_authenticate_with_standing_operator_flag_surfaced")


# =============================================================================
# 4. auth_agent.get_agent_tenant_id — the per-request MCP gate
# =============================================================================

def test_get_agent_tenant_id_402_when_lapsed():
    tenant = uuid.uuid4()
    with patch.object(agent_tokens, "authenticate_with_standing",
                       AsyncMock(return_value=(tenant, False, "your StoryEngine subscription status is 'canceled'",
                                                "pro", False))):
        try:
            _run(auth_agent.get_agent_tenant_id(authorization="Bearer se_agent_whatever"))
            raised = None
        except HTTPException as e:
            raised = e
    assert raised is not None and raised.status_code == 402
    assert raised.detail["error"] == "subscription_lapsed"
    assert "renew" in raised.detail["message"].lower()
    print("✅ test_get_agent_tenant_id_402_when_lapsed")


def test_get_agent_tenant_id_passes_through_when_good_standing():
    tenant = uuid.uuid4()
    # plan="pro" isolates this test to the standing dimension — see the
    # C62 tier-gate tests below for plan-dependent behavior.
    with patch.object(agent_tokens, "authenticate_with_standing",
                       AsyncMock(return_value=(tenant, True, "active subscription", "pro", False))):
        result = _run(auth_agent.get_agent_tenant_id(authorization="Bearer se_agent_whatever"))
    assert result == tenant
    print("✅ test_get_agent_tenant_id_passes_through_when_good_standing")


def test_get_agent_tenant_id_still_401_on_bad_token_not_402():
    """A structurally-invalid/unknown/revoked token must stay a flat 401 —
    the NEW 402 branch only fires for a token that resolved to a real
    tenant whose standing then failed."""
    with patch.object(agent_tokens, "authenticate_with_standing",
                       AsyncMock(return_value=(None, False, "", "free", False))):
        try:
            _run(auth_agent.get_agent_tenant_id(authorization="Bearer se_agent_bad"))
            raised = None
        except HTTPException as e:
            raised = e
    assert raised is not None and raised.status_code == 401
    print("✅ test_get_agent_tenant_id_still_401_on_bad_token_not_402")


# =============================================================================
# 4b. C62: get_agent_tenant_id's per-request MCP tier gate
# =============================================================================

def test_get_agent_tenant_id_402_when_starter_plan():
    """A live token whose account is in good standing but has downgraded to
    Starter must die same-day, mirroring the lapsed-subscription 402 above —
    not stay valid until someone thinks to revoke it."""
    tenant = uuid.uuid4()
    with patch.object(agent_tokens, "authenticate_with_standing",
                       AsyncMock(return_value=(tenant, True, "active subscription", "starter", False))):
        try:
            _run(auth_agent.get_agent_tenant_id(authorization="Bearer se_agent_whatever"))
            raised = None
        except HTTPException as e:
            raised = e
    assert raised is not None and raised.status_code == 402
    assert raised.detail["error"] == "plan_required"
    print("✅ test_get_agent_tenant_id_402_when_starter_plan")


def test_get_agent_tenant_id_allowed_for_agency_plan():
    tenant = uuid.uuid4()
    with patch.object(agent_tokens, "authenticate_with_standing",
                       AsyncMock(return_value=(tenant, True, "active subscription", "agency", False))):
        result = _run(auth_agent.get_agent_tenant_id(authorization="Bearer se_agent_whatever"))
    assert result == tenant
    print("✅ test_get_agent_tenant_id_allowed_for_agency_plan")


def test_get_agent_tenant_id_operator_exempt_from_tier_gate():
    """The operator account (accounts.is_operator, migration 069) must never
    be locked out of MCP by the tier gate, even on plan='free'."""
    tenant = uuid.uuid4()
    with patch.object(agent_tokens, "authenticate_with_standing",
                       AsyncMock(return_value=(tenant, True, "no subscription on file (free tier)", "free", True))):
        result = _run(auth_agent.get_agent_tenant_id(authorization="Bearer se_agent_whatever"))
    assert result == tenant
    print("✅ test_get_agent_tenant_id_operator_exempt_from_tier_gate")


# =============================================================================
# 5. routes.agent_access.create_token — the mint gate
# =============================================================================

import routes.agent_access as agent_access  # noqa: E402


def test_mint_refused_when_lapsed():
    tenant = uuid.uuid4()
    with patch.object(billing, "is_account_in_good_standing",
                       AsyncMock(return_value=(False, "your StoryEngine subscription status is 'canceled'"))):
        try:
            _run(agent_access.create_token(
                agent_access.CreateAgentTokenRequest(name="Test Agent"), tenant_id=tenant,
            ))
            raised = None
        except HTTPException as e:
            raised = e
    assert raised is not None and raised.status_code == 402
    assert raised.detail["error"] == "subscription_lapsed"
    print("✅ test_mint_refused_when_lapsed")


def test_mint_allowed_when_good_standing():
    tenant = uuid.uuid4()
    # plan="pro" in the piggybacked fetch_one row: is_account_in_good_standing
    # is mocked directly (so it never touches fetch_one itself), but the C62
    # tier check that now runs right after it does its OWN fetch_one — must
    # be satisfied too or this test would hit a real (unconfigured) DB call.
    row = {"trial_ends_at": None, "stripe_subscription_id": "sub_1", "stripe_status": "active",
           "plan": "pro", "is_operator": False}
    with patch.object(billing, "is_account_in_good_standing",
                       AsyncMock(return_value=(True, "active subscription"))), \
         _patch_billing_fetch_one(row), \
         patch.object(agent_tokens, "create_agent_token",
                      AsyncMock(return_value=("se_agent_plaintext", {
                          "id": uuid.uuid4(), "name": "Test Agent",
                          "created_at": "2026-07-19T00:00:00Z",
                      }))):
        result = _run(agent_access.create_token(
            agent_access.CreateAgentTokenRequest(name="Test Agent"), tenant_id=tenant,
        ))
    assert result["token"] == "se_agent_plaintext"
    print("✅ test_mint_allowed_when_good_standing")


def test_mint_refused_for_free_tier_never_subscribed():
    """SUPERSEDES the old C57-item-5 expectation ("deliberately NOT
    tier-gated yet") — C62 ratified MCP = Pro+, so a free-tier tenant is now
    good STANDING (not "lapsed": billing.is_account_in_good_standing still
    passes) but fails the SEPARATE tier check, refused with 'plan_required'
    rather than 'subscription_lapsed'."""
    tenant = uuid.uuid4()
    row = {"trial_ends_at": None, "stripe_subscription_id": None, "stripe_status": None,
           "plan": None, "is_operator": False}
    with _patch_billing_fetch_one(row):
        try:
            _run(agent_access.create_token(
                agent_access.CreateAgentTokenRequest(name="Free Tenant"), tenant_id=tenant,
            ))
            raised = None
        except HTTPException as e:
            raised = e
    assert raised is not None and raised.status_code == 402
    assert raised.detail["error"] == "plan_required"
    print("✅ test_mint_refused_for_free_tier_never_subscribed")


# =============================================================================
# 5b. C62: create_token's MCP tier gate (plan/is_operator)
# =============================================================================

def test_mint_refused_for_starter_plan():
    tenant = uuid.uuid4()
    row = {"trial_ends_at": None, "stripe_subscription_id": "sub_1", "stripe_status": "active",
           "plan": "starter", "is_operator": False}
    with _patch_billing_fetch_one(row):
        try:
            _run(agent_access.create_token(
                agent_access.CreateAgentTokenRequest(name="Starter Tenant"), tenant_id=tenant,
            ))
            raised = None
        except HTTPException as e:
            raised = e
    assert raised is not None and raised.status_code == 402
    assert raised.detail["error"] == "plan_required"
    print("✅ test_mint_refused_for_starter_plan")


def test_mint_allowed_for_pro_and_agency_plans():
    for plan in ("pro", "agency"):
        tenant = uuid.uuid4()
        row = {"trial_ends_at": None, "stripe_subscription_id": "sub_1", "stripe_status": "active",
               "plan": plan, "is_operator": False}
        with _patch_billing_fetch_one(row), \
             patch.object(agent_tokens, "create_agent_token",
                          AsyncMock(return_value=("se_agent_plaintext", {
                              "id": uuid.uuid4(), "name": f"{plan.title()} Tenant",
                              "created_at": "2026-07-19T00:00:00Z",
                          }))):
            result = _run(agent_access.create_token(
                agent_access.CreateAgentTokenRequest(name=f"{plan.title()} Tenant"), tenant_id=tenant,
            ))
        assert result["token"] == "se_agent_plaintext", f"plan={plan} should mint"
    print("✅ test_mint_allowed_for_pro_and_agency_plans")


def test_mint_allowed_for_operator_even_on_free_plan():
    """The operator account (accounts.is_operator — migration 069, Ryan's
    own account) must be exempt from the MCP tier gate even if its `plan`
    column is 'free' (the day-one default, per PLAN_LIMITS' comment) —
    otherwise the tier gate locks Ryan out of the MCP tools he dogfoods."""
    tenant = uuid.uuid4()
    row = {"trial_ends_at": None, "stripe_subscription_id": None, "stripe_status": None,
           "plan": "free", "is_operator": True}
    with _patch_billing_fetch_one(row), \
         patch.object(agent_tokens, "create_agent_token",
                      AsyncMock(return_value=("se_agent_plaintext", {
                          "id": uuid.uuid4(), "name": "Operator",
                          "created_at": "2026-07-19T00:00:00Z",
                      }))):
        result = _run(agent_access.create_token(
            agent_access.CreateAgentTokenRequest(name="Operator"), tenant_id=tenant,
        ))
    assert result["token"] == "se_agent_plaintext"
    print("✅ test_mint_allowed_for_operator_even_on_free_plan")


# =============================================================================
# 6. ONE-definition lock
# =============================================================================

def test_good_standing_decision_defined_exactly_once():
    src = (_backend() / "routes" / "billing.py").read_text()
    tree = ast.parse(src)
    defs = [n.name for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "_good_standing_from_fields"]
    assert len(defs) == 1, (
        "C57 regression — `_good_standing_from_fields` must be defined "
        "EXACTLY once, in routes/billing.py. A second definition elsewhere "
        "means the good/bad decision could drift out of sync between the "
        "mint gate and the per-request verify gate."
    )
    print("✅ test_good_standing_decision_defined_exactly_once")


def test_authenticate_with_standing_calls_the_shared_decision_function():
    """agent_tokens.authenticate_with_standing must call
    routes.billing._good_standing_from_fields rather than re-deriving the
    active/canceled/trial branching inline — that re-derivation is exactly
    the kind of drift a second copy invites."""
    src = (_backend() / "agent_tokens.py").read_text()
    fn_src = re.search(
        r"async def authenticate_with_standing\([\s\S]+?(?=\nasync def |\ndef |\Z)", src,
    )
    assert fn_src, "authenticate_with_standing not found in agent_tokens.py"
    body = fn_src.group(0)
    assert "_good_standing_from_fields" in body, (
        "C57 regression — authenticate_with_standing no longer calls "
        "_good_standing_from_fields — it may have re-derived the decision "
        "inline, which can silently drift from the mint gate's logic."
    )
    # Belt-and-suspenders: no inline stripe_status branching duplicated here.
    assert not re.search(r"stripe_status\s*==\s*['\"]active['\"]", body), (
        "C57 regression — agent_tokens.py re-implements the active-status "
        "check inline instead of delegating to billing.py's ONE decision "
        "function."
    )
    print("✅ test_authenticate_with_standing_calls_the_shared_decision_function")


def test_mint_route_calls_shared_good_standing_helper():
    src = (_backend() / "routes" / "agent_access.py").read_text()
    assert "is_account_in_good_standing" in src, (
        "C57 regression — routes/agent_access.py::create_token no longer "
        "calls billing.is_account_in_good_standing — the mint gate is gone."
    )
    print("✅ test_mint_route_calls_shared_good_standing_helper")


TESTS = [
    test_no_subscription_is_good_standing,
    test_active_subscription_is_good_standing,
    test_active_free_trial_is_good_standing_even_with_no_stripe_status,
    test_expired_trial_falls_through_to_stripe_status,
    test_canceled_subscription_is_not_good_standing,
    test_past_due_subscription_is_not_good_standing,
    test_unpaid_subscription_is_not_good_standing,
    test_trial_end_in_past_but_has_stripe_subscription_does_not_override_bad_status,
    test_is_account_in_good_standing_true_for_active,
    test_is_account_in_good_standing_false_for_canceled,
    test_is_account_in_good_standing_no_account_row_fails_closed,
    test_authenticate_with_standing_good_account,
    test_authenticate_with_standing_lapsed_account,
    test_authenticate_with_standing_revoked_token_returns_none_tenant,
    test_authenticate_with_standing_wrong_prefix_short_circuits,
    test_authenticate_with_standing_starter_plan_surfaced,
    test_authenticate_with_standing_operator_flag_surfaced,
    test_get_agent_tenant_id_402_when_lapsed,
    test_get_agent_tenant_id_passes_through_when_good_standing,
    test_get_agent_tenant_id_still_401_on_bad_token_not_402,
    test_get_agent_tenant_id_402_when_starter_plan,
    test_get_agent_tenant_id_allowed_for_agency_plan,
    test_get_agent_tenant_id_operator_exempt_from_tier_gate,
    test_mint_refused_when_lapsed,
    test_mint_allowed_when_good_standing,
    test_mint_refused_for_free_tier_never_subscribed,
    test_mint_refused_for_starter_plan,
    test_mint_allowed_for_pro_and_agency_plans,
    test_mint_allowed_for_operator_even_on_free_plan,
    test_good_standing_decision_defined_exactly_once,
    test_authenticate_with_standing_calls_the_shared_decision_function,
    test_mint_route_calls_shared_good_standing_helper,
]


def main() -> int:
    failed = 0
    for t in TESTS:
        try:
            t()
        except AssertionError as e:
            print(f"❌ {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"❌ {t.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
