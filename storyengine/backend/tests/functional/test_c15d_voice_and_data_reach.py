"""Tests for C15d (checklist: "One director voice + data reach"): the audit
found two gaps between the home producer chat and the in-video copilot:

  1. Two different VOICES for one director — the home producer speaks in
     producer_prompt.PRODUCER_SYSTEM_PROMPT's full creative-producer
     personality; the in-video copilot's tool loop (agent_brain.py) ran on a
     thin task-classifier prompt with none of that tone.
  2. Data-blind copilot — the "what should I make next" / "how are my
     videos doing" briefs (_next_to_make_brief / _own_performance_brief /
     _learnings_brief) were only ever injected into the HOME chat's prompt;
     the in-video copilot's tool loop had no tool that could reach them.

Fix, pinned here:
  A. producer_prompt.DIRECTOR_VOICE — the shared personality core (tone,
     "co-thinking partner", never mention internal machinery, diagnose
     before you act) — extracted out of PRODUCER_SYSTEM_PROMPT so BOTH the
     home producer and agent_brain.run_copilot_brain's system prompt compose
     it, instead of the copilot carrying a second, thinner voice.
  B. channel_briefs.py — _next_to_make_brief / _own_performance_brief /
     _learnings_brief moved out of routes/chat.py into their own module
     (no dependency on chat.py or agent_brain.py, so both can import it with
     no circular-import risk). routes/chat.py now imports them from there
     (same names, same call sites — _loop_brief is unchanged); agent_brain.py
     gets a new read-only "channel_data" tool that calls the SAME three
     functions, so both chat surfaces answer from one data source.

No new paid path, no verb/op changes, no schema changes: the copilot's
op/verb classification, confidence gating, and JSON decision-schema output
contract are all pinned unchanged here as a regression check.

Same stub pattern as test_c15a/b/c: no live DB, no network.
Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c15d_voice_and_data_reach.py -q
"""
import asyncio
import inspect
import os
import sys
import types

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
_stub("vault", get_secret=_boom)

import agent_brain  # noqa: E402
import channel_briefs  # noqa: E402
import producer_prompt  # noqa: E402
import routes.chat as chat  # noqa: E402

TENANT = "tenant-1"
VIDEO = "video-1"
SUMMARY = {"status": "ready_for_video_generation", "model": "grok-imagine", "pics": 10, "scenes": 5}


# ---------------------------------------------------------------------------
# A. Shared director voice: one constant, composed into BOTH prompts
# ---------------------------------------------------------------------------

def test_director_voice_constant_carries_the_personality_core():
    voice = producer_prompt.DIRECTOR_VOICE
    assert "warm, sharp producer" in voice
    assert "co-thinking partner".lower() in voice.lower() or "push back when you disagree" in voice
    assert "DIAGNOSE BEFORE YOU ACT" in voice
    assert "NEVER mention internal machinery" in voice
    assert "pipeline, stage, status, render" in voice


def test_home_producer_prompt_composes_director_voice():
    prompt = producer_prompt.build_system_prompt()
    assert "creative producer" in prompt.lower()  # planning-rubric identity retained
    assert "DIAGNOSE BEFORE YOU ACT" in prompt
    assert "NEVER mention internal machinery" in prompt
    # extracted once, not duplicated in its old spot AND the shared block
    assert prompt.count("NEVER mention internal machinery") == 1


class _FakeBrainClient:
    """Records the prompt agent_brain.run_copilot_brain actually sent, and
    returns one canned final decision — no tool calls, no network."""

    def __init__(self, response_json: str):
        self._response = response_json
        self.last_prompt = None

    async def generate(self, prompt, **kw):
        self.last_prompt = prompt
        return self._response


_FINAL_READ = (
    '{"final":{"kind":"read","verb":"none","surface":"null","op":"null",'
    '"scene":null,"index":null,"change":"","direction":"","length_min":null,'
    '"scope":"channel","answer":"ok","reply":"","confidence":0.9}}'
)


