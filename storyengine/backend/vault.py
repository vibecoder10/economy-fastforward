"""API key storage using a simple secrets table.

Uses a regular PostgreSQL table for secret storage.
Falls back to environment variables if database secrets don't exist.

Usage:
    from vault import get_secret, set_secret, list_secrets

    # Get a secret (falls back to env var)
    api_key = await get_secret("anthropic_api_key")

    # Set a secret
    await set_secret("anthropic_api_key", "sk-ant-...")

    # List all secrets (names only)
    secrets = await list_secrets()
"""

import os
from typing import Optional
from database import fetch_all, fetch_one, execute


# Known API key names and their environment variable equivalents
SECRET_ENV_MAP: dict[str, str] = {
    "anthropic_api_key": "ANTHROPIC_API_KEY",
    "elevenlabs_api_key": "ELEVENLABS_API_KEY",
    "elevenlabs_voice_id": "ELEVENLABS_VOICE_ID",
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


async def get_secret(name: str, tenant_id: Optional[str] = None) -> Optional[str]:
    """Get a secret from database, with env var fallback ONLY for non-tenant contexts.

    SECURITY: When tenant_id is provided, only returns tenant-scoped secrets
    from the database. Environment variables are NEVER exposed to tenant users.
    Env var fallback only applies to pipeline bot calls (no tenant context).

    Args:
        name: Secret name (e.g., "anthropic_api_key")
        tenant_id: Optional tenant ID for multi-tenant isolation

    Returns:
        Secret value or None if not found
    """
    # Try database first
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
            return row["value"]
    except Exception:
        # Table might not exist - fall back to env vars only if no tenant
        pass

    # SECURITY: Only fall back to env vars when NO tenant_id is provided.
    # This prevents env var API keys from leaking to other tenants.
    if not tenant_id:
        env_key = SECRET_ENV_MAP.get(name, name.upper())
        return os.getenv(env_key)

    return None


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

        # Upsert the secret
        await execute(
            """INSERT INTO secrets (name, value, description, updated_at)
               VALUES ($1, $2, $3, now())
               ON CONFLICT (name) DO UPDATE SET
                   value = EXCLUDED.value,
                   description = EXCLUDED.description,
                   updated_at = now()""",
            full_name, value, desc,
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

    # Also show which env vars are configured (even if not in database)
    for secret_name, env_key in SECRET_ENV_MAP.items():
        if os.getenv(env_key):
            # Check if already in list
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
            db_value = row["value"]
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
                # Test Anthropic by listing models
                resp = await client.get(
                    "https://api.anthropic.com/v1/models",
                    headers={
                        "x-api-key": value,
                        "anthropic-version": "2023-06-01",
                    },
                )
                if resp.status_code == 200:
                    return {"success": True, "message": "Anthropic API key valid"}
                return {"success": False, "message": f"Anthropic API error: {resp.status_code}"}

            elif name == "openai_api_key":
                # Test OpenAI by listing models
                resp = await client.get(
                    "https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {value}"},
                )
                if resp.status_code == 200:
                    return {"success": True, "message": "OpenAI API key valid"}
                return {"success": False, "message": f"OpenAI API error: {resp.status_code}"}

            elif name == "kie_ai_api_key":
                # Test Kie.ai by checking balance/status
                resp = await client.get(
                    "https://api.kie.ai/api/v1/user/balance",
                    headers={"Authorization": f"Bearer {value}"},
                )
                if resp.status_code == 200:
                    return {"success": True, "message": "Kie.ai API key valid"}
                return {"success": False, "message": f"Kie.ai API error: {resp.status_code}"}

            elif name == "gemini_api_key":
                # Test Gemini by listing models
                resp = await client.get(
                    f"https://generativelanguage.googleapis.com/v1beta/models?key={value}"
                )
                if resp.status_code == 200:
                    return {"success": True, "message": "Gemini API key valid"}
                return {"success": False, "message": f"Gemini API error: {resp.status_code}"}

            elif name == "elevenlabs_api_key":
                # Test ElevenLabs by getting user info
                resp = await client.get(
                    "https://api.elevenlabs.io/v1/user",
                    headers={"xi-api-key": value},
                )
                if resp.status_code == 200:
                    return {"success": True, "message": "ElevenLabs API key valid"}
                return {"success": False, "message": f"ElevenLabs API error: {resp.status_code}"}

            elif name == "tavily_api_key":
                # Test Tavily by making a simple search
                resp = await client.post(
                    "https://api.tavily.com/search",
                    json={"api_key": value, "query": "test", "max_results": 1},
                )
                if resp.status_code == 200:
                    return {"success": True, "message": "Tavily API key valid"}
                return {"success": False, "message": f"Tavily API error: {resp.status_code}"}

            else:
                return {"success": None, "message": f"No test implemented for {name}"}

    except Exception as e:
        return {"success": False, "message": f"Connection error: {str(e)}"}
