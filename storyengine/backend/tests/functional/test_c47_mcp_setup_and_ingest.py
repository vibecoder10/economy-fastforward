"""Tests for C47 (checklist — MCP setup surface + content-ingest surface,
decisions.md 2026-07-19's "MCP is the setup brain" + "MCP economics"
entries).

Covers:
  1. Tool surface: every new setup/ingest tool name is present in
     mcp.TOOL_NAMES; script_profile/budget_cap are NOT duplicated as
     set_script_profile/set_budget_cap (they already exist as free verb
     tools generated from actions.ACTIONS); S5-2's remember/forget exclusion
     still holds against the LARGER v3 tool set; no setup/ingest tool
     carries a confirm_token (all free).
  2. "Same callable" proof for every setup tool: patches the REAL underlying
     module/route function each MCP handler wraps and asserts it — not a
     parallel MCP-local implementation — was invoked with the tenant-scoped
     arguments (mirrors test_c27_mcp_toolset_money_gate.py's
     "test_paid_verb_confirmed_call_dispatches_same_runner_as_chat" pattern).
  3. Attribution: upsert_quality_rule stamps source="mcp_agent" (a real
     quality_rules.SOURCES value, not silently dropped by create_rule's own
     allowlist fallback); confirm_channel_pattern/retire_channel_pattern
     pass the calling agent's name into the REAL confirmed_by column.
  4. submit_script accept/reject matrix through the REAL
     user_script.accept_external_script gate (patched at the module-function
     level so mcp.py's lazy import picks it up), proving mcp.py doesn't
     reimplement the critic/rule logic itself.
  5. submit_research: shape validation (bad list/dict-typed fields raise with
     a concrete field name, before any DB write), the roster gate reusing
     pipeline_executor._roster_validation verbatim, and the honest
     save+advance path on a pass.
  6. learn_channel_start/status: same-callable proof + the busy-claim state
     surfaces through unchanged (not reinterpreted/hidden by the MCP layer).
  7. No media URLs: get_channel_dna passes `channel_dna._current_identity`'s
     result through byte-identical (no accidental leak of a field that
     wasn't there, no accidental stripping of one that should have been) —
     the C25a "no media URL" guarantee here is structural to
     channel_identity's own shape (channel_dna_meta.py's docstring), proven
     by round-tripping a representative fixture.

No live DB, no network, no paid calls — every DB boundary is patched
directly (matches test_c27_mcp_toolset_money_gate.py / test_c46d_trust_
boundaries.py conventions). Run:
  cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c47_mcp_setup_and_ingest.py -q
"""
from __future__ import annotations

import json
import os
import sys
import types
from unittest.mock import AsyncMock, patch

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _BACKEND)

import actions  # noqa: E402
import channel_patterns  # noqa: E402
import quality_rules  # noqa: E402
import research_ingest  # noqa: E402
import routes.mcp as mcp_mod  # noqa: E402
import user_script  # noqa: E402


class _FakeBackgroundTasks:
    def __init__(self):
        self.calls = []

    def add_task(self, fn, *a, **k):
        self.calls.append((fn, a, k))


# =============================================================================
# 1. Tool surface
# =============================================================================

_NEW_SETUP_TOOLS = [
    "get_channel_dna", "learn_channel_start", "learn_channel_status",
    "list_quality_rules", "upsert_quality_rule", "deactivate_quality_rule",
    "list_channel_patterns", "confirm_channel_pattern", "retire_channel_pattern",
    "get_script_template", "set_script_template", "list_script_profiles",
    "get_system_prompts", "set_system_prompt", "set_render_style", "set_style_preset",
]
_NEW_INGEST_TOOLS = ["submit_research", "submit_script"]


def test_all_new_tools_present():
    names = mcp_mod.TOOL_NAMES
    missing = [t for t in _NEW_SETUP_TOOLS + _NEW_INGEST_TOOLS if t not in names]
    assert not missing, f"missing C47 tools: {missing}"
    print("✅ test_all_new_tools_present")


