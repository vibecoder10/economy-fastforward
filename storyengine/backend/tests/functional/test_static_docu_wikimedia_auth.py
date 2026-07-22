"""Tests for chunk C5 (2026-07-22): authenticated Wikimedia API access.

Problem being solved: anonymous datacenter-IP traffic to Wikimedia got the
VPS 429/403-jailed live. A classic MediaWiki bot password
(Special:BotPasswords, WIKIMEDIA_BOT_USER/WIKIMEDIA_BOT_PASSWORD env vars)
logged in once per process gets materially better rate treatment.

Verified live (scratchpad/wm_login_test.py, 2026-07-22) before writing this:
a bot-password login sets a WIKI-SCOPED session cookie (e.g.
`commonswikiSession` on commons.wikimedia.org), NOT a shared
`.wikimedia.org` CentralAuth cookie — logging in on commons.wikimedia.org
does not authenticate a subsequent en.wikipedia.org call. So static_docu
logs in separately to each host in _WM_LOGIN_HOSTS, on the SAME shared
httpx.AsyncClient (httpx's cookie jar is domain-scoped, so one client can
hold both hosts' session cookies at once).

These tests fake httpx entirely (no real network) and cover:
  1. login flow: token fetch -> action=login -> the shared client is used
     for subsequent _wm_get calls instead of the caller's own client.
  2. assertuserfailed on a call -> ONE re-login -> retry succeeds.
  3. creds absent -> _get_wm_auth_client returns None and _wm_get falls back
     to the caller's own (anonymous) client, unchanged from before C5.

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest \
        tests/functional/test_static_docu_wikimedia_auth.py -q
"""
import os
import sys
from pathlib import Path

import pytest

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

_REPO_ROOT = Path(__file__).resolve().parents[4]
_PIPELINE_ROOT = _REPO_ROOT / "skills" / "video-pipeline"
if str(_PIPELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(_PIPELINE_ROOT))

import static_docu  # noqa: E402


class _FakeResp:
    def __init__(self, body, status_code=200, headers=None):
        self._body = body
        self.status_code = status_code
        self.headers = headers or {"content-type": "application/json"}

    def json(self):
        return self._body

    def raise_for_status(self):
        pass


class _FakeAuthClient:
    """Stands in for the shared authenticated httpx.AsyncClient. Records
    every GET/POST it's asked to make and returns canned bodies keyed by
    (method, url)."""

    def __init__(self):
        self.calls = []
        self.get_queue = {}  # url -> list of responses, popped in order
        self.closed = False

    async def get(self, url, params=None, **kwargs):
        self.calls.append(("GET", url, params))
        q = self.get_queue.get(url, [])
        if q:
            return q.pop(0)
        return _FakeResp({})

    async def post(self, url, data=None, **kwargs):
        self.calls.append(("POST", url, data))
        return _FakeResp({"login": {"result": "Success"}})

    async def aclose(self):
        self.closed = True


@pytest.fixture(autouse=True)
def _reset_wm_auth_singleton(monkeypatch):
    """The auth client is a lazy process-wide singleton — reset all of its
    module-level state before every test so tests don't leak into each
    other."""
    monkeypatch.setattr(static_docu, "_wm_auth_client", None)
    monkeypatch.setattr(static_docu, "_wm_auth_init_lock", None)
    monkeypatch.setattr(static_docu, "_wm_auth_ready", False)
    monkeypatch.setattr(static_docu, "_wm_auth_init_done", False)
    monkeypatch.setattr(static_docu, "_wm_lock", None)
    monkeypatch.setattr(static_docu, "_wm_last", 0.0)
    yield


