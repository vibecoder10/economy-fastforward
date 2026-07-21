"""Tests for C48 (checklist "Media-bearing MCP tools + creation-walkthrough
recipe" — now unblocked, C25a's signed tenant-scoped media proxy merged +
deployed 2026-07-21). Adds the FIRST MCP tools allowed to carry a media URL
(the C25a hold's blanket ban is lifted for exactly one shape: a SIGNED,
SHORT-LIVED media-proxy URL) plus the staged `quick_demo_video` convenience
tool.

Covers:
  1. Tool surface: all 5 new tool names present in mcp.TOOL_NAMES; the 4
     media-read tools carry no confirm_token (free reads); quick_demo_video
     does (it can trigger the paid "build" verb).
  2. `_sign_media_url` reuses the REAL shared signing function
     (`shared.clients.image_client._kie_fetchable_url` — the SAME one Kie's
     own image-to-image calls use, C25a-fix2) rather than a forked/parallel
     implementation — a source-pattern lock test, same idiom as
     test_c25a_fix2's ImageClient-construction locks.
  3. get_scene_boards: signs URLs, caps at 6, tenant-scoped (video_summary
     None -> refused), a no-`scene` call returns a compact per-scene count
     summary with NO images/urls at all.
  4. get_character_sheets: video_id -> that video's cast (routes.characters.
     list_characters); no video_id -> the channel-level locked cast
     (routes.projects.get_channel_cast). Both signed.
  5. get_environment_images: wraps routes.environments.list_environments,
     signs reference_url.
  6. get_thumbnail_image: signs videos.thumbnail_url; a video with no
     thumbnail gets a friendly "no thumbnail yet" reply, not an error; wrong
     tenant is refused.
  7. Every media tool's result carries an expiry `note` naming the REAL TTL
     (read off routes.media.mint_media_token's own default, not a duplicated
     literal).
  8. quick_demo_video: staged, no video_id -> create_video verbatim (thin
     pass-through, proven by patching routes.videos.create_video itself);
     video_id + no confirm_token -> a quote and NOTHING paid is scheduled
     (background_tasks/chat._run_pending_action never touched); video_id +
     valid confirm_token -> dispatches through the EXACT SAME
     routes.chat._run_pending_action every other paid tool uses, verb="build"
     — proven by patching that function directly (not some MCP-local copy).

No live DB, no network, no paid calls — every DB boundary and confirm_
tokens.execute is patched directly (same conventions as test_c27_mcp_
toolset_money_gate.py / test_c49_mcp_atomic_surface.py).

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c48_media_tools.py -q
"""
from __future__ import annotations

import inspect
import json
import os
import sys
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _BACKEND)

os.environ.setdefault("SESSION_SECRET", "test-secret-only-for-c48")
os.environ.setdefault("PUBLIC_MEDIA_BASE", "https://storyengine.dev")

import actions  # noqa: E402
import confirm_tokens  # noqa: E402
import routes.chat as chat  # noqa: E402
import routes.mcp as mcp_mod  # noqa: E402

DRIVE_URL = "https://drive.google.com/uc?export=download&id=1AbCdEfGhIjKlMnOpQrStUvWxYz"


class _FakeBackgroundTasks:
    def __init__(self):
        self.calls = []

    def add_task(self, fn, *a, **k):
        self.calls.append((fn, a, k))


def _summary(status="ready_for_images", pics=6, scenes=2):
    return {"title": "T", "status": status, "scenes": scenes, "pics": pics, "clips": 0,
            "model": "grok-imagine", "spent": 1.0, "voiced": 0, "boards": 0,
            "max_scene": scenes, "cast": 0, "validation": "", "render_style": None}


# =============================================================================
# 1. Tool surface
# =============================================================================

_NEW_TOOLS = [
    "get_scene_boards", "get_character_sheets", "get_environment_images",
    "get_thumbnail_image", "quick_demo_video",
]
_FREE_READ_TOOLS = {"get_scene_boards", "get_character_sheets", "get_environment_images", "get_thumbnail_image"}


def test_all_new_tools_present():
    missing = [t for t in _NEW_TOOLS if t not in mcp_mod.TOOL_NAMES]
    assert not missing, f"missing C48 tools: {missing}"
    print("✅ test_all_new_tools_present")