def test_script_profile_and_budget_cap_not_duplicated():
    """These are 'existing verbs/columns' per the checklist — already free
    verb tools from actions.ACTIONS. C47 must not add a second tool for the
    same write path under a 'set_' alias."""
    assert "script_profile" in mcp_mod.TOOL_NAMES
    assert "budget_cap" in mcp_mod.TOOL_NAMES
    assert "set_script_profile" not in mcp_mod.TOOL_NAMES
    assert "set_budget_cap" not in mcp_mod.TOOL_NAMES
    print("✅ test_script_profile_and_budget_cap_not_duplicated")


def test_s5_2_memory_tools_never_appear_in_v3_surface():
    for verb in ("remember", "forget", "set_budget"):
        assert verb not in mcp_mod.TOOL_NAMES, f"{verb!r} must never be an MCP tool (S5-2)"
    print("✅ test_s5_2_memory_tools_never_appear_in_v3_surface")


def test_no_setup_or_ingest_tool_carries_confirm_token():
    by_name = {t["name"]: t for t in mcp_mod.TOOLS}
    for name in _NEW_SETUP_TOOLS + _NEW_INGEST_TOOLS:
        props = by_name[name]["inputSchema"]["properties"]
        assert "confirm_token" not in props, f"{name!r} is free — must not expose confirm_token"
    print("✅ test_no_setup_or_ingest_tool_carries_confirm_token")


def test_learn_channel_start_description_states_its_real_cost():
    tool = next(t for t in mcp_mod.TOOLS if t["name"] == "learn_channel_start")
    assert "$0.10" in tool["description"] or "0.10-0.30" in tool["description"]
    print("✅ test_learn_channel_start_description_states_its_real_cost")


# =============================================================================
# 2. Same-callable proofs — setup tools
# =============================================================================

async def test_get_channel_dna_calls_current_identity_and_round_trips():
    fake_identity = {
        "voice": "deadpan analyst", "hooks": ["cold open with a number"],
        "_sources": {"voice": {"learner": "identity_builder", "at": "2026-01-01T00:00:00Z", "confidence": 0.8}},
        "_history": [], "_last_run": {"ok": True, "learners": {}},
    }
    fake_mod = types.ModuleType("channel_dna")
    fake_mod._current_identity = AsyncMock(return_value=fake_identity)
    with patch.dict(sys.modules, {"channel_dna": fake_mod}):
        result = await mcp_mod._call_get_channel_dna("t1", {}, "agent")
    fake_mod._current_identity.assert_awaited_once_with("t1")
    payload = json.loads(result["content"][0]["text"])
    assert payload == fake_identity, "must pass the identity through byte-identical, no silent stripping/adding"
    print("✅ test_get_channel_dna_calls_current_identity_and_round_trips")


async def test_learn_channel_start_calls_same_route_function_and_surfaces_busy():
    """Same-callable proof (patches the REAL routes.channel_dna.start_learn_
    channel, not an mcp-local copy) AND proves the busy-claim state (checklist
    V's 'busy-claim surfaced') passes through unreinterpreted."""
    import routes.channel_dna as channel_dna_route

    class _FakeResponse:
        def model_dump(self):
            return {"started": False, "busy": True, "message": "Already learning this channel's DNA — check GET /status in a moment."}

    call_args = {}

    async def _fake_start(body, background_tasks, tenant_id):
        call_args["body"] = body
        call_args["tenant_id"] = tenant_id
        return _FakeResponse()

    with patch.object(channel_dna_route, "start_learn_channel", _fake_start):
        result = await mcp_mod._call_learn_channel_start(
            "t1", {"channel_url": "https://youtube.com/@x"}, "agent:Bot", _FakeBackgroundTasks(),
        )
    assert call_args["tenant_id"] == "t1"
    assert call_args["body"].channel_url == "https://youtube.com/@x"
    payload = json.loads(result["content"][0]["text"])
    assert payload["busy"] is True
    assert payload["started"] is False
    print("✅ test_learn_channel_start_calls_same_route_function_and_surfaces_busy")


