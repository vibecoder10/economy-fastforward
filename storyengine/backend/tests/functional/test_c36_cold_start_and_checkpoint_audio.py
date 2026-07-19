"""Tests for C36 (checklist §3.3 items 1-2, tasks/storyengine-wiring-fix-
checklist.md):

Item 1 — the pictures-review checkpoint had no audio yet (voice deferred to
the finish phase on purpose), but the copy never said so
(`actions.PICTURES_READY_MSG`), so a creator who then opened the Scenes tab
and hit a stock "Voice Required" gate had every reason to think something
was broken (the frontend half of this fix lives in ScenesWorkspaceTab.tsx —
no jest/vitest harness exists for it in this repo, verified via
`npx tsc --noEmit`/manual read instead). This file pins the backend copy.

Item 2 — cold-start: a tenant with zero competitor data silently got the
generic "dragon video" example forever. `routes.chat._handle_cold_start_
competitor_followup()` (extracted so it's directly testable, not buried
inline in `chat_turn()`) drives the one-tap "Add 3 competitors now" card's
follow-up turns; `_add_competitors_card()` is the card itself.

Non-vacuous: `_add_competitors_card`/`_handle_cold_start_competitor_followup`
don't exist at all before C36 (confirmed via `git stash`); the old
PICTURES_READY_MSG never mentioned voice.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c36_cold_start_and_checkpoint_audio.py -q
"""
import asyncio
import os
import sys
from unittest.mock import patch

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

import actions  # noqa: E402
import routes.chat as chat_route  # noqa: E402

TENANT = "tenant-1"


class _Body:
    """Minimal stand-in for ChatTurnRequest -- only the two fields
    _handle_cold_start_competitor_followup reads."""
    def __init__(self, message=None, selections=None):
        self.message = message
        self.selections = selections


# --- item 1: checkpoint-audio expectation -----------------------------------

def test_pictures_ready_message_sets_the_voice_expectation():
    msg = actions.PICTURES_READY_MSG.lower()
    assert "no voice" in msg or "voice" in msg, (
        "the pictures-review checkpoint message must say audio isn't there "
        "yet, not just 'review them'"
    )
    assert "review" in msg
    print("✅ test_pictures_ready_message_sets_the_voice_expectation")


# --- item 2: cold-start competitors card ------------------------------------

def test_add_competitors_card_shape():
    card = chat_route._add_competitors_card()
    assert card["id"] == "add_competitors"
    values = {o["value"] for o in card["options"]}
    assert values == {"add", "skip"}
    print("✅ test_add_competitors_card_shape")


def test_followup_returns_none_when_not_awaiting():
    state = {}
    result = asyncio.run(chat_route._handle_cold_start_competitor_followup(
        _Body(message="hello"), "conv-1", TENANT, [], state, None,
    ))
    assert result is None, "must fall through to normal intake when no card is pending"
    print("✅ test_followup_returns_none_when_not_awaiting")


def test_followup_skip_clears_state_and_greets():
    state = {"awaiting_competitor_paste": "prompt"}
    seen = {}

    async def fake_ob_reply(conversation_id, tenant_id, transcript, state_arg, text, **kw):
        seen["text"] = text
        seen["phase"] = kw.get("phase")
        return "REPLY"

    with patch.object(chat_route, "_ob_reply", fake_ob_reply):
        result = asyncio.run(chat_route._handle_cold_start_competitor_followup(
            _Body(selections={"add_competitors": "skip"}), "conv-1", TENANT, [], state, None,
        ))
    assert result == "REPLY"
    assert state["awaiting_competitor_paste"] is None
    assert seen["text"] == chat_route._GREETING
    print("✅ test_followup_skip_clears_state_and_greets")


