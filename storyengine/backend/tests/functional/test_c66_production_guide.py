"""Tests for C66 (checklist "MCP process brain" — tasks/decisions.md
2026-07-21 "MCP co-pilot must be PROCESS-AWARE"). Ryan's live-driving pain:
the connected agent skipped environment design and a character-presence
check because nothing taught it the canonical stage order or the current
video's gaps. This chunk adds:

  1. `initialize` response `instructions` teaching the canonical stage order
     (built LIVE from production_guide.GUIDE_STAGES, not baked into a module
     constant — proven by a lock test that monkeypatches the map and
     re-dispatches "initialize").
  2. `get_production_guide(video_id)` — the full ordered stage checklist for
     ONE video: done/in_progress/not_started/skipped_by_format per stage,
     concrete gaps read from real data, and a next_step recommendation.
  3. The environments MCP tool family (the NAMED skipped step): design_
     environments (PAID, new — environment design never had a verb before
     this chunk), redo_environment (PAID), edit_environment / delete_
     environment (FREE) — every one a thin wrapper over the EXISTING
     routes/environments.py endpoint of the same shape.

No live DB, no network, no paid calls — every DB boundary and confirm_
tokens.execute is patched directly (same conventions as test_c48/test_c49).

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c66_production_guide.py -q
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _BACKEND)

os.environ.setdefault("SESSION_SECRET", "test-secret-only-for-c66")

import actions  # noqa: E402
import confirm_tokens  # noqa: E402
import production_guide  # noqa: E402
import routes.mcp as mcp_mod  # noqa: E402


class _FakeBackgroundTasks:
    def __init__(self):
        self.calls = []

    def add_task(self, fn, *a, **k):
        self.calls.append((fn, a, k))


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


# =============================================================================
# 1. Tool surface
# =============================================================================

_NEW_TOOLS = [
    "get_production_guide", "design_environments", "redo_environment",
    "edit_environment", "delete_environment",
]
_NEW_PAID_TOOLS = {"design_environments", "redo_environment"}


def test_all_new_tools_present():
    missing = [t for t in _NEW_TOOLS if t not in mcp_mod.TOOL_NAMES]
    assert not missing, f"missing C66 tools: {missing}"
    print("✅ test_all_new_tools_present")


def test_only_the_paid_environment_tools_carry_confirm_token():
    by_name = {t["name"]: t for t in mcp_mod.TOOLS}
    for name in _NEW_TOOLS:
        has_token = "confirm_token" in by_name[name]["inputSchema"]["properties"]
        if name in _NEW_PAID_TOOLS:
            assert has_token, f"{name!r} is PAID — must expose confirm_token"
        else:
            assert not has_token, f"{name!r} is free/read — must not expose confirm_token"
    print("✅ test_only_the_paid_environment_tools_carry_confirm_token")


def test_s5_2_memory_tools_still_excluded():
    for verb in ("remember", "forget"):
        assert verb not in mcp_mod.TOOL_NAMES
    print("✅ test_s5_2_memory_tools_still_excluded")


# =============================================================================
# 2. `initialize` instructions — single-source lock test
# =============================================================================

async def test_initialize_instructions_carry_the_canonical_order():
    result = await mcp_mod._dispatch("initialize", {}, "t1")
    text = result["instructions"]
    for label in ("Research", "Script", "Characters (presence check + sheets)",
                  "Environments (design + approve)", "Storyboard grids", "Upload to YouTube"):
        assert label in text, f"missing stage label {label!r} in instructions"
    assert "get_production_guide" in text
    assert "get_workspace_info" in text
    print("✅ test_initialize_instructions_carry_the_canonical_order")


async def test_initialize_instructions_are_built_live_from_guide_stages_not_a_copy():
    """Lock test: mutate production_guide.GUIDE_STAGES, re-dispatch
    "initialize" — the returned instructions text must change. Proves the
    instructions are computed from the SAME single source get_production_
    guide reads, not a hand-typed duplicate that can drift."""
    marker = "ZZZ_MARKER_STAGE_FOR_LOCK_TEST"
    mutated = production_guide.GUIDE_STAGES + [
        {"key": "zzz_test", "label": marker, "format_bucket": "upload"}
    ]
    with patch.object(production_guide, "GUIDE_STAGES", mutated):
        result = await mcp_mod._dispatch("initialize", {}, "t1")
    assert marker in result["instructions"]

    # And the marker is gone again once GUIDE_STAGES is back to normal —
    # proving the text isn't cached/baked in either.
    result2 = await mcp_mod._dispatch("initialize", {}, "t1")
    assert marker not in result2["instructions"]
    print("✅ test_initialize_instructions_are_built_live_from_guide_stages_not_a_copy")


# =============================================================================
# 3. get_production_guide — stage snapshots + gaps + next_step
# =============================================================================

def _video_row(**overrides):
    row = {
        "video_title": "Test Video", "status": "ready_for_scripting",
        "render_mode": None, "pipeline_stages": None, "skip_voice": False,
        "story_locked_at": None, "characters_approved_at": None,
        "environments_approved_at": None, "thumbnail_url": None,
        "youtube_url": None, "youtube_video_id": None, "story_bible": None,
        "research_payload": None,
    }
    row.update(overrides)
    return row


def _summary(**overrides):
    s = {"scenes": 0, "boards": 0, "voiced": 0, "pics": 0, "clips": 0, "cast": 0}
    s.update(overrides)
    return s


def _patch_all(video_row, *, cast_rows=None, env_rows=None, board_rows=None,
                active_rows=None, summary=None):
    async def _fake_fetch_one(query, *args):
        assert "FROM videos WHERE id" in query
        return video_row

    async def _fake_fetch_all(query, *args):
        if "video_characters" in query:
            return cast_rows or []
        if "video_environments" in query:
            return env_rows or []
        if "FROM scripts" in query:
            return board_rows or []
        if "background_tasks" in query:
            return active_rows or []
        raise AssertionError(f"unexpected fetch_all query: {query!r}")

    return (
        patch.object(production_guide, "fetch_one", _fake_fetch_one),
        patch.object(production_guide, "fetch_all", _fake_fetch_all),
        patch.object(production_guide, "video_summary", AsyncMock(return_value=summary or _summary())),
    )


async def test_video_not_found_returns_none():
    async def _fake_fetch_one(query, *args):
        return None
    with patch.object(production_guide, "fetch_one", _fake_fetch_one):
        guide = await production_guide.get_production_guide("t1", "missing")
    assert guide is None
    print("✅ test_video_not_found_returns_none")


async def test_fresh_video_next_step_is_research():
    p1, p2, p3 = _patch_all(_video_row(status="idea_logged"))
    with p1, p2, p3:
        guide = await production_guide.get_production_guide("t1", "v1")
    assert guide["next_step"]["stage"] == "research"
    assert guide["next_step"]["action"] == "start"
    by_key = {s["key"]: s for s in guide["stages"]}
    assert by_key["research"]["state"] == "not_started"
    assert by_key["script"]["state"] == "not_started"
    print("✅ test_fresh_video_next_step_is_research")


async def test_scripted_video_with_no_cast_next_step_is_characters():
    """The exact skipped-step scenario from the ruling: research+script+
    voice done, but no characters designed yet -> next_step must be
    "characters", not skip straight to storyboards/images."""
    video = _video_row(status="ready_for_image_prompts", research_payload={"x": 1})
    summary = _summary(scenes=3, voiced=3)
    p1, p2, p3 = _patch_all(video, summary=summary)
    with p1, p2, p3:
        guide = await production_guide.get_production_guide("t1", "v1")
    by_key = {s["key"]: s for s in guide["stages"]}
    assert by_key["research"]["state"] == "done"
    assert by_key["script"]["state"] == "done"
    assert by_key["voice"]["state"] == "done"
    assert by_key["characters"]["state"] == "not_started"
    assert guide["next_step"]["stage"] == "characters"
    print("✅ test_scripted_video_with_no_cast_next_step_is_characters")


async def test_cast_designed_but_not_approved_is_in_progress_with_gap():
    video = _video_row(status="ready_for_image_prompts", research_payload={"x": 1},
                        characters_approved_at=None)
    summary = _summary(scenes=2, voiced=2)
    cast_rows = [{"id": "c1", "name": "Ava", "reference_url": "https://x/ava.png"}]
    p1, p2, p3 = _patch_all(video, cast_rows=cast_rows, summary=summary)
    with p1, p2, p3:
        guide = await production_guide.get_production_guide("t1", "v1")
    by_key = {s["key"]: s for s in guide["stages"]}
    assert by_key["characters"]["state"] == "in_progress"
    assert any("approve" in g.lower() for g in by_key["characters"]["gaps"])
    assert guide["next_step"]["stage"] == "characters"
    assert guide["next_step"]["action"] == "wait"
    print("✅ test_cast_designed_but_not_approved_is_in_progress_with_gap")


async def test_environments_hard_gate_blocks_storyboards_when_not_designed():
    """pipeline_executor._environments_ready_gate HARD-blocks storyboard
    generation until environments are designed-or-skipped AND approved —
    the guide's next_step must route here BEFORE storyboards, once cast is
    approved."""
    video = _video_row(status="ready_for_storyboards", research_payload={"x": 1},
                        characters_approved_at="2026-07-01T00:00:00")
    summary = _summary(scenes=2, voiced=2)
    cast_rows = [{"id": "c1", "name": "Ava", "reference_url": "https://x/ava.png"}]
    p1, p2, p3 = _patch_all(video, cast_rows=cast_rows, summary=summary)
    with p1, p2, p3:
        guide = await production_guide.get_production_guide("t1", "v1")
    by_key = {s["key"]: s for s in guide["stages"]}
    assert by_key["characters"]["state"] == "done"
    assert by_key["environments"]["state"] == "not_started"
    assert any("BLOCKS" in g for g in by_key["environments"]["gaps"])
    assert guide["next_step"]["stage"] == "environments"
    print("✅ test_environments_hard_gate_blocks_storyboards_when_not_designed")


async def test_environments_explicitly_skipped_reads_done():
    video = _video_row(status="ready_for_storyboards", research_payload={"x": 1},
                        characters_approved_at="2026-07-01T00:00:00",
                        environments_approved_at="2026-07-01T00:00:00")
    summary = _summary(scenes=2, voiced=2, boards=2)
    cast_rows = [{"id": "c1", "name": "Ava", "reference_url": "https://x/ava.png"}]
    board_rows = [
        {"scene": 1, "storyboard_1_url": "https://x/1.png", "storyboard_2_url": None, "storyboard_3_url": None},
        {"scene": 2, "storyboard_1_url": "https://x/2.png", "storyboard_2_url": None, "storyboard_3_url": None},
    ]
    p1, p2, p3 = _patch_all(video, cast_rows=cast_rows, board_rows=board_rows, summary=summary)
    with p1, p2, p3:
        guide = await production_guide.get_production_guide("t1", "v1")
    by_key = {s["key"]: s for s in guide["stages"]}
    assert by_key["environments"]["state"] == "done"
    assert by_key["storyboards"]["state"] == "done"
    print("✅ test_environments_explicitly_skipped_reads_done")


async def test_missing_storyboard_scenes_are_named_in_the_gap():
    video = _video_row(status="ready_for_storyboards", research_payload={"x": 1},
                        characters_approved_at="2026-07-01T00:00:00",
                        environments_approved_at="2026-07-01T00:00:00")
    summary = _summary(scenes=3, voiced=3, boards=1)
    board_rows = [
        {"scene": 1, "storyboard_1_url": "https://x/1.png", "storyboard_2_url": None, "storyboard_3_url": None},
        {"scene": 2, "storyboard_1_url": None, "storyboard_2_url": None, "storyboard_3_url": None},
        {"scene": 3, "storyboard_1_url": None, "storyboard_2_url": None, "storyboard_3_url": None},
    ]
    p1, p2, p3 = _patch_all(video, board_rows=board_rows, summary=summary)
    with p1, p2, p3:
        guide = await production_guide.get_production_guide("t1", "v1")
    by_key = {s["key"]: s for s in guide["stages"]}
    assert by_key["storyboards"]["state"] == "in_progress"
    assert "2" in by_key["storyboards"]["gaps"][0] and "3" in by_key["storyboards"]["gaps"][0]
    print("✅ test_missing_storyboard_scenes_are_named_in_the_gap")


async def test_bible_cross_check_finds_undesigned_character():
    video = _video_row(status="ready_for_image_prompts", research_payload={"x": 1},
                        story_bible=json.dumps({"characters": [{"name": "Ava"}, {"name": "Rex"}]}))
    summary = _summary(scenes=2, voiced=2)
    cast_rows = [{"id": "c1", "name": "Ava", "reference_url": "https://x/ava.png"}]
    p1, p2, p3 = _patch_all(video, cast_rows=cast_rows, summary=summary)
    with p1, p2, p3:
        guide = await production_guide.get_production_guide("t1", "v1")
    by_key = {s["key"]: s for s in guide["stages"]}
    assert any("Rex" in g for g in by_key["characters"]["gaps"])
    print("✅ test_bible_cross_check_finds_undesigned_character")


async def test_bible_missing_reports_unavailable_not_computed():
    video = _video_row(status="ready_for_image_prompts", research_payload={"x": 1}, story_bible=None)
    summary = _summary(scenes=2, voiced=2)
    p1, p2, p3 = _patch_all(video, summary=summary)
    with p1, p2, p3:
        guide = await production_guide.get_production_guide("t1", "v1")
    by_key = {s["key"]: s for s in guide["stages"]}
    assert any("unavailable" in g.lower() for g in by_key["characters"]["gaps"])
    assert any("unavailable" in g.lower() for g in by_key["environments"]["gaps"])
    print("✅ test_bible_missing_reports_unavailable_not_computed")


async def test_active_background_task_reads_in_progress():
    video = _video_row(status="idea_logged")
    active_rows = [{"task_type": "research"}]
    p1, p2, p3 = _patch_all(video, active_rows=active_rows)
    with p1, p2, p3:
        guide = await production_guide.get_production_guide("t1", "v1")
    by_key = {s["key"]: s for s in guide["stages"]}
    assert by_key["research"]["state"] == "in_progress"
    assert guide["next_step"]["action"] == "wait"
    print("✅ test_active_background_task_reads_in_progress")


async def test_static_docu_video_skips_video_and_sound_by_format():
    """status_map.static_stage_plan drops video+sound for render_mode=
    'static_docu' — the guide must reflect that as skipped_by_format, not
    not_started, and next_step must never recommend them."""
    video = _video_row(status="ready_to_render", render_mode="static_docu",
                        research_payload={"x": 1},
                        characters_approved_at="2026-07-01T00:00:00",
                        environments_approved_at="2026-07-01T00:00:00")
    summary = _summary(scenes=2, voiced=2, boards=2, pics=2, clips=0)
    p1, p2, p3 = _patch_all(video, summary=summary)
    with p1, p2, p3:
        guide = await production_guide.get_production_guide("t1", "v1")
    assert guide["format"] == "static_docu"
    by_key = {s["key"]: s for s in guide["stages"]}
    assert by_key["video"]["state"] == "skipped_by_format"
    assert by_key["sound"]["state"] == "skipped_by_format"
    assert guide["next_step"]["stage"] != "video"
    assert guide["next_step"]["stage"] != "sound"
    print("✅ test_static_docu_video_skips_video_and_sound_by_format")


async def test_reduced_plan_marks_everything_outside_it_skipped_by_format():
    video = _video_row(status="idea_logged", pipeline_stages=["thumbnail"])
    p1, p2, p3 = _patch_all(video)
    with p1, p2, p3:
        guide = await production_guide.get_production_guide("t1", "v1")
    by_key = {s["key"]: s for s in guide["stages"]}
    assert by_key["research"]["state"] == "skipped_by_format"
    assert by_key["script"]["state"] == "skipped_by_format"
    assert by_key["characters"]["state"] == "skipped_by_format"
    assert by_key["render"]["state"] == "skipped_by_format"
    assert by_key["thumbnail"]["state"] != "skipped_by_format"
    assert guide["next_step"]["stage"] == "thumbnail"
    print("✅ test_reduced_plan_marks_everything_outside_it_skipped_by_format")


async def test_fully_done_video_celebrates():
    video = _video_row(status="done", research_payload={"x": 1}, skip_voice=True,
                        characters_approved_at="2026-07-01T00:00:00",
                        environments_approved_at="2026-07-01T00:00:00",
                        thumbnail_url="https://x/thumb.png",
                        youtube_url="https://youtube.com/watch?v=abc")
    summary = _summary(scenes=2, voiced=0, boards=2, pics=2, clips=2)
    cast_rows = [{"id": "c1", "name": "Ava", "reference_url": "https://x/ava.png"}]
    board_rows = [
        {"scene": 1, "storyboard_1_url": "https://x/1.png", "storyboard_2_url": None, "storyboard_3_url": None},
        {"scene": 2, "storyboard_1_url": "https://x/2.png", "storyboard_2_url": None, "storyboard_3_url": None},
    ]
    p1, p2, p3 = _patch_all(video, cast_rows=cast_rows, board_rows=board_rows, summary=summary)
    with p1, p2, p3:
        guide = await production_guide.get_production_guide("t1", "v1")
    assert guide["next_step"] == {
        "stage": "done", "action": "celebrate",
        "reason": "Every stage in this video's plan is done.",
    }
    print("✅ test_fully_done_video_celebrates")


# =============================================================================
# 4. get_production_guide MCP tool wrapper
# =============================================================================

async def test_get_production_guide_tool_requires_video_id():
    result = await mcp_mod._call_get_production_guide("t1", {})
    assert result["isError"] is True
    print("✅ test_get_production_guide_tool_requires_video_id")


async def test_get_production_guide_tool_tenant_scoped():
    with patch.object(production_guide, "get_production_guide", AsyncMock(return_value=None)):
        result = await mcp_mod._call_get_production_guide("tenant-other", {"video_id": "v1"})
    assert result["isError"] is True
    print("✅ test_get_production_guide_tool_tenant_scoped")


async def test_get_production_guide_tool_wraps_the_real_function():
    fake_guide = {"video_id": "v1", "stages": [], "next_step": {"stage": "done", "action": "celebrate", "reason": "x"}}
    with patch.object(production_guide, "get_production_guide", AsyncMock(return_value=fake_guide)) as mocked:
        result = await mcp_mod._call_get_production_guide("t1", {"video_id": "v1"})
    mocked.assert_awaited_once_with("t1", "v1")
    payload = json.loads(result["content"][0]["text"])
    assert payload == fake_guide
    print("✅ test_get_production_guide_tool_wraps_the_real_function")


# =============================================================================
# 5. Environments tool family
# =============================================================================

async def test_design_environments_quote_scales_with_existing_count_then_confirms_real_route():
    import routes.environments as environments_route

    async def _fake_fetch_one(query, *args):
        assert "count(*)" in query
        return {"n": 3}

    call_args = {}

    async def _fake_design(video_id, background_tasks, tenant_id):
        call_args["video_id"] = video_id
        call_args["tenant_id"] = tenant_id
        return {"status": "running", "message": "Designing…"}

    store = _FakeConfirmStore()
    bg = _FakeBackgroundTasks()
    with patch.object(mcp_mod, "fetch_one", _fake_fetch_one), \
         _patch_confirm(store), \
         patch.object(environments_route, "design_environments", _fake_design):
        quote = await mcp_mod._call_design_environments("t1", {"video_id": "v1"}, bg, "agent")
        payload = json.loads(quote["content"][0]["text"])
        assert payload["status"] == "quote"
        assert payload["cost"] == round(3 * actions.PICTURE_COST, 2)
        token = payload["confirm_token"]

        confirmed = await mcp_mod._call_design_environments(
            "t1", {"video_id": "v1", "confirm_token": token}, bg, "agent")
    assert confirmed["isError"] is False
    assert call_args == {"video_id": "v1", "tenant_id": "t1"}
    print("✅ test_design_environments_quote_scales_with_existing_count_then_confirms_real_route")


async def test_design_environments_defaults_to_four_when_none_designed_yet():
    async def _fake_fetch_one(query, *args):
        return {"n": 0}

    with patch.object(mcp_mod, "fetch_one", _fake_fetch_one), \
         patch.object(confirm_tokens, "create", AsyncMock(return_value="mcpc_faketoken")):
        result = await mcp_mod._call_design_environments("t1", {"video_id": "v1"}, _FakeBackgroundTasks(), "agent")
    payload = json.loads(result["content"][0]["text"])
    assert payload["cost"] == round(4 * actions.PICTURE_COST, 2)
    print("✅ test_design_environments_defaults_to_four_when_none_designed_yet")


async def test_redo_environment_refuses_before_any_quote_when_not_owned():
    async def _fake_fetch_one(query, *args):
        return None

    with patch.object(mcp_mod, "fetch_one", _fake_fetch_one), \
         patch.object(confirm_tokens, "create", AsyncMock(side_effect=AssertionError("must not quote an unowned environment"))):
        result = await mcp_mod._call_redo_environment(
            "t1", {"video_id": "v1", "env_id": "not-mine"}, _FakeBackgroundTasks(), "agent")
    assert result["isError"] is True
    print("✅ test_redo_environment_refuses_before_any_quote_when_not_owned")


async def test_redo_environment_quote_then_confirm_dispatches_same_route_function():
    import routes.environments as environments_route

    async def _fake_fetch_one(query, *args):
        return {"id": "e1"}

    call_args = {}

    async def _fake_regenerate(video_id, env_id, background_tasks, tenant_id):
        call_args["video_id"] = video_id
        call_args["env_id"] = env_id
        return {"status": "running", "message": "Redesigning Kitchen…"}

    store = _FakeConfirmStore()
    bg = _FakeBackgroundTasks()
    with patch.object(mcp_mod, "fetch_one", _fake_fetch_one), \
         _patch_confirm(store), \
         patch.object(environments_route, "regenerate_environment", _fake_regenerate):
        quote = await mcp_mod._call_redo_environment("t1", {"video_id": "v1", "env_id": "e1"}, bg, "agent")
        payload = json.loads(quote["content"][0]["text"])
        assert payload["cost"] == actions.PICTURE_COST
        token = payload["confirm_token"]

        confirmed = await mcp_mod._call_redo_environment(
            "t1", {"video_id": "v1", "env_id": "e1", "confirm_token": token}, bg, "agent")
    assert confirmed["isError"] is False
    assert call_args == {"video_id": "v1", "env_id": "e1"}
    print("✅ test_redo_environment_quote_then_confirm_dispatches_same_route_function")


async def test_redo_environment_confirm_bound_to_the_quoted_env_only():
    async def _fake_fetch_one(query, *args):
        return {"id": "either"}

    store = _FakeConfirmStore()
    with patch.object(mcp_mod, "fetch_one", _fake_fetch_one), _patch_confirm(store):
        quote = await mcp_mod._call_redo_environment(
            "t1", {"video_id": "v1", "env_id": "e1"}, _FakeBackgroundTasks(), "agent")
        token = json.loads(quote["content"][0]["text"])["confirm_token"]
        confirmed = await mcp_mod._call_redo_environment(
            "t1", {"video_id": "v1", "env_id": "e2", "confirm_token": token}, _FakeBackgroundTasks(), "agent")
    assert confirmed["isError"] is True
    print("✅ test_redo_environment_confirm_bound_to_the_quoted_env_only")


async def test_edit_environment_calls_real_route():
    import routes.environments as environments_route
    call_args = {}

    async def _fake_update(video_id, env_id, body, tenant_id):
        call_args["env_id"] = env_id
        call_args["name"] = body.name
        return {"id": env_id, "name": body.name}

    with patch.object(environments_route, "update_environment", _fake_update):
        result = await mcp_mod._call_edit_environment(
            "t1", {"video_id": "v1", "env_id": "e1", "name": "Kitchen"}, "agent")
    assert call_args == {"env_id": "e1", "name": "Kitchen"}
    assert result["isError"] is False
    print("✅ test_edit_environment_calls_real_route")


async def test_delete_environment_calls_real_route():
    import routes.environments as environments_route
    call_args = {}

    async def _fake_delete(video_id, env_id, tenant_id):
        call_args["video_id"] = video_id
        call_args["env_id"] = env_id
        return {"status": "deleted"}

    with patch.object(environments_route, "delete_environment", _fake_delete):
        result = await mcp_mod._call_delete_environment("t1", {"video_id": "v1", "env_id": "e1"}, "agent")
    assert call_args == {"video_id": "v1", "env_id": "e1"}
    assert result["isError"] is False
    print("✅ test_delete_environment_calls_real_route")