def test_media_read_tools_carry_no_confirm_token_quick_demo_does():
    by_name = {t["name"]: t for t in mcp_mod.TOOLS}
    for name in _FREE_READ_TOOLS:
        assert "confirm_token" not in by_name[name]["inputSchema"]["properties"], name
    assert "confirm_token" in by_name["quick_demo_video"]["inputSchema"]["properties"]
    print("✅ test_media_read_tools_carry_no_confirm_token_quick_demo_does")


def test_s5_2_memory_tools_still_excluded():
    for verb in ("remember", "forget"):
        assert verb not in mcp_mod.TOOL_NAMES
    print("✅ test_s5_2_memory_tools_still_excluded")


# =============================================================================
# 2. _sign_media_url reuses the REAL shared signing function, not a fork
# =============================================================================

def test_sign_media_url_calls_the_shared_kie_fetchable_url_not_a_fork():
    src = inspect.getsource(mcp_mod._sign_media_url)
    assert "from shared.clients.image_client import _kie_fetchable_url" in src
    assert "_kie_fetchable_url(url, tenant_id)" in src
    print("✅ test_sign_media_url_calls_the_shared_kie_fetchable_url_not_a_fork")


def test_sign_media_url_produces_a_real_signed_token():
    import jwt as pyjwt
    tenant = "11111111-1111-1111-1111-111111111111"
    url = mcp_mod._sign_media_url(DRIVE_URL, tenant)
    assert url.startswith("https://storyengine.dev/api/media/drive/1AbCdEfGhIjKlMnOpQrStUvWxYz.png?token=")
    token = url.split("?token=", 1)[1]
    payload = pyjwt.decode(token, os.environ["SESSION_SECRET"], algorithms=["HS256"])
    assert payload["tenant_id"] == tenant
    assert payload["purpose"] == "media"
    print("✅ test_sign_media_url_produces_a_real_signed_token")


def test_sign_media_url_none_passes_through():
    assert mcp_mod._sign_media_url(None, "t1") is None
    print("✅ test_sign_media_url_none_passes_through")


def test_media_expiry_note_names_the_real_default_ttl():
    from routes.media import mint_media_token
    real_default = inspect.signature(mint_media_token).parameters["minutes"].default
    note = mcp_mod._media_expiry_note()
    assert str(real_default) in note
    assert mcp_mod._media_token_ttl_minutes() == real_default
    print("✅ test_media_expiry_note_names_the_real_default_ttl")


# =============================================================================
# 3. get_scene_boards
# =============================================================================

async def test_get_scene_boards_no_scene_returns_compact_summary_no_images():
    async def _fake_fetch_all(query, *args):
        assert "GROUP BY scene" in query
        return [{"scene": 1, "pics": 3}, {"scene": 2, "pics": 0}]

    with patch.object(actions, "video_summary", AsyncMock(return_value=_summary())), \
         patch.object(mcp_mod, "fetch_all", _fake_fetch_all):
        result = await mcp_mod._call_get_scene_boards("t1", {"video_id": "v1"})
    payload = json.loads(result["content"][0]["text"])
    assert payload["scenes"] == [{"scene": 1, "pics": 3}, {"scene": 2, "pics": 0}]
    assert "images" not in payload
    assert "url" not in json.dumps(payload)
    print("✅ test_get_scene_boards_no_scene_returns_compact_summary_no_images")


async def test_get_scene_boards_scene_signs_and_caps_at_six():
    rows = [
        {"id": f"a{i}", "image_index": i, "image_url": DRIVE_URL, "drive_image_url": None,
         "image_prompt": f"prompt number {i} " * 20}
        for i in range(10)
    ]

    async def _fake_fetch_all(query, *args):
        assert "LIMIT $4" in query
        limit = args[-1]
        return rows[:limit]

    with patch.object(actions, "video_summary", AsyncMock(return_value=_summary())), \
         patch.object(mcp_mod, "fetch_all", _fake_fetch_all):
        result = await mcp_mod._call_get_scene_boards("t1", {"video_id": "v1", "scene": 2})
    payload = json.loads(result["content"][0]["text"])
    assert payload["scene"] == 2
    assert len(payload["images"]) == mcp_mod._MAX_BOARD_IMAGES
    img = payload["images"][0]
    assert img["url"].startswith("https://storyengine.dev/api/media/drive/")
    assert "token=" in img["url"]
    assert len(img["prompt_snippet"]) <= 141
    assert "asset_id" in img and "index" in img
    assert str(mcp_mod._media_token_ttl_minutes()) in payload["note"]
    print("✅ test_get_scene_boards_scene_signs_and_caps_at_six")


