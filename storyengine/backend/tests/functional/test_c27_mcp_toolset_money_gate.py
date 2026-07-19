"""Tests for C27 (checklist P2.4b — StoryEngine MCP tool set + quote/
confirm_token money gate on every paid tool, tasks/storyengine-copilot-ux-
map.md §7, docs/reports/2026-07-17-storyengine-agent-audit-findings.md §S5-2
and the C26-flagged rate-limit gap — that gap has its own test file,
test_c27_rate_limit_agent_tokens.py).

C26 shipped exactly 2 read-only tools (list_videos/get_video). This chunk
expands the surface to every actions.ACTIONS verb (free AND paid) plus 5
more read tools plus create_video, dispatching every verb through the SAME
`routes.chat._run_pending_action` chat/buttons already use — no forked
dispatch, no parallel cost math. Covers:

  1. confirm_tokens.py: create()/redeem() round-trip, and every refusal path
     the money gate depends on — wrong token, wrong tenant/video/verb,
     mismatched params (bait-and-switch), already-used (single-use), and
     expired (10-minute TTL) — each is ONE atomic UPDATE, proven by
     asserting the SAME redeem() call returns False for every wrong case.
  2. Tool surface: every ACTIONS verb appears (free AND paid), S5-2's
     remember/forget exclusion still holds, paid verb schemas carry
     confirm_token, free verb schemas don't, create_video is present and
     free, media-URL-bearing fields (preview_url, thumbnail_url) are
     stripped from tool results (C25a hold).
  3. The money-gate matrix on `_call_verb` (routes/mcp.py): a paid verb
     with no confirm_token returns a quote and does NOT dispatch; wrong/
     expired/reused/params-mismatched confirm_token is refused and does NOT
     dispatch; a correctly confirmed call dispatches through the SAME
     `routes.chat._run_pending_action` chat's own confirm-card path calls
     (proven by patching THAT function and asserting it — not some MCP-local
     copy — was invoked with the right arguments); a free verb (paid=False)
     never touches confirm_tokens at all and dispatches immediately; a
     blocked verb (missing prerequisite) is refused before a quote is even
     minted.
  4. Attribution: `_run_pending_action`'s new `caller` parameter (default
     "chat", unchanged for every existing chat.py call site) reaches
     generation_claims.acquire's claimed_by for both the single-stage path
     and the "build" autobuild path; `actions._runner_draft_pass`/
     `_runner_finalize` read `pending["caller"]` the same way.
  5. Tenant scoping: `_call_verb` refuses when video_summary can't find the
     video for THIS tenant (mirrors C26's get_video tenant-scoping test).

No live DB, no network, no paid calls — every DB boundary and every
generation_claims/background_tasks call is patched directly (same
conventions as test_c16a_generation_claims.py / test_c17_draft_pass_and_
finalize.py / test_c26_mcp_agent_tokens.py).

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c27_mcp_toolset_money_gate.py -q
"""
from __future__ import annotations

import asyncio
import os
import sys
import types
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _BACKEND)

import actions  # noqa: E402
import confirm_tokens  # noqa: E402
import generation_claims  # noqa: E402
import generation_passes  # noqa: E402
import routes.chat as chat  # noqa: E402
import routes.mcp as mcp_mod  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


class _FakeBackgroundTasks:
    def __init__(self):
        self.calls = []

    def add_task(self, fn, *a, **k):
        self.calls.append((fn, a, k))


# =============================================================================
# 1. confirm_tokens.py — create/redeem, every refusal path
# =============================================================================

class _FakeConfirmStore:
    def __init__(self):
        self.rows: list[dict] = []


def _patch_confirm(store: _FakeConfirmStore):
    async def _execute(query, *args):
        if "INSERT INTO mcp_confirm_tokens" in query:
            tenant_id, video_id, verb, phash, token_hash, ttl_secs = args
            store.rows.append({
                "tenant_id": tenant_id, "video_id": video_id, "verb": verb,
                "params_hash": phash, "token_hash": token_hash,
                "expires_at": datetime.now(timezone.utc) + timedelta(seconds=ttl_secs),
                "used_at": None,
            })
            return "INSERT 0 1"
        if "UPDATE mcp_confirm_tokens SET used_at" in query:
            token_hash, tenant_id, video_id, verb, phash = args
            now = datetime.now(timezone.utc)
            for r in store.rows:
                if (r["token_hash"] == token_hash and r["tenant_id"] == tenant_id
                        and r["video_id"] == video_id and r["verb"] == verb
                        and r["params_hash"] == phash and r["used_at"] is None
                        and r["expires_at"] > now):
                    r["used_at"] = now
                    return "UPDATE 1"
            return "UPDATE 0"
        raise AssertionError(f"unexpected query: {query!r}")
    return patch.object(confirm_tokens, "execute", _execute)