async def test_learn_channel_status_calls_same_route_function():
    import routes.channel_dna as channel_dna_route

    class _FakeStatus:
        def model_dump(self):
            return {"learning": False, "ok": True, "at": "2026-01-01T00:00:00Z", "learners": {}, "identity": {}}

    seen_tenant = {}

    async def _fake_status(tenant_id):
        seen_tenant["v"] = tenant_id
        return _FakeStatus()

    with patch.object(channel_dna_route, "get_learn_channel_status", _fake_status):
        result = await mcp_mod._call_learn_channel_status("t1", {}, "agent")
    assert seen_tenant["v"] == "t1"
    payload = json.loads(result["content"][0]["text"])
    assert payload["ok"] is True
    print("✅ test_learn_channel_status_calls_same_route_function")


async def test_upsert_quality_rule_calls_create_rule_with_mcp_agent_source():
    create_mock = AsyncMock(return_value={"id": "r1", "rule_id": "QL-99", "law": "Never do X."})
    with patch.object(quality_rules, "create_rule", create_mock):
        result = await mcp_mod._call_upsert_quality_rule(
            "t1", {"rule_id": "QL-99", "law": "Never do X.", "severity": "hard_gate"}, "agent:Bot",
        )
    create_mock.assert_awaited_once_with(
        "t1", rule_id="QL-99", law="Never do X.", severity="hard_gate",
        evidence=None, applies_to=None, source="mcp_agent",
    )
    assert "mcp_agent" in quality_rules.SOURCES, "source value must be a real accepted SOURCES member, not silently dropped"
    assert result["isError"] is False
    print("✅ test_upsert_quality_rule_calls_create_rule_with_mcp_agent_source")


async def test_upsert_quality_rule_rejects_bad_severity_before_any_write():
    create_mock = AsyncMock(side_effect=AssertionError("must not write on bad severity"))
    with patch.object(quality_rules, "create_rule", create_mock):
        result = await mcp_mod._call_upsert_quality_rule(
            "t1", {"rule_id": "QL-1", "law": "x", "severity": "nonsense"}, "agent",
        )
    assert result["isError"] is True
    print("✅ test_upsert_quality_rule_rejects_bad_severity_before_any_write")


async def test_deactivate_quality_rule_calls_deactivate_rule():
    deact_mock = AsyncMock(return_value=True)
    with patch.object(quality_rules, "deactivate_rule", deact_mock):
        result = await mcp_mod._call_deactivate_quality_rule("t1", {"id": "r1"}, "agent")
    deact_mock.assert_awaited_once_with("t1", "r1")
    assert result["isError"] is False
    print("✅ test_deactivate_quality_rule_calls_deactivate_rule")


async def test_list_quality_rules_calls_list_all_rules_tenant_scoped():
    list_mock = AsyncMock(return_value=[{"id": "r1"}])
    with patch.object(quality_rules, "list_all_rules", list_mock):
        result = await mcp_mod._call_list_quality_rules("t1", {"active_only": True}, "agent")
    list_mock.assert_awaited_once_with("t1", active_only=True)
    payload = json.loads(result["content"][0]["text"])
    assert payload["rules"] == [{"id": "r1"}]
    print("✅ test_list_quality_rules_calls_list_all_rules_tenant_scoped")


async def test_confirm_channel_pattern_attributes_to_the_calling_agent():
    """OR-6's human-confirm gate: an agent calling this on behalf of its
    owner is attributed via the REAL confirmed_by column, not silently
    anonymous."""
    confirm_mock = AsyncMock(return_value={"id": "p1", "status": "confirmed"})
    with patch.object(channel_patterns, "confirm_pattern", confirm_mock):
        result = await mcp_mod._call_confirm_channel_pattern("t1", {"id": "p1"}, "agent:Claude Desktop")
    confirm_mock.assert_awaited_once_with("t1", "p1", confirmed_by="agent:Claude Desktop")
    assert result["isError"] is False
    print("✅ test_confirm_channel_pattern_attributes_to_the_calling_agent")


async def test_retire_channel_pattern_attributes_to_the_calling_agent():
    retire_mock = AsyncMock(return_value={"id": "p1", "status": "retired"})
    with patch.object(channel_patterns, "retire_pattern", retire_mock):
        result = await mcp_mod._call_retire_channel_pattern("t1", {"id": "p1"}, "agent:Bot")
    retire_mock.assert_awaited_once_with("t1", "p1", confirmed_by="agent:Bot")
    assert result["isError"] is False
    print("✅ test_retire_channel_pattern_attributes_to_the_calling_agent")