def test_followup_add_asks_for_urls_and_advances_state():
    state = {"awaiting_competitor_paste": "prompt"}
    seen = {}

    async def fake_ob_reply(conversation_id, tenant_id, transcript, state_arg, text, **kw):
        seen["text"] = text
        return "REPLY"

    with patch.object(chat_route, "_ob_reply", fake_ob_reply):
        result = asyncio.run(chat_route._handle_cold_start_competitor_followup(
            _Body(selections={"add_competitors": "add"}), "conv-1", TENANT, [], state, None,
        ))
    assert result == "REPLY"
    assert state["awaiting_competitor_paste"] == "collecting"
    assert "paste" in seen["text"].lower()
    print("✅ test_followup_add_asks_for_urls_and_advances_state")


def test_followup_collecting_no_urls_reprompts_without_advancing():
    state = {"awaiting_competitor_paste": "collecting"}
    seen = {}

    async def fake_ob_reply(conversation_id, tenant_id, transcript, state_arg, text, **kw):
        seen["text"] = text
        return "REPLY"

    with patch.object(chat_route, "_ob_reply", fake_ob_reply):
        result = asyncio.run(chat_route._handle_cold_start_competitor_followup(
            _Body(message="not a url"), "conv-1", TENANT, [], state, None,
        ))
    assert result == "REPLY"
    assert state["awaiting_competitor_paste"] == "collecting", "must stay in collecting, not silently give up"
    assert "didn't catch" in seen["text"].lower()
    print("✅ test_followup_collecting_no_urls_reprompts_without_advancing")


def test_followup_collecting_with_urls_kicks_off_analysis_and_clears_state():
    state = {"awaiting_competitor_paste": "collecting"}
    seen = {}
    called = {}

    async def fake_ob_reply(conversation_id, tenant_id, transcript, state_arg, text, **kw):
        seen["text"] = text
        return "REPLY"

    class FakeCompetitorAnalyze:
        def __init__(self, channel_urls):
            called["channel_urls"] = channel_urls

    async def fake_analyze_competitors(spec, background_tasks, tenant_id):
        called["ran"] = True
        return {"job_id": "job-1"}

    import types
    fake_onboarding = types.ModuleType("routes.onboarding")
    fake_onboarding.CompetitorAnalyze = FakeCompetitorAnalyze
    fake_onboarding.analyze_competitors = fake_analyze_competitors

    with patch.object(chat_route, "_ob_reply", fake_ob_reply), \
         patch.dict(sys.modules, {"routes.onboarding": fake_onboarding}):
        result = asyncio.run(chat_route._handle_cold_start_competitor_followup(
            _Body(message="https://youtube.com/@rival1, @rival2"), "conv-1", TENANT, [], state, "bg-tasks",
        ))
    assert result == "REPLY"
    assert state["awaiting_competitor_paste"] is None
    assert called.get("ran") is True
    assert called["channel_urls"] == ["https://youtube.com/@rival1", "@rival2"]
    assert "analyzing" in seen["text"].lower()
    print("✅ test_followup_collecting_with_urls_kicks_off_analysis_and_clears_state")


def test_followup_stale_state_clears_and_falls_through():
    state = {"awaiting_competitor_paste": "some-unrecognized-value"}
    result = asyncio.run(chat_route._handle_cold_start_competitor_followup(
        _Body(message="hi"), "conv-1", TENANT, [], state, None,
    ))
    assert result is None
    assert state["awaiting_competitor_paste"] is None
    print("✅ test_followup_stale_state_clears_and_falls_through")


if __name__ == "__main__":
    test_pictures_ready_message_sets_the_voice_expectation()
    test_add_competitors_card_shape()
    test_followup_returns_none_when_not_awaiting()
    test_followup_skip_clears_state_and_greets()
    test_followup_add_asks_for_urls_and_advances_state()
    test_followup_collecting_no_urls_reprompts_without_advancing()
    test_followup_collecting_with_urls_kicks_off_analysis_and_clears_state()
    test_followup_stale_state_clears_and_falls_through()
    print("All C36 cold-start/checkpoint-audio tests passed!")
