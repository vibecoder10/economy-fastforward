"""Agent-token auth — a DISTINCT FastAPI dependency, wired ONLY on the
explicit MCP route allowlist (routes/mcp.py).

checklist P2.4a, chunk C26. docs/reports/2026-07-17-storyengine-agent-audit-
findings.md §S5-4 is the design law this file exists to satisfy: agent
tokens must NEVER become a 4th token type recognized inside auth.py's shared
verify_token/get_tenant_id. If they were, an external agent token would
immediately satisfy every OTHER route that depends on get_tenant_id too —
including `/api/settings/keys/{name}/reveal` (returns decrypted BYOK key
material, tenant-scoped but reachable by anything satisfying the generic
dependency) — worse than the money-gated paid verbs, since key-reveal isn't
gated at all. Every existing route stays reachable ONLY by a session JWT,
Supabase JWT, or dev-token, exactly as before this file was added — auth.py
is untouched (grep-proof: this module never imports it, and never adds
anything named "agent" to it).

Wire this dependency ONLY on routes/mcp.py. Never import it from auth.py,
never add it as a fallback branch inside get_tenant_id, never expose it on
any route outside the MCP router.
"""
from __future__ import annotations

import uuid as _uuid
from typing import Optional

from fastapi import Header, HTTPException

import agent_tokens


async def get_agent_tenant_id(
    authorization: Optional[str] = Header(None),
) -> _uuid.UUID:
    """FastAPI dependency for MCP routes only.

    Parses `Authorization: Bearer se_agent_<secret>`, verifies it against
    agent_tokens.authenticate_with_standing() (DB-row-backed, individually
    revocable — S5-3), and returns the owning tenant_id. 401 on anything
    else: missing header, wrong scheme, wrong/missing prefix, unknown hash,
    or a revoked token.

    Deliberately does NOT fall back to auth.verify_token for any reason
    (S5-4) — a session JWT presented here is just an unrecognized bearer
    string and gets the exact same flat 401 as garbage input (see
    tests/functional/test_c26_mcp_agent_tokens.py's cross-acceptance tests
    for the non-vacuous proof in both directions).

    C57: a valid, non-revoked token whose tenant's subscription has lapsed
    (billing.is_account_in_good_standing's decision, piggybacked onto this
    same DB query — see authenticate_with_standing's docstring) gets a 402
    with a renew-here message INSTEAD of a 401 — the token itself is still
    valid, the account just isn't in good standing. This is what makes
    existing tokens "die same-day" on a lapsed subscription with no
    separate revocation step: every call re-checks live, never a cached
    claim.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing agent token")
    token = authorization[len("Bearer "):].strip()
    if not token.startswith(agent_tokens.TOKEN_PREFIX):
        raise HTTPException(status_code=401, detail="Not a valid agent token")
    tenant_id, ok, reason = await agent_tokens.authenticate_with_standing(token)
    if tenant_id is None:
        raise HTTPException(status_code=401, detail="Invalid or revoked agent token")
    if not ok:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "subscription_lapsed",
                "message": (
                    f"Your StoryEngine subscription has lapsed ({reason}) — "
                    "renew at /billing to keep using the MCP agent."
                ),
                "upgrade_url": "/billing",
            },
        )
    return tenant_id
