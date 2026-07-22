"""Tests for channel_identity_context.py — THE channel-identity POOL
(chat channel-identity rebuild, checklist P1).

Covers:
  1. Each section builder independently: real data -> correct shape;
     missing/error input -> empty-safe (never raises).
  2. own_median_minutes: prefers channel_videos.duration_seconds; falls back
     to this tenant's own pipeline-produced videos (scripts.
     voice_duration_seconds summed per video, actions.DONE_STATUSES-gated);
     None when neither source has data.
  3. build_identity_pool: full-fixture shape, and an all-empty-tenant shape
     (every field None/empty-safe, no crash).
  4. render_identity_brief: full fixture renders every section plus the
     precedence law; an empty pool still renders a minimal, valid block
     (no "None" literal leaking into prose); never raises on a malformed
     pool; stays within the ~40-line budget.
  5. MCP wiring: get_channel_identity_context is registered, carries no
     confirm_token (free/read-only), and its handler calls THIS module's
     build_identity_pool (not a parallel implementation) and round-trips
     the result byte-identical.

No live DB, no network. DB boundaries are patched at the module-level
fetch_one/fetch_all names each module imported (same convention as
tests/test_identity_context.py and tests/functional/test_c47_mcp_setup_and_
ingest.py). shared.profiles.script's catalog is real (a small, durable code
registry — see routes/script_profiles.py's own docstring for why it isn't
tenant DB data), so its section is exercised for real rather than mocked.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/test_channel_identity_context.py -q
"""
from __future__ import annotations

import json
import os
import sys
import types
from unittest.mock import AsyncMock, patch

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

import channel_identity_context as cic  # noqa: E402


# =============================================================================
# 1a. dna section
# =============================================================================

async def test_dna_section_strips_envelope_keys(monkeypatch):
    fake = {
        "voice_tone": "deadpan analyst",
        "_sources": {"voice_tone": {"learner": "identity_builder"}},
        "_history": [{"at": "x"}],
        "_last_run": {"ok": True},
    }
    monkeypatch.setattr("channel_dna._current_identity", AsyncMock(return_value=fake))
    out = await cic._dna_section("t1")
    assert out == {"voice_tone": "deadpan analyst"}


async def test_dna_section_empty_on_missing(monkeypatch):
    monkeypatch.setattr("channel_dna._current_identity", AsyncMock(return_value={}))
    assert await cic._dna_section("t1") == {}


async def test_dna_section_fail_soft_on_error(monkeypatch):
    async def boom(tenant_id):
        raise RuntimeError("db down")
    monkeypatch.setattr("channel_dna._current_identity", boom)
    assert await cic._dna_section("t1") == {}


# =============================================================================
# 1b. cast section
# =============================================================================

async def test_cast_section_locked_with_always_members(monkeypatch):
    async def fake_fetch_one(q, *a):
        assert "projects" in q
        return {
            "cast_locked": True,
            "character_references": [
                {"name": "Ryan", "description": "the curious host", "always": True, "reference_url": "x"},
                {"name": "Vanessa", "description": "the co-host", "always": True, "reference_url": "y"},
            ],
        }
    monkeypatch.setattr(cic, "fetch_one", fake_fetch_one)
    out = await cic._cast_section("t1")
    assert out == [
        {"name": "Ryan", "description": "the curious host"},
        {"name": "Vanessa", "description": "the co-host"},
    ]


async def test_cast_section_unlocked_returns_empty(monkeypatch):
    async def fake_fetch_one(q, *a):
        return {"cast_locked": False, "character_references": [{"name": "Ryan"}]}
    monkeypatch.setattr(cic, "fetch_one", fake_fetch_one)
    assert await cic._cast_section("t1") == []


async def test_cast_section_no_project_row_returns_empty(monkeypatch):
    monkeypatch.setattr(cic, "fetch_one", AsyncMock(return_value=None))
    assert await cic._cast_section("t1") == []


