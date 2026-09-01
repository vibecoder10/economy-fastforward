"""Voice provider keys are validated before replacing the working vault value."""

import os
import sys
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from routes import settings  # noqa: E402


@pytest.mark.asyncio
@pytest.mark.parametrize("key_name", ["elevenlabs_api_key", "kie_ai_api_key"])
async def test_invalid_voice_provider_key_is_not_saved(monkeypatch, key_name):
    validate = AsyncMock(return_value={"success": False, "message": "Provider rejected the key"})
    save = AsyncMock(return_value=True)
    monkeypatch.setattr(settings, "test_api_key", validate)
    monkeypatch.setattr(settings, "set_secret", save)

    with pytest.raises(HTTPException) as exc:
        await settings.set_api_key(
            key_name,
            settings.SetKeyRequest(value="bad-key"),
            tenant_id="tenant-1",
        )

    assert exc.value.status_code == 400
    assert "Provider rejected" in exc.value.detail
    validate.assert_awaited_once_with(key_name, "tenant-1", value_override="bad-key")
    save.assert_not_awaited()


@pytest.mark.asyncio
async def test_valid_voice_provider_key_is_saved(monkeypatch):
    validate = AsyncMock(return_value={"success": True, "message": "valid"})
    save = AsyncMock(return_value=True)
    audit = AsyncMock(return_value=None)
    monkeypatch.setattr(settings, "test_api_key", validate)
    monkeypatch.setattr(settings, "set_secret", save)
    monkeypatch.setattr(settings, "execute", audit)

    result = await settings.set_api_key(
        "elevenlabs_api_key",
        settings.SetKeyRequest(value="good-key"),
        tenant_id="tenant-1",
    )

    assert result["status"] == "ok"
    validate.assert_awaited_once_with(
        "elevenlabs_api_key", "tenant-1", value_override="good-key"
    )
    save.assert_awaited_once()


@pytest.mark.asyncio
async def test_non_provider_configuration_is_not_network_validated(monkeypatch):
    validate = AsyncMock()
    save = AsyncMock(return_value=True)
    audit = AsyncMock(return_value=None)
    monkeypatch.setattr(settings, "test_api_key", validate)
    monkeypatch.setattr(settings, "set_secret", save)
    monkeypatch.setattr(settings, "execute", audit)

    await settings.set_api_key(
        "elevenlabs_voice_id",
        settings.SetKeyRequest(value="voice-id"),
        tenant_id="tenant-1",
    )

    validate.assert_not_awaited()
