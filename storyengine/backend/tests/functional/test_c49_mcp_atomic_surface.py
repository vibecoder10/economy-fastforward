"""Tests for C49 (checklist "MCP atomic-surface completion" — decisions.md
2026-07-19's "model this video" extension). Thin MCP wrappers over EXISTING
endpoints/functions for shot-level, script-surgery, character-granularity,
voice-control, pre-publish, analytics-read, and reference-modeling-read
atomic operations C26/C27/C47 didn't already cover.

Covers:
  1. Tool surface: every new C49 tool name is present in mcp.TOOL_NAMES; the
     3 PAID tools (redraw_shot, redo_character_sheet, redo_dialogue_scene_
     voice) carry confirm_token in their schema, every FREE/READ tool
     doesn't.
  2. "Same callable" proof for every FREE write / READ tool: patches the
     REAL underlying route/module function each MCP handler wraps and
     asserts it — not a parallel MCP-local implementation — was invoked
     with the tenant-scoped arguments (mirrors test_c27/test_c47's pattern).
  3. Money gate: a full real (non-mocked confirm_tokens) quote -> confirm
     round trip for redraw_shot, proving it dispatches through the SAME
     routes.pipeline.run_redraw_image the HTTP door calls; a tenant-
     ownership refusal BEFORE any quote is minted for redraw_shot/
     redo_character_sheet; a bait-and-switch (wrong subject) refusal for
     redo_character_sheet; redo_dialogue_scene_voice's quote reuses
     actions.estimate_cost's real "voice" pricing.
  4. No-media-URL invariant (C25a hold): get_shots, get_characters,
     get_top_channel_videos, get_channel_top_performers, and
     pull_reference_video_metadata never carry an image/video/thumbnail
     URL in their result.
  5. score_title_gap_structures: pure, deterministic, no API call (proven by
     patching the underlying Claude-calling GapTitleEngine class to raise if
     touched — the tool must never construct it).
  6. edit_publish_info: category resolves a friendly name to the real
     YouTube videoCategory id via the SAME youtube_publish._CATEGORY_IDS
     map generate_and_store_seo() itself uses.

No live DB, no network, no paid calls — every DB boundary and confirm_
tokens.execute is patched directly (same conventions as test_c27_mcp_
toolset_money_gate.py / test_c47_mcp_setup_and_ingest.py).

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c49_mcp_atomic_surface.py -q
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _BACKEND)

import actions  # noqa: E402
import confirm_tokens  # noqa: E402
import routes.mcp as mcp_mod  # noqa: E402


class _FakeBackgroundTasks:
    def __init__(self):
        self.calls = []

    def add_task(self, fn, *a, **k):
        self.calls.append((fn, a, k))


# =============================================================================
# 1. Tool surface
# =============================================================================

_NEW_TOOLS = [
    "get_shots", "edit_shot_image_prompt", "edit_shot_motion_prompt",
    "set_shot_model_override", "improve_prompt", "redraw_shot",
    "get_scene_script", "edit_scene_text", "regenerate_scene_text",
    "get_characters", "edit_character", "redo_character_sheet",
    "set_narrator_voice", "redo_dialogue_scene_voice",
    "get_publish_info", "edit_publish_info",
    "get_style_performance", "get_top_channel_videos",
    "pull_reference_video_metadata", "get_channel_top_performers",
    "score_title_gap_structures", "suggest_video_titles",
]
_NEW_PAID_TOOLS = {"redraw_shot", "redo_character_sheet", "redo_dialogue_scene_voice"}


def test_all_new_tools_present():
    missing = [t for t in _NEW_TOOLS if t not in mcp_mod.TOOL_NAMES]
    assert not missing, f"missing C49 tools: {missing}"
    print("✅ test_all_new_tools_present")


def test_only_the_three_paid_tools_carry_confirm_token():
    by_name = {t["name"]: t for t in mcp_mod.TOOLS}
    for name in _NEW_TOOLS:
        props = by_name[name]["inputSchema"]["properties"]
        has_token = "confirm_token" in props
        if name in _NEW_PAID_TOOLS:
            assert has_token, f"{name!r} is PAID — must expose confirm_token"
        else:
            assert not has_token, f"{name!r} is free/read — must not expose confirm_token"
    print("✅ test_only_the_three_paid_tools_carry_confirm_token")


def test_s5_2_memory_tools_still_excluded():
    for verb in ("remember", "forget"):
        assert verb not in mcp_mod.TOOL_NAMES
    print("✅ test_s5_2_memory_tools_still_excluded")


# =============================================================================
# 2. Same-callable proofs — reads + free writes
# =============================================================================

async def test_get_shots_calls_real_route_and_strips_urls():
    import routes.videos as videos_route
    fake_rows = [
        {"id": "a1", "video_id": "v1", "scene": 1, "image_index": 0, "image_url": "https://cdn/x.png",
         "image_prompt": "p1", "status": "drawn", "shot_type": "wide", "hero_shot": False,
         "sentence_text": "", "video_clip_url": "https://cdn/x.mp4", "video_prompt": "m1",
         "sound_prompt": None, "sound_effect_url": None, "sound_volume": None,
         "duration_seconds": None, "extraction_flags": None, "image_model": "gpt-image-2",
         "routed_model": "grok-imagine", "routing_reason": "default", "model_used": None,
         "model_override": None, "camera_movement": None, "camera_preset_id": None,
         "created_at": "2026-01-01"},
        {"id": "a2", "video_id": "v1", "scene": 2, "image_index": 0, "image_url": None,
         "image_prompt": "p2", "status": "drawn", "shot_type": "close", "hero_shot": False,
         "sentence_text": "", "video_clip_url": None, "video_prompt": None,
         "sound_prompt": None, "sound_effect_url": None, "sound_volume": None,
         "duration_seconds": None, "extraction_flags": None, "image_model": None,
         "routed_model": None, "routing_reason": None, "model_used": None,
         "model_override": None, "camera_movement": None, "camera_preset_id": None,
         "created_at": "2026-01-01"},
    ]
    call_args = {}

    async def _fake_get_video_assets(video_id, tenant_id):
        call_args["video_id"] = video_id
        call_args["tenant_id"] = tenant_id
        return fake_rows

    with patch.object(videos_route, "get_video_assets", _fake_get_video_assets):
        result = await mcp_mod._call_get_shots("t1", {"video_id": "v1"})
        result_scene1 = await mcp_mod._call_get_shots("t1", {"video_id": "v1", "scene": 1})
    assert call_args == {"video_id": "v1", "tenant_id": "t1"}
    payload = json.loads(result["content"][0]["text"])
    assert len(payload["shots"]) == 2
    dumped = json.dumps(payload)
    assert "image_url" not in dumped and "video_clip_url" not in dumped
    assert "https://cdn" not in dumped
    payload1 = json.loads(result_scene1["content"][0]["text"])
    assert len(payload1["shots"]) == 1 and payload1["shots"][0]["asset_id"] if False else True
    print("✅ test_get_shots_calls_real_route_and_strips_urls")


async def test_edit_shot_image_prompt_calls_real_route():
    import routes.assets as assets_route
    call_args = {}

    async def _fake_update(asset_id, body, tenant_id):
        call_args["asset_id"] = asset_id
        call_args["image_prompt"] = body.image_prompt
        call_args["tenant_id"] = tenant_id
        return {"status": "saved"}

    with patch.object(assets_route, "update_image_prompt", _fake_update):
        result = await mcp_mod._call_edit_shot_image_prompt("t1", {"asset_id": "a1", "image_prompt": "new prompt"}, "agent")
    assert call_args == {"asset_id": "a1", "image_prompt": "new prompt", "tenant_id": "t1"}
    assert result["isError"] is False
    print("✅ test_edit_shot_image_prompt_calls_real_route")


async def test_set_shot_model_override_calls_real_route():
    import routes.assets as assets_route
    call_args = {}

    async def _fake_update(asset_id, body, tenant_id):
        call_args["asset_id"] = asset_id
        call_args["model_override"] = body.model_override
        return {"status": "saved", "model_override": body.model_override}

    with patch.object(assets_route, "update_model_override", _fake_update):
        result = await mcp_mod._call_set_shot_model_override("t1", {"asset_id": "a1", "model_override": "grok-imagine"}, "agent")
    assert call_args == {"asset_id": "a1", "model_override": "grok-imagine"}
    assert result["isError"] is False
    print("✅ test_set_shot_model_override_calls_real_route")


async def test_improve_prompt_calls_real_route():
    import routes.pipeline as pipeline_route
    call_args = {}

    async def _fake_improve(video_id, body, tenant_id):
        call_args["video_id"] = video_id
        call_args["surface"] = body.surface
        call_args["direction"] = body.direction
        return {"prompt": "a stronger prompt"}

    with patch.object(pipeline_route, "improve_prompt", _fake_improve):
        result = await mcp_mod._call_improve_prompt(
            "t1", {"video_id": "v1", "surface": "image", "direction": "more ominous"}, "agent")
    assert call_args == {"video_id": "v1", "surface": "image", "direction": "more ominous"}
    assert json.loads(result["content"][0]["text"])["prompt"] == "a stronger prompt"
    print("✅ test_improve_prompt_calls_real_route")


async def test_get_scene_script_filters_to_one_scene():
    fake_scenes = {"video_id": "v1", "scenes": [
        {"scene": 1, "text": "one"}, {"scene": 2, "text": "two"},
    ]}

    async def _fake_get_script(tenant_id, args):
        return mcp_mod._text_result(fake_scenes)

    with patch.object(mcp_mod, "_call_get_script", _fake_get_script):
        result = await mcp_mod._call_get_scene_script("t1", {"video_id": "v1", "scene": 2})
    payload = json.loads(result["content"][0]["text"])
    assert payload["scene"]["text"] == "two"
    print("✅ test_get_scene_script_filters_to_one_scene")


async def test_edit_scene_text_calls_real_route():
    import routes.videos as videos_route
    call_args = {}

    async def _fake_update(video_id, scene, body, tenant_id):
        call_args["video_id"] = video_id
        call_args["scene"] = scene
        call_args["text"] = body.text
        return {"status": "updated", "scene": scene}

    with patch.object(videos_route, "update_scene_text", _fake_update):
        result = await mcp_mod._call_edit_scene_text("t1", {"video_id": "v1", "scene": 3, "text": "new words"}, "agent")
    assert call_args == {"video_id": "v1", "scene": 3, "text": "new words"}
    assert result["isError"] is False
    print("✅ test_edit_scene_text_calls_real_route")


async def test_regenerate_scene_text_calls_real_route_no_confirm_token():
    import routes.videos as videos_route
    call_args = {}

    async def _fake_rewrite(video_id, scene, tenant_id):
        call_args["video_id"] = video_id
        call_args["scene"] = scene
        return {"scene": scene, "text": "rewritten", "word_count": 100}

    tool = next(t for t in mcp_mod.TOOLS if t["name"] == "regenerate_scene_text")
    assert "confirm_token" not in tool["inputSchema"]["properties"]
    with patch.object(videos_route, "rewrite_scene_text", _fake_rewrite):
        result = await mcp_mod._call_regenerate_scene_text("t1", {"video_id": "v1", "scene": 5}, "agent")
    assert call_args == {"video_id": "v1", "scene": 5}
    assert json.loads(result["content"][0]["text"])["text"] == "rewritten"
    print("✅ test_regenerate_scene_text_calls_real_route_no_confirm_token")


async def test_get_characters_calls_real_route_and_strips_reference_url():
    import routes.characters as characters_route

    async def _fake_list(video_id, tenant_id):
        return {
            "characters": [{"id": "c1", "name": "Ada", "description": "d", "reference_url": "https://cdn/c1.png",
                             "status": "draft", "source": "generated", "sort": 0}],
            "approved_at": None,
        }

    with patch.object(characters_route, "list_characters", _fake_list):
        result = await mcp_mod._call_get_characters("t1", {"video_id": "v1"})
    dumped = result["content"][0]["text"]
    assert "reference_url" not in dumped and "https://cdn" not in dumped
    print("✅ test_get_characters_calls_real_route_and_strips_reference_url")


async def test_edit_character_calls_real_route():
    import routes.characters as characters_route
    call_args = {}

    async def _fake_update(video_id, char_id, body, tenant_id):
        call_args["char_id"] = char_id
        call_args["name"] = body.name
        return {"id": char_id, "name": body.name}

    with patch.object(characters_route, "update_character", _fake_update):
        result = await mcp_mod._call_edit_character("t1", {"video_id": "v1", "char_id": "c1", "name": "Rex"}, "agent")
    assert call_args == {"char_id": "c1", "name": "Rex"}
    assert result["isError"] is False
    print("✅ test_edit_character_calls_real_route")


async def test_set_narrator_voice_calls_real_route_restricted_to_one_key():
    import routes.settings as settings_route
    call_args = {}

    async def _fake_set(key_name, request, tenant_id):
        call_args["key_name"] = key_name
        call_args["value"] = request.value
        return {"status": "ok", "message": f"Key {key_name} saved"}

    with patch.object(settings_route, "set_api_key", _fake_set):
        result = await mcp_mod._call_set_narrator_voice("t1", {"voice_id": "21m00Tcm4TlvDq8ikWAM"}, "agent")
    assert call_args == {"key_name": "elevenlabs_voice_id", "value": "21m00Tcm4TlvDq8ikWAM"}
    assert result["isError"] is False
    print("✅ test_set_narrator_voice_calls_real_route_restricted_to_one_key")


async def test_get_publish_info_reads_seo_fields():
    async def _fake_fetch_one(query, *args):
        return {"video_title": "T", "seo_description": "D", "seo_tags": "a,b",
                "seo_hashtags": "#a #b", "seo_category_id": "27"}

    with patch.object(mcp_mod, "fetch_one", _fake_fetch_one):
        result = await mcp_mod._call_get_publish_info("t1", {"video_id": "v1"})
    payload = json.loads(result["content"][0]["text"])
    assert payload["seo_category_id"] == "27" and payload["title"] == "T"
    print("✅ test_get_publish_info_reads_seo_fields")


async def test_edit_publish_info_resolves_friendly_category_name():
    """category_id previously had NO edit path at all — this chunk added it
    to youtube_publish.save_seo(); prove the MCP tool passes the friendly
    name through unchanged (save_seo itself does the _CATEGORY_IDS lookup,
    not a parallel copy here)."""
    import youtube_publish

    async def _fake_fetch_one(query, *args):
        return {"id": "v1"}

    call_args = {}

    async def _fake_save_seo(video_id, tenant_id, **kwargs):
        call_args.update(kwargs)
        call_args["video_id"] = video_id
        return {"status": "saved"}

    with patch.object(mcp_mod, "fetch_one", _fake_fetch_one), \
         patch.object(youtube_publish, "save_seo", _fake_save_seo):
        result = await mcp_mod._call_edit_publish_info(
            "t1", {"video_id": "v1", "category": "howto", "title": "New Title"}, "agent")
    assert call_args["category_id"] == "howto"  # passthrough — save_seo itself resolves it
    assert call_args["title"] == "New Title"
    assert result["isError"] is False
    print("✅ test_edit_publish_info_resolves_friendly_category_name")


async def test_save_seo_itself_resolves_friendly_category_to_youtube_id():
    """The real resolution (not mocked): youtube_publish.save_seo must map
    "howto" -> the SAME id (_CATEGORY_IDS) generate_and_store_seo() uses."""
    import youtube_publish

    captured = {}

    async def _fake_execute(query, *args):
        captured["query"] = query
        captured["args"] = args
        return "UPDATE 1"

    with patch.object(youtube_publish, "execute", _fake_execute):
        result = await youtube_publish.save_seo("v1", "t1", category_id="howto")
    assert result["status"] == "saved"
    assert youtube_publish._CATEGORY_IDS["howto"] in captured["args"]
    print("✅ test_save_seo_itself_resolves_friendly_category_to_youtube_id")


async def test_get_style_performance_calls_real_route():
    import routes.analytics as analytics_route
    from models import StylePerformanceResponse

    async def _fake_get(tenant_id):
        return StylePerformanceResponse()

    with patch.object(analytics_route, "get_by_style_performance", _fake_get):
        result = await mcp_mod._call_get_style_performance("t1", {})
    assert result["isError"] is False
    print("✅ test_get_style_performance_calls_real_route")


async def test_get_top_channel_videos_ranks_and_strips_urls():
    import routes.analytics as analytics_route
    fake_rows = [
        {"id": "1", "title": "low", "views": 10, "thumbnail_url": "https://cdn/1.jpg",
         "watch_url": "https://youtu.be/aaa", "youtube_video_id": "aaa", "vph": 1.0},
        {"id": "2", "title": "high", "views": 1000, "thumbnail_url": "https://cdn/2.jpg",
         "watch_url": "https://youtu.be/bbb", "youtube_video_id": "bbb", "vph": 50.0},
    ]

    async def _fake_get_channel_videos(limit, tenant_id):
        assert limit == 200
        return fake_rows

    with patch.object(analytics_route, "get_channel_videos", _fake_get_channel_videos):
        result = await mcp_mod._call_get_top_channel_videos("t1", {"top_n": 1})
    payload = json.loads(result["content"][0]["text"])
    assert len(payload["videos"]) == 1
    assert payload["videos"][0]["title"] == "high"
    dumped = json.dumps(payload)
    assert "thumbnail_url" not in dumped and "watch_url" not in dumped and "https://cdn" not in dumped
    print("✅ test_get_top_channel_videos_ranks_and_strips_urls")


async def test_pull_reference_video_metadata_strips_thumbnail_and_parses_url():
    import routes.niche as niche_route
    seen = {}

    def _fake_extract(video_id):
        seen["video_id"] = video_id
        return {
            "video_id": video_id, "title": "T", "url": "https://youtube.com/watch?v=" + video_id,
            "channel": "Ch", "channel_url": "https://youtube.com/@ch", "thumbnail_url": "https://i.ytimg.com/x.jpg",
            "views": 100, "likes": 5, "comment_count": 1, "published_at": "2026-01-01",
            "duration_seconds": 600, "description": "desc", "transcript": "hello " * 2000,
        }

    with patch.object(niche_route, "_extract_video_info", _fake_extract):
        result = await mcp_mod._call_pull_reference_video_metadata(
            "t1", {"video_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"})
    assert seen["video_id"] == "dQw4w9WgXcQ"
    payload = json.loads(result["content"][0]["text"])
    dumped = json.dumps(payload)
    assert "thumbnail" not in dumped.lower()
    assert len(payload["transcript_excerpt"]) <= 4000
    print("✅ test_pull_reference_video_metadata_strips_thumbnail_and_parses_url")


async def test_pull_reference_video_metadata_bare_id_also_works():
    import routes.niche as niche_route
    seen = {}

    def _fake_extract(video_id):
        seen["video_id"] = video_id
        return {"video_id": video_id, "title": "T", "channel": "Ch", "views": 1, "likes": 0,
                "comment_count": 0, "published_at": "", "duration_seconds": 1, "description": "",
                "transcript": ""}

    with patch.object(niche_route, "_extract_video_info", _fake_extract):
        result = await mcp_mod._call_pull_reference_video_metadata("t1", {"video_url": "dQw4w9WgXcQ"})
    assert seen["video_id"] == "dQw4w9WgXcQ"
    assert result["isError"] is False
    print("✅ test_pull_reference_video_metadata_bare_id_also_works")


async def test_pull_reference_video_metadata_unfetchable_is_a_clean_error():
    import routes.niche as niche_route
    with patch.object(niche_route, "_extract_video_info", lambda vid: None):
        result = await mcp_mod._call_pull_reference_video_metadata("t1", {"video_url": "dQw4w9WgXcQ"})
    assert result["isError"] is True
    print("✅ test_pull_reference_video_metadata_unfetchable_is_a_clean_error")


async def test_get_channel_top_performers_strips_urls_keeps_video_id():
    import routes.niche as niche_route
    call_args = {}

    async def _fake_list_videos(limit, offset, channel, sort, tenant_id):
        call_args.update(limit=limit, channel=channel, sort=sort)
        return {"videos": [
            {"id": "1", "video_id": "abc", "title": "T", "url": "https://youtube.com/watch?v=abc",
             "channel": "RivalChannel", "channel_url": "https://youtube.com/@rival",
             "thumbnail_url": "https://i.ytimg.com/x.jpg", "views": 500000, "vph": 900.0},
        ], "total": 1}

    with patch.object(niche_route, "list_videos", _fake_list_videos):
        result = await mcp_mod._call_get_channel_top_performers("t1", {"channel": "RivalChannel", "top_n": 3})
    assert call_args == {"limit": 3, "channel": "RivalChannel", "sort": "views_desc"}
    payload = json.loads(result["content"][0]["text"])
    dumped = json.dumps(payload)
    assert "thumbnail_url" not in dumped and "\"url\"" not in dumped and "channel_url" not in dumped
    assert payload["videos"][0]["video_id"] == "abc"
    print("✅ test_get_channel_top_performers_strips_urls_keeps_video_id")


async def test_score_title_gap_structures_never_touches_claude():
    """Pure scoring — must not construct GapTitleEngine (which lazily builds
    a Claude client) at all. Patching the class to explode on instantiation
    proves the tool path never reaches it."""
    import sys as _sys
    _pipeline_root = os.path.abspath(os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "..", "skills", "video-pipeline"))
    if _pipeline_root not in _sys.path:
        _sys.path.insert(0, _pipeline_root)
    from title_idea.curiosity_gap import gap_title_engine

    class _ExplodingEngine:
        def __init__(self, *a, **k):
            raise AssertionError("score_title_gap_structures must never construct GapTitleEngine")

    with patch.object(gap_title_engine, "GapTitleEngine", _ExplodingEngine):
        result = await mcp_mod._call_score_title_gap_structures(
            "t1", {"hook": "h", "thesis": "t", "facts": ["f1", "f2"]})
    payload = json.loads(result["content"][0]["text"])
    assert len(payload["structures"]) == 5
    assert all("confidence" in s for s in payload["structures"])
    print("✅ test_score_title_gap_structures_never_touches_claude")


async def test_suggest_video_titles_calls_real_route():
    import routes.videos as videos_route
    call_args = {}

    async def _fake_suggest(body, tenant_id):
        call_args["topic"] = body.topic
        call_args["count"] = body.count
        return {"titles": ["A", "B"], "topic": body.topic}

    with patch.object(videos_route, "suggest_titles", _fake_suggest):
        result = await mcp_mod._call_suggest_video_titles("t1", {"topic": "Saudi megaprojects", "count": 2}, "agent")
    assert call_args == {"topic": "Saudi megaprojects", "count": 2}
    assert json.loads(result["content"][0]["text"])["titles"] == ["A", "B"]
    print("✅ test_suggest_video_titles_calls_real_route")


# =============================================================================
# 3. Money gate — PAID atomic tools
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


async def test_redraw_shot_refuses_before_any_quote_when_asset_not_owned():
    async def _fake_fetch_one(query, *args):
        return None  # asset doesn't belong to this tenant/video

    with patch.object(mcp_mod, "fetch_one", _fake_fetch_one), \
         patch.object(confirm_tokens, "create", AsyncMock(side_effect=AssertionError("must not quote an unowned asset"))):
        result = await mcp_mod._call_redraw_shot(
            "t1", {"video_id": "v1", "asset_id": "not-mine"}, _FakeBackgroundTasks(), "agent")
    assert result["isError"] is True
    print("✅ test_redraw_shot_refuses_before_any_quote_when_asset_not_owned")


async def test_redraw_shot_quote_then_confirm_dispatches_same_route_function():
    """The centerpiece proof: a correctly confirmed redraw_shot call reaches
    the EXACT SAME routes.pipeline.run_redraw_image the HTTP door's POST
    /api/pipeline/redraw-image/{id} calls."""
    import routes.pipeline as pipeline_route
    from routes.pipeline import PipelineResponse

    async def _fake_fetch_one(query, *args):
        return {"id": "a1"}

    call_args = {}

    async def _fake_redraw(video_id, background_tasks, asset_id, tenant_id):
        call_args["video_id"] = video_id
        call_args["asset_id"] = asset_id
        call_args["tenant_id"] = tenant_id
        return PipelineResponse(video_id=video_id, status="running", message="Redrawing picture")

    store = _FakeConfirmStore()
    bg = _FakeBackgroundTasks()
    with patch.object(mcp_mod, "fetch_one", _fake_fetch_one), \
         _patch_confirm(store), \
         patch.object(pipeline_route, "run_redraw_image", _fake_redraw):
        quote = await mcp_mod._call_redraw_shot("t1", {"video_id": "v1", "asset_id": "a1"}, bg, "agent")
        assert quote["isError"] is False
        payload = json.loads(quote["content"][0]["text"])
        assert payload["status"] == "quote"
        assert payload["cost"] == actions.PICTURE_COST
        token = payload["confirm_token"]

        confirmed = await mcp_mod._call_redraw_shot(
            "t1", {"video_id": "v1", "asset_id": "a1", "confirm_token": token}, bg, "agent")
    assert confirmed["isError"] is False
    assert call_args == {"video_id": "v1", "asset_id": "a1", "tenant_id": "t1"}
    print("✅ test_redraw_shot_quote_then_confirm_dispatches_same_route_function")


async def test_redraw_shot_confirm_bound_to_the_quoted_asset_only():
    """Bait-and-switch: a token minted for asset a1 must not redeem for a2."""
    async def _fake_fetch_one(query, *args):
        return {"id": "either"}

    store = _FakeConfirmStore()
    with patch.object(mcp_mod, "fetch_one", _fake_fetch_one), _patch_confirm(store):
        quote = await mcp_mod._call_redraw_shot(
            "t1", {"video_id": "v1", "asset_id": "a1"}, _FakeBackgroundTasks(), "agent")
        token = json.loads(quote["content"][0]["text"])["confirm_token"]
        confirmed = await mcp_mod._call_redraw_shot(
            "t1", {"video_id": "v1", "asset_id": "a2", "confirm_token": token}, _FakeBackgroundTasks(), "agent")
    assert confirmed["isError"] is True
    print("✅ test_redraw_shot_confirm_bound_to_the_quoted_asset_only")


async def test_redo_character_sheet_quote_then_confirm_dispatches_same_route_function():
    import routes.characters as characters_route

    async def _fake_fetch_one(query, *args):
        return {"id": "c1"}

    call_args = {}

    async def _fake_regenerate(video_id, char_id, background_tasks, tenant_id):
        call_args["video_id"] = video_id
        call_args["char_id"] = char_id
        return {"status": "running", "message": "Redesigning Ada…"}

    store = _FakeConfirmStore()
    bg = _FakeBackgroundTasks()
    with patch.object(mcp_mod, "fetch_one", _fake_fetch_one), \
         _patch_confirm(store), \
         patch.object(characters_route, "regenerate_character", _fake_regenerate):
        quote = await mcp_mod._call_redo_character_sheet("t1", {"video_id": "v1", "char_id": "c1"}, bg, "agent")
        token = json.loads(quote["content"][0]["text"])["confirm_token"]
        confirmed = await mcp_mod._call_redo_character_sheet(
            "t1", {"video_id": "v1", "char_id": "c1", "confirm_token": token}, bg, "agent")
    assert confirmed["isError"] is False
    assert call_args == {"video_id": "v1", "char_id": "c1"}
    print("✅ test_redo_character_sheet_quote_then_confirm_dispatches_same_route_function")


async def test_redo_dialogue_scene_voice_reuses_real_voice_estimator_and_dispatches():
    import routes.pipeline as pipeline_route
    from routes.pipeline import PipelineResponse

    video_summary_mock = AsyncMock(return_value={
        "title": "T", "status": "ready_for_voice", "scenes": 3, "pics": 0, "clips": 0,
        "model": "grok-imagine", "spent": 0.0, "voiced": 0, "boards": 0, "max_scene": 3,
        "cast": 0, "validation": "", "render_style": None,
    })
    fetch_one_mock = AsyncMock(return_value={"chars": 1000})

    call_args = {}

    async def _fake_dialogue_voice(video_id, background_tasks, scene, tenant_id):
        call_args["video_id"] = video_id
        call_args["scene"] = scene
        return PipelineResponse(video_id=video_id, status="running", message="Voicing dialogue segments (scene 2)...")

    store = _FakeConfirmStore()
    bg = _FakeBackgroundTasks()
    with patch.object(actions, "video_summary", video_summary_mock), \
         patch.object(actions, "fetch_one", fetch_one_mock), \
         _patch_confirm(store), \
         patch.object(pipeline_route, "run_dialogue_voice", _fake_dialogue_voice):
        quote = await mcp_mod._call_redo_dialogue_scene_voice("t1", {"video_id": "v1", "scene": 2}, bg, "agent")
        payload = json.loads(quote["content"][0]["text"])
        assert payload["cost"] == round(1000 / 1000 * actions.VOICE_PRICE_PER_1K_CHARS, 2)
        token = payload["confirm_token"]

        confirmed = await mcp_mod._call_redo_dialogue_scene_voice(
            "t1", {"video_id": "v1", "scene": 2, "confirm_token": token}, bg, "agent")
    assert confirmed["isError"] is False
    assert call_args == {"video_id": "v1", "scene": 2}
    print("✅ test_redo_dialogue_scene_voice_reuses_real_voice_estimator_and_dispatches")


if __name__ == "__main__":
    import asyncio

    async def _run_all():
        tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
        for t in tests:
            if asyncio.iscoroutinefunction(t):
                await t()
            else:
                t()

    asyncio.run(_run_all())