async def test_get_scene_boards_tenant_scoped():
    with patch.object(actions, "video_summary", AsyncMock(return_value=None)):
        result = await mcp_mod._call_get_scene_boards("tenant-other", {"video_id": "v1"})
    assert result["isError"] is True
    print("✅ test_get_scene_boards_tenant_scoped")


async def test_get_scene_boards_empty_scene_no_crash():
    async def _fake_fetch_all(query, *args):
        return []

    with patch.object(actions, "video_summary", AsyncMock(return_value=_summary())), \
         patch.object(mcp_mod, "fetch_all", _fake_fetch_all):
        result = await mcp_mod._call_get_scene_boards("t1", {"video_id": "v1", "scene": 9})
    payload = json.loads(result["content"][0]["text"])
    assert payload["images"] == []
    print("✅ test_get_scene_boards_empty_scene_no_crash")


# =============================================================================
# 4. get_character_sheets
# =============================================================================

async def test_get_character_sheets_with_video_id_calls_real_route():
    call_args = {}

    async def _fake_list_characters(video_id, tenant_id):
        call_args["video_id"] = video_id
        call_args["tenant_id"] = tenant_id
        return {"characters": [
            {"id": "c1", "name": "Ava", "status": "approved", "reference_url": DRIVE_URL},
        ], "approved_at": None}

    import routes.characters as characters_route
    with patch.object(characters_route, "list_characters", _fake_list_characters):
        result = await mcp_mod._call_get_character_sheets("t1", {"video_id": "v1"})
    assert call_args == {"video_id": "v1", "tenant_id": "t1"}
    payload = json.loads(result["content"][0]["text"])
    assert payload["characters"][0]["name"] == "Ava"
    assert payload["characters"][0]["url"].startswith("https://storyengine.dev/api/media/drive/")
    print("✅ test_get_character_sheets_with_video_id_calls_real_route")


async def test_get_character_sheets_without_video_id_falls_back_to_channel_cast():
    async def _fake_get_channel_cast(tenant_id):
        return {"characters": [{"name": "Rex", "reference_url": DRIVE_URL}], "cast_locked": True}

    import routes.projects as projects_route
    with patch.object(projects_route, "get_channel_cast", _fake_get_channel_cast):
        result = await mcp_mod._call_get_character_sheets("t1", {})
    payload = json.loads(result["content"][0]["text"])
    assert payload["channel_cast_locked"] is True
    assert payload["characters"][0]["name"] == "Rex"
    assert "token=" in payload["characters"][0]["url"]
    print("✅ test_get_character_sheets_without_video_id_falls_back_to_channel_cast")


async def test_get_character_sheets_caps_at_max():
    async def _fake_get_channel_cast(tenant_id):
        return {"characters": [{"name": f"C{i}", "reference_url": DRIVE_URL} for i in range(30)],
                "cast_locked": False}

    import routes.projects as projects_route
    with patch.object(projects_route, "get_channel_cast", _fake_get_channel_cast):
        result = await mcp_mod._call_get_character_sheets("t1", {})
    payload = json.loads(result["content"][0]["text"])
    assert len(payload["characters"]) == mcp_mod._MAX_CHARACTER_SHEETS
    print("✅ test_get_character_sheets_caps_at_max")


# =============================================================================
# 5. get_environment_images
# =============================================================================

async def test_get_environment_images_calls_real_route_and_signs():
    call_args = {}

    async def _fake_list_environments(video_id, tenant_id):
        call_args["video_id"] = video_id
        call_args["tenant_id"] = tenant_id
        return {"environments": [
            {"id": "e1", "name": "Kitchen", "status": "approved", "reference_url": DRIVE_URL},
        ], "approved_at": "2026-07-20T00:00:00"}

    import routes.environments as environments_route
    with patch.object(environments_route, "list_environments", _fake_list_environments):
        result = await mcp_mod._call_get_environment_images("t1", {"video_id": "v1"})
    assert call_args == {"video_id": "v1", "tenant_id": "t1"}
    payload = json.loads(result["content"][0]["text"])
    assert payload["environments"][0]["name"] == "Kitchen"
    assert payload["environments"][0]["url"].startswith("https://storyengine.dev/api/media/drive/")
    assert payload["approved_at"] == "2026-07-20T00:00:00"
    print("✅ test_get_environment_images_calls_real_route_and_signs")