def test_in_video_copilot_composes_the_same_director_voice():
    """Non-vacuous proof the copilot's ACTUAL system prompt (not just source
    text) carries the shared voice: run the real loop with a fake client and
    inspect what was sent."""
    client = _FakeBrainClient(_FINAL_READ)
    result = asyncio.run(agent_brain.run_copilot_brain(
        client, None, TENANT, VIDEO, SUMMARY, "how's it going", {}, "SUMMARY LINE"))
    assert result is not None and result.get("kind") == "read"
    assert client.last_prompt is not None
    assert "DIAGNOSE BEFORE YOU ACT" in client.last_prompt
    assert "NEVER mention internal machinery" in client.last_prompt
    assert "warm, sharp producer" in client.last_prompt
    # it still identifies as the copilot AGENT, not a second/different director
    assert "co-pilot AGENT for ONE video" in client.last_prompt


def test_copilot_source_composes_director_voice_via_the_shared_constant():
    src = inspect.getsource(agent_brain.run_copilot_brain)
    assert "DIRECTOR_VOICE" in src
    assert "from producer_prompt import" in src


# ---------------------------------------------------------------------------
# Regression pin: the copilot's classification precision is untouched
# ---------------------------------------------------------------------------

def test_decision_schema_and_verb_vocabulary_unchanged():
    schema = agent_brain._decision_schema()
    for verb in (
        "script", "characters", "storyboards", "images", "voice", "animate", "sound",
        "thumbnail", "render", "research", "seo", "upload", "approve_cast",
        "approve_environments", "skip_environments", "approve_scene", "lock", "unlock",
        "drive_push", "drive_sync", "advance", "build", "none",
    ):
        assert verb in schema
    assert '"kind":"read|action|prompt|show|remember|forget"' in schema
    assert '"confidence":<0.0-1.0>' in schema


def test_c15c_preference_hydration_still_present_in_both_prompts():
    """Regression pin: C15c's STANDING PREFERENCES hydration must survive
    this voice/data refactor untouched in both chat surfaces."""
    src_home = inspect.getsource(chat.chat_turn)
    assert "_preferences_brief(tenant_id)" in src_home
    src_copilot = inspect.getsource(chat._handle_copilot)
    assert "_preferences_brief(tenant_id, video_id)" in src_copilot


# ---------------------------------------------------------------------------
# B. Data reach: one shared brief implementation, both consumers
# ---------------------------------------------------------------------------

def test_chat_and_channel_briefs_share_the_identical_function_objects():
    """Proves routes/chat.py did not fork a copy of these builders — it
    imports the SAME function objects channel_briefs.py defines."""
    assert chat._next_to_make_brief is channel_briefs._next_to_make_brief
    assert chat._own_performance_brief is channel_briefs._own_performance_brief
    assert chat._learnings_brief is channel_briefs._learnings_brief


def test_tool_doc_retains_existing_tools_and_adds_channel_data():
    doc = agent_brain.TOOL_DOC
    for name in ("actions", "script", "shots", "prompt", "history", "cost", "channel_data"):
        assert f'"tool":"{name}"' in doc


def test_channel_data_reachable_via_run_tool_dispatch(monkeypatch):
    async def fake_next(tenant_id):
        assert tenant_id == TENANT
        return "\nWHAT TO MAKE NEXT (...):\n- pick this one"

    async def fake_perf(tenant_id):
        return ""

    async def fake_learn(tenant_id):
        return ""

    monkeypatch.setattr(channel_briefs, "_next_to_make_brief", fake_next)
    monkeypatch.setattr(channel_briefs, "_own_performance_brief", fake_perf)
    monkeypatch.setattr(channel_briefs, "_learnings_brief", fake_learn)

    result = asyncio.run(agent_brain._run_tool("channel_data", {}, TENANT, VIDEO, SUMMARY))
    assert "WHAT TO MAKE NEXT" in result
    assert "pick this one" in result


def test_channel_data_tool_fails_soft_to_a_plain_message_when_all_empty(monkeypatch):
    async def empty(tenant_id):
        return ""

    monkeypatch.setattr(channel_briefs, "_next_to_make_brief", empty)
    monkeypatch.setattr(channel_briefs, "_own_performance_brief", empty)
    monkeypatch.setattr(channel_briefs, "_learnings_brief", empty)

    result = asyncio.run(agent_brain._tool_channel_data(TENANT))
    assert result == "No channel performance or competitor data available yet."


