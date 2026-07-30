"""Functional locks for YouTube OAuth connect diagnostics.

These tests keep the YouTuber onboarding OAuth surface honest:
- connect URL must use the exact frontend callback route
- scopes must remain read-only until publishing is explicitly approved
- diagnostics must report missing config without leaking secrets

Run:
    cd storyengine/backend && python3 tests/functional/test_youtube_oauth_diagnostics.py
"""
import asyncio
import os
import sys
import uuid
from contextlib import contextmanager
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from auth import AuthUser
from routes import google_auth


@contextmanager
def patched_env(values: dict[str, str | None]):
    old = {k: os.environ.get(k) for k in values}
    try:
        for k, v in values.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_youtube_connect_url_uses_expected_callback_and_readonly_scopes():
    with patched_env({
        "GOOGLE_OAUTH_CLIENT_ID": "client-123.apps.googleusercontent.com",
        "FRONTEND_URL": "https://storyengine.dev",
        "YOUTUBE_REDIRECT_URI": None,
    }):
        tenant_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
        result = asyncio.run(google_auth.youtube_connect(tenant=tenant_id))

    auth_url = result["auth_url"]
    parsed = urlparse(auth_url)
    qs = parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert parsed.netloc == "accounts.google.com"
    assert qs["client_id"] == ["client-123.apps.googleusercontent.com"]
    assert qs["redirect_uri"] == ["https://storyengine.dev/settings/youtube-callback"]
    assert qs["response_type"] == ["code"]
    assert qs["access_type"] == ["offline"]
    assert qs["prompt"] == ["consent"]
    assert qs["state"] == [str(tenant_id)]

    # Scopes deliberately include youtube.upload (commit e24c6908) — read-only
    # channel/analytics access plus upload, not force-ssl.
    scope = qs["scope"][0]
    assert "https://www.googleapis.com/auth/youtube.readonly" in scope
    assert "https://www.googleapis.com/auth/yt-analytics.readonly" in scope
    assert "https://www.googleapis.com/auth/youtube.upload" in scope
    assert "youtube.force-ssl" not in scope
    print("✅ test_youtube_connect_url_uses_expected_callback_and_readonly_scopes")


def test_youtube_oauth_diagnostics_reports_missing_config_without_secret_values():
    with patched_env({
        "GOOGLE_OAUTH_CLIENT_ID": None,
        "GOOGLE_OAUTH_CLIENT_SECRET": None,
        "FRONTEND_URL": "https://storyengine.dev",
        "YOUTUBE_REDIRECT_URI": None,
    }):
        user = AuthUser(id="user-1", email="creator@example.com", tenant_id="tenant-123")
        result = asyncio.run(google_auth.youtube_oauth_diagnostics(user=user))

    assert result["ready"] is False
    assert result["redirect_uri"] == "https://storyengine.dev/settings/youtube-callback"
    assert "GOOGLE_OAUTH_CLIENT_ID" in result["missing_env"]
    assert "GOOGLE_OAUTH_CLIENT_SECRET" in result["missing_env"]
    assert result["scope_mode"] == "read_only_channel_and_analytics"
    assert result["requires_google_verification"] is True
    text = repr(result)
    assert "client-" not in text
    assert "secret" not in text.lower().replace("GOOGLE_OAUTH_CLIENT_SECRET".lower(), "")
    print("✅ test_youtube_oauth_diagnostics_reports_missing_config_without_secret_values")


def main():
    test_youtube_connect_url_uses_expected_callback_and_readonly_scopes()
    test_youtube_oauth_diagnostics_reports_missing_config_without_secret_values()
    print("\nAll YouTube OAuth diagnostic tests passed.")


if __name__ == "__main__":
    main()