async def test_confirm_token_roundtrip_succeeds():
    store = _FakeConfirmStore()
    phash = confirm_tokens.params_hash("animate", 3, None, None, None)
    with _patch_confirm(store):
        token = await confirm_tokens.create("t1", "v1", "animate", phash)
        ok = await confirm_tokens.redeem("t1", "v1", "animate", phash, token)
    assert token.startswith(confirm_tokens.TOKEN_PREFIX)
    assert ok is True
    print("✅ test_confirm_token_roundtrip_succeeds")


async def test_confirm_token_rejects_wrong_token_string():
    store = _FakeConfirmStore()
    phash = confirm_tokens.params_hash("animate", 3, None, None, None)
    with _patch_confirm(store):
        await confirm_tokens.create("t1", "v1", "animate", phash)
        ok = await confirm_tokens.redeem("t1", "v1", "animate", phash, "mcpc_totally-made-up")
    assert ok is False
    print("✅ test_confirm_token_rejects_wrong_token_string")


async def test_confirm_token_rejects_wrong_tenant():
    store = _FakeConfirmStore()
    phash = confirm_tokens.params_hash("animate", 3, None, None, None)
    with _patch_confirm(store):
        token = await confirm_tokens.create("tenant-a", "v1", "animate", phash)
        ok = await confirm_tokens.redeem("tenant-b", "v1", "animate", phash, token)
    assert ok is False, "a token minted for one tenant must not redeem for another"
    print("✅ test_confirm_token_rejects_wrong_tenant")


async def test_confirm_token_rejects_wrong_video():
    store = _FakeConfirmStore()
    phash = confirm_tokens.params_hash("animate", 3, None, None, None)
    with _patch_confirm(store):
        token = await confirm_tokens.create("t1", "video-a", "animate", phash)
        ok = await confirm_tokens.redeem("t1", "video-b", "animate", phash, token)
    assert ok is False
    print("✅ test_confirm_token_rejects_wrong_video")


async def test_confirm_token_rejects_wrong_verb():
    """A token minted for 'animate' must not spend 'render' — even same
    tenant/video/params_hash coincidence (params_hash alone is not the whole
    binding; verb is checked independently)."""
    store = _FakeConfirmStore()
    phash = confirm_tokens.params_hash("animate", 3, None, None, None)
    with _patch_confirm(store):
        token = await confirm_tokens.create("t1", "v1", "animate", phash)
        ok = await confirm_tokens.redeem("t1", "v1", "render", phash, token)
    assert ok is False
    print("✅ test_confirm_token_rejects_wrong_verb")


async def test_confirm_token_rejects_params_mismatch_bait_and_switch():
    """The checklist's explicit bait-and-switch case: quote for scene 3,
    try to confirm scene 12 with the same token — must fail closed."""
    store = _FakeConfirmStore()
    phash_quoted = confirm_tokens.params_hash("animate", 3, None, None, None)
    phash_actual = confirm_tokens.params_hash("animate", 12, None, None, None)
    assert phash_quoted != phash_actual
    with _patch_confirm(store):
        token = await confirm_tokens.create("t1", "v1", "animate", phash_quoted)
        ok = await confirm_tokens.redeem("t1", "v1", "animate", phash_actual, token)
    assert ok is False, "a token quoted for scene 3 must not spend on scene 12"
    print("✅ test_confirm_token_rejects_params_mismatch_bait_and_switch")


async def test_confirm_token_is_single_use():
    store = _FakeConfirmStore()
    phash = confirm_tokens.params_hash("images", None, None, None, None)
    with _patch_confirm(store):
        token = await confirm_tokens.create("t1", "v1", "images", phash)
        first = await confirm_tokens.redeem("t1", "v1", "images", phash, token)
        second = await confirm_tokens.redeem("t1", "v1", "images", phash, token)
    assert first is True
    assert second is False, "a confirm_token must not redeem twice (single-use, not a replay-able credential)"
    print("✅ test_confirm_token_is_single_use")


