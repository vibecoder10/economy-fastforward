"""Authentication routes — email/password and Google OAuth.

Supports two login methods:
1. Email/password: POST /api/auth/register + POST /api/auth/login
2. Google OAuth: POST /api/auth/google (requires domain, optional)

All methods create an account + tenant on first signup and return a session JWT.
"""

import os
import uuid
import hashlib
import hmac
import secrets
from datetime import datetime, timezone, timedelta

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import verify_token, AuthUser
from database import fetch_one, execute

router = APIRouter(prefix="/api/auth", tags=["auth"])

SESSION_SECRET_ENV = "SESSION_SECRET"
GOOGLE_CLIENT_ID_ENV = "GOOGLE_OAUTH_CLIENT_ID"
SESSION_EXPIRY_DAYS = 30


class RegisterRequest(BaseModel):
    email: str
    password: str
    display_name: str = ""


class LoginRequest(BaseModel):
    email: str
    password: str


class GoogleAuthRequest(BaseModel):
    credential: str  # Google ID token from frontend


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


class AuthResponse(BaseModel):
    token: str
    user: dict


async def _verify_google_token(id_token: str) -> dict:
    """Verify Google ID token via Google's tokeninfo endpoint."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://oauth2.googleapis.com/tokeninfo",
            params={"id_token": id_token},
            timeout=10.0,
        )

    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid Google token")

    payload = resp.json()

    # Verify audience matches our client ID (if configured)
    expected_client_id = os.getenv(GOOGLE_CLIENT_ID_ENV)
    if expected_client_id and payload.get("aud") != expected_client_id:
        raise HTTPException(status_code=401, detail="Token audience mismatch")

    if not payload.get("email_verified", "false") == "true":
        raise HTTPException(status_code=401, detail="Email not verified")

    return payload


def _create_session_jwt(account_id: str, email: str, tenant_id: str) -> str:
    """Create a signed JWT for the authenticated session."""
    secret = os.getenv(SESSION_SECRET_ENV)
    if not secret:
        raise HTTPException(status_code=500, detail="SESSION_SECRET not configured")

    now = datetime.now(timezone.utc)
    payload = {
        "sub": account_id,
        "email": email,
        "tenant_id": tenant_id,
        "iat": now,
        "exp": now + timedelta(days=SESSION_EXPIRY_DAYS),
        "iss": "storyengine",
    }
    return jwt.encode(payload, secret, algorithm="HS256")


async def _create_tenant_for_account(account_id: str, name: str, email: str = "") -> str:
    """Create a tenant and membership for a new account."""
    tenant_id = str(uuid.uuid4())
    slug = f"user-{account_id[:8]}"

    # Ensure user exists in users table (memberships FK references users, not accounts)
    await execute(
        "INSERT INTO users (id, email, display_name) VALUES ($1, $2, $3) ON CONFLICT (id) DO NOTHING",
        account_id, email, name,
    )
    await execute(
        "INSERT INTO tenants (id, name, slug) VALUES ($1, $2, $3)",
        tenant_id, f"{name}'s Workspace", slug,
    )
    await execute(
        "INSERT INTO memberships (user_id, tenant_id, role) VALUES ($1, $2, 'owner')",
        account_id, tenant_id,
    )
    await execute(
        "INSERT INTO autopilot_config (tenant_id, enabled) VALUES ($1, false) ON CONFLICT (tenant_id) DO NOTHING",
        tenant_id,
    )

    return tenant_id


def _hash_password(password: str) -> str:
    """Hash password with PBKDF2-SHA256 (no external deps needed)."""
    salt = os.urandom(32)
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000)
    return salt.hex() + ":" + key.hex()


def _verify_password(password: str, stored_hash: str) -> bool:
    """Verify password against stored PBKDF2 hash."""
    try:
        salt_hex, key_hex = stored_hash.split(":")
        salt = bytes.fromhex(salt_hex)
        expected_key = bytes.fromhex(key_hex)
        actual_key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000)
        return hmac.compare_digest(actual_key, expected_key)
    except (ValueError, AttributeError):
        return False


@router.post("/register", response_model=AuthResponse)
async def register(body: RegisterRequest):
    """Register a new account with email and password.

    Creates account + tenant + membership on signup.
    Returns session JWT on success.
    """
    email = body.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Valid email required")
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    # Check if email already exists
    existing = await fetch_one("SELECT id FROM accounts WHERE email = $1", email)
    if existing:
        raise HTTPException(status_code=409, detail="An account with this email already exists")

    # Create account
    account_id = str(uuid.uuid4())
    display_name = body.display_name.strip() or email.split("@")[0]
    password_hash = _hash_password(body.password)

    await execute(
        """INSERT INTO accounts (id, email, display_name, password_hash, plan)
           VALUES ($1, $2, $3, $4, 'free')""",
        account_id, email, display_name, password_hash,
    )

    # Create tenant + membership
    tenant_id = await _create_tenant_for_account(account_id, display_name, email)

    token = _create_session_jwt(account_id, email, tenant_id)
    return AuthResponse(
        token=token,
        user={
            "id": account_id,
            "email": email,
            "display_name": display_name,
            "avatar_url": None,
            "plan": "free",
        },
    )


@router.post("/login", response_model=AuthResponse)
async def login(body: LoginRequest):
    """Login with email and password. Returns session JWT."""
    email = body.email.strip().lower()

    account = await fetch_one(
        "SELECT id, email, display_name, password_hash, avatar_url, plan FROM accounts WHERE email = $1",
        email,
    )
    if not account or not account.get("password_hash"):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not _verify_password(body.password, account["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    account_id = str(account["id"])
    membership = await fetch_one(
        "SELECT tenant_id FROM memberships WHERE user_id = $1 LIMIT 1",
        account_id,
    )
    tenant_id = str(membership["tenant_id"]) if membership else None
    if not tenant_id:
        tenant_id = await _create_tenant_for_account(account_id, account.get("display_name", ""))

    token = _create_session_jwt(account_id, email, tenant_id)
    return AuthResponse(
        token=token,
        user={
            "id": account_id,
            "email": account.get("email"),
            "display_name": account.get("display_name"),
            "avatar_url": account.get("avatar_url"),
            "plan": account.get("plan") or "free",
        },
    )


@router.post("/google", response_model=AuthResponse)
async def google_login(body: GoogleAuthRequest):
    """Authenticate with Google ID token.

    Creates account + tenant on first login.
    Returns session JWT on success.
    """
    google_payload = await _verify_google_token(body.credential)

    google_id = google_payload["sub"]
    email = google_payload.get("email", "")
    name = google_payload.get("name", email.split("@")[0])
    picture = google_payload.get("picture")

    # Look up existing account by google_id
    account = await fetch_one(
        "SELECT id, email, display_name, plan, avatar_url FROM accounts WHERE google_id = $1",
        google_id,
    )

    if account:
        # Existing user — update avatar if changed
        if picture and picture != account.get("avatar_url"):
            await execute(
                "UPDATE accounts SET avatar_url = $1, updated_at = now() WHERE id = $2",
                picture, account["id"],
            )

        account_id = str(account["id"])
        membership = await fetch_one(
            "SELECT tenant_id FROM memberships WHERE user_id = $1 LIMIT 1",
            account_id,
        )
        tenant_id = str(membership["tenant_id"]) if membership else None

        if not tenant_id:
            tenant_id = await _create_tenant_for_account(account_id, name)

        token = _create_session_jwt(account_id, email, tenant_id)
        return AuthResponse(
            token=token,
            user={
                "id": account_id,
                "email": account.get("email"),
                "display_name": account.get("display_name"),
                "avatar_url": picture or account.get("avatar_url"),
                "plan": account.get("plan") or "free",
            },
        )

    # Also check by email — account may exist from dev seeding without google_id
    account = await fetch_one(
        "SELECT id, email, display_name, plan, avatar_url FROM accounts WHERE email = $1",
        email,
    )

    if account:
        # Link Google identity to existing account
        await execute(
            "UPDATE accounts SET google_id = $1, avatar_url = COALESCE($2, avatar_url), updated_at = now() WHERE id = $3",
            google_id, picture, account["id"],
        )
        account_id = str(account["id"])
        membership = await fetch_one(
            "SELECT tenant_id FROM memberships WHERE user_id = $1 LIMIT 1",
            account_id,
        )
        tenant_id = str(membership["tenant_id"]) if membership else None
        if not tenant_id:
            tenant_id = await _create_tenant_for_account(account_id, name)

        token = _create_session_jwt(account_id, email, tenant_id)
        return AuthResponse(
            token=token,
            user={
                "id": account_id,
                "email": account.get("email"),
                "display_name": account.get("display_name"),
                "avatar_url": picture or account.get("avatar_url"),
                "plan": account.get("plan") or "free",
            },
        )

    # Brand new user — create account + tenant + membership
    account_id = str(uuid.uuid4())
    await execute(
        """INSERT INTO accounts (id, email, display_name, google_id, avatar_url, plan)
           VALUES ($1, $2, $3, $4, $5, 'free')""",
        account_id, email, name, google_id, picture,
    )
    tenant_id = await _create_tenant_for_account(account_id, name)

    token = _create_session_jwt(account_id, email, tenant_id)
    return AuthResponse(
        token=token,
        user={
            "id": account_id,
            "email": email,
            "display_name": name,
            "avatar_url": picture,
            "plan": "free",
        },
    )


@router.get("/me")
async def get_me(user: AuthUser = Depends(verify_token)):
    """Return current authenticated user info from session JWT."""
    account_id = user.id
    if account_id == "dev-user":
        account_id = "00000000-0000-0000-0000-000000000001"

    account = await fetch_one(
        "SELECT id, email, display_name, avatar_url, plan, created_at FROM accounts WHERE id = $1",
        account_id,
    )
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    membership = await fetch_one(
        "SELECT tenant_id FROM memberships WHERE user_id = $1 LIMIT 1",
        str(account["id"]),
    )

    return {
        "id": str(account["id"]),
        "email": account.get("email"),
        "display_name": account.get("display_name"),
        "avatar_url": account.get("avatar_url"),
        "plan": account.get("plan") or "free",
        "tenant_id": str(membership["tenant_id"]) if membership else None,
        "created_at": str(account["created_at"]) if account.get("created_at") else None,
    }


# =============================================
# Password Reset
# =============================================

RESET_TOKEN_EXPIRY_HOURS = 1


async def _send_reset_email(email: str, token: str):
    """Send password reset email via Resend API."""
    api_key = os.getenv("RESEND_API_KEY")
    if not api_key:
        # Dev mode: log the token instead of sending email
        print(f"[DEV] Password reset token for {email}: {token}")
        return

    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3001")
    reset_url = f"{frontend_url}/reset-password?token={token}"

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "from": os.getenv("EMAIL_FROM", "StoryEngine <noreply@storyengine.ai>"),
                "to": [email],
                "subject": "Reset your StoryEngine password",
                "html": (
                    f"<p>You requested a password reset.</p>"
                    f'<p><a href="{reset_url}">Click here to reset your password</a></p>'
                    f"<p>This link expires in {RESET_TOKEN_EXPIRY_HOURS} hour.</p>"
                    f"<p>If you didn't request this, you can safely ignore this email.</p>"
                ),
            },
            timeout=10.0,
        )
        if resp.status_code not in (200, 201):
            print(f"[WARN] Failed to send reset email: {resp.status_code} {resp.text}")


@router.post("/forgot-password")
async def forgot_password(body: ForgotPasswordRequest):
    """Request a password reset email.

    Always returns 200 (even if email not found) to prevent email enumeration.
    """
    email = body.email.strip().lower()

    account = await fetch_one(
        "SELECT id, email FROM accounts WHERE email = $1", email
    )

    if account and account.get("id"):
        # Invalidate any existing unused tokens for this account
        await execute(
            """UPDATE password_reset_tokens
               SET used_at = now()
               WHERE account_id = $1 AND used_at IS NULL""",
            str(account["id"]),
        )

        # Create new token
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=RESET_TOKEN_EXPIRY_HOURS)

        await execute(
            """INSERT INTO password_reset_tokens (account_id, token, expires_at)
               VALUES ($1, $2, $3)""",
            str(account["id"]), token, expires_at,
        )

        await _send_reset_email(email, token)

    # Always return success to prevent email enumeration
    return {"message": "If an account with that email exists, a reset link has been sent."}


@router.post("/reset-password")
async def reset_password(body: ResetPasswordRequest):
    """Reset password using a valid reset token."""
    if len(body.new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    token_row = await fetch_one(
        """SELECT id, account_id, expires_at, used_at
           FROM password_reset_tokens WHERE token = $1""",
        body.token,
    )

    if not token_row:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    if token_row.get("used_at"):
        raise HTTPException(status_code=400, detail="This reset token has already been used")

    if token_row["expires_at"] < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="This reset token has expired")

    # Update password
    account_id = str(token_row["account_id"])
    new_hash = _hash_password(body.new_password)

    await execute(
        "UPDATE accounts SET password_hash = $1, updated_at = now() WHERE id = $2",
        new_hash, account_id,
    )

    # Mark token as used
    await execute(
        "UPDATE password_reset_tokens SET used_at = now() WHERE id = $1",
        str(token_row["id"]),
    )

    return {"message": "Password has been reset successfully. You can now log in."}