async def test_confirm_channel_pattern_missing_id_errors_without_a_call():
    retire_mock = AsyncMock(side_effect=AssertionError("must not call without an id"))
    with patch.object(channel_patterns, "confirm_pattern", retire_mock):
        result = await mcp_mod._call_confirm_channel_pattern("t1", {}, "agent")
    assert result["isError"] is True
    print("✅ test_confirm_channel_pattern_missing_id_errors_without_a_call")


async def test_list_channel_patterns_calls_list_patterns_with_filters():
    list_mock = AsyncMock(return_value=[{"id": "p1", "polarity": "anti"}])
    with patch.object(channel_patterns, "list_patterns", list_mock):
        result = await mcp_mod._call_list_channel_patterns("t1", {"polarity": "anti", "status": "confirmed"}, "agent")
    list_mock.assert_awaited_once_with("t1", polarity="anti", status="confirmed")
    payload = json.loads(result["content"][0]["text"])
    assert payload["patterns"] == [{"id": "p1", "polarity": "anti"}]
    print("✅ test_list_channel_patterns_calls_list_patterns_with_filters")


async def test_set_script_template_reports_replaced_when_one_already_existed():
    import routes.script_templates as script_templates_mod

    async def _fake_fetch_one(query, *args):
        assert "script_templates" in query
        return {"id": "existing-tpl"}  # a template already exists

    analyze_mock = AsyncMock(return_value={"id": "existing-tpl", "name": "House format", "structure": "..."})
    with patch.object(mcp_mod, "fetch_one", _fake_fetch_one), \
         patch.object(script_templates_mod, "analyze_and_save_template", analyze_mock):
        result = await mcp_mod._call_set_script_template("t1", {"text": "a" * 200}, "agent")
    analyze_mock.assert_awaited_once_with("t1", "a" * 200, "")
    payload = json.loads(result["content"][0]["text"])
    assert payload["status"] == "replaced"
    print("✅ test_set_script_template_reports_replaced_when_one_already_existed")


async def test_set_script_template_reports_saved_when_none_existed():
    import routes.script_templates as script_templates_mod

    async def _fake_fetch_one(query, *args):
        return None  # no existing template

    analyze_mock = AsyncMock(return_value={"id": "new-tpl", "name": "House format", "structure": "..."})
    with patch.object(mcp_mod, "fetch_one", _fake_fetch_one), \
         patch.object(script_templates_mod, "analyze_and_save_template", analyze_mock):
        result = await mcp_mod._call_set_script_template("t1", {"text": "b" * 200, "name": "My format"}, "agent")
    payload = json.loads(result["content"][0]["text"])
    assert payload["status"] == "saved"
    print("✅ test_set_script_template_reports_saved_when_none_existed")


async def test_get_script_template_calls_same_route_function():
    import routes.script_templates as script_templates_mod

    seen = {}

    async def _fake_list(tenant_id):
        seen["v"] = tenant_id
        return {"templates": [{"id": "t1"}]}

    with patch.object(script_templates_mod, "list_templates", _fake_list):
        result = await mcp_mod._call_get_script_template("t1", {}, "agent")
    assert seen["v"] == "t1"
    payload = json.loads(result["content"][0]["text"])
    assert payload["templates"] == [{"id": "t1"}]
    print("✅ test_get_script_template_calls_same_route_function")


async def test_list_script_profiles_calls_same_route_function():
    import routes.script_profiles as script_profiles_mod

    class _FakeProfiles:
        def model_dump(self):
            return {"profiles": [{"id": "neutral_v1", "display_name": "Neutral"}]}

    seen = {}

    async def _fake_list(tenant_id):
        seen["v"] = tenant_id
        return _FakeProfiles()

    with patch.object(script_profiles_mod, "list_script_profiles", _fake_list):
        result = await mcp_mod._call_list_script_profiles("t1", {}, "agent")
    assert seen["v"] == "t1"
    payload = json.loads(result["content"][0]["text"])
    assert payload["profiles"][0]["id"] == "neutral_v1"
    print("✅ test_list_script_profiles_calls_same_route_function")


