"""Tests for C25a (checklist §S5-1 BLOCKER — tasks/storyengine-wiring-fix-
checklist.md, audit tasks/docs/reports/2026-07-17-storyengine-agent-audit-
findings.md §S5-1): the Drive media proxy (`routes/media.py::serve_drive_file`)
had NO auth dependency, and its file-id allowlist (`_is_allowed`) checked
`assets`/`scripts`/`videos`/`video_characters`/`chat_assets`/`projects` ACROSS
THE WHOLE DATABASE with no tenant clause. A leaked/guessed 33-44 char Drive id
served ANY tenant's file to ANYONE, and `/api/media/` is rate-limit-exempt.

Two things must now both be true:
1. `_ALLOWLIST_SQL` scopes every EXISTS subquery to `tenant_id = ANY($2::uuid[])`
   — a file id that exists under tenant A is NOT allowed under tenant B's token.
2. `serve_drive_file` requires a valid token (?token=, since <img>/<video>
   can't send Authorization headers) — missing/invalid/expired -> 401, and
   the resolved tenant set from that token is what scopes the allowlist check.

C25a-fix12 (2026-07-20, prod evidence: video cd5d2883 / tenant 44ecc95a
"PocoAPoco"): a browser session JWT's `tenant_id` claim is fixed at login to
the account's HOME tenant. `<img>`/`<video>` tags can't send the
`X-Active-Tenant` header normal API calls use to switch client workspaces, so
every asset in a CLIENT channel 404'd — the allowlist ran against the wrong
tenant. Fix: `_authorized_tenant_ids` expands a session JWT to every tenant
the account has a `memberships` row for; a backend-minted `purpose: media`
token (Kie/internal fetch paths) stays scoped to exactly its one tenant,
unchanged, with no membership query at all.

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
    """Every EXISTS(...) subquery must carry `tenant_id = ANY($2::uuid[])` —
    one per table. This is the literal fix for the BLOCKER: before C25a, none
    of them did, and the allowlist matched a file id belonging to ANY tenant.
    C25a-fix12 widened $2 from a single tenant_id to a uuid[] (the account's
    full authorized-workspace set) — the ANY(...) form is the same
    tenant-scoping guarantee, just over a set instead of one id."""
    exists_count = len(re.findall(r"EXISTS\s*\(", media._ALLOWLIST_SQL))
    tenant_scoped_count = len(re.findall(r"tenant_id\s*=\s*ANY\(\$2::uuid\[\]\)", media._ALLOWLIST_SQL))
    assert exists_count == 8, f"expected 8 EXISTS subqueries (one per table), found {exists_count}"
    assert tenant_scoped_count == 8, (
        f"expected every one of the {exists_count} EXISTS subqueries to carry "
        f"tenant_id = ANY($2::uuid[]), only found {tenant_scoped_count}"
    )


@pytest.mark.parametrize("table", [
    "assets", "video_characters", "scripts", "videos",
    "video_environments", "chat_assets", "projects", "static_reference_cache",
])
def test_allowlist_sql_names_every_table_once(table):
    assert media._ALLOWLIST_SQL.count(f"FROM {table}") == 1


def test_is_allowed_denies_cross_tenant_and_allows_same_tenant(monkeypatch):
    """The heart of the fix: the SAME file id is allowed under the tenant
    that owns it and denied under a different tenant's request. `_is_allowed`
    now takes an iterable of authorized tenant ids (C25a-fix12), so each call
    below passes a one-tenant list — the single-tenant case must behave
    exactly as before."""
    calls = []

    async def fake_fetch_one(sql, like_pattern, tenant_ids):
        calls.append((like_pattern, tuple(str(t) for t in tenant_ids)))
        # Simulate: this file id exists in `assets` ONLY for TENANT_A.
        return {"?column?": 1} if TENANT_A in [str(t) for t in tenant_ids] else None

    monkeypatch.setattr(media, "fetch_one", fake_fetch_one)
    media._allow_cache.clear()

    allowed_a = asyncio.run(media._is_allowed(FILE_ID, [uuid.UUID(TENANT_A)]))
    allowed_b = asyncio.run(media._is_allowed(FILE_ID, [uuid.UUID(TENANT_B)]))

    assert allowed_a is True
    assert allowed_b is False
    # Both tenant sets actually hit the DB (not served from a shared,
    # un-scoped cache entry) — the cache key includes the full tenant set.
    assert len(calls) == 2


def test_is_allowed_allows_static_reference_cache_file_for_owning_tenant_only(monkeypatch):
    """The roster-thumbnail fix: a Drive file id that exists ONLY in
    `static_reference_cache` (the machine-consistency reference photos
    pipeline_executor.py::roster_repair_dashboard hands to the browser as
    `reference.hosted_url`) must pass the allowlist for the tenant that owns
    the cache row and be refused for any other tenant — same tenant-scoping
    guarantee as every other table, now extended to this one."""
    async def fake_fetch_one(sql, like_pattern, tenant_ids):
        assert "static_reference_cache" in sql, "must query the new table, not some other path"
        # Simulate: this file id exists in static_reference_cache ONLY for TENANT_A.
        return {"?column?": 1} if TENANT_A in [str(t) for t in tenant_ids] else None

    monkeypatch.setattr(media, "fetch_one", fake_fetch_one)
    media._allow_cache.clear()

    allowed_a = asyncio.run(media._is_allowed(FILE_ID, [uuid.UUID(TENANT_A)]))
    allowed_b = asyncio.run(media._is_allowed(FILE_ID, [uuid.UUID(TENANT_B)]))

    assert allowed_a is True
    assert allowed_b is False


def test_is_allowed_allows_file_owned_by_any_tenant_in_a_multi_tenant_set(monkeypatch):
    """C25a-fix12's actual new behavior: a request authorized for MULTIPLE
    tenants (a two-workspace account's session JWT) is allowed if the file
    belongs to ANY one of them — not just the first/claimed one."""
    async def fake_fetch_one(sql, like_pattern, tenant_ids):
        # File belongs only to TENANT_B, which is the SECOND id in the set.
        return {"?column?": 1} if TENANT_B in [str(t) for t in tenant_ids] else None

    monkeypatch.setattr(media, "fetch_one", fake_fetch_one)
    media._allow_cache.clear()

    allowed = asyncio.run(
        media._is_allowed(FILE_ID, [uuid.UUID(TENANT_A), uuid.UUID(TENANT_B)])
    )
    assert allowed is True


def test_is_allowed_cache_is_keyed_per_tenant(monkeypatch):
    hits = {"n": 0}

    async def fake_fetch_one(sql, like_pattern, tenant_ids):
        hits["n"] += 1
        return {"?column?": 1}

    monkeypatch.setattr(media, "fetch_one", fake_fetch_one)
    media._allow_cache.clear()

    asyncio.run(media._is_allowed(FILE_ID, [uuid.UUID(TENANT_A)]))
    asyncio.run(media._is_allowed(FILE_ID, [uuid.UUID(TENANT_A)]))  # cached, no new hit
    asyncio.run(media._is_allowed(FILE_ID, [uuid.UUID(TENANT_B)]))  # different set, real hit

    assert hits["n"] == 2


# ---------------------------------------------------------------------------
# 1b. C25a-fix10 (2026-07-20 MCP go-live incident): a NEGATIVE verdict must
#     expire fast and re-query, not ride the full 3600s TTL — a browser
#     asked for a freshly-drawn storyboard file milliseconds before its DB
#     row landed, the "not allowed" verdict got cached, and every retry
#     404'd from memory for what would have been an hour while the DB
#     plainly allowed the file moments later.
# ---------------------------------------------------------------------------

def test_is_allowed_negative_verdict_expires_after_short_ttl_and_requeries(monkeypatch):
    hits = {"n": 0}
    clock = {"t": 1_000_000.0}

    async def fake_fetch_one(sql, like_pattern, tenant_ids):
        hits["n"] += 1
        # Always "not found" — models the race: the DB write hasn't landed
        # yet, or the file genuinely doesn't belong to this tenant.
        return None

    monkeypatch.setattr(media, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(media.time, "time", lambda: clock["t"])
    media._allow_cache.clear()

    allowed_1 = asyncio.run(media._is_allowed(FILE_ID, [uuid.UUID(TENANT_A)]))
    assert allowed_1 is False
    assert hits["n"] == 1

    # Still well inside the short negative TTL — served from cache, no re-hit.
    clock["t"] += media._NEGATIVE_ALLOW_TTL - 1
    allowed_2 = asyncio.run(media._is_allowed(FILE_ID, [uuid.UUID(TENANT_A)]))
    assert allowed_2 is False
    assert hits["n"] == 1, "still inside the negative TTL — must not re-query yet"

    # Past the short negative TTL (but nowhere near the old 3600s positive
    # TTL) — must re-query, proving the negative verdict doesn't ride the
    # long TTL the old code gave it.
    clock["t"] += 2
    allowed_3 = asyncio.run(media._is_allowed(FILE_ID, [uuid.UUID(TENANT_A)]))
    assert allowed_3 is False
    assert hits["n"] == 2, "negative verdict must expire and re-query well before 3600s"
    assert media._NEGATIVE_ALLOW_TTL <= 10.0, (
        "negative TTL crept back up — the incident was a full-hour outage "
        "from exactly this"
    )


def test_is_allowed_positive_verdict_still_honors_long_ttl(monkeypatch):
    """The fix must not weaken the POSITIVE cache — that's what protects
    the DB from 404-hammering on legitimately-denied ids, and there's no
    reason a real, already-confirmed file needs to be re-checked every 10s."""
    hits = {"n": 0}
    clock = {"t": 2_000_000.0}

    async def fake_fetch_one(sql, like_pattern, tenant_ids):
        hits["n"] += 1
        return {"?column?": 1}

    monkeypatch.setattr(media, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(media.time, "time", lambda: clock["t"])
    media._allow_cache.clear()

    allowed_1 = asyncio.run(media._is_allowed(FILE_ID, [uuid.UUID(TENANT_A)]))
    assert allowed_1 is True
    assert hits["n"] == 1

    # Well past the (short) negative TTL but still inside the long positive
    # TTL — a positive verdict must still be served from cache here.
    clock["t"] += media._NEGATIVE_ALLOW_TTL + 30
    allowed_2 = asyncio.run(media._is_allowed(FILE_ID, [uuid.UUID(TENANT_A)]))
    assert allowed_2 is True
    assert hits["n"] == 1, "positive verdicts must keep the full long TTL, unaffected by this fix"

    # Past the long TTL too — now it re-queries.
    clock["t"] += media._ALLOW_TTL
    allowed_3 = asyncio.run(media._is_allowed(FILE_ID, [uuid.UUID(TENANT_A)]))
    assert allowed_3 is True
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


async def _fake_fetch_all_no_extra_memberships(sql, user_id):
    """Models an account with no OTHER memberships beyond its JWT's claimed
    tenant — `_authorized_tenant_ids` then falls back to exactly that one
    tenant, so these tests keep asserting the original single-tenant
    semantics unchanged by the C25a-fix12 expansion."""
    return []


def test_serve_drive_file_404_for_another_tenants_token(monkeypatch):
    """The actual cross-tenant leak scenario: tenant B holds a VALID token
    (their own real session), but requests a file id that only exists under
    tenant A. Must be denied, not served — even after C25a-fix12's
    membership expansion (this account has no membership in tenant A)."""
    async def fake_is_allowed(file_id, tenant_ids):
        return TENANT_A in [str(t) for t in tenant_ids]

    monkeypatch.setattr(media, "_is_allowed", fake_is_allowed)
    monkeypatch.setattr(media, "fetch_all", _fake_fetch_all_no_extra_memberships)
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
    async def fake_is_allowed(file_id, tenant_ids):
        return TENANT_A in [str(t) for t in tenant_ids]

    monkeypatch.setattr(media, "_is_allowed", fake_is_allowed)
    monkeypatch.setattr(media, "fetch_all", _fake_fetch_all_no_extra_memberships)

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


# ---------------------------------------------------------------------------
# 3. C25a-fix12: `_authorized_tenant_ids` — the membership expansion itself.
# ---------------------------------------------------------------------------

def test_authorized_tenant_ids_expands_session_jwt_via_memberships(monkeypatch):
    """THE literal fix, isolated: an account whose session JWT carries its
    HOME tenant (TENANT_A) but ALSO has a `memberships` row for a CLIENT
    workspace (TENANT_B) must be authorized for BOTH. This is exactly the
    prod scenario (video cd5d2883, tenant 44ecc95a "PocoAPoco" operated by an
    account whose JWT tenant_id was ee93e6d1 "Slow English") that 404'd
    before this fix."""
    calls = []

    async def fake_fetch_all(sql, user_id):
        calls.append(user_id)
        return [{"tenant_id": TENANT_A}, {"tenant_id": TENANT_B}]

    monkeypatch.setattr(media, "fetch_all", fake_fetch_all)

    token = _session_jwt(TENANT_A)  # JWT's own claim = home tenant A
    ids = asyncio.run(media._authorized_tenant_ids(token))

    assert {str(t) for t in ids} == {TENANT_A, TENANT_B}
    assert calls == ["user-1"], "must query memberships by the JWT's `sub` (account id)"


def test_authorized_tenant_ids_home_tenant_only_when_single_membership(monkeypatch):
    """Home-tenant fetch, UNCHANGED: a single-workspace account (one
    membership row, matching its JWT's own claim) resolves to exactly that
    one tenant — same behavior as before C25a-fix12."""
    async def fake_fetch_all(sql, user_id):
        return [{"tenant_id": TENANT_A}]

    monkeypatch.setattr(media, "fetch_all", fake_fetch_all)

    token = _session_jwt(TENANT_A)
    ids = asyncio.run(media._authorized_tenant_ids(token))
    assert {str(t) for t in ids} == {TENANT_A}


def test_authorized_tenant_ids_non_member_workspace_not_included(monkeypatch):
    """Cross-account isolation must survive the expansion: a tenant the
    account has NO membership row for is never added to the authorized set,
    even though the expansion is now broader than a single claimed tenant."""
    tenant_c = str(uuid.uuid4())

    async def fake_fetch_all(sql, user_id):
        return [{"tenant_id": TENANT_A}]  # member of A only, never C

    monkeypatch.setattr(media, "fetch_all", fake_fetch_all)

    token = _session_jwt(TENANT_A)
    ids = asyncio.run(media._authorized_tenant_ids(token))
    assert tenant_c not in {str(t) for t in ids}


def test_authorized_tenant_ids_kie_shaped_token_stays_single_tenant_unchanged():
    """Kie-shape tenant-scoped token, UNCHANGED: a backend-minted
    `mint_media_token()` (purpose=media — pipeline_executor.py, characters.py,
    environments.py, the Kie fetch path) resolves to EXACTLY its own tenant
    and never queries `memberships` at all — `media.fetch_all` is left as the
    module's raw database stub here, so any membership query would blow up
    with the stub's AssertionError and fail this test, proving the branch
    never touches the DB."""
    token = media.mint_media_token(TENANT_A)
    ids = asyncio.run(media._authorized_tenant_ids(token))
    assert [str(t) for t in ids] == [TENANT_A]


def test_serve_drive_file_two_workspace_account_reaches_client_tenant_file(monkeypatch):
    """End-to-end reproduction of the prod bug (fails pre-C25a-fix12): an
    account's session JWT carries its HOME tenant, but the requested file
    belongs only to a CLIENT workspace the account also has a membership in.
    Must get PAST the auth/allowlist gate (502 = reached the Drive-meta
    fetch, same proof-of-passage pattern as the tests above) — pre-fix this
    404'd because the allowlist only ever ran against the JWT's home tenant."""
    home_tenant = TENANT_A
    client_tenant = TENANT_B

    async def fake_fetch_all(sql, user_id):
        return [{"tenant_id": home_tenant}, {"tenant_id": client_tenant}]

    async def fake_fetch_one(sql, like_pattern, tenant_ids):
        ids = tenant_ids if isinstance(tenant_ids, (list, tuple, set)) else [tenant_ids]
        # File belongs ONLY to the client workspace, not the home tenant.
        return {"?column?": 1} if client_tenant in [str(t) for t in ids] else None

    monkeypatch.setattr(media, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(media, "fetch_one", fake_fetch_one)
    media._allow_cache.clear()

    def boom_meta(*a, **k):
        raise RuntimeError("reached Drive meta fetch — auth + allowlist passed")
    monkeypatch.setattr(media, "_fetch_drive_meta", boom_meta)

    fake_request = types.SimpleNamespace(headers={})
    token = _session_jwt(home_tenant)
    with pytest.raises(Exception) as exc_info:
        asyncio.run(media.serve_drive_file(FILE_ID, fake_request, token=token))
    assert getattr(exc_info.value, "status_code", None) == 502


def test_serve_drive_file_non_member_still_404s(monkeypatch):
    """Preserved invariant: an account with NO membership in the owning
    tenant is still denied after the expansion — the fix widens the
    authorized set to real memberships, it does not remove the tenant
    boundary."""
    async def fake_fetch_all(sql, user_id):
        return [{"tenant_id": TENANT_A}]  # only a member of A

    async def fake_fetch_one(sql, like_pattern, tenant_ids):
        other_tenant = str(uuid.uuid4())  # file belongs to some OTHER tenant
        return {"?column?": 1} if other_tenant in [str(t) for t in tenant_ids] else None

    monkeypatch.setattr(media, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(media, "fetch_one", fake_fetch_one)
    media._allow_cache.clear()

    fake_request = types.SimpleNamespace(headers={})
    token = _session_jwt(TENANT_A)
    with pytest.raises(Exception) as exc_info:
        asyncio.run(media.serve_drive_file(FILE_ID, fake_request, token=token))
    assert getattr(exc_info.value, "status_code", None) == 404
