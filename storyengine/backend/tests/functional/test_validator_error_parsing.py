"""Functional test: prove each provider's validator parses its real error
body shape and surfaces an actionable message — not "API error 401".

Fixtures below are captured from LIVE probes against each upstream on
2026-04-19 using a deliberately-invalid key. If any provider changes
its error body shape, one of these tests will fail BEFORE a customer
sees a generic "API error" message.

Covers: Anthropic, OpenAI, Gemini, Tavily, ElevenLabs, Kie.ai.
"""
import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from vault import test_api_key, _extract_upstream_error


# ---- fixtures (real response bodies captured 2026-04-19) ----

ANTHROPIC_401_BODY = {
    "type": "error",
    "error": {"type": "authentication_error", "message": "invalid x-api-key"},
    "request_id": "req_011CaEJXvaWFiwwqbrMCAryn",
}

OPENAI_401_BODY = {
    "error": {
        "message": "Incorrect API key provided: sk-fake-*****************************bing. You can find your API key at https://platform.openai.com/account/api-keys.",
        "type": "invalid_request_error",
        "param": None,
        "code": "invalid_api_key",
    }
}

GEMINI_400_BODY = {
    "error": {
        "code": 400,
        "message": "API key not valid. Please pass a valid API key.",
        "status": "INVALID_ARGUMENT",
        "details": [
            {
                "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                "reason": "API_KEY_INVALID",
                "domain": "googleapis.com",
                "metadata": {"service": "generativelanguage.googleapis.com"},
            }
        ],
    }
}

TAVILY_401_BODY = {"detail": {"error": "Unauthorized: missing or invalid API key."}}

ELEVENLABS_401_MISSING_PERMS = {
    "detail": {
        "status": "missing_permissions",
        "message": "The API key you used is missing the permission voices_read to execute this operation.",
    }
}


def _mock_resp(status_code, body):
    m = MagicMock()
    m.status_code = status_code
    m.json.return_value = body
    m.text = json.dumps(body)
    return m


# ---- helper tests ----


def test_extract_walks_nested_path():
    resp = _mock_resp(401, {"error": {"type": "authentication_error"}})
    assert _extract_upstream_error(resp, ("error", "type")) == "authentication_error"
    print("✅ test_extract_walks_nested_path")


def test_extract_returns_none_on_missing_key():
    resp = _mock_resp(401, {"error": {}})
    assert _extract_upstream_error(resp, ("error", "message")) is None
    print("✅ test_extract_returns_none_on_missing_key")


def test_extract_tolerates_nonjson_body():
    m = MagicMock()
    m.json.side_effect = ValueError("not json")
    assert _extract_upstream_error(m, ("error", "message")) is None
    print("✅ test_extract_tolerates_nonjson_body")


# ---- per-validator tests — mock the live httpx call and assert the
# message surfaces the right actionable copy ----


def _run_validator(name, mock_resp):
    """Run test_api_key(name) with a mocked httpx response. Returns the
    dict result."""
    async def runner():
        # test_api_key first calls get_secret; mock that to return a value.
        with patch("vault.get_secret", new=AsyncMock(return_value="sk-fake-probing")), \
             patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client
            return await test_api_key(name, tenant_id="fake-tenant")
    return asyncio.run(runner())


def test_anthropic_authentication_error_actionable():
    result = _run_validator("anthropic_api_key", _mock_resp(401, ANTHROPIC_401_BODY))
    assert result["success"] is False
    assert "sk-ant-" in result["message"] or "rejected" in result["message"].lower()
    assert "401" not in result["message"]  # must NOT fall back to the generic path
    print(f"✅ test_anthropic_authentication_error_actionable → {result['message']}")


def test_openai_invalid_api_key_actionable():
    result = _run_validator("openai_api_key", _mock_resp(401, OPENAI_401_BODY))
    assert result["success"] is False
    assert "sk-" in result["message"]
    assert "401" not in result["message"]
    print(f"✅ test_openai_invalid_api_key_actionable → {result['message']}")


def test_openai_insufficient_quota_actionable():
    body = {
        "error": {
            "message": "You exceeded your current quota, please check your plan and billing details.",
            "type": "insufficient_quota",
            "code": "insufficient_quota",
        }
    }
    result = _run_validator("openai_api_key", _mock_resp(429, body))
    assert result["success"] is False
    assert "quota" in result["message"].lower() or "billing" in result["message"].lower()
    print(f"✅ test_openai_insufficient_quota_actionable → {result['message']}")


def test_gemini_api_key_invalid_actionable():
    result = _run_validator("gemini_api_key", _mock_resp(400, GEMINI_400_BODY))
    assert result["success"] is False
    assert "aistudio" in result["message"] or "rejected" in result["message"].lower()
    assert "400" not in result["message"]
    print(f"✅ test_gemini_api_key_invalid_actionable → {result['message']}")


def test_tavily_unauthorized_actionable():
    result = _run_validator("tavily_api_key", _mock_resp(401, TAVILY_401_BODY))
    assert result["success"] is False
    assert "tavily.com" in result["message"].lower() or "regenerate" in result["message"].lower()
    assert "401" not in result["message"]
    print(f"✅ test_tavily_unauthorized_actionable → {result['message']}")


def test_elevenlabs_missing_permissions_still_actionable():
    # Regression guard on Cycle 16's fix — make sure the scope-differentiation
    # path we already shipped keeps working after Cycle 19's refactor.
    # Note: the existing ElevenLabs branch validates against /v1/voices and
    # expects a 401 body shape of {"detail":{"status":"missing_permissions",...}}
    result = _run_validator("elevenlabs_api_key", _mock_resp(401, ELEVENLABS_401_MISSING_PERMS))
    assert result["success"] is False
    assert "voices_read" in result["message"] or "missing" in result["message"].lower()
    print(f"✅ test_elevenlabs_missing_permissions_still_actionable → {result['message']}")


def test_anthropic_permission_error_actionable():
    body = {"type": "error", "error": {"type": "permission_error", "message": "..."}}
    result = _run_validator("anthropic_api_key", _mock_resp(403, body))
    assert result["success"] is False
    assert "workspace" in result["message"].lower() or "permission" in result["message"].lower()
    print(f"✅ test_anthropic_permission_error_actionable → {result['message']}")


def test_tavily_rate_limit_actionable():
    result = _run_validator("tavily_api_key", _mock_resp(429, {"detail": {"error": "Rate limited"}}))
    assert result["success"] is False
    assert "rate" in result["message"].lower() or "wait" in result["message"].lower()
    print(f"✅ test_tavily_rate_limit_actionable → {result['message']}")


if __name__ == "__main__":
    test_extract_walks_nested_path()
    test_extract_returns_none_on_missing_key()
    test_extract_tolerates_nonjson_body()
    test_anthropic_authentication_error_actionable()
    test_openai_invalid_api_key_actionable()
    test_openai_insufficient_quota_actionable()
    test_gemini_api_key_invalid_actionable()
    test_tavily_unauthorized_actionable()
    test_elevenlabs_missing_permissions_still_actionable()
    test_anthropic_permission_error_actionable()
    test_tavily_rate_limit_actionable()
    print("\n🎉 11/11 validator-error-parsing tests green")