async def test_confirm_token_expires():
    store = _FakeConfirmStore()
    phash = confirm_tokens.params_hash("voice", None, None, None, None)
    with _patch_confirm(store):
        token = await confirm_tokens.create("t1", "v1", "voice", phash)
    store.rows[0]["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
    with _patch_confirm(store):
        ok = await confirm_tokens.redeem("t1", "v1", "voice", phash, token)
    assert ok is False, "an expired confirm_token must be refused, same as a used one"
    print("✅ test_confirm_token_expires")


def test_params_hash_stable_and_sensitive():
    a = confirm_tokens.params_hash("script", None, "make it punchier", 12, None)
    b = confirm_tokens.params_hash("script", None, "make it punchier", 12, None)
    c = confirm_tokens.params_hash("script", None, "make it punchier", 8, None)
    assert a == b, "identical inputs must hash identically"
    assert a != c, "a different length_min must hash differently"
    print("✅ test_params_hash_stable_and_sensitive")


# =============================================================================
# 2. Tool surface
# =============================================================================

def test_every_actions_verb_is_a_tool():
    names = mcp_mod.TOOL_NAMES
    missing = [v for v in actions.ACTIONS if v not in names]
    assert not missing, f"every actions.ACTIONS verb must be an MCP tool, missing: {missing}"
    print("✅ test_every_actions_verb_is_a_tool")


def test_s5_2_memory_tools_never_appear():
    names = mcp_mod.TOOL_NAMES
    for verb in ("remember", "forget", "set_budget"):
        assert verb not in names, f"{verb!r} must never be an MCP tool (S5-2)"
    print("✅ test_s5_2_memory_tools_never_appear")


def test_create_video_tool_present_and_free():
    tool = next(t for t in mcp_mod.TOOLS if t["name"] == "create_video")
    assert "free" in tool["description"].lower()
    assert "title" in tool["inputSchema"]["required"]
    print("✅ test_create_video_tool_present_and_free")


def test_paid_verb_schemas_carry_confirm_token_free_verbs_dont():
    by_name = {t["name"]: t for t in mcp_mod.TOOLS}
    for verb in mcp_mod._PAID_VERBS:
        props = by_name[verb]["inputSchema"]["properties"]
        assert "confirm_token" in props, f"{verb!r} is paid — must expose confirm_token"
        assert "PAID" in by_name[verb]["description"]
    for verb in mcp_mod._FREE_VERBS:
        props = by_name[verb]["inputSchema"]["properties"]
        assert "confirm_token" not in props, f"{verb!r} is free — must not expose confirm_token"
    print("✅ test_paid_verb_schemas_carry_confirm_token_free_verbs_dont")


async def test_list_style_presets_strips_preview_url():
    class _FakePreset:
        def model_dump(self):
            return {"presets": [{"id": "p1", "display_name": "Noir", "preview_url": "https://x/img.png"}]}

    async def _fake_route(tenant_id):
        return _FakePreset()

    fake_mod = types.ModuleType("routes.style_presets")
    fake_mod.list_style_presets = _fake_route
    with patch.dict(sys.modules, {"routes.style_presets": fake_mod}):
        result = await mcp_mod._call_list_style_presets("t1", {})
    text = result["content"][0]["text"]
    assert "preview_url" not in text
    assert "https://" not in text, "C25a hold: no media URL may leave an MCP tool result"
    print("✅ test_list_style_presets_strips_preview_url")


async def test_create_video_strips_thumbnail_url():
    class _FakeSummary:
        def model_dump(self):
            return {"id": "v1", "video_title": "T", "status": "idea_logged", "thumbnail_url": "https://x/thumb.png"}

    async def _fake_create(body, background_tasks, tenant_id):
        return _FakeSummary()

    fake_mod = types.ModuleType("routes.videos")
    fake_mod.create_video = _fake_create
    with patch.dict(sys.modules, {"routes.videos": fake_mod}):
        result = await mcp_mod._call_create_video("t1", {"title": "My Video"}, _FakeBackgroundTasks())
    text = result["content"][0]["text"]
    assert "thumbnail_url" not in text
    assert "https://" not in text
    print("✅ test_create_video_strips_thumbnail_url")


async def test_create_video_requires_title():
    result = await mcp_mod._call_create_video("t1", {}, _FakeBackgroundTasks())
    assert result["isError"] is True
    print("✅ test_create_video_requires_title")


# =============================================================================
# 3. The money-gate matrix — _call_verb
# =============================================================================

def _summary(status="ready_for_images", pics=6, scenes=2, model="grok-imagine"):
    return {"title": "T", "status": status, "scenes": scenes, "pics": pics, "clips": 0,
            "model": model, "spent": 1.0, "voiced": 0, "boards": 0, "max_scene": scenes,
            "cast": 0, "validation": "", "render_style": None}


def _patched_verb_env(*, video_summary=None, blocked=None, estimate=(1.23, "~$1.23"),
                       breakdown=None, redeem_result=None, create_token="mcpc_faketoken",
                       run_pending_result="On it.", run_pending_mock=None):
    video_summary = video_summary if video_summary is not None else AsyncMock(return_value=_summary())
    run_pending_mock = run_pending_mock or AsyncMock(return_value=run_pending_result)
    patches = [
        patch.object(actions, "video_summary", video_summary),
        patch.object(actions, "blocked_reason", lambda verb, summary: blocked),
        patch.object(actions, "estimate_cost", AsyncMock(return_value=estimate)),
        patch.object(actions, "cost_breakdown", AsyncMock(return_value=breakdown)),
        patch.object(actions, "already_uploaded_reply", AsyncMock(return_value=None)),
        patch.object(confirm_tokens, "create", AsyncMock(return_value=create_token)),
        patch.object(chat, "_run_pending_action", run_pending_mock),
    ]
    if redeem_result is not None:
        patches.append(patch.object(confirm_tokens, "redeem", AsyncMock(return_value=redeem_result)))
    return patches, run_pending_mock


def _apply(patches):
    ctx = []
    for p in patches:
        p.start()
        ctx.append(p)
    return ctx


def _stop(ctx):
    for p in ctx:
        p.stop()


async def test_paid_verb_without_confirm_token_returns_quote_not_execution():
    patches, run_pending_mock = _patched_verb_env()
    ctx = _apply(patches)
    try:
        result = await mcp_mod._call_verb("t1", "animate", {"video_id": "v1", "scene": 3}, _FakeBackgroundTasks(), "agent")
    finally:
        _stop(ctx)
    assert result["isError"] is False
    payload = result["content"][0]["text"]
    assert '"status": "quote"' in payload
    assert '"confirm_token": "mcpc_faketoken"' in payload
    run_pending_mock.assert_not_awaited()
    print("✅ test_paid_verb_without_confirm_token_returns_quote_not_execution")


async def test_paid_verb_wrong_confirm_token_refused():
    patches, run_pending_mock = _patched_verb_env(redeem_result=False)
    ctx = _apply(patches)
    try:
        result = await mcp_mod._call_verb(
            "t1", "animate", {"video_id": "v1", "scene": 3, "confirm_token": "mcpc_garbage"},
            _FakeBackgroundTasks(), "agent",
        )
    finally:
        _stop(ctx)
    assert result["isError"] is True
    assert "invalid" in result["content"][0]["text"].lower()
    run_pending_mock.assert_not_awaited()
    print("✅ test_paid_verb_wrong_confirm_token_refused")


async def test_paid_verb_expired_or_reused_token_refused():
    """redeem() returning False covers BOTH expiry and reuse — confirm_tokens'
    own unit tests (section 1) already prove those are the two real causes;
    this proves _call_verb's refusal behavior is identical for either."""
    patches, run_pending_mock = _patched_verb_env(redeem_result=False)
    ctx = _apply(patches)
    try:
        result = await mcp_mod._call_verb(
            "t1", "voice", {"video_id": "v1", "confirm_token": "mcpc_expired_or_used"},
            _FakeBackgroundTasks(), "agent",
        )
    finally:
        _stop(ctx)
    assert result["isError"] is True
    run_pending_mock.assert_not_awaited()
    print("✅ test_paid_verb_expired_or_reused_token_refused")


async def test_paid_verb_params_mismatched_confirm_refused():
    """The bait-and-switch case at the _call_verb layer: the SECOND call
    changes `scene` from what the (fake) quote token was minted against.
    Because confirm_tokens.redeem is exercised for REAL here (not mocked),
    this proves _call_verb actually recomputes params_hash from the
    confirming call's OWN arguments rather than trusting a client-supplied
    hash — a token minted for scene=3 must fail when the confirm call says
    scene=12."""
    store = _FakeConfirmStore()
    video_summary_mock = AsyncMock(return_value=_summary())
    with _patch_confirm(store), \
         patch.object(actions, "video_summary", video_summary_mock), \
         patch.object(actions, "blocked_reason", lambda verb, summary: None), \
         patch.object(actions, "estimate_cost", AsyncMock(return_value=(1.0, "~$1.00"))), \
         patch.object(actions, "cost_breakdown", AsyncMock(return_value=None)), \
         patch.object(actions, "already_uploaded_reply", AsyncMock(return_value=None)), \
         patch.object(chat, "_run_pending_action", AsyncMock(return_value="ran")) as run_pending_mock:
        quote = await mcp_mod._call_verb("t1", "animate", {"video_id": "v1", "scene": 3}, _FakeBackgroundTasks(), "agent")
        assert quote["isError"] is False
        import json as _json
        token = _json.loads(quote["content"][0]["text"])["confirm_token"]

        confirmed = await mcp_mod._call_verb(
            "t1", "animate", {"video_id": "v1", "scene": 12, "confirm_token": token},
            _FakeBackgroundTasks(), "agent",
        )
    assert confirmed["isError"] is True
    run_pending_mock.assert_not_awaited()
    print("✅ test_paid_verb_params_mismatched_confirm_refused")


async def test_paid_verb_confirmed_call_dispatches_same_runner_as_chat():
    """The centerpiece proof: a correctly confirmed MCP call reaches the
    EXACT SAME routes.chat._run_pending_action chat's own confirm-card
    tap-to-run calls — not a parallel MCP-local dispatcher. Patches
    routes.chat._run_pending_action itself (the real source), not some
    mcp.py-local copy, so a regression that forked dispatch would show up
    as this mock never being called."""
    store = _FakeConfirmStore()
    video_summary_mock = AsyncMock(return_value=_summary())
    with _patch_confirm(store), \
         patch.object(actions, "video_summary", video_summary_mock), \
         patch.object(actions, "blocked_reason", lambda verb, summary: None), \
         patch.object(actions, "estimate_cost", AsyncMock(return_value=(4.20, "~$4.20"))), \
         patch.object(actions, "cost_breakdown", AsyncMock(return_value=None)), \
         patch.object(actions, "already_uploaded_reply", AsyncMock(return_value=None)), \
         patch.object(chat, "_run_pending_action", AsyncMock(return_value="On it — animating scene 3.")) as run_pending_mock:
        bg = _FakeBackgroundTasks()
        quote = await mcp_mod._call_verb("t1", "animate", {"video_id": "v1", "scene": 3}, bg, "agent:Claude Desktop")
        import json as _json
        token = _json.loads(quote["content"][0]["text"])["confirm_token"]

        confirmed = await mcp_mod._call_verb(
            "t1", "animate", {"video_id": "v1", "scene": 3, "confirm_token": token}, bg, "agent:Claude Desktop",
        )

    assert confirmed["isError"] is False
    assert '"status": "started"' in confirmed["content"][0]["text"]
    run_pending_mock.assert_awaited_once_with(
        "t1", "v1", {"verb": "animate", "scene": 3, "change": None, "length_min": None}, bg,
        caller="agent:Claude Desktop",
    )
    print("✅ test_paid_verb_confirmed_call_dispatches_same_runner_as_chat")


async def test_free_verb_dispatches_immediately_no_confirm_token_ever_touched():
    video_summary_mock = AsyncMock(return_value=_summary())
    run_pending_mock = AsyncMock(return_value="Scene 2 approved.")
    with patch.object(actions, "video_summary", video_summary_mock), \
         patch.object(actions, "blocked_reason", lambda verb, summary: None), \
         patch.object(confirm_tokens, "create", AsyncMock(side_effect=AssertionError("must not quote a free verb"))), \
         patch.object(confirm_tokens, "redeem", AsyncMock(side_effect=AssertionError("must not redeem a free verb"))), \
         patch.object(chat, "_run_pending_action", run_pending_mock):
        bg = _FakeBackgroundTasks()
        result = await mcp_mod._call_verb("t1", "approve_scene", {"video_id": "v1", "scene": 2}, bg, "agent")
    assert result["isError"] is False
    assert '"status": "done"' in result["content"][0]["text"]
    run_pending_mock.assert_awaited_once_with(
        "t1", "v1", {"verb": "approve_scene", "scene": 2, "change": None, "length_min": None}, bg, caller="agent",
    )
    print("✅ test_free_verb_dispatches_immediately_no_confirm_token_ever_touched")


async def test_blocked_verb_refused_before_any_quote_minted():
    video_summary_mock = AsyncMock(return_value=_summary(pics=0))
    create_mock = AsyncMock(side_effect=AssertionError("must not mint a token for a blocked verb"))
    run_pending_mock = AsyncMock(side_effect=AssertionError("must not dispatch a blocked verb"))
    with patch.object(actions, "video_summary", video_summary_mock), \
         patch.object(actions, "blocked_reason", lambda verb, summary: "there are no pictures to work from yet"), \
         patch.object(confirm_tokens, "create", create_mock), \
         patch.object(chat, "_run_pending_action", run_pending_mock):
        result = await mcp_mod._call_verb("t1", "animate", {"video_id": "v1"}, _FakeBackgroundTasks(), "agent")
    assert result["isError"] is True
    assert "pictures" in result["content"][0]["text"]
    print("✅ test_blocked_verb_refused_before_any_quote_minted")


async def test_verb_call_is_tenant_scoped():
    """Mirrors C26's get_video tenant-scoping test: video_summary returning
    None for THIS tenant (video belongs to someone else, or doesn't exist)
    must refuse, never fall through to a quote or a dispatch."""
    async def _fake_video_summary(tenant_id, video_id):
        return None if tenant_id == "tenant-other" else _summary()

    with patch.object(actions, "video_summary", _fake_video_summary):
        result = await mcp_mod._call_verb("tenant-other", "animate", {"video_id": "v1"}, _FakeBackgroundTasks(), "agent")
    assert result["isError"] is True
    assert "no video" in result["content"][0]["text"].lower()
    print("✅ test_verb_call_is_tenant_scoped")


async def test_build_verb_target_rides_the_params_hash():
    """The 'build' verb's target ('pictures' vs 'finish') is server-derived
    from the video's CURRENT status, not a client argument — and it's baked
    into the params_hash, so a video that crosses the pictures->finish
    boundary between quote and confirm naturally invalidates any
    outstanding token (the target the confirm call re-derives no longer
    matches what was quoted)."""
    store = _FakeConfirmStore()
    call_count = {"n": 0}

    async def _fake_video_summary(tenant_id, video_id):
        call_count["n"] += 1
        # First call (quote): before pictures. Second call (confirm): pictures
        # already exist — the video advanced in between, same as if a
        # different verb had run concurrently.
        status = "ready_for_scripting" if call_count["n"] == 1 else "ready_for_images"
        return _summary(status=status, pics=0 if call_count["n"] == 1 else 6)

    with _patch_confirm(store), \
         patch.object(actions, "video_summary", _fake_video_summary), \
         patch.object(actions, "blocked_reason", lambda verb, summary: None), \
         patch.object(actions, "estimate_cost", AsyncMock(return_value=(2.0, "~$2.00"))), \
         patch.object(actions, "cost_breakdown", AsyncMock(return_value=None)), \
         patch.object(chat, "_run_pending_action", AsyncMock(return_value="ran")) as run_pending_mock:
        quote = await mcp_mod._call_verb("t1", "build", {"video_id": "v1"}, _FakeBackgroundTasks(), "agent")
        import json as _json
        token = _json.loads(quote["content"][0]["text"])["confirm_token"]
        confirmed = await mcp_mod._call_verb(
            "t1", "build", {"video_id": "v1", "confirm_token": token}, _FakeBackgroundTasks(), "agent",
        )
    assert confirmed["isError"] is True, "target changed between quote and confirm — must refuse, not silently run 'finish'"
    run_pending_mock.assert_not_awaited()
    print("✅ test_build_verb_target_rides_the_params_hash")


# =============================================================================
# 4. Attribution — the `caller` seam
# =============================================================================

async def test_run_pending_action_default_caller_is_chat_unchanged():
    """Backward compatibility: every existing chat.py call site omits
    `caller`, so the claimed_by string must be byte-identical to pre-C27
    behavior (tests in test_c16a_generation_claims.py pin these exact
    strings elsewhere; this is the same proof for a single-stage verb)."""
    bg = _FakeBackgroundTasks()
    acquire_mock = AsyncMock(return_value=True)
    with patch.object(chat, "generation_claims", types.SimpleNamespace(
            acquire=acquire_mock, stage_for_verb=generation_claims.stage_for_verb)):
        await chat._run_pending_action("tenant-1", "video-1", {"verb": "script"}, bg)
    acquire_mock.assert_awaited_once_with("tenant-1", "video-1", "main", claimed_by="chat:script")
    print("✅ test_run_pending_action_default_caller_is_chat_unchanged")


async def test_run_pending_action_agent_caller_attributes_single_stage_claim():
    bg = _FakeBackgroundTasks()
    acquire_mock = AsyncMock(return_value=True)
    with patch.object(chat, "generation_claims", types.SimpleNamespace(
            acquire=acquire_mock, stage_for_verb=generation_claims.stage_for_verb)):
        await chat._run_pending_action("tenant-1", "video-1", {"verb": "script"}, bg, caller="agent:Claude Desktop")
    acquire_mock.assert_awaited_once_with("tenant-1", "video-1", "main", claimed_by="agent:Claude Desktop:script")
    print("✅ test_run_pending_action_agent_caller_attributes_single_stage_claim")


async def test_run_pending_action_agent_caller_attributes_build_claim():
    bg = _FakeBackgroundTasks()
    acquire_mock = AsyncMock(return_value=True)

    async def _fake_fetch_one(query, *a):
        return {"render_mode": None}

    with patch.object(chat, "fetch_one", _fake_fetch_one), \
         patch.object(chat, "_make_autobuild_step", lambda *a, **k: "sentinel"), \
         patch.object(chat, "generation_claims", types.SimpleNamespace(
            acquire=acquire_mock, stage_for_verb=generation_claims.stage_for_verb)):
        await chat._run_pending_action(
            "tenant-1", "video-1", {"verb": "build", "target": "pictures"}, bg, caller="agent:CI bot",
        )
    acquire_mock.assert_awaited_once_with("tenant-1", "video-1", "main", claimed_by="agent:CI bot:build:pictures")
    print("✅ test_run_pending_action_agent_caller_attributes_build_claim")


async def test_runner_verb_caller_rides_in_pending_dict():
    """cfg.get('runner') verbs (approve_cast, draft_pass, finalize, ...) get
    `caller` injected into the pending dict `_run_pending_action` hands them
    — proven here against approve_cast's runner (a thin patch target) rather
    than draft_pass/finalize (which need a heavier fixture already covered
    by test_c17_draft_pass_and_finalize.py's own patches)."""
    bg = _FakeBackgroundTasks()
    seen_pending = {}

    async def _fake_runner(tenant_id, video_id, background_tasks, pending):
        seen_pending.update(pending)
        return "ok"

    with patch.object(chat, "_ACTION_RUNNERS", {"approve_cast": _fake_runner}):
        await chat._run_pending_action(
            "tenant-1", "video-1", {"verb": "approve_cast"}, bg, caller="agent:Bot",
        )
    assert seen_pending.get("caller") == "agent:Bot"
    print("✅ test_runner_verb_caller_rides_in_pending_dict")


async def test_draft_pass_runner_attributes_its_own_claim():
    """actions._runner_draft_pass claims its own lane (not through
    _run_pending_action's generic claim path) — proves it reads
    pending['caller'] the same way."""
    acquire_mock = AsyncMock(return_value=False)  # deny -> short-circuits before any dispatch, cheapest fixture
    with patch.object(actions, "_draft_tier_model_id", lambda: "grok-imagine"), \
         patch.object(actions, "video_summary", AsyncMock(return_value=_summary())), \
         patch.object(actions, "_routed_clip_rows", AsyncMock(return_value=[{"scene": 1}])), \
         patch.object(generation_passes, "already_done", AsyncMock(return_value=False)), \
         patch.object(generation_claims, "acquire", acquire_mock):
        line = await actions._runner_draft_pass("t1", "v1", _FakeBackgroundTasks(), {"caller": "agent:Bot"})
    acquire_mock.assert_awaited_once_with("t1", "v1", "main", claimed_by="agent:Bot:draft_pass")
    assert line == actions._ALREADY_WORKING_REPLY
    print("✅ test_draft_pass_runner_attributes_its_own_claim")


async def test_finalize_runner_attributes_its_own_claim():
    acquire_mock = AsyncMock(return_value=False)
    with patch.object(actions, "video_summary", AsyncMock(return_value=_summary())), \
         patch.object(actions, "_approved_scenes", AsyncMock(return_value=[1])), \
         patch.object(actions, "_routed_clip_rows", AsyncMock(return_value=[{"scene": 1}])), \
         patch.object(generation_passes, "already_done", AsyncMock(return_value=False)), \
         patch.object(generation_claims, "acquire", acquire_mock):
        line = await actions._runner_finalize("t1", "v1", _FakeBackgroundTasks(), {"caller": "agent:Bot"})
    acquire_mock.assert_awaited_once_with("t1", "v1", "main", claimed_by="agent:Bot:finalize")
    assert line == actions._ALREADY_WORKING_REPLY
    print("✅ test_finalize_runner_attributes_its_own_claim")


# =============================================================================
# 5. mcp_rpc route — resolves attribution from the bearer token
# =============================================================================

async def test_mcp_rpc_resolves_agent_name_for_attribution():
    from starlette.requests import Request as StarletteRequest

    scope = {
        "type": "http",
        "headers": [(b"authorization", b"Bearer se_agent_whatever")],
        "method": "POST", "path": "/api/mcp", "query_string": b"",
    }

    async def _receive():
        import json as _json
        body = _json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}).encode()
        return {"type": "http.request", "body": body, "more_body": False}

    request = StarletteRequest(scope, receive=_receive)
    seen = {}

    async def _fake_dispatch(method, params, tenant_id, background_tasks=None, caller="agent"):
        seen["caller"] = caller
        return {"tools": []}

    with patch.object(mcp_mod.agent_tokens, "name_for_token", AsyncMock(return_value="Claude Desktop")), \
         patch.object(mcp_mod, "_dispatch", _fake_dispatch):
        await mcp_mod.mcp_rpc(request, _FakeBackgroundTasks(), tenant_id="t1")

    assert seen["caller"] == "agent:Claude Desktop"
    print("✅ test_mcp_rpc_resolves_agent_name_for_attribution")


