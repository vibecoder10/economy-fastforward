"""API key storage using a simple secrets table.

Uses a regular PostgreSQL table for secret storage. Values are encrypted at rest
with Fernet when SECRETS_MASTER_KEY is configured (see the encryption section
below); without it, values are stored plaintext for a safe gradual rollout.
Falls back to environment variables if database secrets don't exist.

Usage:
    from vault import get_secret, set_secret, list_secrets

    # Get a secret (falls back to env var)
    api_key = await get_secret("anthropic_api_key")

    # Per-user key resolution (requires PER_USER_KEYS_ENABLED=true)
    api_key = await get_secret("anthropic_api_key", tenant_id="t1", user_id="u1")

    # Set a secret
    await set_secret("anthropic_api_key", "sk-ant-...")

    # List all secrets (names only)
    secrets = await list_secrets()
"""

import os
from typing import Optional
from database import fetch_all, fetch_one, execute
from error_utils import humanize_error


# Known API key names and their environment variable equivalents
SECRET_ENV_MAP: dict[str, str] = {
    "anthropic_api_key": "ANTHROPIC_API_KEY",
    "elevenlabs_api_key": "ELEVENLABS_API_KEY",
    "elevenlabs_voice_id": "ELEVENLABS_VOICE_ID",
    "elevenlabs_model_id": "ELEVENLABS_MODEL_ID",
    "elevenlabs_voice_style": "ELEVENLABS_VOICE_STYLE",
    "kie_ai_api_key": "KIE_AI_API_KEY",
    "openai_api_key": "OPENAI_API_KEY",
    "gemini_api_key": "GEMINI_API_KEY",
    "airtable_api_key": "AIRTABLE_API_KEY",
    "airtable_base_id": "AIRTABLE_BASE_ID",
    "google_client_id": "GOOGLE_CLIENT_ID",
    "google_client_secret": "GOOGLE_CLIENT_SECRET",
    "google_refresh_token": "GOOGLE_REFRESH_TOKEN",
    "slack_bot_token": "SLACK_BOT_TOKEN",
    "slack_app_token": "SLACK_APP_TOKEN",
    "tavily_api_key": "TAVILY_API_KEY",
}

# Feature flag: when True, get_secret resolves user-key first, then tenant-fallback.
PER_USER_KEYS_ENABLED: bool = os.getenv("PER_USER_KEYS_ENABLED", "false").lower() == "true"


# --- encryption at rest ------------------------------------------------------
# Secrets are stored encrypted with a master key (SECRETS_MASTER_KEY) using
# Fernet (AES-128-CBC + HMAC). MultiFernet lets us rotate: the env var may hold
# several comma-separated keys — the FIRST encrypts, ALL can decrypt.
#
# Two design choices keep the rollout safe (the vault is the single point of
# failure for text + images + video):
#   1. Stored ciphertext carries an `enc::` marker. On read, a value WITHOUT the
#      marker is treated as legacy plaintext and passed through unchanged — so
#      existing keys keep working the instant this ships, before any backfill.
#   2. If SECRETS_MASTER_KEY is unset, _encrypt stores plaintext (the pre-
#      encryption behavior). A deploy that forgets the env var therefore can't
#      brick key intake; encryption simply switches on once the key is present.
_ENC_PREFIX = "enc::"
_fernet_cache: dict[str, object] = {}


def _fernet():
    """Build a MultiFernet from SECRETS_MASTER_KEY, or None if it's unset/invalid.
    Cached per distinct env value so tests and key rotation pick up changes."""
    raw = os.getenv("SECRETS_MASTER_KEY", "").strip()
    if not raw:
        return None
    if raw not in _fernet_cache:
        try:
            from cryptography.fernet import Fernet, MultiFernet
            keys = [Fernet(k.strip().encode()) for k in raw.split(",") if k.strip()]
            _fernet_cache[raw] = MultiFernet(keys) if keys else None
        except Exception as e:  # noqa: BLE001 — bad key must not crash the process
            print(f"SECURITY WARNING: SECRETS_MASTER_KEY is set but invalid ({e}); "
                  "secrets will be stored/read as PLAINTEXT until it's fixed.")
            _fernet_cache[raw] = None
    return _fernet_cache[raw]


