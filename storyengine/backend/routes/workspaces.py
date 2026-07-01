"""Channel Manager Command Center — workspace list + create (operator-only create).

A "workspace" is a tenant the current user is a member of. The operator (Ryan) can
hold many (one per client channel) and switch between them with the X-Active-Tenant
header (see auth.get_tenant_id). These endpoints intentionally key off the USER
(verify_token), not the active tenant, so listing/creating spans all workspaces
regardless of which one is currently active.
"""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import AuthUser, verify_token
from database import execute, fetch_all, fetch_one

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


class Workspace(BaseModel):
    tenant_id: str
    name: str
    role: str
    channel_name: Optional[str] = None
    youtube_connected: bool = False


class WorkspacesResponse(BaseModel):
    # Whether the caller may hold/create multiple client workspaces and see the
    # switcher UI. The real auth boundary is still the per-request membership
    # check in get_tenant_id; this only gates the UI.
    is_operator: bool
    workspaces: list[Workspace]


async def _is_operator(user_id: str) -> bool:
    row = await fetch_one("SELECT is_operator FROM accounts WHERE id = $1", user_id)
    return bool(row and row.get("is_operator"))


@router.get("", response_model=WorkspacesResponse)
async def list_workspaces(user: AuthUser = Depends(verify_token)):
    """Every tenant this user belongs to, with display info for the switcher."""
    rows = await fetch_all(
        """SELECT m.tenant_id, m.role, t.name AS tenant_name,
                  cp.channel_name, cp.youtube_refresh_token
           FROM memberships m
           JOIN tenants t ON t.id = m.tenant_id
           LEFT JOIN channel_profiles cp ON cp.tenant_id = m.tenant_id
           WHERE m.user_id = $1
           ORDER BY t.created_at""",
        user.id,
    )
    workspaces = [
        Workspace(
            tenant_id=str(r["tenant_id"]),
            name=r.get("channel_name") or r.get("tenant_name") or "Workspace",
            role=r["role"],
            channel_name=r.get("channel_name"),
            youtube_connected=bool(r.get("youtube_refresh_token")),
        )
        for r in rows
    ]
    return WorkspacesResponse(is_operator=await _is_operator(user.id), workspaces=workspaces)


class CreateWorkspaceRequest(BaseModel):
    name: str


@router.post("", response_model=Workspace)
async def create_workspace(body: CreateWorkspaceRequest, user: AuthUser = Depends(verify_token)):
    """Create a new client workspace (a tenant) and make the operator its owner.
    Operator-only: normal users don't spin up extra workspaces. Mirrors the signup
    tenant-creation (google_auth._create_tenant_for_account)."""
    if not await _is_operator(user.id):
        raise HTTPException(status_code=403, detail="Not authorized to create workspaces")
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Workspace name required")

    acct = await fetch_one("SELECT email, display_name FROM accounts WHERE id = $1", user.id)
    tenant_id = str(uuid.uuid4())
    slug = f"client-{tenant_id[:8]}"

    # memberships.user_id FK -> users (not accounts); ensure the row exists.
    await execute(
        "INSERT INTO users (id, email, display_name) VALUES ($1, $2, $3) ON CONFLICT (id) DO NOTHING",
        user.id, (acct or {}).get("email") or "", (acct or {}).get("display_name") or "",
    )
    await execute("INSERT INTO tenants (id, name, slug) VALUES ($1, $2, $3)", tenant_id, name, slug)
    await execute(
        "INSERT INTO memberships (user_id, tenant_id, role) VALUES ($1, $2, 'owner')",
        user.id, tenant_id,
    )
    await execute(
        "INSERT INTO autopilot_config (tenant_id, enabled) VALUES ($1, false) ON CONFLICT (tenant_id) DO NOTHING",
        tenant_id,
    )
    return Workspace(tenant_id=tenant_id, name=name, role="owner", channel_name=None, youtube_connected=False)