def test_channel_data_tool_prompt_teaches_when_to_use_it():
    src = inspect.getsource(agent_brain.run_copilot_brain)
    assert "channel_data" in src
    assert "what should i make next" in src.lower()


# ---------------------------------------------------------------------------
# channel_briefs.py: tenant scoping + fail-soft, confirmed after the move
# ---------------------------------------------------------------------------

def test_next_to_make_brief_is_tenant_scoped_and_fail_soft(monkeypatch):
    seen = {}

    async def fake_fetch_all(query, *args):
        seen["query"] = query
        seen["args"] = args
        return []

    monkeypatch.setattr(channel_briefs, "fetch_all", fake_fetch_all)
    result = asyncio.run(channel_briefs._next_to_make_brief(TENANT))
    assert result == ""
    assert "tenant_id = $1" in seen["query"]
    assert seen["args"][0] == TENANT

    async def fake_fetch_all_boom(query, *args):
        raise RuntimeError("db is down")

    monkeypatch.setattr(channel_briefs, "fetch_all", fake_fetch_all_boom)
    result = asyncio.run(channel_briefs._next_to_make_brief(TENANT))
    assert result == ""  # never raises


def test_own_performance_brief_is_tenant_scoped_and_fail_soft(monkeypatch):
    seen = {}

    async def fake_fetch_all(query, *args):
        seen["query"] = query
        seen["args"] = args
        return []

    monkeypatch.setattr(channel_briefs, "fetch_all", fake_fetch_all)
    result = asyncio.run(channel_briefs._own_performance_brief(TENANT))
    assert result == ""
    assert "tenant_id = $1" in seen["query"]
    assert seen["args"][0] == TENANT

    async def fake_fetch_all_boom(query, *args):
        raise RuntimeError("db is down")

    monkeypatch.setattr(channel_briefs, "fetch_all", fake_fetch_all_boom)
    result = asyncio.run(channel_briefs._own_performance_brief(TENANT))
    assert result == ""


def test_learnings_brief_is_tenant_scoped_and_fail_soft(monkeypatch):
    seen = {}

    async def fake_fetch_all(query, *args):
        seen["query"] = query
        seen["args"] = args
        return []

    monkeypatch.setattr(channel_briefs, "fetch_all", fake_fetch_all)
    result = asyncio.run(channel_briefs._learnings_brief(TENANT))
    assert result == ""
    assert "tenant_id = $1" in seen["query"]
    assert seen["args"][0] == TENANT

    async def fake_fetch_all_boom(query, *args):
        raise RuntimeError("db is down")

    monkeypatch.setattr(channel_briefs, "fetch_all", fake_fetch_all_boom)
    result = asyncio.run(channel_briefs._learnings_brief(TENANT))
    assert result == ""


def test_next_to_make_brief_produces_scored_ranked_output(monkeypatch):
    """Non-vacuous: with real-shaped rows and a real scorer, the brief
    actually ranks and formats — proves the moved function still works
    end to end, not just that it doesn't crash."""
    rows = [
        {"title": "Old cold case reopened", "channel": "TrueCrimeHQ", "url": "https://y/1",
         "vph": 500.0, "hours_old": 10.0, "views": 5000, "distilled_at": None},
        {"title": "Newer viral heist", "channel": "CrimeDaily", "url": "https://y/2",
         "vph": 2000.0, "hours_old": 4.0, "views": 8000, "distilled_at": "2026-01-01"},
    ]

    async def fake_fetch_all(query, *args):
        return rows

    monkeypatch.setattr(channel_briefs, "fetch_all", fake_fetch_all)

    class _BD:
        def __init__(self, total):
            self.total_score = total

    def fake_confidence(vph, hours, meta):
        return _BD(90.0 if vph > 1000 else 40.0)

    fake_autopilot_mod = types.ModuleType("routes.autopilot")
    fake_autopilot_mod.calculate_confidence_with_breakdown = fake_confidence
    monkeypatch.setitem(sys.modules, "routes.autopilot", fake_autopilot_mod)

    result = asyncio.run(channel_briefs._next_to_make_brief(TENANT))
    assert "WHAT TO MAKE NEXT" in result
    assert "Newer viral heist" in result
    assert result.index("Newer viral heist") < result.index("Old cold case reopened")