async def test_get_environment_images_requires_video_id():
    result = await mcp_mod._call_get_environment_images("t1", {})
    assert result["isError"] is True
    print("✅ test_get_environment_images_requires_video_id")


# =============================================================================
# 6. get_thumbnail_image
# =============================================================================

async def test_get_thumbnail_image_signs_when_present():
    async def _fake_fetch_one(query, *args):
        assert "thumbnail_url" in query
        return {"thumbnail_url": DRIVE_URL}

    with patch.object(mcp_mod, "fetch_one", _fake_fetch_one):
        result = await mcp_mod._call_get_thumbnail_image("t1", {"video_id": "v1"})
    payload = json.loads(result["content"][0]["text"])
    assert payload["url"].startswith("https://storyengine.dev/api/media/drive/")
    print("✅ test_get_thumbnail_image_signs_when_present")


async def test_get_thumbnail_image_none_yet_is_friendly_not_an_error():
    async def _fake_fetch_one(query, *args):
        return {"thumbnail_url": None}

    with patch.object(mcp_mod, "fetch_one", _fake_fetch_one):
        result = await mcp_mod._call_get_thumbnail_image("t1", {"video_id": "v1"})
    assert result["isError"] is False
    payload = json.loads(result["content"][0]["text"])
    assert payload["url"] is None
    print("✅ test_get_thumbnail_image_none_yet_is_friendly_not_an_error")


async def test_get_thumbnail_image_tenant_scoped():
    async def _fake_fetch_one(query, *args):
        return None

    with patch.object(mcp_mod, "fetch_one", _fake_fetch_one):
        result = await mcp_mod._call_get_thumbnail_image("tenant-other", {"video_id": "v1"})
    assert result["isError"] is True
    print("✅ test_get_thumbnail_image_tenant_scoped")


# =============================================================================
# 7. quick_demo_video — staged, money gate never weakened
# =============================================================================

async def test_quick_demo_video_requires_title_on_first_call():
    result = await mcp_mod._call_quick_demo_video("t1", {}, _FakeBackgroundTasks(), "agent")
    assert result["isError"] is True
    print("✅ test_quick_demo_video_requires_title_on_first_call")


async def test_quick_demo_video_first_call_creates_via_real_create_video():
    class _FakeCreated:
        def model_dump(self):
            return {"id": "v1", "video_title": "Demo", "status": "idea_logged"}

    call_args = {}

    async def _fake_create(body, background_tasks, tenant_id):
        call_args["title"] = body.title
        call_args["tenant_id"] = tenant_id
        return _FakeCreated()

    fake_mod = types.ModuleType("routes.videos")
    fake_mod.create_video = _fake_create
    with patch.dict(sys.modules, {"routes.videos": fake_mod}):
        result = await mcp_mod._call_quick_demo_video(
            "t1", {"title": "Demo"}, _FakeBackgroundTasks(), "agent",
        )
    assert call_args == {"title": "Demo", "tenant_id": "t1"}
    payload = json.loads(result["content"][0]["text"])
    assert payload["id"] == "v1"
    assert "next_step" in payload
    print("✅ test_quick_demo_video_first_call_creates_via_real_create_video")


async def test_quick_demo_video_no_confirm_token_quotes_and_schedules_nothing():
    """The money-gate proof: without a confirm_token, quick_demo_video must
    return a quote and must NEVER reach chat._run_pending_action (the only
    function that actually schedules the paid autobuild background task)."""
    run_pending_mock = AsyncMock(side_effect=AssertionError(
        "quick_demo_video must not dispatch anything paid without a redeemed confirm_token"
    ))
    with patch.object(confirm_tokens, "create", AsyncMock(return_value="mcpc_faketoken")), \
         patch.object(actions, "video_summary", AsyncMock(return_value=_summary(status="idea_logged", pics=0))), \
         patch.object(actions, "blocked_reason", lambda verb, summary: None), \
         patch.object(actions, "estimate_cost", AsyncMock(return_value=(3.5, "~$3.50"))), \
         patch.object(actions, "cost_breakdown", AsyncMock(return_value=None)), \
         patch.object(actions, "already_uploaded_reply", AsyncMock(return_value=None)), \
         patch.object(chat, "_run_pending_action", run_pending_mock):
        result = await mcp_mod._call_quick_demo_video(
            "t1", {"video_id": "v1"}, _FakeBackgroundTasks(), "agent",
        )
    run_pending_mock.assert_not_awaited()
    payload = json.loads(result["content"][0]["text"])
    assert payload["status"] == "quote"
    assert payload["verb"] == "build"
    assert payload["confirm_token"] == "mcpc_faketoken"
    print("✅ test_quick_demo_video_no_confirm_token_quotes_and_schedules_nothing")