@pytest.mark.asyncio
async def test_login_flow_token_then_login_then_reused_for_subsequent_calls(monkeypatch):
    """Login: token fetch -> action=login succeeds on BOTH hosts -> the
    shared client (not the caller's own `c`) is used for a subsequent
    _wm_get call."""
    monkeypatch.setattr(static_docu, "WIKIMEDIA_BOT_USER", "Ayler92@storyengine")
    monkeypatch.setattr(static_docu, "WIKIMEDIA_BOT_PASSWORD", "secret-not-real")

    fake = _FakeAuthClient()
    # Every host's login token-fetch + POST /login gets a canned Success —
    # _FakeAuthClient.get() default-returns {} which has no "tokens" key, so
    # give the token fetch a real token to hand back.
    for host in static_docu._WM_LOGIN_HOSTS:
        fake.get_queue[host] = [
            _FakeResp({"query": {"tokens": {"logintoken": "TOKEN123"}}}),
        ]

    monkeypatch.setattr(static_docu.httpx, "AsyncClient", lambda **kw: fake)

    client = await static_docu._get_wm_auth_client()
    assert client is fake
    assert static_docu._wm_auth_ready is True

    # Both hosts got a token fetch (GET) and a login POST.
    get_urls = [c[1] for c in fake.calls if c[0] == "GET"]
    post_urls = [c[1] for c in fake.calls if c[0] == "POST"]
    assert set(get_urls) == set(static_docu._WM_LOGIN_HOSTS)
    assert set(post_urls) == set(static_docu._WM_LOGIN_HOSTS)

    # A never-used "caller's own client" must be ignored in favor of the
    # shared authenticated session on a subsequent _wm_get call.
    caller_client = object()  # deliberately not awaitable/usable as a client
    fake.get_queue[static_docu._WIKIPEDIA_API] = [_FakeResp({"ok": True})]
    resp = await static_docu._wm_get(caller_client, static_docu._WIKIPEDIA_API,
                                      params={"action": "query"})
    assert resp.json() == {"ok": True}
    # The params sent for the authenticated call carry assert=user.
    last_get = [c for c in fake.calls if c[0] == "GET" and c[1] == static_docu._WIKIPEDIA_API][-1]
    assert last_get[2]["assert"] == "user"


@pytest.mark.asyncio
async def test_assertuserfailed_triggers_one_relogin_then_retry_succeeds(monkeypatch):
    """A silently-expired session surfaces as assertuserfailed on a normal
    call — caught, triggers exactly one re-login, then a retried call that
    succeeds."""
    monkeypatch.setattr(static_docu, "WIKIMEDIA_BOT_USER", "Ayler92@storyengine")
    monkeypatch.setattr(static_docu, "WIKIMEDIA_BOT_PASSWORD", "secret-not-real")

    fake = _FakeAuthClient()
    for host in static_docu._WM_LOGIN_HOSTS:
        fake.get_queue[host] = [
            _FakeResp({"query": {"tokens": {"logintoken": "TOKEN123"}}}),
        ]
    monkeypatch.setattr(static_docu.httpx, "AsyncClient", lambda **kw: fake)

    client = await static_docu._get_wm_auth_client()
    assert client is fake

    # First call to the wikipedia API: assertuserfailed. Re-login re-queues a
    # fresh login token for both hosts. Second call after re-login: success.
    fake.get_queue[static_docu._WIKIPEDIA_API] = [
        _FakeResp({"error": {"code": "assertuserfailed"}}),
    ]
    for host in static_docu._WM_LOGIN_HOSTS:
        fake.get_queue.setdefault(host, [])
        fake.get_queue[host].append(_FakeResp({"query": {"tokens": {"logintoken": "TOKEN456"}}}))
    fake.get_queue[static_docu._WIKIPEDIA_API].append(_FakeResp({"ok": True}))

    calls_before = len(fake.calls)
    resp = await static_docu._wm_get(object(), static_docu._WIKIPEDIA_API,
                                      params={"action": "query"})
    assert resp.json() == {"ok": True}
    assert static_docu._wm_auth_ready is True
    # A re-login happened: more calls were made than just the one failed GET.
    assert len(fake.calls) > calls_before + 1


@pytest.mark.asyncio
async def test_creds_absent_anonymous_path_unchanged(monkeypatch):
    """No WIKIMEDIA_BOT_USER/PASSWORD configured -> _get_wm_auth_client
    returns None without ever touching httpx.AsyncClient, and _wm_get falls
    back to the caller's own (anonymous) client exactly like before C5."""
    monkeypatch.setattr(static_docu, "WIKIMEDIA_BOT_USER", None)
    monkeypatch.setattr(static_docu, "WIKIMEDIA_BOT_PASSWORD", None)

    def _boom(**kw):
        raise AssertionError("AsyncClient should not be constructed when creds are absent")
    monkeypatch.setattr(static_docu.httpx, "AsyncClient", _boom)

    client = await static_docu._get_wm_auth_client()
    assert client is None

    class _AnonClient:
        def __init__(self):
            self.calls = 0

        async def get(self, url, **kwargs):
            self.calls += 1
            return _FakeResp({"anon": True})

    anon = _AnonClient()
    resp = await static_docu._wm_get(anon, "https://en.wikipedia.org/w/api.php",
                                      params={"action": "query"})
    assert resp.json() == {"anon": True}
    assert anon.calls == 1
