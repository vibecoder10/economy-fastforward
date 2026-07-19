"""Tests for C25a (checklist §S5-1 BLOCKER — tasks/storyengine-wiring-fix-
checklist.md, audit tasks/docs/reports/2026-07-17-storyengine-agent-audit-
findings.md §S5-1): the Drive media proxy (`routes/media.py::serve_drive_file`)
had NO auth dependency, and its file-id allowlist (`_is_allowed`) checked
`assets`/`scripts`/`videos`/`video_characters`/`chat_assets`/`projects` ACROSS
THE WHOLE DATABASE with no tenant clause. A leaked/guessed 33-44 char Drive id
served ANY tenant's file to ANYONE, and `/api/media/` is rate-limit-exempt.

Two things must now both be true:
1. `_ALLOWLIST_SQL` scopes every EXISTS subquery to `tenant_id = $2` — a file
   id that exists under tenant A is NOT allowed under tenant B's token.
2. `serve_drive_file` requires a valid token (?token=, since <img>/<video>
   can't send Authorization headers) — missing/invalid/expired -> 401, and
   the resolved tenant_id from that token is what scopes the allowlist check.

Same stub pattern as test_c15b_show_and_approve_scene.py: stub `database`
before importing routes.media (module-level `from database import fetch_one`
binds a name on routes.media itself — tests monkeypatch that name directly,
no live DB, no network).

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c25a_media_tenant_auth.py -q
"""
import asyncio
import os
import re
import sys
import types
import uuid

import jwt as pyjwt
import pytest

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod


async def _boom(*a, **k):
    raise AssertionError("pure tests must not touch runtime services")


_stub("database", fetch_one=_boom, fetch_all=_boom, execute=_boom)

os.environ.setdefault("SESSION_SECRET", "test-secret-only-for-c25a")

import routes.media as media  # noqa: E402

SECRET = os.environ["SESSION_SECRET"]
TENANT_A = str(uuid.uuid4())
TENANT_B = str(uuid.uuid4())
FILE_ID = "a" * 33  # inside the 10-80 char id shape the route validates


def _session_jwt(tenant_id: str) -> str:
    return pyjwt.encode(
        {"sub": "user-1", "email": "u@example.com", "tenant_id": tenant_id, "iss": "storyengine"},
        SECRET, algorithm="HS256",
    )


# ---------------------------------------------------------------------------
# 1. The allowlist SQL is tenant-scoped — the actual BLOCKER.
# ---------------------------------------------------------------------------

def test_allowlist_sql_scopes_every_table_by_tenant():
    """Every EXISTS(...) subquery must carry `tenant_id = $2` — one per table.
    This is the literal fix for the BLOCKER: before C25a, none of them did,
    and the allowlist matched a file id belonging to ANY tenant."""
    exists_count = len(re.findall(r"EXISTS\s*\(", media._ALLOWLIST_SQL))
    tenant_scoped_count = len(re.findall(r"tenant_id\s*=\s*\$2", media._ALLOWLIST_SQL))
    assert exists_count == 7, f"expected 7 EXISTS subqueries (one per table), found {exists_count}"
    assert tenant_scoped_count == 7, (
        f"expected every one of the {exists_count} EXISTS subqueries to carry "
        f"tenant_id = $2, only found {tenant_scoped_count}"
    )


@pytest.mark.parametrize("table", [
    "assets", "video_characters", "scripts", "videos",
    "video_environments", "chat_assets", "projects",
])
def test_allowlist_sql_names_every_table_once(table):
    assert media._ALLOWLIST_SQL.count(f"FROM {table}") == 1


def test_is_allowed_denies_cross_tenant_and_allows_same_tenant(monkeypatch):
    """The heart of the fix: the SAME file id is allowed under the tenant
    that owns it and denied under a different tenant's request."""
    calls = []

    async def fake_fetch_one(sql, like_pattern, tenant_id):
        calls.append((like_pattern, tenant_id))
        # Simulate: this file id exists in `assets` ONLY for TENANT_A.
        return {"?column?": 1} if str(tenant_id) == TENANT_A else None

    monkeypatch.setattr(media, "fetch_one", fake_fetch_one)
    media._allow_cache.clear()

    allowed_a = asyncio.run(media._is_allowed(FILE_ID, uuid.UUID(TENANT_A)))
    allowed_b = asyncio.run(media._is_allowed(FILE_ID, uuid.UUID(TENANT_B)))

    assert allowed_a is True
    assert allowed_b is False
    # Both tenants actually hit the DB (not served from a shared, un-scoped
    # cache entry) — the cache key includes tenant_id.
    assert len(calls) == 2


