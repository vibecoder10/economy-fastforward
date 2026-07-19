"""Agent tokens — DB-row-backed, individually revocable API tokens for
external MCP clients (checklist P2.4a, chunk C26). See migrations/
099_agent_tokens.sql for the schema rationale and docs/reports/2026-07-17-
storyengine-agent-audit-findings.md §S5-3/S5-4 for the design laws this
module exists to satisfy:

  S5-3: revocation must take effect on the NEXT request, not "eventually" —
  authenticate() re-checks `revoked_at IS NULL` against the DB on every
  single call, never trusts a cached or stateless claim.
  S5-4: this module is the ONLY place that mints/verifies agent tokens.
  auth.py (session/Supabase JWTs) never imports this module and this module
  never imports auth.py's token logic — see auth_agent.py for the FastAPI
  dependency that consumes authenticate() on the MCP route allowlist.

Token shape: `se_agent_<43-char urlsafe secret>`. The `se_agent_` prefix
means a session JWT (a `.`-delimited base64 blob) can never be mistaken for
an agent token, and lets get_agent_tenant_id (auth_agent.py) reject anything
without the prefix before ever touching the database.

Mint/list/revoke are USER actions — called from the normal session-authed
app surface (routes/agent_access.py, Depends(get_tenant_id)), never from an
agent-authed request. authenticate() is the one function an agent-authed
request (auth_agent.get_agent_tenant_id) is allowed to call.
"""
from __future__ import annotations

import hashlib
import secrets
import uuid as _uuid
from typing import Any, Optional

from database import execute, fetch_all, fetch_one

TOKEN_PREFIX = "se_agent_"


def _hash_token(secret: str) -> str:
    """sha256 hex digest of the plaintext secret.

    Deliberately NOT a slow KDF (pbkdf2/bcrypt/scrypt): this hashes a
    256-bit random token that is already all entropy — nothing to
    dictionary-guess — so a slow hash only taxes every legitimate MCP call
    for zero security benefit. Contrast google_auth.py's pbkdf2 hashing,
    which defends a LOW-entropy human-chosen password against offline
    guessing; that threat model does not apply here.
    """
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


async def create_agent_token(tenant_id, name: str) -> tuple[str, dict[str, Any]]:
    """Mint a new agent token for this tenant.

    Returns (plaintext_once, row). The plaintext is NEVER persisted anywhere
    — this return value is the only time it will ever exist outside the
    caller's memory. The caller (C28's mint route/UI) must show it to the
    user exactly once and then discard it; only the hash is stored.
    """
    secret = secrets.token_urlsafe(32)
    plaintext = f"{TOKEN_PREFIX}{secret}"
    token_hash = _hash_token(plaintext)
    row = await fetch_one(
        """INSERT INTO agent_tokens (tenant_id, name, token_hash)
           VALUES ($1, $2, $3)
           RETURNING id, name, created_at, last_used_at, revoked_at""",
        tenant_id, name, token_hash,
    )
    return plaintext, dict(row)


async def list_agent_tokens(tenant_id) -> list[dict[str, Any]]:
    """List this tenant's tokens. Never returns token_hash (or plaintext,
    which is never stored at all) — display-safe by construction, since the
    SELECT simply never names that column."""
    rows = await fetch_all(
        """SELECT id, name, created_at, last_used_at, revoked_at
           FROM agent_tokens
           WHERE tenant_id = $1
           ORDER BY created_at DESC""",
        tenant_id,
    )
    return [dict(r) for r in (rows or [])]


async def revoke_agent_token(tenant_id, token_id) -> bool:
    """Revoke one token. Idempotent: revoking an already-revoked or
    nonexistent token both return False (no row updated) — either way the
    token is (still) unusable, so the caller doesn't need to distinguish
    those cases."""
    result = await execute(
        """UPDATE agent_tokens SET revoked_at = now()
           WHERE id = $1 AND tenant_id = $2 AND revoked_at IS NULL""",
        token_id, tenant_id,
    )
    # asyncpg's execute() returns a command tag string like "UPDATE 1".
    return isinstance(result, str) and result.strip().endswith(" 1")


async def authenticate(token: str) -> Optional[_uuid.UUID]:
    """The ONLY function an agent-authed request may call (auth_agent.py).

    Returns the tenant_id UUID for a valid, non-revoked token, else None.
    Never raises for a bad/malformed token — the caller (get_agent_tenant_id)
    owns the HTTP status decision.

    S5-3: `revoked_at IS NULL` is evaluated on THIS call, every call — a
    token revoked a second ago is rejected on the very next request. There is
    no cache and no stateless claim to fall back on.
    """
    if not token or not token.startswith(TOKEN_PREFIX):
        return None
    token_hash = _hash_token(token)
    row = await fetch_one(
        """SELECT id, tenant_id FROM agent_tokens
           WHERE token_hash = $1 AND revoked_at IS NULL""",
        token_hash,
    )
    if not row:
        return None
    # Fail-soft: last_used_at is telemetry only, never allowed to block auth.
    try:
        await execute(
            "UPDATE agent_tokens SET last_used_at = now() WHERE id = $1",
            row["id"],
        )
    except Exception:
        pass
    tenant_id = row["tenant_id"]
    return tenant_id if isinstance(tenant_id, _uuid.UUID) else _uuid.UUID(str(tenant_id))
