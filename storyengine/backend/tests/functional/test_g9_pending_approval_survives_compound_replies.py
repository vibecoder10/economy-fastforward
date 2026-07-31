"""Tests for G9 (diagnosed live 2026-07-30, video d05efae3-46f8-4ee3-b690-
849c3ca31fbc): replying to a pending confirm_action card with anything other
than a bare yes/no must never silently destroy the approval.

Real broken transcript (chat_conversations.transcript for that video):
  1. user creates a video, asks for a budget cap + "research stage only" in
     one compound message -> the classifier picks ONE verb ("build") and a
     "Build the video (~$0.75)" confirm_action card is presented.
  2. user replies: 'Before running: change the video title to exactly "All 5
     King George V Class Battleships" - nothing else in the title. Then go
     ahead.' — neither a bare "yes" nor a bare "no".
  3. Pre-fix: this fell straight through to the general classifier with
     `state["pending_action"]` left untouched. The classifier's actual reply
     was "Budget cap set to $5.00..." — a stale, unrelated verb (`budget_cap`)
     re-fired instead of the pending build ever resuming. The title was NEVER
     changed (actions.ACTIONS has no title verb to route it to at all — the
     classifier's own JSON schema doesn't even list one). The creator had to
     retype "Run the build now" from scratch to get a second confirm card.

Fix (routes/chat.py, three parts):
  1. `_has_consent_tail` — a message ending in "then go ahead"/"then run it"/
     "then do it"/"then proceed" auto-resumes the SAME pending action
     (_run_pending_action), no model call needed.
  2. `_extract_title_edit` / `_maybe_apply_title_edit` — a recognized
     "change the title to X" instruction applies immediately and for real
     (youtube_publish.save_seo), regardless of what else is in the message.
  3. `_still_pending_card_reply` — when a title edit is recognized but there
     is no clear consent tail, OR when the classifier lands on some OTHER
     action verb while a pending confirm is still open, the SAME pending
     card is re-presented ("Still waiting on: ...") instead of silently
     dropping or replacing it.

Style matches test_script_review_gate.py exactly (same `_summary`/`_claims`/
`_RecordingBackgroundTasks`/`_run_copilot_turn` helpers, duplicated here so
this file stays self-contained like every other file in this suite): real
`actions`/`routes.chat` modules, `database`/`generation_claims` monkeypatched
— no live DB, no network, no paid API calls.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_g9_pending_approval_survives_compound_replies.py -q
"""
import asyncio
import os
import sys
import types
from unittest.mock import AsyncMock, patch

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
_PIPELINE_PATH = os.path.join(_BACKEND, "..", "..", "skills", "video-pipeline")
sys.path.insert(0, os.path.abspath(_BACKEND))
sys.path.insert(0, os.path.abspath(_PIPELINE_PATH))

import actions  # noqa: E402
import generation_claims  # noqa: E402
import routes.chat as chat  # noqa: E402
import youtube_publish  # noqa: E402

TENANT = "tenant-1"
VIDEO = "video-1"

# The exact compound reply from the real broken transcript (turn 2).
REAL_COMPOUND_REPLY = (
    'Before running: change the video title to exactly '
    '"All 5 King George V Class Battleships" - nothing else in the title. '
    "Then go ahead."
)

PENDING_BUILD = {
    "verb": "build", "scene": None, "change": "", "length_min": None,
    "target": "pictures",
}


def _summary(**over):
    base = {
        "title": "Untitled", "status": "ready_for_scripting", "length_min": 1.0,
        "model": "grok-imagine", "scenes": 0, "boards": 0, "voiced": 0,
        "max_scene": 0, "pics": 0, "clips": 0, "cast": 0, "envs": 0,
        "chars_approved": False, "envs_approved": False,
        "spent": 0.0, "total_cost": 0.0, "max_spend": None,
        "validation": "", "render_style": None, "render_mode": None,
        "plays_sfx": True, "sfx_blocked_reason": None,
    }
    base.update(over)
    return base


class _RecordingBackgroundTasks:
    def __init__(self):
        self.calls = []

    def add_task(self, fn, *a, **k):
        self.calls.append((fn, a, k))


def _claims(acquire_result=True):
    return types.SimpleNamespace(
        acquire=AsyncMock(return_value=acquire_result),
        release=AsyncMock(return_value=None),
        stage_for_verb=generation_claims.stage_for_verb,
    )


EXECUTED = []


async def _fake_execute(query, *args):
    EXECUTED.append((query, args))
    return "OK"


