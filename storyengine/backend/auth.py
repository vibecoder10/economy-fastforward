"""JWT verification for Supabase Auth tokens."""

import os
import uuid as _uuid
import jwt
from fastapi import Depends, HTTPException, Request, status
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

    # Fall back to Supabase JWT
    jwt_secret = os.getenv("SUPABASE_JWT_SECRET")
    if not jwt_secret:
        raise HTTPException(status_code=401, detail="Invalid token")

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


async def get_tenant_id(user: AuthUser = Depends(verify_token)) -> _uuid.UUID:
    """Get tenant_id for the current user as a UUID.

    Returns UUID so asyncpg can match against UUID columns directly.
    """
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