def _encrypt(value: Optional[str]) -> Optional[str]:
    """Encrypt a secret for storage. Returns plaintext unchanged when no master
    key is configured (safe rollout). Marker prefix tags real ciphertext."""
    if not value:
        return value
    f = _fernet()
    if f is None:
        return value
    return _ENC_PREFIX + f.encrypt(value.encode()).decode()


def _decrypt(stored: Optional[str]) -> Optional[str]:
    """Reverse of _encrypt. Legacy plaintext (no marker) passes through unchanged.
    An encrypted value we can't read (missing/wrong key) returns None rather than
    crashing the caller — it's treated as 'not configured', and the user re-pastes."""
    if not stored or not stored.startswith(_ENC_PREFIX):
        return stored
    f = _fernet()
    if f is None:
        print("SECURITY WARNING: an encrypted secret was found but SECRETS_MASTER_KEY "
              "is unset/invalid — cannot decrypt it.")
        return None
    try:
        return f.decrypt(stored[len(_ENC_PREFIX):].encode()).decode()
    except Exception as e:  # noqa: BLE001 — a bad token must not 500 the pipeline
        print(f"Failed to decrypt secret: {e}")
        return None


async def _ensure_secrets_table() -> bool:
    """Ensure the secrets table exists."""
    try:
        await execute("""
            CREATE TABLE IF NOT EXISTS secrets (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                name TEXT UNIQUE NOT NULL,
                value TEXT NOT NULL,
                description TEXT,
                created_at TIMESTAMPTZ DEFAULT now(),
                updated_at TIMESTAMPTZ DEFAULT now()
            )
        """)
        return True
    except Exception as e:
        print(f"Warning: Could not create secrets table: {e}")
        return False


async def get_secret(name: str, tenant_id: Optional[str] = None, user_id: Optional[str] = None) -> Optional[str]:
    """Get a secret from database, with env var fallback ONLY for non-tenant contexts.

    SECURITY: When tenant_id is provided, only returns tenant-scoped secrets
    from the database. Environment variables are NEVER exposed to tenant users.
    Env var fallback only applies to pipeline bot calls (no tenant context).

    When PER_USER_KEYS_ENABLED is True and user_id is provided, resolves in
    two tiers: user-scoped key first (tenant:user:name), then tenant-shared
    fallback (tenant:name). Raises KeyError if neither exists.

    Args:
        name: Secret name (e.g., "anthropic_api_key")
        tenant_id: Optional tenant ID for multi-tenant isolation
        user_id: Optional user ID for per-user key resolution.
            Requires PER_USER_KEYS_ENABLED=True and tenant_id to be set;
            ignored otherwise (falls through to legacy path).
            Empty string is treated as None (falsy check).

    Returns:
        Secret value, or None if not found (legacy path only).
        When PER_USER_KEYS_ENABLED is on and user_id is provided,
        raises KeyError instead of returning None.

    Raises:
        KeyError: When PER_USER_KEYS_ENABLED is on and neither user nor tenant key exists.
        RuntimeError: When PER_USER_KEYS_ENABLED is on and the database is unreachable.
    """
    # PER_USER_KEYS_ENABLED path: two-tier resolution (user → tenant → raise)
    if PER_USER_KEYS_ENABLED and user_id and tenant_id:
        try:
            # Tier 1: user-scoped key
            user_row = await fetch_one(
                "SELECT value FROM secrets WHERE name = $1",
                f"{tenant_id}:{user_id}:{name}",
            )
            if user_row and user_row.get("value"):
                return _decrypt(user_row["value"])

            # Tier 2: tenant-shared fallback
            tenant_row = await fetch_one(
                "SELECT value FROM secrets WHERE name = $1",
                f"{tenant_id}:{name}",
            )
            if tenant_row and tenant_row.get("value"):
                return _decrypt(tenant_row["value"])
        except Exception as e:
            # Log so operators can diagnose DB outages vs genuinely missing keys
            print(f"Warning: DB error resolving per-user key '{name}' "
                  f"(tenant={tenant_id!r}, user={user_id!r}): {e}")
            raise RuntimeError(
                f"Could not retrieve '{name}' — database temporarily unavailable. "
                "Please try again in a moment."
            ) from e

        # Key genuinely absent in both tiers; callers must handle KeyError in this path.
        raise KeyError(
            f"No API key found for '{name}' (user {user_id!r} or tenant {tenant_id!r}). "
            "Set it in Settings \u2192 API Keys."
        )

    # Legacy path: existing tenant-only behavior (back-compat preserved)
    try:
        if tenant_id:
            full_name = f"{tenant_id}:{name}"
        else:
            full_name = name

        row = await fetch_one(
            "SELECT value FROM secrets WHERE name = $1",
            full_name,
        )
        if row and row.get("value"):
            return _decrypt(row["value"])
    except Exception:
        # Table might not exist - fall back to env vars only if no tenant
        pass

    # SECURITY: Only fall back to env vars when NO tenant_id is provided.
    # This prevents env var API keys from leaking to other tenants.
    if not tenant_id:
        env_key = SECRET_ENV_MAP.get(name, name.upper())
        return os.getenv(env_key)

    return None


