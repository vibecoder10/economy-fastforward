"""Agent access tokens — mint/list/revoke (checklist P2.4a, chunk C26).

USER actions only: every route here is gated by the normal session auth
(Depends(get_tenant_id) — the SAME dependency every other authed route in
this app uses), never auth_agent.get_agent_tenant_id. An agent token can
list/read videos over MCP (routes/mcp.py); it can never mint or revoke a
token for itself or anyone else — minting/revoking requires a real logged-in
session. C28 wires the Settings "Agent access" UI to these three routes;
this chunk ships the routes unconditionally (they're exactly as safe as any
other session-authed route with no caller yet — no new attack surface, no
MCP_ENABLED gate needed here).
"""
from __future__ import annotations

import uuid as _uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import agent_tokens
from auth import get_tenant_id

router = APIRouter(prefix="/api/agent-tokens", tags=["agent-tokens"])


class CreateAgentTokenRequest(BaseModel):
    name: str


@router.post("")
async def create_token(
    body: CreateAgentTokenRequest,
    tenant_id: _uuid.UUID = Depends(get_tenant_id),
):
    """Mint a new agent token. The `token` field in the response is shown
    exactly once — it is never retrievable again (only its hash is stored,
    migrations/099_agent_tokens.sql)."""
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    plaintext, row = await agent_tokens.create_agent_token(tenant_id, name)
    return {
        "id": str(row["id"]),
        "name": row["name"],
        "token": plaintext,
        "created_at": row["created_at"],
    }


@router.get("")
async def list_tokens(tenant_id: _uuid.UUID = Depends(get_tenant_id)):
    """Never includes token_hash or plaintext — display-safe by construction."""
    rows = await agent_tokens.list_agent_tokens(tenant_id)
    return [
        {
            "id": str(r["id"]),
            "name": r["name"],
            "created_at": r["created_at"],
            "last_used_at": r.get("last_used_at"),
            "revoked_at": r.get("revoked_at"),
        }
        for r in rows
    ]


@router.delete("/{token_id}")
async def revoke_token(
    token_id: str,
    tenant_id: _uuid.UUID = Depends(get_tenant_id),
):
    try:
        token_uuid = _uuid.UUID(token_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid token id")
    ok = await agent_tokens.revoke_agent_token(tenant_id, token_uuid)
    if not ok:
        raise HTTPException(status_code=404, detail="Token not found or already revoked")
    return {"revoked": True}