async def test_get_system_prompts_calls_same_route_function():
    import routes.system_prompts as system_prompts_mod

    seen = {}

    async def _fake_list(tenant_id):
        seen["v"] = tenant_id
        return [{"key": "script", "prompt": "...", "is_custom": False}]

    with patch.object(system_prompts_mod, "list_prompts", _fake_list):
        result = await mcp_mod._call_get_system_prompts("t1", {}, "agent")
    assert seen["v"] == "t1"
    payload = json.loads(result["content"][0]["text"])
    assert payload["prompts"][0]["key"] == "script"
    print("✅ test_get_system_prompts_calls_same_route_function")


async def test_set_system_prompt_calls_same_route_function():
    import routes.system_prompts as system_prompts_mod

    call_args = {}

    async def _fake_upsert(key, body, tenant_id):
        call_args["key"] = key
        call_args["prompt_text"] = body.prompt_text
        call_args["tenant_id"] = tenant_id
        return {"status": "saved", "key": key}

    with patch.object(system_prompts_mod, "upsert_prompt", _fake_upsert):
        result = await mcp_mod._call_set_system_prompt("t1", {"key": "script", "prompt_text": "Be punchy."}, "agent")
    assert call_args == {"key": "script", "prompt_text": "Be punchy.", "tenant_id": "t1"}
    assert result["isError"] is False
    print("✅ test_set_system_prompt_calls_same_route_function")


async def test_set_system_prompt_unknown_key_surfaces_route_error():
    import routes.system_prompts as system_prompts_mod
    from fastapi import HTTPException

    async def _fake_upsert(key, body, tenant_id):
        raise HTTPException(status_code=404, detail=f"Unknown prompt key: {key}")

    with patch.object(system_prompts_mod, "upsert_prompt", _fake_upsert):
        result = await mcp_mod._call_set_system_prompt("t1", {"key": "bogus", "prompt_text": "x"}, "agent")
    assert result["isError"] is True
    assert "Unknown prompt key" in result["content"][0]["text"]
    print("✅ test_set_system_prompt_unknown_key_surfaces_route_error")


async def test_set_render_style_calls_update_video_route():
    import routes.videos as videos_mod

    call_args = {}

    async def _fake_update(video_id, body, tenant_id):
        call_args["video_id"] = video_id
        call_args["body"] = body
        call_args["tenant_id"] = tenant_id
        return {"status": "updated", "video_id": video_id}

    with patch.object(videos_mod, "update_video", _fake_update):
        result = await mcp_mod._call_set_render_style("t1", {"video_id": "v1", "render_style": "animated"}, "agent")
    assert call_args == {"video_id": "v1", "body": {"render_style": "animated"}, "tenant_id": "t1"}
    assert result["isError"] is False
    print("✅ test_set_render_style_calls_update_video_route")


async def test_set_render_style_auto_clears_to_none():
    import routes.videos as videos_mod

    call_args = {}

    async def _fake_update(video_id, body, tenant_id):
        call_args["body"] = body
        return {"status": "updated", "video_id": video_id}

    with patch.object(videos_mod, "update_video", _fake_update):
        await mcp_mod._call_set_render_style("t1", {"video_id": "v1", "render_style": "auto"}, "agent")
    assert call_args["body"] == {"render_style": None}
    print("✅ test_set_render_style_auto_clears_to_none")


async def test_set_render_style_invalid_value_surfaces_route_error():
    import routes.videos as videos_mod
    from fastapi import HTTPException

    async def _fake_update(video_id, body, tenant_id):
        raise HTTPException(status_code=400, detail="Invalid render_style")

    with patch.object(videos_mod, "update_video", _fake_update):
        result = await mcp_mod._call_set_render_style("t1", {"video_id": "v1", "render_style": "bogus"}, "agent")
    assert result["isError"] is True
    print("✅ test_set_render_style_invalid_value_surfaces_route_error")