async def test_cast_section_skips_optional_always_false_members(monkeypatch):
    async def fake_fetch_one(q, *a):
        return {
            "cast_locked": True,
            "character_references": [
                {"name": "Ryan", "description": "host", "always": True, "reference_url": "x"},
                {"name": "Guest Star", "description": "one-off", "always": False, "reference_url": "z"},
            ],
        }
    monkeypatch.setattr(cic, "fetch_one", fake_fetch_one)
    out = await cic._cast_section("t1")
    assert [c["name"] for c in out] == ["Ryan"]


async def test_cast_section_handles_json_string_refs(monkeypatch):
    """asyncpg returns JSONB with no codec registered -> often a raw JSON
    STRING (same quirk identity.py's _clean_frameworks docstring calls
    out)."""
    async def fake_fetch_one(q, *a):
        return {
            "cast_locked": True,
            "character_references": json.dumps([
                {"name": "Ryan", "description": "host", "always": True, "reference_url": "x"},
            ]),
        }
    monkeypatch.setattr(cic, "fetch_one", fake_fetch_one)
    out = await cic._cast_section("t1")
    assert out == [{"name": "Ryan", "description": "host"}]


async def test_cast_section_malformed_json_string_never_raises(monkeypatch):
    async def fake_fetch_one(q, *a):
        return {"cast_locked": True, "character_references": "not json"}
    monkeypatch.setattr(cic, "fetch_one", fake_fetch_one)
    assert await cic._cast_section("t1") == []


async def test_cast_section_fail_soft_on_error(monkeypatch):
    async def boom(q, *a):
        raise RuntimeError("db down")
    monkeypatch.setattr(cic, "fetch_one", boom)
    assert await cic._cast_section("t1") == []


# =============================================================================
# 1c. format section
# =============================================================================

async def test_format_section_passthrough(monkeypatch):
    fmt = {"style": "3D animated", "motion": "animated", "segmentation": "short scenes", "on_camera": "no"}
    monkeypatch.setattr("channel_format.get_channel_format", AsyncMock(return_value=(fmt, True)))
    out = await cic._format_section("t1")
    assert out == {"visual_format": fmt, "locked": True}


async def test_format_section_fail_soft_on_error(monkeypatch):
    async def boom(tenant_id):
        raise RuntimeError("db down")
    monkeypatch.setattr("channel_format.get_channel_format", boom)
    out = await cic._format_section("t1")
    assert out == {"visual_format": {}, "locked": False}


# =============================================================================
# 2. own_median_minutes
# =============================================================================