async def get_required_tenant_secret(
    name: str,
    tenant_id: str,
    *,
    provider_label: Optional[str] = None,
) -> str:
    """Resolve a tenant-owned provider key and never use the process env.

    Paid generation routes use this helper before constructing clients whose
    own legacy constructors may fall back to environment variables. That
    keeps StoryEngine a BYOK software product even when an operator key is
    present in the service environment.
    """
    normalized_tenant = str(tenant_id or "").strip()
    if not normalized_tenant:
        raise ValueError("A tenant is required for BYOK generation.")
    try:
        value = await get_secret(name, normalized_tenant)
    except KeyError:
        value = None
    if value:
        return value
    label = provider_label or SECRET_ENV_MAP.get(name, name).replace("_", " ")
    raise RuntimeError(
        f"Add your {label} key in Settings → API Keys before generating. "
        "StoryEngine does not use a shared provider key."
    )


async def set_secret(
    name: str,
    value: str,
    tenant_id: Optional[str] = None,
    description: Optional[str] = None,
) -> bool:
    """Store a secret in database.

    Args:
        name: Secret name (e.g., "anthropic_api_key")
        value: Secret value
        tenant_id: Optional tenant ID for multi-tenant isolation
        description: Optional description

    Returns:
        True if successful, False otherwise
    """
    try:
        # Ensure table exists
        await _ensure_secrets_table()

        if tenant_id:
            full_name = f"{tenant_id}:{name}"
        else:
            full_name = name

        desc = description or f"API key: {name}"

        # Upsert the secret — encrypted at rest when SECRETS_MASTER_KEY is set.
        await execute(
            """INSERT INTO secrets (name, value, description, updated_at)
               VALUES ($1, $2, $3, now())
               ON CONFLICT (name) DO UPDATE SET
                   value = EXCLUDED.value,
                   description = EXCLUDED.description,
                   updated_at = now()""",
            full_name, _encrypt(value), desc,
        )

        return True
    except Exception as e:
        print(f"Failed to set secret {name}: {e}")
        return False


