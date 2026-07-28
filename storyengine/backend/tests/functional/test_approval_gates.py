"""Tests for the approval-gate mechanism (feat/approval-gates,
DIRECTOR-CHAT-PLAN.md Task 5.2): the shared "this conversation is awaiting a
decision" slot (`state["pending_approval_gate"]`) and the two checkpoints it
drives — review the script before spending on cast/locations, review the
cast+locations together before spending on storyboards/pictures.

None of the names this file imports/patches (`chat._pending_gate_kind_for`,
`chat._approval_gate_card`, the `"approval_gate"` selections key, or
`actions.video_summary`'s `cast`/`envs`/`chars_approved`/`envs_approved`
keys) exist on `main` — every test below raises `AttributeError` on an
unpatched checkout, which is the non-vacuous proof requested in the review
brief (confirmed by running this file against a `git checkout --` of
actions.py/routes/chat.py, see the branch's own verification notes).

Style matches the existing chat.py test suite (test_frontdoor_explicit_
build_intent.py, test_c16a_generation_claims.py, test_c15_itemized_cost_
breakdown.py): real `actions`/`routes.chat` modules, `database`/
`generation_claims` calls monkeypatched — no live DB, no network.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_approval_gates.py -q
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

TENANT = "tenant-1"
VIDEO = "video-1"


def _summary(**over):
    """The exact shape actions.video_summary() returns (post feat/approval-
    gates: includes envs/chars_approved/envs_approved)."""
    base = {
        "title": "Slow English", "status": "ready_for_image_prompts", "length_min": 1.0,
        "model": "grok-imagine", "scenes": 8, "boards": 0, "voiced": 0,
        "max_scene": 8, "pics": 0, "clips": 0, "cast": 0, "envs": 0,
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


# ---------------------------------------------------------------------------
# 1. _pending_gate_kind_for — pure function, the routing decision itself
# ---------------------------------------------------------------------------

def test_script_gate_fires_only_before_any_character_exists():
    assert chat._pending_gate_kind_for("characters", _summary(cast=0)) == "script"
    # Once even ONE character row exists (drafted, whether approved or not),
    # the script gate has already been shown once — a later "redo the
    # characters" must confirm normally, not re-litigate the script.
    assert chat._pending_gate_kind_for("characters", _summary(cast=1)) is None
    assert chat._pending_gate_kind_for("characters", _summary(cast=4, chars_approved=True)) is None


def test_anchors_gate_fires_for_storyboards_and_images_when_cast_exists_and_unapproved():
    for verb in ("storyboards", "images"):
        s = _summary(cast=4, envs=8, chars_approved=False, envs_approved=False)
        assert chat._pending_gate_kind_for(verb, s) == "anchors", verb


def test_anchors_gate_never_fires_with_nothing_to_review():
    """Guard: a video that jumps straight to 'make the pictures' with zero
    characters designed has nothing to show in an anchors review — must fall
    through to None (the ordinary confirm_action path), not display a
    'Characters x 0' gate."""
    s = _summary(cast=0, envs=0, chars_approved=False, envs_approved=False)
    assert chat._pending_gate_kind_for("storyboards", s) is None
    assert chat._pending_gate_kind_for("images", s) is None


def test_anchors_gate_clears_once_both_approved():
    s = _summary(cast=4, envs=8, chars_approved=True, envs_approved=True)
    assert chat._pending_gate_kind_for("storyboards", s) is None
    assert chat._pending_gate_kind_for("images", s) is None
    # Only ONE of the two approved is not enough — "approved together in one
    # gate, not two" per the design brief.
    half = _summary(cast=4, envs=8, chars_approved=True, envs_approved=False)
    assert chat._pending_gate_kind_for("images", half) == "anchors"


def test_gate_never_fires_for_unrelated_verbs():
    s = _summary(cast=0, envs=0)
    for verb in ("script", "voice", "animate", "render", "thumbnail", "upload", "build", "sound"):
        assert chat._pending_gate_kind_for(verb, s) is None, verb


# ---------------------------------------------------------------------------
# 2. _approval_gate_card — the thin card builder (counts + cost, no
#    duplicated data — the panel re-fetches the real script/cast/locations)
# ---------------------------------------------------------------------------

def test_script_gate_card_shape():
    async def fake_fetch_all(query, *a):
        assert "FROM scripts" in query
        return [{"scene": 1, "scene_text": "hi"}, {"scene": 2, "scene_text": "there"}]

    with patch.object(chat, "fetch_all", fake_fetch_all):
        card = asyncio.run(chat._approval_gate_card(
            "script", TENANT, VIDEO, _summary(scenes=2, length_min=1.0),
            "~$0.10", None,
        ))
    assert card["id"] == "approval_gate"
    assert card["gate_kind"] == "script"
    assert card["label"] == "Slow English"
    assert card["scene_count"] == 2
    assert card["duration_seconds"] == 60
    assert card["cost_text"] == "~$0.10"
    assert "breakdown" not in card
    # single-select options so an old frontend that only understands
    # {value,label} option pairs still has something sane to render.
    assert {"value": "yes", "label": "Looks good!"} in card["options"]


def test_anchors_gate_card_shape_and_breakdown_passthrough():
    breakdown = {"lines": [{"model_id": "gpt-image-2", "display_name": "GPT Image 2",
                             "tier": "2K", "count": 48, "subtotal": 2.4}],
                 "total": 2.4, "all_premium_total": None, "hero_scenes": [], "scene_count": 8}
    card = asyncio.run(chat._approval_gate_card(
        "anchors", TENANT, VIDEO, _summary(cast=4, envs=8), "~$2.40", breakdown,
    ))
    assert card["gate_kind"] == "anchors"
    assert card["label"] == "Review Anchors"
    assert card["character_count"] == 4
    assert card["location_count"] == 8
    assert card["breakdown"] == breakdown


def test_gate_card_omits_breakdown_when_nothing_to_itemize():
    card = asyncio.run(chat._approval_gate_card(
        "anchors", TENANT, VIDEO, _summary(cast=2, envs=1), "~$0.30",
        {"lines": [], "total": 0, "all_premium_total": None, "hero_scenes": [], "scene_count": 0},
    ))
    assert "breakdown" not in card


# ---------------------------------------------------------------------------
# 3. End-to-end through _handle_copilot: the gate REPLACES the plain
#    confirm_action card at the paid-branch injection point, and — critically
#    — money does NOT move on the turn that merely DISPLAYS the gate (no
#    generation_claims.acquire, no background_tasks.add_task).
# ---------------------------------------------------------------------------

EXECUTED = []


async def _fake_execute(query, *args):
    EXECUTED.append((query, args))
    return "OK"


def _run_copilot_turn(body, state=None, summary=None, claims=None, char_count_row=None):
    EXECUTED.clear()
    state = state if state is not None else {}
    transcript = []
    bg = _RecordingBackgroundTasks()

    async def _fake_summary(*_a, **_k):
        return summary or _summary()

    async def _fake_actions_fetch_one(query, *a):
        # actions.estimate_cost's "characters" branch counts video_characters.
        if "video_characters" in query:
            return char_count_row or {"n": 0}
        raise AssertionError(f"unexpected actions.fetch_one call: {query}")

    with patch.object(chat, "_copilot_summary", _fake_summary), \
         patch.object(chat, "execute", _fake_execute), \
         patch.object(actions, "fetch_one", _fake_actions_fetch_one), \
         patch.object(chat, "generation_claims", claims or _claims(acquire_result=True)):
        result = asyncio.run(
            chat._handle_copilot(body, "conv-1", TENANT, transcript, state, VIDEO, bg)
        )
    return result, state, bg


def test_characters_verb_shows_script_gate_instead_of_plain_confirm():
    """The moment that used to render a plain 'Design the characters — $0.12,
    yes/no?' confirm_action card now renders the richer script-review gate
    instead — same real cost quote, richer body."""
    body = chat.ChatTurnRequest(message="design the characters", video_id=VIDEO, explicit_verb="characters")
    summary = _summary(status="ready_for_image_prompts", scenes=8, cast=0)

    async def fake_fetch_all(query, *a):
        return [{"scene": i, "scene_text": f"scene {i} text"} for i in range(1, 9)]

    with patch.object(chat, "fetch_all", fake_fetch_all):
        result, state, bg = _run_copilot_turn(body, summary=summary)

    assert bg.calls == [], "showing the gate must NOT itself schedule any generation"
    assert result.cards, "expected the script gate card"
    card = result.cards[0]
    assert card["id"] == "approval_gate"
    assert card["gate_kind"] == "script"
    assert "$" in card["cost_text"]
    # the shared pending slot, carrying exactly what a plain confirm would
    # have run — same money path, richer card.
    gate = state["pending_approval_gate"]
    assert gate["gate_kind"] == "script"
    assert gate["resume"]["verb"] == "characters"
    assert state.get("pending_action") is None
    print("✅ test_characters_verb_shows_script_gate_instead_of_plain_confirm")


def test_images_verb_shows_anchors_gate_when_cast_and_locations_exist_unapproved():
    body = chat.ChatTurnRequest(message="make the pictures", video_id=VIDEO, explicit_verb="images")
    summary = _summary(status="ready_for_image_prompts", scenes=8, pics=0,
                        cast=4, envs=8, chars_approved=False, envs_approved=False)

    result, state, bg = _run_copilot_turn(body, summary=summary)

    assert bg.calls == [], "showing the gate must NOT itself schedule any generation"
    card = result.cards[0]
    assert card["id"] == "approval_gate"
    assert card["gate_kind"] == "anchors"
    assert card["character_count"] == 4
    assert card["location_count"] == 8
    assert state["pending_approval_gate"]["resume"]["verb"] == "images"
    print("✅ test_images_verb_shows_anchors_gate_when_cast_and_locations_exist_unapproved")


def test_second_pass_after_cast_exists_confirms_normally_not_the_gate_again():
    """Stash-proof companion: once a character row exists, a LATER 'design
    the characters' turn must go through the untouched plain confirm_action
    path, not re-show the script gate — this is the exact behavior every
    verb had before this feature, and it must be unchanged for a video
    that's already past the checkpoint."""
    body = chat.ChatTurnRequest(message="design the characters", video_id=VIDEO, explicit_verb="characters")
    summary = _summary(status="ready_for_image_prompts", scenes=8, cast=2)

    result, state, bg = _run_copilot_turn(body, summary=summary, char_count_row={"n": 2})

    assert bg.calls == []
    card = result.cards[0]
    assert card["id"] == "confirm_action", "a video already past the script gate must see the ORIGINAL card"
    assert state.get("pending_approval_gate") is None
    print("✅ test_second_pass_after_cast_exists_confirms_normally_not_the_gate_again")