async def test_set_style_preset_calls_update_video_route():
    import routes.videos as videos_mod

    call_args = {}

    async def _fake_update(video_id, body, tenant_id):
        call_args["body"] = body
        return {"status": "updated", "video_id": video_id}

    with patch.object(videos_mod, "update_video", _fake_update):
        result = await mcp_mod._call_set_style_preset("t1", {"video_id": "v1", "style_preset_id": "cinematic_dossier"}, "agent")
    assert call_args["body"] == {"style_preset_id": "cinematic_dossier"}
    assert result["isError"] is False
    print("✅ test_set_style_preset_calls_update_video_route")


def test_style_preset_id_is_settable_after_creation_via_generic_update():
    """The gap this chunk fixed: style_preset_id previously had NO write path
    after video creation at all. Pin it directly against the route's own
    allowlist so a future refactor can't silently drop it again."""
    import inspect
    import routes.videos as videos_mod

    src = inspect.getsource(videos_mod.update_video)
    assert '"style_preset_id"' in src, "style_preset_id must be in update_video's allowed_fields"
    assert "_resolve_style_preset_id(body.get(\"style_preset_id\"))" in src
    print("✅ test_style_preset_id_is_settable_after_creation_via_generic_update")


# =============================================================================
# 3. submit_script — thin wrapper over the REAL accept_external_script
# =============================================================================

def _scenes(*texts):
    return [{"text": t} for t in texts]


async def test_submit_script_accept_path_calls_real_accept_external_script():
    accept_mock = AsyncMock(return_value={
        "accepted": True, "verdict": "pass", "violations": [], "warnings": [],
        "scenes": 2, "status": "ready_for_voice",
    })
    with patch.object(user_script, "accept_external_script", accept_mock):
        result = await mcp_mod._call_submit_script(
            "t1", {"video_id": "v1", "scenes": _scenes("Scene one.", "Scene two.")}, "agent:Bot",
        )
    accept_mock.assert_awaited_once_with("t1", "v1", _scenes("Scene one.", "Scene two."), source="agent_submitted")
    payload = json.loads(result["content"][0]["text"])
    assert payload["accepted"] is True
    assert payload["status"] == "ready_for_voice"
    print("✅ test_submit_script_accept_path_calls_real_accept_external_script")


async def test_submit_script_reject_path_surfaces_rule_by_rule_violations():
    accept_mock = AsyncMock(return_value={
        "accepted": False, "verdict": "revise",
        "violations": ["QL-2"], "rule_verdicts": [{"rule": "QL-2", "passed": False}],
    })
    with patch.object(user_script, "accept_external_script", accept_mock):
        result = await mcp_mod._call_submit_script("t1", {"video_id": "v1", "scenes": _scenes("Weak.")}, "agent")
    payload = json.loads(result["content"][0]["text"])
    assert payload["accepted"] is False
    assert payload["violations"] == ["QL-2"]
    print("✅ test_submit_script_reject_path_surfaces_rule_by_rule_violations")


async def test_submit_script_bad_shape_returns_error_not_a_500():
    async def _boom(*a, **k):
        raise ValueError("scene 1 has no non-empty 'text'")

    with patch.object(user_script, "accept_external_script", _boom):
        result = await mcp_mod._call_submit_script("t1", {"video_id": "v1", "scenes": [{"text": ""}]}, "agent")
    assert result["isError"] is True
    assert "non-empty" in result["content"][0]["text"]
    print("✅ test_submit_script_bad_shape_returns_error_not_a_500")


async def test_submit_script_missing_video_id_errors_without_a_call():
    accept_mock = AsyncMock(side_effect=AssertionError("must not call without a video_id"))
    with patch.object(user_script, "accept_external_script", accept_mock):
        result = await mcp_mod._call_submit_script("t1", {"scenes": _scenes("x")}, "agent")
    assert result["isError"] is True
    print("✅ test_submit_script_missing_video_id_errors_without_a_call")


# =============================================================================
# 4. submit_research — shape validation, roster gate reuse, save+advance
# =============================================================================

def test_research_shape_rejects_non_list_unit_roster():
    try:
        research_ingest._validate_research_shape({"unit_roster": "not a list"})
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "unit_roster" in str(e)
    print("✅ test_research_shape_rejects_non_list_unit_roster")


def test_research_shape_rejects_non_dict_roster_audit():
    try:
        research_ingest._validate_research_shape({"roster_audit": ["not", "a", "dict"]})
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "roster_audit" in str(e)
    print("✅ test_research_shape_rejects_non_dict_roster_audit")


