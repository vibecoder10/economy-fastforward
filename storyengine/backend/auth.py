"""JWT verification for Supabase Auth tokens."""

import os
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import Optional

security = HTTPBearer()


class AuthUser(BaseModel):
    """Authenticated user from JWT."""
    id: str
    email: Optional[str] = None
    tenant_id: Optional[str] = None


def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> AuthUser:
    """Verify Supabase JWT and extract user info.

    For now, also supports a simple API key mode for development.
    """
    token = credentials.credentials

    # Dev mode: accept "dev-token" for local testing
    if token == "dev-token" and os.getenv("ENV", "development") == "development":
        return AuthUser(id="dev-user", email="dev@local", tenant_id=os.getenv("DEV_TENANT_ID"))

    jwt_secret = os.getenv("SUPABASE_JWT_SECRET")
    if not jwt_secret:
        raise HTTPException(status_code=500, detail="JWT secret not configured")

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


async def get_tenant_id(user: AuthUser = Depends(verify_token)) -> str:
    """Get tenant_id for the current user.

    Queries memberships table to find user's tenant.
    For now, returns DEV_TENANT_ID or queries DB.
    """
    if user.tenant_id:
        return user.tenant_id

    # Query memberships table
    from database import fetch_one
    row = await fetch_one(
        "SELECT tenant_id FROM memberships WHERE user_id = $1 LIMIT 1",
        user.id,
    )
    if not row:
        raise HTTPException(status_code=403, detail="No tenant membership found")

    return str(row["tenant_id"])