async def delete_secret(name: str, tenant_id: Optional[str] = None) -> bool:
    """Delete a secret from database.

    Args:
        name: Secret name
        tenant_id: Optional tenant ID

    Returns:
        True if deleted, False otherwise
    """
    try:
        if tenant_id:
            full_name = f"{tenant_id}:{name}"
        else:
            full_name = name

        await execute(
            "DELETE FROM secrets WHERE name = $1",
            full_name,
        )
        return True
    except Exception as e:
        print(f"Failed to delete secret {name}: {e}")
        return False


async def list_secrets(tenant_id: Optional[str] = None) -> list[dict]:
    """List all secrets (names only, not values).

    Args:
        tenant_id: Optional tenant ID to filter by

    Returns:
        List of dicts with name, description, created_at
    """
    secrets = []

    # Get from database
    try:
        if tenant_id:
            rows = await fetch_all(
                """SELECT name, description, created_at::text
                   FROM secrets
                   WHERE name LIKE $1 || ':%'""",
                tenant_id,
            )
            # Strip tenant prefix from names
            for row in rows:
                row["name"] = row["name"].split(":", 1)[1] if ":" in row["name"] else row["name"]
        else:
            rows = await fetch_all(
                "SELECT name, description, created_at::text FROM secrets"
            )

        secrets.extend([dict(r) for r in rows])
    except Exception:
        # Table might not exist
        pass

    # SECURITY: Only show env vars when NO tenant_id is provided (pipeline bot context).
    # Tenant-scoped callers must NEVER see server-side env var keys.
    if not tenant_id:
        for secret_name, env_key in SECRET_ENV_MAP.items():
            if os.getenv(env_key):
                if not any(s["name"] == secret_name for s in secrets):
                    secrets.append({
                        "name": secret_name,
                        "description": f"From environment: {env_key}",
                        "source": "env",
                    })

    return secrets


async def get_secret_status(name: str, tenant_id: Optional[str] = None) -> dict:
    """Get status of a secret (configured, source, masked value).

    Args:
        name: Secret name
        tenant_id: Optional tenant ID

    Returns:
        Dict with configured, source, masked_value
    """
    # Check database first
    db_value = None
    try:
        if tenant_id:
            full_name = f"{tenant_id}:{name}"
        else:
            full_name = name

        row = await fetch_one(
            "SELECT value FROM secrets WHERE name = $1",
            full_name,
        )
        if row and row.get("value"):
            db_value = _decrypt(row["value"])
    except Exception:
        pass

    # SECURITY: Only check env vars when NO tenant_id is provided.
    env_value = None
    if not tenant_id:
        env_key = SECRET_ENV_MAP.get(name, name.upper())
        env_value = os.getenv(env_key)

    # Determine source and value
    if db_value:
        value = db_value
        source = "database"
    elif env_value:
        value = env_value
        source = "env"
    else:
        return {
            "name": name,
            "configured": False,
            "source": None,
            "masked_value": None,
        }

    # Mask value (show last 4 chars)
    if len(value) > 8:
        masked = "•" * 8 + value[-4:]
    else:
        masked = "•" * len(value)

    return {
        "name": name,
        "configured": True,
        "source": source,
        "masked_value": masked,
    }


def _extract_upstream_error(resp, path):
    """Walk a JSON response body via a dotted tuple path, returning the leaf
    value as a string if present, else None. Tolerates non-JSON bodies and
    missing keys — used to surface actionable error detail from upstream
    validator 4xx responses without letting a malformed body 500 the caller.
    """
    try:
        body = resp.json()
    except Exception:
        return None
    node = body
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
        if node is None:
            return None
    return str(node) if node else None


