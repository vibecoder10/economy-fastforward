"""Settings routes - API key management and configuration.

Handles secure storage and retrieval of API keys via Supabase Vault.
"""

import asyncio
import time
from collections import defaultdict
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import get_tenant_id
from database import execute

# Rate limiting: max N requests per minute per tenant
_reveal_timestamps: dict[str, list[float]] = defaultdict(list)
_list_timestamps: dict[str, list[float]] = defaultdict(list)
REVEAL_RATE_LIMIT = 5
LIST_RATE_LIMIT = 10
REVEAL_WINDOW_SECONDS = 60
from vault import (
    get_secret,
    set_secret,
    delete_secret,
    list_secrets,
    get_secret_status,
    test_api_key,
    SECRET_ENV_MAP,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])


# --- Models ---

class ApiKeyStatus(BaseModel):
    """Status of a single API key."""
    name: str
    configured: bool
    source: Optional[str] = None  # "vault" or "env"
    masked_value: Optional[str] = None


class ApiKeyList(BaseModel):
    """List of all API key statuses."""
    keys: list[ApiKeyStatus]


class SetKeyRequest(BaseModel):
    """Request to set an API key."""
    value: str


class TestKeyResponse(BaseModel):
    """Response from testing an API key."""
    success: Optional[bool] = None
    message: str


# --- Endpoints ---

@router.get("/keys", response_model=ApiKeyList)
async def list_api_keys(tenant_id: str = Depends(get_tenant_id)):
    """List all API keys and their configuration status.

    Returns masked values for configured keys.
    """
    now = time.time()
    ts = _list_timestamps[str(tenant_id)]
    _list_timestamps[str(tenant_id)] = [t for t in ts if now - t < REVEAL_WINDOW_SECONDS]
    if len(_list_timestamps[str(tenant_id)]) >= LIST_RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again later.")
    _list_timestamps[str(tenant_id)].append(now)

    # Get status for all known keys
    keys = []
    for key_name in SECRET_ENV_MAP.keys():
        status = await get_secret_status(key_name, tenant_id)
        keys.append(ApiKeyStatus(
            name=status["name"],
            configured=status["configured"],
            source=status.get("source"),
            masked_value=status.get("masked_value"),
        ))

    return ApiKeyList(keys=keys)


@router.get("/keys/{key_name}", response_model=ApiKeyStatus)
async def get_api_key_status(
    key_name: str,
    tenant_id: str = Depends(get_tenant_id),
):
    """Get status of a specific API key."""
    now = time.time()
    ts = _list_timestamps[str(tenant_id)]
    _list_timestamps[str(tenant_id)] = [t for t in ts if now - t < REVEAL_WINDOW_SECONDS]
    if len(_list_timestamps[str(tenant_id)]) >= LIST_RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again later.")
    _list_timestamps[str(tenant_id)].append(now)

    if key_name not in SECRET_ENV_MAP:
        raise HTTPException(status_code=404, detail=f"Unknown key: {key_name}")

    status = await get_secret_status(key_name, tenant_id)
    return ApiKeyStatus(
        name=status["name"],
        configured=status["configured"],
        source=status.get("source"),
        masked_value=status.get("masked_value"),
    )


@router.post("/keys/{key_name}")
async def set_api_key(
    key_name: str,
    request: SetKeyRequest,
    tenant_id: str = Depends(get_tenant_id),
):
    """Set or update an API key.

    Stores the key in Supabase Vault with encryption.
    """
    if key_name not in SECRET_ENV_MAP:
        raise HTTPException(status_code=404, detail=f"Unknown key: {key_name}")

    if not request.value or not request.value.strip():
        raise HTTPException(status_code=400, detail="Value cannot be empty")

    success = await set_secret(
        name=key_name,
        value=request.value.strip(),
        tenant_id=tenant_id,
        description=f"API key for {key_name}",
    )

    if not success:
        raise HTTPException(status_code=500, detail="Failed to save key")

    await execute(
        """INSERT INTO bot_activity (tenant_id, bot_name, status, message)
           VALUES ($1, $2, $3, $4)""",
        tenant_id, "api_key_audit", "completed", f"Key set: {key_name}",
    )

    return {"status": "ok", "message": f"Key {key_name} saved"}


