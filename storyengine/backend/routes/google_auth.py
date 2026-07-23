"""Authentication routes — email/password and Google OAuth.

Supports two login methods:
1. Email/password: POST /api/auth/register + POST /api/auth/login
2. Google OAuth: POST /api/auth/google (requires domain, optional)

All methods create an account + tenant on first signup and return a session JWT.
"""

import os
import time
import uuid
import hashlib
import hmac
import secrets
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from auth import verify_token, AuthUser, get_tenant_id
from database import fetch_one, execute
from email_service import send_welcome_email, send_reset_email, send_verification_email

router = APIRouter(prefix="/api/auth", tags=["auth"])

SESSION_SECRET_ENV = "SESSION_SECRET"
GOOGLE_CLIENT_ID_ENV = "GOOGLE_OAUTH_CLIENT_ID"
SESSION_EXPIRY_DAYS = 30
TRIAL_DAYS = 7  # free trial length; expires to Free tier (see email_tasks.check_trial_expired)
EMAIL_VERIFY_EXPIRY_HOURS = 24  # how long a verification link stays valid


class RegisterRequest(BaseModel):
    email: str
    password: str
    display_name: str = ""
    beta_code: Optional[str] = None


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
    beta_applied: bool = False


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


async def _send_welcome_email(email_addr: str, display_name: str):
    """Send welcome email to new users (delegates to shared email module)."""
    await send_welcome_email(email_addr, display_name)


# PBKDF2-HMAC-SHA256 work factor. 600k is the OWASP 2023 floor for this KDF.
# (bcrypt/argon2 would be stronger but need a new dependency; PBKDF2 is stdlib
# and ships now. The self-describing hash format lets this rise later and old
# hashes upgrade transparently on the next successful login.)
PBKDF2_ITERATIONS = 600_000
_LEGACY_ITERATIONS = 100_000


def _hash_password(password: str) -> str:
    """Hash a password with PBKDF2-HMAC-SHA256 (stdlib, no external deps).

    Self-describing format so the work factor can rise over time:
    'pbkdf2_sha256$<iterations>$<salt_hex>$<key_hex>'.
    """
    salt = os.urandom(32)
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${key.hex()}"


def _verify_password(password: str, stored_hash: str) -> bool:
    """Verify against the new self-describing format OR the legacy 'salt:key'
    format (fixed 100k iterations). Constant-time compare on both paths."""
    try:
        if stored_hash.startswith("pbkdf2_sha256$"):
            _, iter_s, salt_hex, key_hex = stored_hash.split("$")
            iterations = int(iter_s)
        else:
            salt_hex, key_hex = stored_hash.split(":")
            iterations = _LEGACY_ITERATIONS
        salt = bytes.fromhex(salt_hex)
        expected_key = bytes.fromhex(key_hex)
        actual_key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
        return hmac.compare_digest(actual_key, expected_key)
    except (ValueError, AttributeError):
        return False


def _password_needs_upgrade(stored_hash: str) -> bool:
    """True if the stored hash is the legacy format or uses fewer iterations
    than the current target — re-hash on the next successful login."""
    try:
        if not stored_hash.startswith("pbkdf2_sha256$"):
            return True
        return int(stored_hash.split("$")[1]) < PBKDF2_ITERATIONS
    except (ValueError, AttributeError, IndexError):
        return False


# ── Brute-force guard for unauthenticated auth endpoints ─────────────────────
# The global RateLimitMiddleware skips /api/auth and keys on tenant_id (none
# exists pre-login), so login/register/forgot would otherwise be unthrottled.
# Sliding-window per-IP + per-email. In-memory (per-process) — fine for the
# single-worker deployment; move to Redis if/when we scale to multiple workers.
# ponytail: keys accumulate until restart; negligible at launch scale.
_AUTH_ATTEMPTS: dict[str, list[float]] = defaultdict(list)
_AUTH_WINDOW = 300.0   # 5 minutes
_AUTH_MAX = 10         # attempts per identity per window


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _auth_rate_limit(request: Request, email: str = "") -> None:
    """Record an attempt and raise 429 if this IP or email is over the cap."""
    now = time.time()
    keys = [f"ip:{_client_ip(request)}"]
    if email:
        keys.append(f"email:{email}")
    for k in keys:
        bucket = [t for t in _AUTH_ATTEMPTS[k] if t > now - _AUTH_WINDOW]
        if len(bucket) >= _AUTH_MAX:
            _AUTH_ATTEMPTS[k] = bucket
            raise HTTPException(
                status_code=429,
                detail="Too many attempts. Please wait a few minutes and try again.",
            )
        bucket.append(now)
        _AUTH_ATTEMPTS[k] = bucket