def test_research_shape_rejects_empty_payload():
    try:
        research_ingest._validate_research_shape({})
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
    print("✅ test_research_shape_rejects_empty_payload")


def test_research_shape_accepts_minimal_non_roster_payload():
    research_ingest._validate_research_shape({"headline": "X", "thesis": "Y"})
    print("✅ test_research_shape_accepts_minimal_non_roster_payload")


async def test_accept_submitted_research_missing_video_raises():
    async def _fake_fetch_one(query, *args):
        return None

    with patch.object(research_ingest, "fetch_one", _fake_fetch_one):
        try:
            await research_ingest.accept_submitted_research("t1", "v1", {"headline": "X"})
            raise AssertionError("expected ValueError")
        except ValueError as e:
            assert "not found" in str(e).lower()
    print("✅ test_accept_submitted_research_missing_video_raises")


async def test_accept_submitted_research_roster_gate_rejects_incomplete_roster():
    import pipeline_executor

    video = {"id": "v1", "tenant_id": "t1", "video_title": "Every B-52 Variant Ever Built",
             "video_length_minutes": 20, "deleted_at": None}

    async def _fake_fetch_one(query, *args):
        return dict(video)

    fake_roster_check = {
        "passed": False, "complete_title": True, "warnings": ["only 2 roster items"],
        "gaps": ["designation/number sequence gaps"],
    }
    with patch.object(research_ingest, "fetch_one", _fake_fetch_one), \
         patch.object(pipeline_executor, "_roster_validation", lambda *a, **k: fake_roster_check):
        result = await research_ingest.accept_submitted_research(
            "t1", "v1", {"unit_roster": ["B-52A"]}, source="agent:Bot",
        )
    assert result["accepted"] is False
    assert result["reason"] == "roster_gate_failed"
    assert result["warnings"] == ["only 2 roster items"]
    print("✅ test_accept_submitted_research_roster_gate_rejects_incomplete_roster")


async def test_accept_submitted_research_saves_and_advances_on_pass():
    import pipeline_executor

    video = {"id": "v1", "tenant_id": "t1", "video_title": "A Normal Video Title",
             "video_length_minutes": 10, "deleted_at": None}
    writes = []

    async def _fake_fetch_one(query, *args):
        return dict(video)

    async def _fake_execute(query, *args):
        writes.append((query, args))
        return "UPDATE 1"

    fake_roster_check = {"passed": True, "complete_title": False, "warnings": [], "gaps": []}
    with patch.object(research_ingest, "fetch_one", _fake_fetch_one), \
         patch.object(research_ingest, "execute", _fake_execute), \
         patch.object(pipeline_executor, "_roster_validation", lambda *a, **k: fake_roster_check):
        result = await research_ingest.accept_submitted_research(
            "t1", "v1", {"headline": "H", "thesis": "T", "executive_hook": "E"}, source="agent:Bot",
        )
    assert result["accepted"] is True
    assert result["status"] == "ready_for_scripting"
    assert result["headline"] == "H"
    save_write = next(w for w in writes if w[0].strip().startswith("UPDATE videos SET"))
    payload_json, thesis_arg, hook_arg, status_arg, video_id_arg, tenant_arg = save_write[1]
    saved_payload = json.loads(payload_json)
    assert saved_payload["headline"] == "H"
    assert "unit_roster_validation" in saved_payload
    assert thesis_arg == "T"
    assert hook_arg == "E"
    assert status_arg == "ready_for_scripting"
    assert video_id_arg == "v1" and tenant_arg == "t1"
    print("✅ test_accept_submitted_research_saves_and_advances_on_pass")


async def test_call_submit_research_bad_shape_returns_error_not_exception():
    async def _fake_fetch_one(query, *args):
        return {"id": "v1", "tenant_id": "t1", "video_title": "T", "deleted_at": None}

    with patch.object(research_ingest, "fetch_one", _fake_fetch_one):
        result = await mcp_mod._call_submit_research(
            "t1", {"video_id": "v1", "payload": {"unit_roster": "nope"}}, "agent",
        )
    assert result["isError"] is True
    assert "unit_roster" in result["content"][0]["text"]
    print("✅ test_call_submit_research_bad_shape_returns_error_not_exception")


