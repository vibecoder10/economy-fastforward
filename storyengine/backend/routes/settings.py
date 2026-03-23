"""Settings routes - API key management and configuration.

Handles secure storage and retrieval of API keys via Supabase Vault.
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import get_tenant_id
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

    return TestKeyResponse(
        success=result.get("success"),
        message=result.get("message", "Unknown result"),
    )


@router.get("/keys/{key_name}/reveal")
async def reveal_api_key(
    key_name: str,
    tenant_id: str = Depends(get_tenant_id),
):
    """Reveal the full API key value.

    WARNING: This returns the unmasked key. Use with caution.
    Consider implementing additional security (e.g., require re-authentication).
    """
    if key_name not in SECRET_ENV_MAP:
        raise HTTPException(status_code=404, detail=f"Unknown key: {key_name}")

    value = await get_secret(key_name, tenant_id)

    if not value:
        raise HTTPException(status_code=404, detail="Key not configured")

    return {"value": value}