@router.post("/register", response_model=AuthResponse)
async def register(body: RegisterRequest, request: Request):
    """Register a new account with email and password.

    Creates account + tenant + membership on signup.
    Returns session JWT on success.
    """
    email = body.email.strip().lower()
    _auth_rate_limit(request, email)
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

    # Beta access code redemption (migration 119): a submitted code can grant
    # a longer free trial than the default TRIAL_DAYS. Redemption is ONE
    # atomic UPDATE...RETURNING — the returned row IS the "valid, active, and
    # under cap" check, so two signups racing the same code can't both win
    # past a max_redemptions cap (see migrations/119_beta_codes.sql). A
    # missing row (bad code, inactive, or cap already hit) — or no code
    # submitted at all — falls back to the normal grant. This NEVER blocks
    # or errors the signup.
    beta_applied = False
    trial_days = TRIAL_DAYS
    redeemed_code = None
    submitted_code = (body.beta_code or "").strip().lower()
    if submitted_code:
        redeemed = await fetch_one(
            """UPDATE beta_codes
                  SET redemptions_used = redemptions_used + 1
                WHERE code = $1 AND active = TRUE
                  AND (max_redemptions IS NULL OR redemptions_used < max_redemptions)
                RETURNING trial_days""",
            submitted_code,
        )
        if redeemed:
            trial_days = redeemed["trial_days"]
            beta_applied = True
            redeemed_code = submitted_code

    trial_ends_at = datetime.now(timezone.utc) + timedelta(days=trial_days)
    # Email verification: password signups start unverified and must confirm via
    # the emailed link before they can generate (gated in billing.check_plan_limits).
    verify_token = secrets.token_urlsafe(32)
    verify_expires = datetime.now(timezone.utc) + timedelta(hours=EMAIL_VERIFY_EXPIRY_HOURS)
    await execute(
        """INSERT INTO accounts (id, email, display_name, password_hash, plan, trial_ends_at,
               email_verified, email_verification_token, email_verification_expires, beta_code)
           VALUES ($1, $2, $3, $4, 'free', $5, false, $6, $7, $8)""",
        account_id, email, display_name, password_hash, trial_ends_at,
        verify_token, verify_expires, redeemed_code,
    )

    # Create tenant + membership
    tenant_id = await _create_tenant_for_account(account_id, display_name, email)

    await send_verification_email(email, display_name, verify_token)

    token = _create_session_jwt(account_id, email, tenant_id)
    return AuthResponse(
        token=token,
        user={
            "id": account_id,
            "email": email,
            "display_name": display_name,
            "avatar_url": None,
            "plan": "free",
            "email_verified": False,
        },
        beta_applied=beta_applied,
    )