async def test_own_median_prefers_channel_videos(monkeypatch):
    async def fake_fetch_one(q, *a):
        assert "channel_videos" in q
        return {"med": 372}  # 6.2 min
    fetch_all_calls = []

    async def fake_fetch_all(q, *a):
        fetch_all_calls.append(q)
        return []
    monkeypatch.setattr(cic, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(cic, "fetch_all", fake_fetch_all)
    med = await cic._own_median_minutes("t1")
    assert med == 6.2
    # channel_videos had usable data -> the pipeline-videos fallback query
    # never even fires.
    assert fetch_all_calls == []


async def test_own_median_falls_back_to_pipeline_videos(monkeypatch):
    async def fake_fetch_one(q, *a):
        assert "channel_videos" in q
        return {"med": None}  # nothing imported yet

    async def fake_fetch_all(q, *a):
        assert "scripts" in q
        # 3 own-produced videos, per-video totals in seconds
        return [{"total": 300}, {"total": 360}, {"total": 420}]  # median 360s = 6.0 min
    monkeypatch.setattr(cic, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(cic, "fetch_all", fake_fetch_all)
    med = await cic._own_median_minutes("t1")
    assert med == 6.0


async def test_own_median_none_when_no_data_anywhere(monkeypatch):
    monkeypatch.setattr(cic, "fetch_one", AsyncMock(return_value=None))
    monkeypatch.setattr(cic, "fetch_all", AsyncMock(return_value=[]))
    assert await cic._own_median_minutes("t1") is None


async def test_own_median_fail_soft_when_both_queries_error(monkeypatch):
    async def boom_one(q, *a):
        raise RuntimeError("db down")

    async def boom_all(q, *a):
        raise RuntimeError("db down")
    monkeypatch.setattr(cic, "fetch_one", boom_one)
    monkeypatch.setattr(cic, "fetch_all", boom_all)
    assert await cic._own_median_minutes("t1") is None


# =============================================================================
# 1d. title patterns section
# =============================================================================

async def test_title_patterns_only_confirmed_good(monkeypatch):
    calls = []

    async def fake_list_patterns(tenant_id, polarity=None, status=None):
        calls.append((polarity, status))
        return [{"pattern": '"X" outperforms median by 40%.', "evidence": {"metric": "vph"}}]
    monkeypatch.setattr("channel_patterns.list_patterns", fake_list_patterns)
    out = await cic._title_patterns_section("t1")
    assert calls == [("good", "confirmed")]
    assert out == [{"pattern": '"X" outperforms median by 40%.', "evidence": {"metric": "vph"}}]


async def test_title_patterns_capped(monkeypatch):
    rows = [{"pattern": f"pattern {i}", "evidence": {}} for i in range(20)]
    monkeypatch.setattr("channel_patterns.list_patterns", AsyncMock(return_value=rows))
    out = await cic._title_patterns_section("t1")
    assert len(out) == cic._TITLE_PATTERNS_CAP


async def test_title_patterns_fail_soft_on_error(monkeypatch):
    async def boom(tenant_id, polarity=None, status=None):
        raise RuntimeError("db down")
    monkeypatch.setattr("channel_patterns.list_patterns", boom)
    assert await cic._title_patterns_section("t1") == []


# =============================================================================
# 1e. script profiles catalog (real, not mocked — a code registry)
# =============================================================================

async def test_script_profiles_section_returns_real_catalog():
    out = await cic._script_profiles_section()
    ids = {p["id"] for p in out}
    assert "neutral_v1" in ids
    default = [p for p in out if p["is_default"]]
    assert len(default) == 1
    assert default[0]["id"] == "neutral_v1"
    for p in out:
        assert p["display_name"]
        assert p["description"]


# =============================================================================
# 1f. script prompt summary
# =============================================================================

async def test_script_prompt_summary_only_when_custom(monkeypatch):
    async def fake_list_prompts(tenant_id=None):
        return [
            {"key": "script", "is_custom": True, "prompt": "Always end with a friendly takeaway."},
            {"key": "thumbnail", "is_custom": True, "prompt": "irrelevant"},
        ]
    monkeypatch.setattr("routes.system_prompts.list_prompts", fake_list_prompts)
    out = await cic._script_prompt_summary("t1")
    assert out == "Always end with a friendly takeaway."


async def test_script_prompt_summary_none_when_not_custom(monkeypatch):
    async def fake_list_prompts(tenant_id=None):
        return [{"key": "script", "is_custom": False, "prompt": "the neutral default template..."}]
    monkeypatch.setattr("routes.system_prompts.list_prompts", fake_list_prompts)
    assert await cic._script_prompt_summary("t1") is None


async def test_script_prompt_summary_truncates(monkeypatch):
    long_text = "x" * 1000

    async def fake_list_prompts(tenant_id=None):
        return [{"key": "script", "is_custom": True, "prompt": long_text}]
    monkeypatch.setattr("routes.system_prompts.list_prompts", fake_list_prompts)
    out = await cic._script_prompt_summary("t1")
    assert len(out) == cic._SCRIPT_PROMPT_SUMMARY_MAX_CHARS


async def test_script_prompt_summary_fail_soft_on_error(monkeypatch):
    async def boom(tenant_id=None):
        raise RuntimeError("db down")
    monkeypatch.setattr("routes.system_prompts.list_prompts", boom)
    assert await cic._script_prompt_summary("t1") is None


# =============================================================================
# 3. build_identity_pool
# =============================================================================

_FULL_DNA = {
    "voice_tone": "warm, curious narrator",
    "cadence": "short punchy sentences, quick cuts",
    "hook_style": "open on a surprising fact, then a question",
    "structure": "hook -> 3 acts -> twist -> payoff",
    "signature_phrases": ["here is the thing nobody tells you", "but it gets worse", "so what really happened"],
    "hook_examples": [{"video": "The Bus Nobody Talks About", "line": "Every day, 40 kids get on a bus that never arrives."}],
    "style_description": (
        "A warm, curious documentary voice for a PocoAPoco-style ESL kids channel, short scenes, "
        "simple vocabulary, gentle pacing, always ends with a friendly takeaway for young viewers."
    ),
    "visual_format": {"style": "3D animated", "motion": "animated", "segmentation": "short scenes", "on_camera": "no"},
    "_sources": {"voice_tone": {}},
    "_history": [],
}


def _wire_full_fixture(monkeypatch):
    monkeypatch.setattr("channel_dna._current_identity", AsyncMock(return_value=dict(_FULL_DNA)))

    async def fake_fetch_one(q, *a):
        if "projects" in q:
            return {
                "cast_locked": True,
                "character_references": [
                    {"name": "Ryan", "description": "the curious host", "always": True, "reference_url": "x"},
                    {"name": "Vanessa", "description": "the co-host who asks the dumb questions", "always": True, "reference_url": "y"},
                ],
            }
        if "channel_videos" in q:
            return {"med": 372}
        return None
    monkeypatch.setattr(cic, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(cic, "fetch_all", AsyncMock(return_value=[]))

    fmt = {"style": "3D animated", "motion": "animated", "segmentation": "short scenes", "on_camera": "no"}
    monkeypatch.setattr("channel_format.get_channel_format", AsyncMock(return_value=(fmt, True)))

    async def fake_list_patterns(tenant_id, polarity=None, status=None):
        return [{
            "pattern": '"Why This Bus Never Arrives" outperforms this channel median views by 64% (n=9 videos with views data).',
            "evidence": {"metric": "vph"},
        }]
    monkeypatch.setattr("channel_patterns.list_patterns", fake_list_patterns)

    async def fake_list_prompts(tenant_id=None):
        return [{"key": "script", "is_custom": True, "prompt": "Always end with a one-sentence friendly takeaway aimed at 8-10 year olds."}]
    monkeypatch.setattr("routes.system_prompts.list_prompts", fake_list_prompts)


async def test_build_identity_pool_full_fixture_shape(monkeypatch):
    _wire_full_fixture(monkeypatch)
    pool = await cic.build_identity_pool("t1")

    assert set(pool.keys()) == {
        "dna", "cast", "format", "own_median_minutes", "title_patterns",
        "script_profiles", "script_prompt_summary",
    }
    assert pool["dna"]["voice_tone"] == "warm, curious narrator"
    assert "_sources" not in pool["dna"]
    assert pool["cast"] == [
        {"name": "Ryan", "description": "the curious host"},
        {"name": "Vanessa", "description": "the co-host who asks the dumb questions"},
    ]
    assert pool["format"]["locked"] is True
    assert pool["own_median_minutes"] == 6.2
    assert len(pool["title_patterns"]) == 1
    assert any(p["id"] == "neutral_v1" for p in pool["script_profiles"])
    assert pool["script_prompt_summary"].startswith("Always end with")


async def test_build_identity_pool_empty_tenant_shape(monkeypatch):
    monkeypatch.setattr("channel_dna._current_identity", AsyncMock(return_value={}))
    monkeypatch.setattr(cic, "fetch_one", AsyncMock(return_value=None))
    monkeypatch.setattr(cic, "fetch_all", AsyncMock(return_value=[]))
    monkeypatch.setattr("channel_format.get_channel_format", AsyncMock(return_value=({}, False)))
    monkeypatch.setattr("channel_patterns.list_patterns", AsyncMock(return_value=[]))
    monkeypatch.setattr("routes.system_prompts.list_prompts", AsyncMock(return_value=[]))

    pool = await cic.build_identity_pool("fresh-tenant")

    assert pool["dna"] == {}
    assert pool["cast"] == []
    assert pool["format"] == {"visual_format": {}, "locked": False}
    assert pool["own_median_minutes"] is None
    assert pool["title_patterns"] == []
    assert pool["script_prompt_summary"] is None
    # script_profiles is a real global code catalog, not tenant data — it's
    # never empty even for a brand-new tenant.
    assert len(pool["script_profiles"]) >= 1


# =============================================================================
# 4. render_identity_brief
# =============================================================================

_PRECEDENCE_MARKERS = ("LEADS", "TOPIC and appeal", "NEVER changes")


async def test_render_identity_brief_full_fixture(monkeypatch):
    _wire_full_fixture(monkeypatch)
    pool = await cic.build_identity_pool("t1")
    brief = cic.render_identity_brief(pool)

    for marker in _PRECEDENCE_MARKERS:
        assert marker in brief
    assert "VOICE:" in brief
    assert "STYLE:" in brief
    assert "LOOK/FORMAT (LOCKED):" in brief
    assert "SIGNATURE PHRASES:" in brief
    assert "HOOK EXAMPLE:" in brief
    assert "TITLE PATTERN (confirmed):" in brief
    assert "LOCKED CAST:" in brief
    assert "Ryan" in brief and "Vanessa" in brief
    assert "LENGTH:" in brief
    assert "6 min" in brief
    assert "SCRIPT VOICE OVERRIDE" in brief
    assert "None" not in brief
    assert len(brief.splitlines()) <= 40


async def test_render_identity_brief_empty_pool_is_minimal_and_valid():
    pool = {
        "dna": {}, "cast": [], "format": {"visual_format": {}, "locked": False},
        "own_median_minutes": None, "title_patterns": [], "script_profiles": [],
        "script_prompt_summary": None,
    }
    brief = cic.render_identity_brief(pool)

    for marker in _PRECEDENCE_MARKERS:
        assert marker in brief
    assert "None" not in brief
    assert "No channel identity learned yet" in brief
    assert "LENGTH:" in brief
    assert len(brief.splitlines()) <= 40


def test_render_identity_brief_never_raises_on_malformed_pool():
    for bad in (None, {}, {"dna": "not a dict"}, {"cast": "not a list"}, {"format": None}, 12345, "a string"):
        brief = cic.render_identity_brief(bad)  # must not raise
        assert isinstance(brief, str)
        assert "None" not in brief


def test_render_identity_brief_own_median_uses_minutes_and_seconds():
    pool = {"own_median_minutes": 6.2}
    brief = cic.render_identity_brief(pool)
    assert "6 min 12 sec" in brief


# =============================================================================
# 5. MCP wiring
# =============================================================================

import routes.mcp as mcp_mod  # noqa: E402


def test_get_channel_identity_context_tool_registered():
    names = mcp_mod.TOOL_NAMES
    assert "get_channel_identity_context" in names


def test_get_channel_identity_context_tool_is_free_no_confirm_token():
    tool = next(t for t in mcp_mod.TOOLS if t["name"] == "get_channel_identity_context")
    assert "confirm_token" not in tool["inputSchema"].get("properties", {})


def test_get_channel_identity_context_registered_as_read_handler():
    assert mcp_mod._SETUP_READ_HANDLERS["get_channel_identity_context"] is mcp_mod._call_get_channel_identity_context


async def test_call_get_channel_identity_context_dispatches_to_pool_and_round_trips():
    fake_pool = {
        "dna": {"voice_tone": "deadpan"}, "cast": [{"name": "Ryan", "description": "host"}],
        "format": {"visual_format": {"style": "3D"}, "locked": True},
        "own_median_minutes": 6.2, "title_patterns": [], "script_profiles": [],
        "script_prompt_summary": None,
    }
    fake_mod = types.ModuleType("channel_identity_context")
    fake_mod.build_identity_pool = AsyncMock(return_value=fake_pool)
    with patch.dict(sys.modules, {"channel_identity_context": fake_mod}):
        result = await mcp_mod._call_get_channel_identity_context("t1", {}, "agent")
    fake_mod.build_identity_pool.assert_awaited_once_with("t1")
    payload = json.loads(result["content"][0]["text"])
    assert payload == fake_pool, "must pass the pool through byte-identical, no silent stripping/adding"
