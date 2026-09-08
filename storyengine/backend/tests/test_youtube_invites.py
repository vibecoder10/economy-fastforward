from unittest.mock import AsyncMock
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from starlette.requests import Request
from routes import youtube_invites as mod


def request(cookie="browser"):
    return Request({"type": "http", "headers": [(b"cookie", f"{mod.COOKIE}={cookie}".encode())]})


@pytest.mark.asyncio
async def test_missing_browser_rejected_before_database(monkeypatch):
    fetch = AsyncMock()
    monkeypatch.setattr(mod, "fetch_one", fetch)
    with pytest.raises(HTTPException) as exc:
        await mod.invite_callback(mod.InviteCallback(state="ytinvite.test", code="code"), request(""))
    assert exc.value.status_code == 403
    fetch.assert_not_called()


@pytest.mark.asyncio
async def test_replayed_state_rejected(monkeypatch):
    fetch = AsyncMock(return_value=None)
    monkeypatch.setattr(mod, "fetch_one", fetch)
    with pytest.raises(HTTPException) as exc:
        await mod.invite_callback(mod.InviteCallback(state="ytinvite.test", code="code"), request())
    assert exc.value.status_code == 410
    assert fetch.call_args.args[1:] == (mod.digest("ytinvite.test"), mod.digest("browser"))
    assert "consumed_at IS NULL" in fetch.call_args.args[0]


@pytest.mark.asyncio
async def test_denial_consumes_state_without_provider_or_invite_save(monkeypatch):
    fetch = AsyncMock(return_value={"invite_id": "invite"})
    pool = AsyncMock()
    monkeypatch.setattr(mod, "fetch_one", fetch)
    monkeypatch.setattr(mod, "get_pool", pool)
    with pytest.raises(HTTPException) as exc:
        await mod.invite_callback(mod.InviteCallback(state="ytinvite.test", error="access_denied"), request())
    assert exc.value.status_code == 400
    assert fetch.call_count == 1
    pool.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("channel,scope", [("wrong-channel", mod.SCOPES), ("expected", "https://www.googleapis.com/auth/youtube.readonly")])
async def test_mismatch_or_missing_grants_never_save(monkeypatch, channel, scope):
    monkeypatch.setattr(mod, "fetch_one", AsyncMock(side_effect=[{"invite_id": "invite"}, {"tenant_id": "tenant", "expected_channel_id": "expected"}]))
    monkeypatch.setattr(mod, "get_youtube_oauth_credentials", lambda: SimpleNamespace(missing_env=[], client_id="client", client_secret="secret"))
    pool = AsyncMock()
    monkeypatch.setattr(mod, "get_pool", pool)
    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, *args, **kwargs):
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"access_token": "access", "refresh_token": "refresh", "scope": scope})
        async def get(self, *args, **kwargs):
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"items": [{"id": channel}]})
    monkeypatch.setattr(mod.httpx, "AsyncClient", Client)
    with pytest.raises(HTTPException) as exc:
        await mod.invite_callback(mod.InviteCallback(state="ytinvite.test", code="code"), request())
    assert exc.value.status_code == 400
    pool.assert_not_called()


@pytest.mark.asyncio
async def test_landing_does_not_consume_invite_and_sets_secure_cookie(monkeypatch):
    monkeypatch.setattr(mod, "fetch_one", AsyncMock(return_value={"id": "invite", "expected_channel_id": "UCchannel", "youtube_channel_name": "Designed & Used <DVSU>"}))
    save = AsyncMock()
    monkeypatch.setattr(mod, "execute", save)
    result = await mod.invite_landing("randomtoken")
    assert result.headers["cache-control"] == "no-store"
    assert result.headers["referrer-policy"] == "no-referrer"
    assert "HttpOnly" in result.headers["set-cookie"] and "Secure" in result.headers["set-cookie"]
    assert b"Connect with Google" in result.body
    assert b"Designed &amp; Used &lt;DVSU&gt;" in result.body
    assert b'href="/privacy"' in result.body and b'href="/terms"' in result.body
    save.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("claimed", [True, False])
async def test_verified_channel_commits_once_in_transaction(monkeypatch, claimed):
    monkeypatch.setattr(mod, "fetch_one", AsyncMock(side_effect=[{"invite_id": "invite"}, {"tenant_id": "tenant", "expected_channel_id": "expected"}]))
    monkeypatch.setattr(mod, "get_youtube_oauth_credentials", lambda: SimpleNamespace(missing_env=[], client_id="client", client_secret="secret"))
    class Context:
        def __init__(self, value): self.value = value
        async def __aenter__(self): return self.value
        async def __aexit__(self, *args): pass
    conn = SimpleNamespace(fetchrow=AsyncMock(return_value={"tenant_id": "bound-tenant"} if claimed else None), execute=AsyncMock())
    conn.transaction = lambda: Context(None)
    monkeypatch.setattr(mod, "get_pool", AsyncMock(return_value=SimpleNamespace(acquire=lambda: Context(conn))))
    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, *args, **kwargs):
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"access_token": "access", "refresh_token": "refresh", "scope": mod.SCOPES})
        async def get(self, *args, **kwargs):
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"items": [{"id": "expected", "snippet": {"title": "Channel"}}]})
    monkeypatch.setattr(mod.httpx, "AsyncClient", Client)
    if claimed:
        response = await mod.invite_callback(mod.InviteCallback(state="ytinvite.test", code="code"), request())
        assert response.status_code == 200
        assert conn.execute.call_args.args[1:] == ("bound-tenant", "refresh", "expected", "Channel")
    else:
        with pytest.raises(HTTPException) as exc:
            await mod.invite_callback(mod.InviteCallback(state="ytinvite.test", code="code"), request())
        assert exc.value.status_code == 410
        conn.execute.assert_not_called()
    assert "consumed_at IS NULL" in conn.fetchrow.call_args.args[0]