@router.post("/login", response_model=AuthResponse)
async def login(body: LoginRequest, request: Request):
    """Login with email and password. Returns session JWT."""
    email = body.email.strip().lower()
    _auth_rate_limit(request, email)

    account = await fetch_one(
        "SELECT id, email, display_name, password_hash, avatar_url, plan FROM accounts WHERE email = $1",
        email,
    )
    if not account or not account.get("password_hash"):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not _verify_password(body.password, account["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    account_id = str(account["id"])

    # Transparent hash upgrade: legacy/low-iteration hashes get re-hashed at the
    # current work factor on a successful login. Best-effort — never block login.
    if _password_needs_upgrade(account["password_hash"]):
        try:
            await execute(
                "UPDATE accounts SET password_hash = $1, updated_at = now() WHERE id = $2",
                _hash_password(body.password), account_id,
            )
        except Exception:
            pass
    membership = await fetch_one(
        "SELECT tenant_id FROM memberships WHERE user_id = $1 "
        "ORDER BY (role = 'owner') DESC, created_at ASC LIMIT 1",
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
            "SELECT tenant_id FROM memberships WHERE user_id = $1 "
        "ORDER BY (role = 'owner') DESC, created_at ASC LIMIT 1",
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
            "SELECT tenant_id FROM memberships WHERE user_id = $1 "
        "ORDER BY (role = 'owner') DESC, created_at ASC LIMIT 1",
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
    trial_ends_at = datetime.now(timezone.utc) + timedelta(days=TRIAL_DAYS)
    await execute(
        """INSERT INTO accounts (id, email, display_name, google_id, avatar_url, plan,
               trial_ends_at, email_verified)
           VALUES ($1, $2, $3, $4, $5, 'free', $6, true)""",
        account_id, email, name, google_id, picture, trial_ends_at,
    )
    tenant_id = await _create_tenant_for_account(account_id, name)
    await _send_welcome_email(email, name)

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
        "SELECT id, email, display_name, avatar_url, plan, created_at, email_verified FROM accounts WHERE id = $1",
        account_id,
    )
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    membership = await fetch_one(
        "SELECT tenant_id FROM memberships WHERE user_id = $1 "
        "ORDER BY (role = 'owner') DESC, created_at ASC LIMIT 1",
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
        "email_verified": bool(account.get("email_verified")),
    }


class VerifyEmailRequest(BaseModel):
    token: str


@router.post("/verify-email")
async def verify_email(body: VerifyEmailRequest):
    """Confirm an email via the token from the verification link. Public — the
    token IS the credential. Marks the account verified and clears the token."""
    token = (body.token or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="Missing verification token")

    account = await fetch_one(
        """SELECT id, email_verified, email_verification_expires
           FROM accounts WHERE email_verification_token = $1""",
        token,
    )
    if not account:
        # Already-verified accounts have a cleared token; treat as success so a
        # double-click on the link doesn't show a scary error.
        raise HTTPException(status_code=400, detail="This link is invalid or already used. Try logging in.")

    expires = account.get("email_verification_expires")
    if expires and expires < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="This link has expired. Request a new one from the app.")

    await execute(
        """UPDATE accounts
           SET email_verified = true, email_verification_token = NULL,
               email_verification_expires = NULL, updated_at = now()
           WHERE id = $1""",
        account["id"],
    )
    return {"verified": True}


@router.post("/resend-verification")
async def resend_verification(request: Request, user: AuthUser = Depends(verify_token)):
    """Re-send the verification email for the logged-in account."""
    account_id = user.id
    _auth_rate_limit(request, account_id)
    account = await fetch_one(
        "SELECT id, email, display_name, email_verified FROM accounts WHERE id = $1",
        account_id,
    )
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    if account.get("email_verified"):
        return {"sent": False, "already_verified": True}

    new_token = secrets.token_urlsafe(32)
    new_expires = datetime.now(timezone.utc) + timedelta(hours=EMAIL_VERIFY_EXPIRY_HOURS)
    await execute(
        """UPDATE accounts SET email_verification_token = $1,
               email_verification_expires = $2, updated_at = now() WHERE id = $3""",
        new_token, new_expires, account["id"],
    )
    ok = await send_verification_email(account["email"], account.get("display_name") or "", new_token)
    return {"sent": bool(ok)}


# =============================================
# Password Reset
# =============================================

RESET_TOKEN_EXPIRY_HOURS = 1


async def _send_reset_email(email_addr: str, token: str):
    """Send password reset email (delegates to shared email module)."""
    await send_reset_email(email_addr, token, expiry_hours=RESET_TOKEN_EXPIRY_HOURS)


@router.post("/forgot-password")
async def forgot_password(body: ForgotPasswordRequest, request: Request):
    """Request a password reset email.

    Always returns 200 (even if email not found) to prevent email enumeration.
    """
    email = body.email.strip().lower()
    _auth_rate_limit(request, email)

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


# ---------------------------------------------------------------------------
# Google Drive OAuth — server-side flow for per-user Drive access
# ---------------------------------------------------------------------------

DRIVE_SCOPES = "https://www.googleapis.com/auth/drive.file"


@router.get("/google-drive/connect")
async def google_drive_connect(tenant: uuid.UUID = Depends(get_tenant_id)):
    """Initiate Google OAuth for Drive access.

    Returns the authorization URL. Frontend redirects the user there.
    Google redirects back to /api/auth/google-drive/callback with an auth code.
    """
    client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
    if not client_id:
        raise HTTPException(status_code=500, detail="GOOGLE_OAUTH_CLIENT_ID not configured")

    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3001")
    redirect_uri = os.getenv("GOOGLE_DRIVE_REDIRECT_URI", f"{frontend_url}/settings/drive-callback")

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": DRIVE_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": str(tenant),
    }
    qs = "&".join(f"{k}={httpx.URL('').copy_with(params={k: v}).params[k]}" for k, v in params.items())
    auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{qs}"

    return {"auth_url": auth_url}


class DriveCallbackRequest(BaseModel):
    code: str