async def _fake_fetch_one_render_mode(query, *a):
    """chat.py's OWN fetch_one (not actions.fetch_one) — _run_pending_action's
    'build' verb reads render_mode straight off it (routes/chat.py, right
    before scheduling the autobuild step)."""
    if "render_mode" in query:
        return {"render_mode": None}
    return None


def _run_copilot_turn(body, state=None, summary=None, claims=None, char_count_row=None):
    EXECUTED.clear()
    state = state if state is not None else {}
    transcript = []
    bg = _RecordingBackgroundTasks()

    async def _fake_summary(*_a, **_k):
        return summary or _summary()

    async def _fake_actions_fetch_one(query, *a):
        if "video_characters" in query:
            return char_count_row or {"n": 0}
        raise AssertionError(f"unexpected actions.fetch_one call: {query}")

    with patch.object(chat, "_copilot_summary", _fake_summary), \
         patch.object(chat, "execute", _fake_execute), \
         patch.object(chat, "fetch_one", _fake_fetch_one_render_mode), \
         patch.object(actions, "fetch_one", _fake_actions_fetch_one), \
         patch.object(chat, "generation_claims", claims or _claims(acquire_result=True)):
        result = asyncio.run(
            chat._handle_copilot(body, "conv-1", TENANT, transcript, state, VIDEO, bg)
        )
    return result, state, bg


# ---------------------------------------------------------------------------
# 1. THE reproduction: the exact compound reply from the broken transcript.
#    Consent-tail present -> title applied for real AND the pending build
#    resumes in the SAME turn, no retyping needed.
# ---------------------------------------------------------------------------

def test_compound_reply_applies_title_edit_and_resumes_pending_build():
    body = chat.ChatTurnRequest(video_id=VIDEO, message=REAL_COMPOUND_REPLY)
    state = {"pending_action": dict(PENDING_BUILD)}
    claims = _claims(acquire_result=True)

    saved = {}

    async def _fake_save_seo(video_id, tenant_id, **kwargs):
        saved["video_id"] = video_id
        saved["tenant_id"] = tenant_id
        saved.update(kwargs)
        return {"status": "saved"}

    fake_step_factory = lambda *a, **k: "sentinel-autobuild-callable"  # noqa: E731

    with patch.object(youtube_publish, "save_seo", _fake_save_seo), \
         patch.object(chat, "_make_autobuild_step", fake_step_factory):
        result, state, bg = _run_copilot_turn(body, state=state, claims=claims)

    assert saved.get("title") == "All 5 King George V Class Battleships", (
        f"the title edit must be applied for real, got {saved!r}"
    )
    assert saved.get("video_id") == VIDEO and saved.get("tenant_id") == TENANT

    assert len(bg.calls) == 1, "the pending build must resume in this SAME turn"
    assert bg.calls[0][0] == "sentinel-autobuild-callable"
    assert state["pending_action"] is None, "the resumed pending action must be cleared"

    assert 'Title updated to "All 5 King George V Class Battleships"' in result.assistant_text
    assert "building your video" in result.assistant_text.lower(), (
        "the build confirmation must ALSO be present — both things happened, "
        f"got: {result.assistant_text!r}"
    )
    print("✅ test_compound_reply_applies_title_edit_and_resumes_pending_build")


# Swap-proof: this exact scenario (test_compound_reply_applies_title_edit_
# and_resumes_pending_build, above) was run by hand against the unmodified
# HEAD version of routes/chat.py (git show HEAD:.../chat.py swapped in,
# tests re-run, original restored) and FAILS there — `saved` stays empty
# (the title is never written) and `bg.calls` stays empty (the build never
# resumes); the classifier's own "I need an API key" fallback comes back
# instead, matching the real transcript's dead end exactly. Not re-asserted
# as its own test here (patch.object on names that don't exist pre-fix
# raises AttributeError, not a clean assertion) — the swap was done directly
# instead; see the G9 report for the transcript.


# ---------------------------------------------------------------------------
# 2. No consent tail: the title edit still applies, but the pending card is
#    RE-PRESENTED (not silently dropped, not silently run).
# ---------------------------------------------------------------------------