@router.delete("/keys/{key_name}")
async def delete_api_key(
    key_name: str,
    tenant_id: str = Depends(get_tenant_id),
):
    """Delete an API key from Vault.

    Note: This only removes from Vault. If the key is also set in environment
    variables, those will still be used.
    """
    if key_name not in SECRET_ENV_MAP:
        raise HTTPException(status_code=404, detail=f"Unknown key: {key_name}")

    success = await delete_secret(key_name, tenant_id)

    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete key")

    await execute(
        """INSERT INTO bot_activity (tenant_id, bot_name, status, message)
           VALUES ($1, $2, $3, $4)""",
        tenant_id, "api_key_audit", "completed", f"Key deleted: {key_name}",
    )

    return {"status": "ok", "message": f"Key {key_name} deleted from Vault"}


@router.post("/keys/{key_name}/test", response_model=TestKeyResponse)
async def test_api_key_endpoint(
    key_name: str,
    tenant_id: str = Depends(get_tenant_id),
):
    """Test if an API key is valid by making a test API call.

    Supported keys:
    - anthropic_api_key: Tests by listing models
    - openai_api_key: Tests by listing models
    - kie_ai_api_key: Tests by checking balance
    - gemini_api_key: Tests by listing models
    """
    if key_name not in SECRET_ENV_MAP:
        raise HTTPException(status_code=404, detail=f"Unknown key: {key_name}")

    result = await test_api_key(key_name, tenant_id)

    test_status = "completed" if result.get("success") else "failed"
    await execute(
        """INSERT INTO bot_activity (tenant_id, bot_name, status, message)
           VALUES ($1, $2, $3, $4)""",
        tenant_id, "api_key_audit", test_status,
        f"Key tested: {key_name} — {result.get('message', 'Unknown')}",
    )

    return TestKeyResponse(
        success=result.get("success"),
        message=result.get("message", "Unknown result"),
    )


@router.post("/keys/validate")
async def validate_api_keys(tenant_id: str = Depends(get_tenant_id)):
    """Validate all configured API keys in parallel with timeout.

    Tests anthropic, elevenlabs, openai, kie_ai, gemini, and tavily keys.
    Returns per-key results with success/fail status.
    """
    testable_keys = [
        "anthropic_api_key", "elevenlabs_api_key", "openai_api_key",
        "kie_ai_api_key", "gemini_api_key", "tavily_api_key",
    ]

    async def _test_with_timeout(key_name: str) -> dict:
        try:
            result = await asyncio.wait_for(
                test_api_key(key_name, tenant_id),
                timeout=15.0,
            )
            return {"key": key_name, **result}
        except asyncio.TimeoutError:
            return {"key": key_name, "success": False, "message": "Validation timed out"}
        except Exception as e:
            return {"key": key_name, "success": False, "message": str(e)}

    results = await asyncio.gather(*[_test_with_timeout(k) for k in testable_keys])
    return {"results": list(results)}


@router.post("/keys/{key_name}/reveal")
async def reveal_api_key(
    key_name: str,
    tenant_id: str = Depends(get_tenant_id),
):
    """Reveal the full API key value.

    Uses POST to prevent URL logging. Rate limited to 5 reveals per minute.
    All reveals are audit-logged.
    """
    if key_name not in SECRET_ENV_MAP:
        raise HTTPException(status_code=404, detail=f"Unknown key: {key_name}")

    # Rate limiting
    now = time.time()
    timestamps = _reveal_timestamps[tenant_id]
    _reveal_timestamps[tenant_id] = [t for t in timestamps if now - t < REVEAL_WINDOW_SECONDS]
    if len(_reveal_timestamps[tenant_id]) >= REVEAL_RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Max 5 reveals per minute.")
    _reveal_timestamps[tenant_id].append(now)

    value = await get_secret(key_name, tenant_id)

    if not value:
        raise HTTPException(status_code=404, detail="Key not configured")

    # Audit log
    await execute(
        """INSERT INTO bot_activity (tenant_id, bot_name, status, message)
           VALUES ($1, $2, $3, $4)""",
        tenant_id, "api_key_audit", "completed", f"Key revealed: {key_name}",
    )

    return {"value": value}