async def test_quick_demo_video_confirmed_dispatches_the_real_build_verb():
    """Full (non-mocked) confirm_tokens quote -> confirm round trip, proving
    the confirmed call reaches the SAME routes.chat._run_pending_action every
    other paid tool/button uses, with verb="build" — not a parallel dispatch."""
    store: list[dict] = []

    async def _execute(query, *args):
        if "INSERT INTO mcp_confirm_tokens" in query:
            tenant_id, video_id, verb, phash, token_hash, ttl_secs = args
            store.append({
                "tenant_id": tenant_id, "video_id": video_id, "verb": verb,
                "params_hash": phash, "token_hash": token_hash,
                "expires_at": datetime.now(timezone.utc) + timedelta(seconds=ttl_secs),
                "used_at": None,
            })
            return "INSERT 0 1"
        if "UPDATE mcp_confirm_tokens SET used_at" in query:
            token_hash, tenant_id, video_id, verb, phash = args
            now = datetime.now(timezone.utc)
            for r in store:
                if (r["token_hash"] == token_hash and r["tenant_id"] == tenant_id
                        and r["video_id"] == video_id and r["verb"] == verb
                        and r["params_hash"] == phash and r["used_at"] is None
                        and r["expires_at"] > now):
                    r["used_at"] = now
                    return "UPDATE 1"
            return "UPDATE 0"
        raise AssertionError(f"unexpected query: {query!r}")

    run_pending_mock = AsyncMock(return_value="On it — building your video.")
    with patch.object(confirm_tokens, "execute", _execute), \
         patch.object(actions, "video_summary", AsyncMock(return_value=_summary(status="idea_logged", pics=0))), \
         patch.object(actions, "blocked_reason", lambda verb, summary: None), \
         patch.object(actions, "estimate_cost", AsyncMock(return_value=(3.5, "~$3.50"))), \
         patch.object(actions, "cost_breakdown", AsyncMock(return_value=None)), \
         patch.object(actions, "already_uploaded_reply", AsyncMock(return_value=None)), \
         patch.object(chat, "_run_pending_action", run_pending_mock):
        quote = await mcp_mod._call_quick_demo_video(
            "t1", {"video_id": "v1"}, _FakeBackgroundTasks(), "agent",
        )
        token = json.loads(quote["content"][0]["text"])["confirm_token"]
        confirmed = await mcp_mod._call_quick_demo_video(
            "t1", {"video_id": "v1", "confirm_token": token}, _FakeBackgroundTasks(), "agent",
        )
    run_pending_mock.assert_awaited_once()
    awaited_args = run_pending_mock.await_args.args
    assert awaited_args[0] == "t1" and awaited_args[1] == "v1"
    assert awaited_args[2]["verb"] == "build"
    payload = json.loads(confirmed["content"][0]["text"])
    assert payload["status"] == "started"
    assert "next_step" in payload
    print("✅ test_quick_demo_video_confirmed_dispatches_the_real_build_verb")


async def test_quick_demo_video_bad_confirm_token_refused():
    with patch.object(confirm_tokens, "redeem", AsyncMock(return_value=False)), \
         patch.object(actions, "video_summary", AsyncMock(return_value=_summary(status="idea_logged", pics=0))), \
         patch.object(actions, "blocked_reason", lambda verb, summary: None):
        result = await mcp_mod._call_quick_demo_video(
            "t1", {"video_id": "v1", "confirm_token": "mcpc_totally-made-up"}, _FakeBackgroundTasks(), "agent",
        )
    assert result["isError"] is True
    print("✅ test_quick_demo_video_bad_confirm_token_refused")