# ---------------------------------------------------------------------------
# 4. The approval_gate handshake (turn 2): "Looks good!" resumes the exact
#    quoted action via the SAME _run_pending_action dispatcher every other
#    confirm card uses — never a new, unaudited way to spend money.
# ---------------------------------------------------------------------------

def test_looks_good_resumes_the_exact_quoted_action():
    body = chat.ChatTurnRequest(
        video_id=VIDEO, selections={"approval_gate": "yes"},
    )
    state = {"pending_approval_gate": {
        "gate_kind": "script",
        "resume": {"verb": "characters", "scene": None, "change": "", "length_min": None},
    }}
    fake_step_factory = lambda *a, **k: "sentinel-characters-callable"  # noqa: E731
    claims = _claims(acquire_result=True)

    with patch.object(chat, "_make_copilot_step", fake_step_factory):
        result, state, bg = _run_copilot_turn(body, state=state, claims=claims)

    assert len(bg.calls) == 1, "approving the gate must schedule the resumed action exactly once"
    assert bg.calls[0][0] == "sentinel-characters-callable"
    claims.acquire.assert_awaited_once_with(TENANT, VIDEO, "characters", claimed_by="chat:characters")
    assert state["pending_approval_gate"] is None, "the gate must not linger after it's answered"
    print("✅ test_looks_good_resumes_the_exact_quoted_action")


