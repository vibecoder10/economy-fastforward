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


def test_youtube_connect_prefers_dedicated_client_and_requests_only_read_and_upload():
    with patched_env({
        "YOUTUBE_OAUTH_CLIENT_ID": "youtube-client.apps.googleusercontent.com",
        "YOUTUBE_OAUTH_CLIENT_SECRET": "youtube-secret",
        "GOOGLE_OAUTH_CLIENT_ID": "google-client.apps.googleusercontent.com",
        "GOOGLE_OAUTH_CLIENT_SECRET": "google-secret",
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
    assert qs["client_id"] == ["youtube-client.apps.googleusercontent.com"]
    assert qs["redirect_uri"] == ["https://storyengine.dev/settings/youtube-callback"]
    assert qs["response_type"] == ["code"]
    assert qs["access_type"] == ["offline"]
    assert qs["prompt"] == ["consent"]
    assert qs["state"] == [str(tenant_id)]

    # StoryEngine reads channel/video data and uploads videos. It has no direct
    # YouTube Analytics API call, so that sensitive scope must stay absent.
    scope = qs["scope"][0]
    assert "https://www.googleapis.com/auth/youtube.readonly" in scope
    assert "https://www.googleapis.com/auth/youtube.upload" in scope
    assert "https://www.googleapis.com/auth/yt-analytics.readonly" not in scope
    assert "youtube.force-ssl" not in scope
    print("✅ test_youtube_connect_prefers_dedicated_client_and_requests_only_read_and_upload")


def test_youtube_connect_falls_back_to_legacy_google_oauth_pair():
    with patched_env({
        "YOUTUBE_OAUTH_CLIENT_ID": None,
        "YOUTUBE_OAUTH_CLIENT_SECRET": None,
        "GOOGLE_OAUTH_CLIENT_ID": "legacy-client.apps.googleusercontent.com",
        "GOOGLE_OAUTH_CLIENT_SECRET": "legacy-secret",
    }):
        result = asyncio.run(google_auth.youtube_connect(
            tenant=uuid.UUID("11111111-1111-1111-1111-111111111111")
        ))

    assert parse_qs(urlparse(result["auth_url"]).query)["client_id"] == [
        "legacy-client.apps.googleusercontent.com"
    ]


def test_drive_connect_stays_on_google_oauth_client():
    with patched_env({
        "YOUTUBE_OAUTH_CLIENT_ID": "youtube-client.apps.googleusercontent.com",
        "YOUTUBE_OAUTH_CLIENT_SECRET": "youtube-secret",
        "GOOGLE_OAUTH_CLIENT_ID": "drive-client.apps.googleusercontent.com",
        "GOOGLE_OAUTH_CLIENT_SECRET": "drive-secret",
    }):
        result = asyncio.run(google_auth.google_drive_connect(
            tenant=uuid.UUID("11111111-1111-1111-1111-111111111111")
        ))

    assert parse_qs(urlparse(result["auth_url"]).query)["client_id"] == [
        "drive-client.apps.googleusercontent.com"
    ]


def test_youtube_oauth_diagnostics_reports_missing_config_without_secret_values():
    with patched_env({
        "YOUTUBE_OAUTH_CLIENT_ID": None,
        "YOUTUBE_OAUTH_CLIENT_SECRET": None,
        "GOOGLE_OAUTH_CLIENT_ID": None,
        "GOOGLE_OAUTH_CLIENT_SECRET": None,
        "FRONTEND_URL": "https://storyengine.dev",
        "YOUTUBE_REDIRECT_URI": None,
    }):
        user = AuthUser(id="user-1", email="creator@example.com", tenant_id="tenant-123")
        result = asyncio.run(google_auth.youtube_oauth_diagnostics(user=user))

    assert result["ready"] is False
    assert result["redirect_uri"] == "https://storyengine.dev/settings/youtube-callback"
    assert "YOUTUBE_OAUTH_CLIENT_ID" in result["missing_env"]
    assert "YOUTUBE_OAUTH_CLIENT_SECRET" in result["missing_env"]
    assert result["credential_source"] == "missing"
    assert result["scope_mode"] == "youtube_read_and_upload"
    assert result["requires_google_verification"] is True
    text = repr(result)
    assert "client-" not in text
    assert "secret" not in text.lower().replace("YOUTUBE_OAUTH_CLIENT_SECRET".lower(), "")
    print("✅ test_youtube_oauth_diagnostics_reports_missing_config_without_secret_values")


def test_youtube_oauth_diagnostics_reports_dedicated_and_legacy_sources():
    user = AuthUser(id="user-1", email="creator@example.com", tenant_id="tenant-123")
    with patched_env({
        "YOUTUBE_OAUTH_CLIENT_ID": "youtube-client",
        "YOUTUBE_OAUTH_CLIENT_SECRET": "youtube-secret-value",
        "GOOGLE_OAUTH_CLIENT_ID": "google-client",
        "GOOGLE_OAUTH_CLIENT_SECRET": "google-secret-value",
    }):
        dedicated = asyncio.run(google_auth.youtube_oauth_diagnostics(user=user))
    assert dedicated["ready"] is True
    assert dedicated["credential_source"] == "youtube_specific"
    assert dedicated["missing_env"] == []
    assert "youtube-client" not in repr(dedicated)
    assert "youtube-secret-value" not in repr(dedicated)

    with patched_env({
        "YOUTUBE_OAUTH_CLIENT_ID": None,
        "YOUTUBE_OAUTH_CLIENT_SECRET": None,
        "GOOGLE_OAUTH_CLIENT_ID": "google-client",
        "GOOGLE_OAUTH_CLIENT_SECRET": "google-secret-value",
    }):
        legacy = asyncio.run(google_auth.youtube_oauth_diagnostics(user=user))
    assert legacy["ready"] is True
    assert legacy["credential_source"] == "legacy_google_oauth"
    assert legacy["missing_env"] == []


def test_partial_youtube_specific_pair_fails_closed_instead_of_mixing_clients():
    user = AuthUser(id="user-1", email="creator@example.com", tenant_id="tenant-123")
    with patched_env({
        "YOUTUBE_OAUTH_CLIENT_ID": "youtube-client",
        "YOUTUBE_OAUTH_CLIENT_SECRET": None,
        "GOOGLE_OAUTH_CLIENT_ID": "google-client",
        "GOOGLE_OAUTH_CLIENT_SECRET": "google-secret-value",
    }):
        result = asyncio.run(google_auth.youtube_oauth_diagnostics(user=user))

    assert result["ready"] is False
    assert result["credential_source"] == "youtube_specific"
    assert result["missing_env"] == ["YOUTUBE_OAUTH_CLIENT_SECRET"]


def main():
    test_youtube_connect_prefers_dedicated_client_and_requests_only_read_and_upload()
    test_youtube_connect_falls_back_to_legacy_google_oauth_pair()
    test_drive_connect_stays_on_google_oauth_client()
    test_youtube_oauth_diagnostics_reports_missing_config_without_secret_values()
    test_youtube_oauth_diagnostics_reports_dedicated_and_legacy_sources()
    test_partial_youtube_specific_pair_fails_closed_instead_of_mixing_clients()
    print("\nAll YouTube OAuth diagnostic tests passed.")


if __name__ == "__main__":
    main()