async def test_mcp_rpc_falls_back_to_generic_agent_when_name_lookup_misses():
    from starlette.requests import Request as StarletteRequest

    scope = {
        "type": "http",
        "headers": [(b"authorization", b"Bearer se_agent_whatever")],
        "method": "POST", "path": "/api/mcp", "query_string": b"",
    }

    async def _receive():
        import json as _json
        body = _json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}).encode()
        return {"type": "http.request", "body": body, "more_body": False}

    request = StarletteRequest(scope, receive=_receive)
    seen = {}

    async def _fake_dispatch(method, params, tenant_id, background_tasks=None, caller="agent"):
        seen["caller"] = caller
        return {"tools": []}

    with patch.object(mcp_mod.agent_tokens, "name_for_token", AsyncMock(return_value=None)), \
         patch.object(mcp_mod, "_dispatch", _fake_dispatch):
        await mcp_mod.mcp_rpc(request, _FakeBackgroundTasks(), tenant_id="t1")

    assert seen["caller"] == "agent"
    print("✅ test_mcp_rpc_falls_back_to_generic_agent_when_name_lookup_misses")


TESTS_SYNC = [
    test_every_actions_verb_is_a_tool,
    test_s5_2_memory_tools_never_appear,
    test_create_video_tool_present_and_free,
    test_paid_verb_schemas_carry_confirm_token_free_verbs_dont,
    test_params_hash_stable_and_sensitive,
]