@router.post("/google-drive/callback")
async def google_drive_callback(
    body: DriveCallbackRequest,
    tenant: uuid.UUID = Depends(get_tenant_id),
):
    """Exchange Google auth code for refresh token and store it.

    Frontend sends the auth code after Google redirects back.
    We exchange it for tokens server-side (client secret never leaves backend).
    """
    client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise HTTPException(status_code=500, detail="Google OAuth credentials not configured")

    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3001")
    redirect_uri = os.getenv("GOOGLE_DRIVE_REDIRECT_URI", f"{frontend_url}/settings/drive-callback")

    # Exchange auth code for tokens
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": body.code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=15.0,
        )

    if resp.status_code != 200:
        detail = resp.json().get("error_description", "Token exchange failed")
        raise HTTPException(status_code=400, detail=detail)

    tokens = resp.json()
    refresh_token = tokens.get("refresh_token")
    access_token = tokens.get("access_token")

    if not refresh_token:
        raise HTTPException(
            status_code=400,
            detail="No refresh token received. Try disconnecting the app in Google Account settings and reconnecting.",
        )

    # Store refresh token on the tenant's channel profile
    tenant_id = str(tenant)
    existing = await fetch_one(
        "SELECT id FROM channel_profiles WHERE tenant_id = $1", tenant_id
    )
    if existing:
        await execute(
            "UPDATE channel_profiles SET google_drive_refresh_token = $1, updated_at = now() WHERE tenant_id = $2",
            refresh_token, tenant_id,
        )
    else:
        await execute(
            "INSERT INTO channel_profiles (tenant_id, google_drive_refresh_token) VALUES ($1, $2)",
            tenant_id, refresh_token,
        )

    return {"status": "connected", "access_token": access_token}


@router.get("/google-drive/status")
async def google_drive_status(tenant: uuid.UUID = Depends(get_tenant_id)):
    """Check if Google Drive is connected for this tenant."""
    tenant_id = str(tenant)
    row = await fetch_one(
        "SELECT google_drive_refresh_token, google_drive_folder_id, google_drive_folder_name "
        "FROM channel_profiles WHERE tenant_id = $1",
        tenant_id,
    )
    if not row or not row.get("google_drive_refresh_token"):
        return {"connected": False, "folder_id": None, "folder_name": None}

    return {
        "connected": True,
        "folder_id": row.get("google_drive_folder_id") or None,
        "folder_name": row.get("google_drive_folder_name") or None,
    }


@router.post("/google-drive/disconnect")
async def google_drive_disconnect(tenant: uuid.UUID = Depends(get_tenant_id)):
    """Disconnect Google Drive — removes stored refresh token and folder selection."""
    tenant_id = str(tenant)
    await execute(
        "UPDATE channel_profiles SET google_drive_refresh_token = NULL, "
        "google_drive_folder_id = NULL, google_drive_folder_name = NULL, "
        "updated_at = now() WHERE tenant_id = $1",
        tenant_id,
    )
    return {"status": "disconnected"}


@router.post("/google-drive/access-token")
async def google_drive_access_token(tenant: uuid.UUID = Depends(get_tenant_id)):
    """Get a fresh access token for the Google Picker.

    Uses the stored refresh token to mint a short-lived access token.
    The frontend uses this to open the Picker — no API key needed.
    """
    tenant_id = str(tenant)
    row = await fetch_one(
        "SELECT google_drive_refresh_token FROM channel_profiles WHERE tenant_id = $1",
        tenant_id,
    )
    if not row or not row.get("google_drive_refresh_token"):
        raise HTTPException(status_code=400, detail="Google Drive not connected")

    client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise HTTPException(status_code=500, detail="Google OAuth credentials not configured")

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": row["google_drive_refresh_token"],
                "grant_type": "refresh_token",
            },
            timeout=10.0,
        )

    if resp.status_code != 200:
        raise HTTPException(status_code=400, detail="Failed to refresh Drive token. Try reconnecting.")

    tokens = resp.json()
    return {"access_token": tokens["access_token"]}


# ---------------------------------------------------------------------------
# YouTube OAuth — server-side flow for per-user YouTube analytics access
# ---------------------------------------------------------------------------

YOUTUBE_SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly https://www.googleapis.com/auth/yt-analytics.readonly"