def test_looks_good_on_anchors_gate_stamps_approval_columns_before_resuming():
    """Mirrors the ad hoc UPDATE the legacy autobuild image-phase already
    runs when it silently auto-passes this same checkpoint — done explicitly
    here so an anchors gate, once approved, is never re-offered."""
    body = chat.ChatTurnRequest(video_id=VIDEO, selections={"approval_gate": "yes"})
    state = {"pending_approval_gate": {
        "gate_kind": "anchors",
        "resume": {"verb": "images", "scene": None, "change": "", "length_min": None},
    }}
    fake_step_factory = lambda *a, **k: "sentinel-images-callable"  # noqa: E731
    claims = _claims(acquire_result=True)

    with patch.object(chat, "_make_copilot_step", fake_step_factory):
        result, state, bg = _run_copilot_turn(body, state=state, claims=claims)

    assert len(bg.calls) == 1
    approval_updates = [
        (q, a) for (q, a) in EXECUTED
        if "characters_approved_at" in q and "environments_approved_at" in q
    ]
    assert approval_updates, "approving the anchors gate must stamp both approval columns"
    assert approval_updates[0][1] == (VIDEO, TENANT)
    print("✅ test_looks_good_on_anchors_gate_stamps_approval_columns_before_resuming")


def test_looks_good_denied_claim_does_not_schedule():
    """The gate's approval still goes through the SAME acquire-before-
    schedule money guard as every other paid dispatch — a double-tap (or a
    retried turn) must not schedule twice."""
    body = chat.ChatTurnRequest(video_id=VIDEO, selections={"approval_gate": "yes"})
    state = {"pending_approval_gate": {
        "gate_kind": "script",
        "resume": {"verb": "characters", "scene": None, "change": "", "length_min": None},
    }}
    claims = _claims(acquire_result=False)

    result, state, bg = _run_copilot_turn(body, state=state, claims=claims)

    assert bg.calls == [], "a denied claim must NOT schedule the resumed action"
    assert result.assistant_text == chat._ALREADY_WORKING_REPLY
    print("✅ test_looks_good_denied_claim_does_not_schedule")