TESTS_ASYNC = [
    test_confirm_token_roundtrip_succeeds,
    test_confirm_token_rejects_wrong_token_string,
    test_confirm_token_rejects_wrong_tenant,
    test_confirm_token_rejects_wrong_video,
    test_confirm_token_rejects_wrong_verb,
    test_confirm_token_rejects_params_mismatch_bait_and_switch,
    test_confirm_token_is_single_use,
    test_confirm_token_expires,
    test_list_style_presets_strips_preview_url,
    test_create_video_strips_thumbnail_url,
    test_create_video_requires_title,
    test_paid_verb_without_confirm_token_returns_quote_not_execution,
    test_paid_verb_wrong_confirm_token_refused,
    test_paid_verb_expired_or_reused_token_refused,
    test_paid_verb_params_mismatched_confirm_refused,
    test_paid_verb_confirmed_call_dispatches_same_runner_as_chat,
    test_free_verb_dispatches_immediately_no_confirm_token_ever_touched,
    test_blocked_verb_refused_before_any_quote_minted,
    test_verb_call_is_tenant_scoped,
    test_build_verb_target_rides_the_params_hash,
    test_run_pending_action_default_caller_is_chat_unchanged,
    test_run_pending_action_agent_caller_attributes_single_stage_claim,
    test_run_pending_action_agent_caller_attributes_build_claim,
    test_runner_verb_caller_rides_in_pending_dict,
    test_draft_pass_runner_attributes_its_own_claim,
    test_finalize_runner_attributes_its_own_claim,
    test_mcp_rpc_resolves_agent_name_for_attribution,
    test_mcp_rpc_falls_back_to_generic_agent_when_name_lookup_misses,
]


def main() -> int:
    failed = 0
    for t in TESTS_SYNC:
        try:
            t()
        except AssertionError as e:
            print(f"❌ {t.__name__}: {e}")
            failed += 1
    for t in TESTS_ASYNC:
        try:
            asyncio.run(t())
        except AssertionError as e:
            print(f"❌ {t.__name__}: {e}")
            failed += 1
    total = len(TESTS_SYNC) + len(TESTS_ASYNC)
    print(f"\n{total - failed}/{total} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
