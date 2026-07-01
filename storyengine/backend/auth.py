"""JWT verification for Supabase Auth tokens."""

import os
import uuid as _uuid
import jwt
from fastapi import Depends, HTTPException, Header, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import Optional

security = HTTPBearer(auto_error=False)


class AuthUser(BaseModel):
    """Authenticated user from JWT."""
    id: str
    email: Optional[str] = None
    tenant_id: Optional[str] = None


def verify_token(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> AuthUser:
    """Verify JWT and extract user info.

    Supports three token types (tried in order):
    1. Dev token ("dev-token") for local development
    2. StoryEngine session JWT (iss=storyengine, signed with SESSION_SECRET)
    3. Supabase JWT (signed with SUPABASE_JWT_SECRET)

    Also accepts token via query_params ?token= for SSE connections
    (EventSource cannot set Authorization headers).
    """
    # Try Authorization header first, fall back to query param
    token = None
    if credentials:
        token = credentials.credentials
    if not token:
        token = request.query_params.get("token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # Dev mode: accept dev token for local testing (requires explicit opt-in)
    dev_token = os.getenv("DEV_TOKEN")
    if dev_token and token == dev_token and os.getenv("DEV_MODE") == "true":
        return AuthUser(id="dev-user", email="dev@local", tenant_id=os.getenv("DEV_TENANT_ID"))

    # Try StoryEngine session JWT first (from Google OAuth login)
    session_secret = os.getenv("SESSION_SECRET")
    if session_secret:
        try:
            payload = jwt.decode(token, session_secret, algorithms=["HS256"])
            if payload.get("iss") == "storyengine":
                user_id = payload.get("sub")
                if not user_id:
                    raise HTTPException(status_code=401, detail="Invalid token: no sub claim")
                return AuthUser(
                    id=user_id,
                    email=payload.get("email"),
                    tenant_id=payload.get("tenant_id"),
                )
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Token expired")
        except jwt.InvalidTokenError:
            pass  # Not a session JWT, try Supabase next

    # Fall back to Supabase JWT (legacy — only if SUPABASE_JWT_SECRET is configured)
    jwt_secret = os.getenv("SUPABASE_JWT_SECRET")
    if not jwt_secret:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    try:
        payload = jwt.decode(
            token,
            jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
        )
        user_id = payload.get("sub")
        email = payload.get("email")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token: no sub claim")

        return AuthUser(id=user_id, email=email)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")


async def _user_has_membership(user_id: str, tenant_id: _uuid.UUID) -> bool:
    """True iff this user has a membership row in the given tenant. This is the
    authorization boundary for the command center's workspace switch — nothing
    else may be trusted to decide which tenant a request is allowed to act as."""
    from database import fetch_one
    row = await fetch_one(
        "SELECT 1 AS ok FROM memberships WHERE user_id = $1 AND tenant_id = $2 LIMIT 1",
        user_id, tenant_id,
    )
    return bool(row)


async def get_tenant_id(
    user: AuthUser = Depends(verify_token),
    x_active_tenant: Optional[str] = Header(None, alias="X-Active-Tenant"),
) -> _uuid.UUID:
    """Get the tenant_id this request should act as, as a UUID.

    Normally the JWT's tenant (or the user's first membership). The Channel
    Manager command center can override it with an `X-Active-Tenant` header to
    switch between client channels — but ONLY to a tenant the user actually
    belongs to. An override naming a non-member tenant is a hard 403, never a
    silent fallback, so the switch can never become a cross-tenant data leak.

    SECURITY: with no header this is byte-for-byte the prior behavior, so normal
    single-channel requests are entirely unaffected.

    Returns UUID so asyncpg can match against UUID columns directly.
    """
    # Active-workspace override (command center) — validate membership first.
    if x_active_tenant:
        try:
            requested = _uuid.UUID(x_active_tenant)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Invalid X-Active-Tenant header")
        if not await _user_has_membership(user.id, requested):
            raise HTTPException(status_code=403, detail="Not a member of that workspace")
        return requested

    if user.tenant_id:
        return _uuid.UUID(user.tenant_id)

    # Query memberships table
    from database import fetch_one
    row = await fetch_one(
        "SELECT tenant_id FROM memberships WHERE user_id = $1 LIMIT 1",
        user.id,
    )
    if not row:
        raise HTTPException(status_code=403, detail="No tenant membership found")

    return row["tenant_id"] if isinstance(row["tenant_id"], _uuid.UUID) else _uuid.UUID(str(row["tenant_id"]))