def test_compound_reply_without_consent_tail_represents_the_pending_card():
    msg = (
        'Before running: change the video title to exactly '
        '"All 5 King George V Class Battleships" - nothing else in the title.'
    )
    body = chat.ChatTurnRequest(video_id=VIDEO, message=msg)
    state = {"pending_action": dict(PENDING_BUILD)}
    claims = _claims(acquire_result=True)

    saved = {}

    async def _fake_save_seo(video_id, tenant_id, **kwargs):
        saved.update(kwargs)
        return {"status": "saved"}

    with patch.object(youtube_publish, "save_seo", _fake_save_seo):
        result, state, bg = _run_copilot_turn(
            body, state=state, claims=claims,
            summary=_summary(status="ready_for_scripting"),
        )

    assert saved.get("title") == "All 5 King George V Class Battleships"
    assert bg.calls == [], "the build must NOT silently run with no clear consent"
    assert state["pending_action"] == PENDING_BUILD, (
        "the pending action must survive, unchanged, not be lost"
    )
    assert result.cards and result.cards[0]["id"] == "confirm_action", (
        "the SAME pending card must be re-presented"
    )
    assert result.cards[0]["label"] == "Build the video"
    assert "still waiting on" in result.assistant_text.lower()
    assert 'title updated to "all 5 king george v class battleships"' in result.assistant_text.lower()
    print("✅ test_compound_reply_without_consent_tail_represents_the_pending_card")


# ---------------------------------------------------------------------------
# 3. Stale-verb-refire prevention: the general classifier landing on some
#    OTHER action verb (the real transcript's budget_cap misfire) must not
#    silently run while a pending confirm is open — the pending card is
#    re-presented instead.
# ---------------------------------------------------------------------------

def test_classifier_action_verb_does_not_override_a_pending_confirm():
    """Simulates the exact failure mode: pending build is open, the message
    has no title edit and no consent tail, and the classifier (stubbed here
    to mirror the real transcript's actual misfire) decides on the unrelated
    free verb `budget_cap`. Must NOT run it — must re-present the pending
    build card instead."""
    body = chat.ChatTurnRequest(video_id=VIDEO, message="what about the budget on this one")
    state = {"pending_action": dict(PENDING_BUILD)}
    claims = _claims(acquire_result=True)

    fake_client = types.SimpleNamespace()

    async def _fake_get_client(_tenant):
        return fake_client

    fake_kie = types.ModuleType("kie_unified")
    fake_kie.get_text_client_for_tenant = _fake_get_client

    async def _fake_run_brain(*_a, **_k):
        return {"kind": "action", "verb": "budget_cap", "reply": "", "confidence": 0.9,
                "change": "$5", "scene": None, "length_min": None}

    fake_brain = types.ModuleType("agent_brain")
    fake_brain.run_copilot_brain = _fake_run_brain

    budget_cap_calls = []

    async def _fake_budget_cap_runner(tenant_id, video_id, background_tasks, pending):
        budget_cap_calls.append((tenant_id, video_id))
        return "Budget cap set to $5.00 for this video."

    with patch.dict(sys.modules, {"kie_unified": fake_kie, "agent_brain": fake_brain}), \
         patch.dict(chat._ACTION_RUNNERS, {"budget_cap": _fake_budget_cap_runner}):
        result, state, bg = _run_copilot_turn(
            body, state=state, claims=claims,
            summary=_summary(status="ready_for_scripting"),
        )

    assert budget_cap_calls == [], (
        "the stale/unrelated verb must NOT silently run over an open pending confirm"
    )
    assert bg.calls == []
    assert state["pending_action"] == PENDING_BUILD, "the original pending build must survive"
    assert result.cards and result.cards[0]["id"] == "confirm_action"
    assert result.cards[0]["label"] == "Build the video"
    assert "still waiting on" in result.assistant_text.lower()
    print("✅ test_classifier_action_verb_does_not_override_a_pending_confirm")


# ---------------------------------------------------------------------------
# 4. Unrelated QUESTION mid-approval: must still be answered (kind=="read"
#    never touches pending_action), AND the card must survive for the next
#    turn's bare "yes".
# ---------------------------------------------------------------------------