def test_is_allowed_cache_is_keyed_per_tenant(monkeypatch):
    hits = {"n": 0}

    async def fake_fetch_one(sql, like_pattern, tenant_id):
        hits["n"] += 1
        return {"?column?": 1}

    monkeypatch.setattr(media, "fetch_one", fake_fetch_one)
    media._allow_cache.clear()

    asyncio.run(media._is_allowed(FILE_ID, uuid.UUID(TENANT_A)))
    asyncio.run(media._is_allowed(FILE_ID, uuid.UUID(TENANT_A)))  # cached, no new hit
    asyncio.run(media._is_allowed(FILE_ID, uuid.UUID(TENANT_B)))  # different tenant, real hit

    assert hits["n"] == 2


# ---------------------------------------------------------------------------
# 2. serve_drive_file requires a valid, tenant-resolving token.
# ---------------------------------------------------------------------------

def test_media_token_tenant_requires_a_token():
    with pytest.raises(Exception) as exc_info:
        media._media_token_tenant(None)
    assert getattr(exc_info.value, "status_code", None) == 401


def test_media_token_tenant_rejects_garbage_token():
    with pytest.raises(Exception) as exc_info:
        media._media_token_tenant("not-a-jwt")
    assert getattr(exc_info.value, "status_code", None) == 401


def test_media_token_tenant_rejects_expired_token():
    import datetime
    expired = pyjwt.encode(
        {"purpose": "media", "tenant_id": TENANT_A, "iss": "storyengine",
         "exp": datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=1)},
        SECRET, algorithm="HS256",
    )
    with pytest.raises(Exception) as exc_info:
        media._media_token_tenant(expired)
    assert getattr(exc_info.value, "status_code", None) == 401


def test_media_token_tenant_accepts_full_session_jwt():
    """The browser's own long-lived session JWT (same one every other
    fetchApi() call already sends as Authorization: Bearer) works as ?token=
    — same precedent as auth.verify_token's SSE query-param path."""
    tok = _session_jwt(TENANT_A)
    resolved = media._media_token_tenant(tok)
    assert str(resolved) == TENANT_A


def test_mint_media_token_roundtrips_to_the_same_tenant():
    """Backend-internal chokepoints (characters.py cast-sheet vision,
    environments.py vision rewrite, pipeline_executor.py talking-clip path)
    mint their own short-lived token for a KNOWN tenant_id — must resolve
    back to that same tenant."""
    tok = media.mint_media_token(TENANT_A)
    resolved = media._media_token_tenant(tok)
    assert str(resolved) == TENANT_A


def test_serve_drive_file_401_without_token(monkeypatch):
    async def fail_if_called(*a, **k):
        raise AssertionError("allowlist must not be queried before auth")
    monkeypatch.setattr(media, "_is_allowed", fail_if_called)

    fake_request = types.SimpleNamespace(headers={})
    with pytest.raises(Exception) as exc_info:
        asyncio.run(media.serve_drive_file(FILE_ID, fake_request, token=None))
    assert getattr(exc_info.value, "status_code", None) == 401


def test_serve_drive_file_404_for_another_tenants_token(monkeypatch):
    """The actual cross-tenant leak scenario: tenant B holds a VALID token
    (their own real session), but requests a file id that only exists under
    tenant A. Must be denied, not served."""
    async def fake_is_allowed(file_id, tenant_id):
        return str(tenant_id) == TENANT_A

    monkeypatch.setattr(media, "_is_allowed", fake_is_allowed)
    fake_request = types.SimpleNamespace(headers={})

    tenant_b_token = _session_jwt(TENANT_B)
    with pytest.raises(Exception) as exc_info:
        asyncio.run(media.serve_drive_file(FILE_ID, fake_request, token=tenant_b_token))
    assert getattr(exc_info.value, "status_code", None) == 404


def test_serve_drive_file_reaches_allowlist_for_the_owning_tenant(monkeypatch):
    """Positive path: tenant A's own token, file id genuinely allowed for
    tenant A -> auth + allowlist both pass, we get PAST the 401/404 gate (the
    next thing the route does is fetch Drive metadata, which we stub to
    fail — proving execution got that far, not asserting a 200)."""
    async def fake_is_allowed(file_id, tenant_id):
        return str(tenant_id) == TENANT_A

    monkeypatch.setattr(media, "_is_allowed", fake_is_allowed)

    def boom_meta(*a, **k):  # ran via asyncio.to_thread — must be a plain sync callable
        raise RuntimeError("reached Drive meta fetch — auth + allowlist passed")
    monkeypatch.setattr(media, "_fetch_drive_meta", boom_meta)

    fake_request = types.SimpleNamespace(headers={})
    tenant_a_token = _session_jwt(TENANT_A)
    with pytest.raises(Exception) as exc_info:
        asyncio.run(media.serve_drive_file(FILE_ID, fake_request, token=tenant_a_token))
    # 502 == "Couldn't fetch this file right now" (the route's own catch
    # around the Drive call) — NOT 401/404, proving auth+allowlist passed.
    assert getattr(exc_info.value, "status_code", None) == 502