@router.get("/youtube/connect")
async def youtube_connect(tenant: uuid.UUID = Depends(get_tenant_id)):
    """Initiate Google OAuth for YouTube access.

    Returns the authorization URL. Frontend redirects the user there.
    Google redirects back to /settings/youtube-callback with an auth code.
    """
    client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
    if not client_id:
        raise HTTPException(status_code=500, detail="GOOGLE_OAUTH_CLIENT_ID not configured")

    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3001")
    redirect_uri = os.getenv("YOUTUBE_REDIRECT_URI", f"{frontend_url}/settings/youtube-callback")

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": YOUTUBE_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": str(tenant),
    }
    qs = "&".join(f"{k}={httpx.URL('').copy_with(params={k: v}).params[k]}" for k, v in params.items())
    auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{qs}"

    return {"auth_url": auth_url}


class YouTubeCallbackRequest(BaseModel):
    code: str


@router.post("/youtube/callback")
async def youtube_callback(
    body: YouTubeCallbackRequest,
    tenant: uuid.UUID = Depends(get_tenant_id),
):
    """Exchange YouTube auth code for refresh token, fetch channel info, and store.

    After OAuth, we:
    1. Exchange code for tokens
    2. Fetch the user's YouTube channel info (name, description, subscriber count)
    3. Store refresh token + channel info on channel_profiles
    """
    client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise HTTPException(status_code=500, detail="Google OAuth credentials not configured")

    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3001")
    redirect_uri = os.getenv("YOUTUBE_REDIRECT_URI", f"{frontend_url}/settings/youtube-callback")

    # Exchange auth code for tokens
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": body.code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=15.0,
        )

    if resp.status_code != 200:
        detail = resp.json().get("error_description", "Token exchange failed")
        raise HTTPException(status_code=400, detail=detail)

    tokens = resp.json()
    refresh_token = tokens.get("refresh_token")
    access_token = tokens.get("access_token")

    if not refresh_token:
        raise HTTPException(
            status_code=400,
            detail="No refresh token received. Try disconnecting the app in Google Account settings and reconnecting.",
        )

    # Fetch YouTube channel info using the access token
    channel_id = None
    channel_name = None
    channel_description = None
    try:
        async with httpx.AsyncClient() as client:
            yt_resp = await client.get(
                "https://www.googleapis.com/youtube/v3/channels",
                params={"part": "snippet,statistics", "mine": "true"},
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10.0,
            )
        if yt_resp.status_code == 200:
            data = yt_resp.json()
            items = data.get("items", [])
            if items:
                channel_id = items[0]["id"]
                snippet = items[0].get("snippet", {})
                channel_name = snippet.get("title", "")
                channel_description = snippet.get("description", "")
    except Exception:
        pass  # Channel info is nice-to-have, not blocking

    # Store on channel_profiles
    tenant_id = str(tenant)
    existing = await fetch_one(
        "SELECT id FROM channel_profiles WHERE tenant_id = $1", tenant_id
    )
    if existing:
        await execute(
            """UPDATE channel_profiles
               SET youtube_refresh_token = $1, youtube_channel_id = $2,
                   youtube_channel_name = $3, updated_at = now()
               WHERE tenant_id = $4""",
            refresh_token, channel_id or "", channel_name or "", tenant_id,
        )
    else:
        await execute(
            """INSERT INTO channel_profiles (tenant_id, youtube_refresh_token, youtube_channel_id, youtube_channel_name)
               VALUES ($1, $2, $3, $4)""",
            tenant_id, refresh_token, channel_id or "", channel_name or "",
        )

    return {
        "status": "connected",
        "channel_id": channel_id,
        "channel_name": channel_name,
        "channel_description": channel_description,
    }


@router.get("/youtube/status")
async def youtube_status(tenant: uuid.UUID = Depends(get_tenant_id)):
    """Check if YouTube is connected for this tenant."""
    tenant_id = str(tenant)
    row = await fetch_one(
        "SELECT youtube_refresh_token, youtube_channel_id, youtube_channel_name "
        "FROM channel_profiles WHERE tenant_id = $1",
        tenant_id,
    )
    if not row or not row.get("youtube_refresh_token"):
        return {"connected": False, "channel_id": None, "channel_name": None}

    return {
        "connected": True,
        "channel_id": row.get("youtube_channel_id") or None,
        "channel_name": row.get("youtube_channel_name") or None,
    }


@router.post("/youtube/disconnect")
async def youtube_disconnect(tenant: uuid.UUID = Depends(get_tenant_id)):
    """Disconnect YouTube — removes stored refresh token and channel info."""
    tenant_id = str(tenant)
    await execute(
        "UPDATE channel_profiles SET youtube_refresh_token = NULL, "
        "youtube_channel_id = NULL, youtube_channel_name = NULL, "
        "updated_at = now() WHERE tenant_id = $1",
        tenant_id,
    )
    return {"status": "disconnected"}