def test_unrelated_question_mid_approval_is_answered_and_keeps_the_card_alive():
    body = chat.ChatTurnRequest(video_id=VIDEO, message="how much has this cost so far?")
    state = {"pending_action": dict(PENDING_BUILD)}
    claims = _claims(acquire_result=True)

    fake_client = types.SimpleNamespace()

    async def _fake_get_client(_tenant):
        return fake_client

    fake_kie = types.ModuleType("kie_unified")
    fake_kie.get_text_client_for_tenant = _fake_get_client

    async def _fake_run_brain(*_a, **_k):
        return {"kind": "read", "verb": "none", "answer": "You've spent $0.00 so far.",
                "confidence": 0.95}

    fake_brain = types.ModuleType("agent_brain")
    fake_brain.run_copilot_brain = _fake_run_brain

    with patch.dict(sys.modules, {"kie_unified": fake_kie, "agent_brain": fake_brain}):
        result, state, bg = _run_copilot_turn(
            body, state=state, claims=claims,
            summary=_summary(status="ready_for_scripting"),
        )

    assert bg.calls == []
    assert "spent $0.00" in result.assistant_text, "the actual question must be answered"
    assert state["pending_action"] == PENDING_BUILD, "the pending card must survive the question"

    # Next turn: a bare "yes" must still resume the SAME original pending build.
    fake_step_factory = lambda *a, **k: "sentinel-autobuild-callable"  # noqa: E731
    with patch.object(chat, "_make_autobuild_step", fake_step_factory):
        body2 = chat.ChatTurnRequest(video_id=VIDEO, message="yes")
        result2, state2, bg2 = _run_copilot_turn(body2, state=state, claims=claims)
    assert len(bg2.calls) == 1 and bg2.calls[0][0] == "sentinel-autobuild-callable"
    assert state2["pending_action"] is None
    print("✅ test_unrelated_question_mid_approval_is_answered_and_keeps_the_card_alive")


# ---------------------------------------------------------------------------
# 5. Bare yes/no: byte-identical to the pre-existing (untouched) code path —
#    these lines were not modified by G9 at all.
# ---------------------------------------------------------------------------

def test_bare_yes_still_resumes_the_pending_action():
    body = chat.ChatTurnRequest(video_id=VIDEO, message="yes")
    state = {"pending_action": dict(PENDING_BUILD)}
    claims = _claims(acquire_result=True)
    fake_step_factory = lambda *a, **k: "sentinel-autobuild-callable"  # noqa: E731

    with patch.object(chat, "_make_autobuild_step", fake_step_factory):
        result, state, bg = _run_copilot_turn(body, state=state, claims=claims)

    assert len(bg.calls) == 1
    assert bg.calls[0][0] == "sentinel-autobuild-callable"
    assert state["pending_action"] is None
    assert "building your video" in result.assistant_text.lower()
    print("✅ test_bare_yes_still_resumes_the_pending_action")


def test_bare_no_still_cancels_the_pending_action():
    body = chat.ChatTurnRequest(video_id=VIDEO, message="no")
    state = {"pending_action": dict(PENDING_BUILD)}
    claims = _claims(acquire_result=True)

    result, state, bg = _run_copilot_turn(body, state=state, claims=claims)

    assert bg.calls == []
    assert state["pending_action"] is None
    assert result.assistant_text == "No problem — left it as it is. Tell me what you'd like instead."
    print("✅ test_bare_no_still_cancels_the_pending_action")


def test_bare_yes_button_tap_unaffected_by_g9():
    """The button-tap handshake (`confirm_action` selection, not typed text)
    is a completely separate code path from everything G9 touched — proven
    here unchanged."""
    body = chat.ChatTurnRequest(video_id=VIDEO, selections={"confirm_action": "yes"})
    state = {"pending_action": dict(PENDING_BUILD)}
    claims = _claims(acquire_result=True)
    fake_step_factory = lambda *a, **k: "sentinel-autobuild-callable"  # noqa: E731

    with patch.object(chat, "_make_autobuild_step", fake_step_factory):
        result, state, bg = _run_copilot_turn(body, state=state, claims=claims)

    assert len(bg.calls) == 1
    assert bg.calls[0][0] == "sentinel-autobuild-callable"
    assert state["pending_action"] is None
    print("✅ test_bare_yes_button_tap_unaffected_by_g9")


TESTS = [
    test_compound_reply_applies_title_edit_and_resumes_pending_build,
    test_compound_reply_without_consent_tail_represents_the_pending_card,
    test_classifier_action_verb_does_not_override_a_pending_confirm,
    test_unrelated_question_mid_approval_is_answered_and_keeps_the_card_alive,
    test_bare_yes_still_resumes_the_pending_action,
    test_bare_no_still_cancels_the_pending_action,
    test_bare_yes_button_tap_unaffected_by_g9,
]


if __name__ == "__main__":
    failed = 0
    for t in TESTS:
        try:
            t()
        except AssertionError as e:
            print(f"❌ {t.__name__}: {e}")
            failed += 1
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed")
    sys.exit(1 if failed else 0)