async def test_call_submit_research_missing_video_id_errors_without_a_call():
    result = await mcp_mod._call_submit_research("t1", {"payload": {"headline": "H"}}, "agent")
    assert result["isError"] is True
    print("✅ test_call_submit_research_missing_video_id_errors_without_a_call")


# =============================================================================
# 5. No media URLs (C25a hold) — grep-style + structural round-trip
# =============================================================================

def test_new_tool_descriptions_and_schemas_never_reference_media_urls():
    # NOT "video_url" as a bare term — reference_video_url is a legitimate
    # user-INPUT parameter (a YouTube link to style-model from), not a
    # generated-media-asset OUTPUT field like the ones actually named below
    # (get_video/list_style_presets strip exactly these — see module docstring).
    banned = ("preview_url", "thumbnail_url", "image_url", "video_clip_url")
    for tool in mcp_mod.TOOLS:
        if tool["name"] not in (_NEW_SETUP_TOOLS + _NEW_INGEST_TOOLS):
            continue
        blob = json.dumps(tool)
        for b in banned:
            assert b not in blob, f"{tool['name']!r} description/schema references {b!r}"
    print("✅ test_new_tool_descriptions_and_schemas_never_reference_media_urls")


TESTS_SYNC = [
    test_all_new_tools_present,
    test_script_profile_and_budget_cap_not_duplicated,
    test_s5_2_memory_tools_never_appear_in_v3_surface,
    test_no_setup_or_ingest_tool_carries_confirm_token,
    test_learn_channel_start_description_states_its_real_cost,
    test_style_preset_id_is_settable_after_creation_via_generic_update,
    test_research_shape_rejects_non_list_unit_roster,
    test_research_shape_rejects_non_dict_roster_audit,
    test_research_shape_rejects_empty_payload,
    test_research_shape_accepts_minimal_non_roster_payload,
    test_new_tool_descriptions_and_schemas_never_reference_media_urls,
]

TESTS_ASYNC = [
    test_get_channel_dna_calls_current_identity_and_round_trips,
    test_learn_channel_start_calls_same_route_function_and_surfaces_busy,
    test_learn_channel_status_calls_same_route_function,
    test_upsert_quality_rule_calls_create_rule_with_mcp_agent_source,
    test_upsert_quality_rule_rejects_bad_severity_before_any_write,
    test_deactivate_quality_rule_calls_deactivate_rule,
    test_list_quality_rules_calls_list_all_rules_tenant_scoped,
    test_confirm_channel_pattern_attributes_to_the_calling_agent,
    test_retire_channel_pattern_attributes_to_the_calling_agent,
    test_confirm_channel_pattern_missing_id_errors_without_a_call,
    test_list_channel_patterns_calls_list_patterns_with_filters,
    test_set_script_template_reports_replaced_when_one_already_existed,
    test_set_script_template_reports_saved_when_none_existed,
    test_get_script_template_calls_same_route_function,
    test_list_script_profiles_calls_same_route_function,
    test_get_system_prompts_calls_same_route_function,
    test_set_system_prompt_calls_same_route_function,
    test_set_system_prompt_unknown_key_surfaces_route_error,
    test_set_render_style_calls_update_video_route,
    test_set_render_style_auto_clears_to_none,
    test_set_render_style_invalid_value_surfaces_route_error,
    test_set_style_preset_calls_update_video_route,
    test_submit_script_accept_path_calls_real_accept_external_script,
    test_submit_script_reject_path_surfaces_rule_by_rule_violations,
    test_submit_script_bad_shape_returns_error_not_a_500,
    test_submit_script_missing_video_id_errors_without_a_call,
    test_accept_submitted_research_missing_video_raises,
    test_accept_submitted_research_roster_gate_rejects_incomplete_roster,
    test_accept_submitted_research_saves_and_advances_on_pass,
    test_call_submit_research_bad_shape_returns_error_not_exception,
    test_call_submit_research_missing_video_id_errors_without_a_call,
]


def main() -> int:
    import asyncio
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