def test_not_yet_clears_the_gate_without_spending():
    body = chat.ChatTurnRequest(video_id=VIDEO, selections={"approval_gate": "no"})
    state = {"pending_approval_gate": {
        "gate_kind": "script",
        "resume": {"verb": "characters", "scene": None, "change": "", "length_min": None},
    }}
    claims = _claims(acquire_result=True)

    result, state, bg = _run_copilot_turn(body, state=state, claims=claims)

    assert bg.calls == []
    claims.acquire.assert_not_awaited()
    assert state["pending_approval_gate"] is None
    print("✅ test_not_yet_clears_the_gate_without_spending")


def test_approval_gate_yes_with_no_pending_gate_is_a_safe_no_op():
    """Defends a stale/replayed 'yes' turn (e.g. a reload after the gate
    already resolved) — must not crash, must not spend."""
    body = chat.ChatTurnRequest(video_id=VIDEO, selections={"approval_gate": "yes"})
    claims = _claims(acquire_result=True)

    result, state, bg = _run_copilot_turn(body, state={}, claims=claims)

    assert bg.calls == []
    claims.acquire.assert_not_awaited()
    print("✅ test_approval_gate_yes_with_no_pending_gate_is_a_safe_no_op")


# ---------------------------------------------------------------------------
# 5. actions.video_summary() — the additive fields the whole mechanism reads
# ---------------------------------------------------------------------------

def test_video_summary_carries_the_new_gate_fields():
    async def fake_fetch_one(query, *a):
        if "FROM videos" in query:
            return {
                "video_title": "T", "status": "ready_for_image_prompts", "video_length_minutes": 1,
                "video_model": "grok-imagine", "script_validation": None, "render_style": None,
                "render_mode": None, "total_cost": 0, "max_spend": None, "custom_film_plan_id": None,
                "dialogue_audio": None, "dialogue_mode": None,
                "characters_approved_at": None, "environments_approved_at": "2026-01-01T00:00:00Z",
            }
        if "FROM scripts" in query:
            return {"scenes": 8, "boards": 0, "voiced": 0, "max_scene": 8}
        if "FROM assets" in query:
            return {"pics": 0, "clips": 0}
        if "FROM video_characters" in query:
            return {"n": 4}
        if "FROM video_environments" in query:
            return {"n": 8}
        raise AssertionError(f"unexpected query: {query}")

    with patch.object(actions, "fetch_one", fake_fetch_one):
        summary = asyncio.run(actions.video_summary(TENANT, VIDEO))

    assert summary["cast"] == 4
    assert summary["envs"] == 8
    assert summary["chars_approved"] is False
    assert summary["envs_approved"] is True
    print("✅ test_video_summary_carries_the_new_gate_fields")


# ---------------------------------------------------------------------------
# 6. _post_approval_gate_for_autobuild — the seam actions.make_autobuild_step
#    calls (lazy import) when its own loop pauses at a checkpoint. Proves
#    the pause is a normal PERSISTED assistant turn (survives a reload the
#    same way every other pending action card already does), carrying the
#    SAME approval_gate card + pending_approval_gate slot the conversational
#    path already produces — never a second, parallel mechanism.
# ---------------------------------------------------------------------------