async def test_api_key(name: str, tenant_id: Optional[str] = None) -> dict:
    """Test if an API key is valid by making a simple API call.

    Args:
        name: Secret name (e.g., "anthropic_api_key")
        tenant_id: Optional tenant ID

    Returns:
        Dict with success, message
    """
    import httpx

    value = await get_secret(name, tenant_id)
    if not value:
        return {"success": False, "message": "API key not configured"}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            if name == "anthropic_api_key":
                # `/v1/models` returns the same `error.type` structure as
                # `/v1/messages` for invalid keys (verified via live probe),
                # so the validate-where-you-use principle is already honored.
                # Error body shape: {"error":{"type":"authentication_error","message":"..."}}
                resp = await client.get(
                    "https://api.anthropic.com/v1/models",
                    headers={
                        "x-api-key": value,
                        "anthropic-version": "2023-06-01",
                    },
                )
                if resp.status_code == 200:
                    return {"success": True, "message": "Anthropic API key valid"}
                err_msg = _extract_upstream_error(resp, path=("error", "message"))
                err_type = _extract_upstream_error(resp, path=("error", "type"))
                if err_type == "authentication_error":
                    return {"success": False, "message": "Anthropic rejected the key — double-check it starts with `sk-ant-` and isn't missing characters"}
                if err_type == "permission_error":
                    return {"success": False, "message": "Anthropic key is valid but lacks permission for this workspace — check the key's workspace assignment in Anthropic Console"}
                if err_msg:
                    return {"success": False, "message": f"Anthropic rejected the key: {err_msg}"}
                return {"success": False, "message": f"Anthropic API error: {resp.status_code}"}

            elif name == "openai_api_key":
                # `/v1/models` returns 401 with a structured body for
                # invalid keys. Error body shape:
                # {"error":{"message":"...","code":"invalid_api_key","type":"invalid_request_error"}}
                resp = await client.get(
                    "https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {value}"},
                )
                if resp.status_code == 200:
                    return {"success": True, "message": "OpenAI API key valid"}
                err_code = _extract_upstream_error(resp, path=("error", "code"))
                err_msg = _extract_upstream_error(resp, path=("error", "message"))
                if err_code == "invalid_api_key":
                    return {"success": False, "message": "OpenAI rejected the key — double-check it starts with `sk-` and isn't missing characters"}
                if err_code == "insufficient_quota":
                    return {"success": False, "message": "OpenAI key is valid but the account has no remaining quota — add billing credits at platform.openai.com"}
                if err_msg:
                    # OpenAI embeds the (masked) offending key in `message` —
                    # safe to echo since it's already redacted upstream-side.
                    return {"success": False, "message": f"OpenAI rejected the key: {err_msg}"}
                return {"success": False, "message": f"OpenAI API error: {resp.status_code}"}

            elif name == "kie_ai_api_key":
                # Kie.ai uses 200-OK-with-error-body style: the HTTP status is
                # 200 even on auth failure; the real status lives in JSON `code`.
                # Endpoint `/api/v1/user/balance` was deprecated (404s) — current
                # balance endpoint is `/api/v1/chat/credit` which returns
                # {"code":200,"msg":"success","data":<credit_amount>}.
                resp = await client.get(
                    "https://api.kie.ai/api/v1/chat/credit",
                    headers={"Authorization": f"Bearer {value}"},
                )
                if resp.status_code == 200:
                    try:
                        body = resp.json()
                    except Exception:
                        return {"success": False, "message": "Kie.ai returned unparseable response"}
                    if body.get("code") == 200:
                        credit = body.get("data")
                        suffix = f" (credit: {credit})" if credit is not None else ""
                        return {"success": True, "message": f"Kie.ai API key valid{suffix}"}
                    return {"success": False, "message": f"Kie.ai rejected key: {body.get('msg') or 'unknown'}"}
                return {"success": False, "message": f"Kie.ai API error: {resp.status_code}"}

            elif name == "gemini_api_key":
                # Google uses key-as-query-param auth. Invalid keys return 400
                # (not 401) with a Google RPC-style error body:
                # {"error":{"code":400,"message":"...","status":"INVALID_ARGUMENT",
                #   "details":[{"reason":"API_KEY_INVALID"}]}}
                resp = await client.get(
                    f"https://generativelanguage.googleapis.com/v1beta/models?key={value}"
                )
                if resp.status_code == 200:
                    return {"success": True, "message": "Gemini API key valid"}
                err_msg = _extract_upstream_error(resp, path=("error", "message"))
                # Walk the details[] list for a specific `reason`.
                reason = None
                try:
                    details = resp.json().get("error", {}).get("details") or []
                    for d in details:
                        if isinstance(d, dict) and d.get("reason"):
                            reason = d["reason"]
                            break
                except Exception:
                    reason = None
                if reason == "API_KEY_INVALID":
                    return {"success": False, "message": "Gemini rejected the key — generate a new one at aistudio.google.com/apikey"}
                if reason == "API_KEY_SERVICE_BLOCKED":
                    return {"success": False, "message": "Gemini key is blocked from Generative Language API — check API restrictions in Google Cloud Console"}
                if err_msg:
                    return {"success": False, "message": f"Gemini rejected the key: {err_msg}"}
                return {"success": False, "message": f"Gemini API error: {resp.status_code}"}

            elif name == "elevenlabs_api_key":
                # Validate against `/v1/voices` (what StoryEngine actually uses
                # for TTS). `/v1/user` requires the `user_read` scope — keys
                # scoped only for TTS fail there with 401 even though they're
                # perfectly valid for our use case. 401 bodies differentiate
                # `invalid_api_key` from `missing_permissions` so we can give
                # users an actionable message.
                resp = await client.get(
                    "https://api.elevenlabs.io/v1/voices",
                    headers={"xi-api-key": value},
                )
                if resp.status_code == 200:
                    return {"success": True, "message": "ElevenLabs API key valid"}
                if resp.status_code == 401:
                    try:
                        detail = resp.json().get("detail", {})
                    except Exception:
                        detail = {}
                    status = detail.get("status") if isinstance(detail, dict) else None
                    if status == "missing_permissions":
                        return {
                            "success": False,
                            "message": "ElevenLabs key is valid but missing voices_read permission — regenerate the key with full TTS access",
                        }
                    return {"success": False, "message": "ElevenLabs rejected the key"}
                return {"success": False, "message": f"ElevenLabs API error: {resp.status_code}"}

            elif name == "tavily_api_key":
                # HONEST NOTE: Tavily has no free "validate key" endpoint —
                # every test burns one real search credit from the user's
                # account. We pick the minimal-cost query (max_results=1,
                # single-character q) to keep the burn small. Error body
                # shape on bad key: {"detail":{"error":"Unauthorized: ..."}}
                resp = await client.post(
                    "https://api.tavily.com/search",
                    json={"api_key": value, "query": "x", "max_results": 1},
                )
                if resp.status_code == 200:
                    return {"success": True, "message": "Tavily API key valid (used 1 search credit to verify)"}
                # Tavily nests error differently — walk both common shapes.
                err_msg = _extract_upstream_error(resp, path=("detail", "error"))
                if not err_msg:
                    err_msg = _extract_upstream_error(resp, path=("error",))
                if resp.status_code == 401:
                    return {"success": False, "message": "Tavily rejected the key — regenerate at tavily.com/account"}
                if resp.status_code == 429:
                    return {"success": False, "message": "Tavily key is valid but rate-limited — wait a minute and retry"}
                if err_msg:
                    return {"success": False, "message": f"Tavily rejected the key: {err_msg}"}
                return {"success": False, "message": f"Tavily API error: {resp.status_code}"}

            else:
                return {"success": None, "message": f"No test implemented for {name}"}

    except Exception as e:
        # Never echo raw str(e): leaks httpx internals, DNS hostnames, TLS paths
        # into the UI via test-key responses. humanize_error logs the raw error
        # for devs at WARNING level so diagnosis stays possible.
        return {"success": False, "message": humanize_error(e, context="Connection failed while testing key")}