def test_post_approval_gate_for_autobuild_persists_a_normal_chat_turn():
    conv_row = {"id": "conv-1", "project_id": None, "video_id": VIDEO,
                "transcript": [], "state": {}, "phase": "created"}

    async def fake_fetch_one(query, *a):
        if "FROM videos WHERE id" in query and "chat_conversations" not in query:
            return {"id": VIDEO}  # _conversation_for_video's ownership check
        if "FROM chat_conversations" in query:
            return conv_row
        if "video_characters" in query:
            return {"n": 0}
        raise AssertionError(f"unexpected fetch_one: {query}")

    persisted = {}

    async def fake_persist(conversation_id, tenant_id, transcript, state, phase, video_id=None):
        persisted["conversation_id"] = conversation_id
        persisted["transcript"] = transcript
        persisted["state"] = state

    async def fake_summary(*_a, **_k):
        return _summary(status="ready_for_image_prompts", scenes=8, cast=0)

    resume = {"verb": "build", "target": "pictures", "scene": None, "change": "", "length_min": None}

    # _estimate_cost("characters", ...) calls actions.fetch_one directly (a
    # module-level name bound inside actions.py, not chat.fetch_one) — same
    # video_characters count query the script-gate cost quote needs.
    async def fake_actions_fetch_one(query, *a):
        if "video_characters" in query:
            return {"n": 0}
        raise AssertionError(f"unexpected actions.fetch_one: {query}")

    with patch.object(chat, "fetch_one", fake_fetch_one), \
         patch.object(chat, "_persist", fake_persist), \
         patch.object(chat, "_copilot_summary", fake_summary), \
         patch.object(actions, "fetch_one", fake_actions_fetch_one):
        asyncio.run(chat._post_approval_gate_for_autobuild(TENANT, VIDEO, "script", resume))

    assert persisted, "must persist a turn — a silent pause is the exact bug this exists to avoid"
    assert persisted["state"]["pending_approval_gate"] == {"gate_kind": "script", "resume": resume}
    turn = persisted["transcript"][-1]
    assert turn["role"] == "assistant"
    import json as _json
    payload = _json.loads(turn["content"])
    assert payload["cards"][0]["id"] == "approval_gate"
    assert payload["cards"][0]["gate_kind"] == "script"
    # Must read as "waiting on you", never as a stall — the exact bug
    # (chat froze silently, no way to tell thinking from dead) this
    # mechanism exists to not repeat.
    assert "take a look" in payload["assistant_text"].lower()
    print("✅ test_post_approval_gate_for_autobuild_persists_a_normal_chat_turn")


def test_post_approval_gate_for_autobuild_missing_video_is_a_safe_no_op():
    async def fake_fetch_one(query, *a):
        return None  # video doesn't exist / doesn't belong to this tenant

    async def fail_persist(*a, **k):
        raise AssertionError("must never persist for a video it can't find")

    with patch.object(chat, "fetch_one", fake_fetch_one), \
         patch.object(chat, "_persist", fail_persist):
        asyncio.run(chat._post_approval_gate_for_autobuild(
            TENANT, "no-such-video", "script",
            {"verb": "build", "target": "pictures", "scene": None, "change": "", "length_min": None},
        ))
    print("✅ test_post_approval_gate_for_autobuild_missing_video_is_a_safe_no_op")


if __name__ == "__main__":
    test_script_gate_fires_only_before_any_character_exists()
    test_anchors_gate_fires_for_storyboards_and_images_when_cast_exists_and_unapproved()
    test_anchors_gate_never_fires_with_nothing_to_review()
    test_anchors_gate_clears_once_both_approved()
    test_gate_never_fires_for_unrelated_verbs()
    test_script_gate_card_shape()
    test_anchors_gate_card_shape_and_breakdown_passthrough()
    test_gate_card_omits_breakdown_when_nothing_to_itemize()
    test_characters_verb_shows_script_gate_instead_of_plain_confirm()
    test_images_verb_shows_anchors_gate_when_cast_and_locations_exist_unapproved()
    test_second_pass_after_cast_exists_confirms_normally_not_the_gate_again()
    test_looks_good_resumes_the_exact_quoted_action()
    test_looks_good_on_anchors_gate_stamps_approval_columns_before_resuming()
    test_looks_good_denied_claim_does_not_schedule()
    test_not_yet_clears_the_gate_without_spending()
    test_approval_gate_yes_with_no_pending_gate_is_a_safe_no_op()
    test_video_summary_carries_the_new_gate_fields()
    test_post_approval_gate_for_autobuild_persists_a_normal_chat_turn()
    test_post_approval_gate_for_autobuild_missing_video_is_a_safe_no_op()
    print("All tests passed!")
