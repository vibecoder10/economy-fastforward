"""Lock: DirectorHome's front-door box states its intent instead of having it
guessed (checklist C-frontdoor, 2026-07-27).

Root cause (verified live): the Director chat's co-pilot classifier read
"make a 1 minute video about a dystopian world where the elites watch the
citizens through bubbles" — a plain topic pitch typed into the ONE box that
creates a brand-new video — as the SINGLE-STAGE verb `script` (confidence
0.930), not the whole-pipeline verb `build`. `bot_activity` recorded
`kind=action verb=script confidence=0.930 source=brain gated=False`, and the
stored transcript showed the single-verb confirm-card template ("Ready when
you are — I'll write the script...") instead of the build template. `script`
is `ACTIONS["script"]` = one $0.02 stage, no continuation — so the video's
build silently never started.

Fix, two layers:
  1. (primary, tested here) DirectorHome's front door now sends its opening
     chat turn with `ChatTurnRequest.explicit_verb="build"` — a caller that
     already KNOWS the verb, so `_handle_copilot` (routes/chat.py) skips the
     probabilistic classifier ENTIRELY for that turn (no LLM call, no API key
     needed) and goes straight to the same legality-gate + paid-confirm-card
     path every classified verb already goes through — so a declared "build"
     still quotes real cost and still waits for an explicit tap.
  2. (defense in depth, NOT unit-tested here — it changes an LLM prompt, not
     code control flow) the classifier's own prompt was also updated to map a
     plain topic pitch with no prior script/research to `build` rather than
     `script`. That's a wording change to a prompt sent to a real model; it
     can't be pinned by a no-network unit test the way the deterministic
     bypass above can.

This test is the stash-proof for layer 1: with `explicit_verb` unset (the
pre-fix shape), `_handle_copilot` MUST run the classifier fallback for the
generic message; the test forces that fallback to raise (no client
configured — the exact "no LLM available" branch a stashed diff would hit
for ANY message, since the classifier is the only decision-maker), proving
the classifier path is what runs without the fix. With `explicit_verb="build"`
set, the SAME call must reach the paid-confirm-card branch without ever
touching the client/classifier — proving the declared verb bypasses it.

No network, no DB: `database`/`vault` are stubbed (same pattern as
test_c15a_plan_cost_quote.py / test_producer_kie_fallback.py). `_copilot_summary`
(routes.chat, aliasing actions.video_summary) is monkeypatched to a fresh-video
synthetic summary — the same shape actions.video_summary really returns — so
the paid/cost-quote logic downstream (actions.estimate_cost/cost_breakdown/
blocked_reason, all pure given this summary) runs for REAL, not mocked.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_frontdoor_explicit_build_intent.py -q
"""
import asyncio
import os
import sys
import types
from unittest.mock import patch

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod


EXECUTED = []


async def _fake_execute(query, *args):
    EXECUTED.append((query, args))
    return "OK"


async def _boom_fetch(*a, **k):
    raise AssertionError("this test's flow must never touch the real DB")


_stub("database", fetch_one=_boom_fetch, fetch_all=_boom_fetch, execute=_fake_execute)
_stub("vault", get_secret=_boom_fetch)

import routes.chat as chat  # noqa: E402

TENANT = "tenant-1"
VIDEO = "video-1"
PITCH = (
    "make a 1 minute video about a dystopian world where the elites watch "
    "the citizens through bubbles"
)


def _fresh_video_summary():
    """The exact shape actions.video_summary() returns, for a video that was
    JUST created (idea_logged, nothing written yet) — the front door's own
    createVideo() -> seeded first turn scenario."""
    return {
        "title": PITCH[:60],
        "status": "idea_logged",
        "length_min": 1.0,
        "model": "grok-imagine",
        "scenes": 0,
        "boards": 0,
        "voiced": 0,
        "max_scene": 0,
        "pics": 0,
        "clips": 0,
        "cast": 0,
        "spent": 0.0,
        "total_cost": 0.0,
        "max_spend": None,
        "validation": "",
        "render_style": None,
        "render_mode": None,
        "plays_sfx": True,
        "sfx_blocked_reason": None,
    }


class _BoomBackgroundTasks:
    """The paid-confirm-card branch must NEVER schedule work — money moves
    only after a second, explicit `confirm_action: yes` turn. Any call here
    means the fix regressed past the confirm gate."""

    def add_task(self, *a, **k):
        raise AssertionError(
            "explicit_verb='build' must stop at the confirm card — "
            "background_tasks.add_task must not be called on this turn"
        )


async def _fake_summary(*_a, **_k):
    return _fresh_video_summary()


def _run_copilot_turn(body):
    EXECUTED.clear()
    state: dict = {}
    transcript: list = []
    with patch.object(chat, "_copilot_summary", _fake_summary):
        return asyncio.run(
            chat._handle_copilot(
                body,
                "conv-1",
                TENANT,
                transcript,
                state,
                VIDEO,
                _BoomBackgroundTasks(),
            )
        )


def test_explicit_verb_build_bypasses_the_classifier_and_quotes_cost():
    """THE fix: explicit_verb='build' on the front door's exact pitch sentence
    reaches the paid confirm card for 'build' — never 'script' — without any
    LLM classifier call (no client configured; a classifier call would have
    to hit the client and fail this test by construction, since kie_unified
    is not stubbed/importable here)."""
    body = chat.ChatTurnRequest(
        message=PITCH,
        video_id=VIDEO,
        explicit_verb="build",
    )
    result = _run_copilot_turn(body)

    assert result.video_id == VIDEO
    assert result.cards, "expected a confirm card, got none"
    card = result.cards[0]
    assert card["id"] == "confirm_action"
    assert card["label"] == "Build the video", (
        f"expected the BUILD confirm card, got {card['label']!r} — "
        "the classifier ran (or misfired) instead of honoring explicit_verb"
    )
    assert "$" in result.assistant_text, "a paid action must always quote a real cost"
    assert "build the video" in result.assistant_text.lower()
    assert "write the script" not in result.assistant_text.lower(), (
        "must NOT be the single-stage script confirm card — "
        "this is the exact misfire the front door must never reproduce"
    )

    # source=explicit_entry was logged (not "brain"/"legacy" — proves the
    # classifier was genuinely skipped, not just that it happened to agree).
    activity_rows = [args for (q, args) in EXECUTED if "bot_activity" in q]
    assert activity_rows, "expected a classification-confidence telemetry row"
    message = activity_rows[0][2]
    assert "verb=build" in message
    assert "source=explicit_entry" in message
    assert "confidence=1.000" in message
    print("✅ test_explicit_verb_build_bypasses_the_classifier_and_quotes_cost")


def test_explicit_verb_ignores_unrecognized_values_and_falls_through():
    """A stale/tampered client sending a junk explicit_verb must not crash or
    silently run a fake verb — it's ignored and the turn falls through to the
    ordinary classifier path (which then needs a client; asserting THAT
    failure mode proves the junk value was discarded, not honored)."""
    body = chat.ChatTurnRequest(
        message=PITCH,
        video_id=VIDEO,
        explicit_verb="definitely-not-a-real-verb",
    )
    result = _run_copilot_turn(body)
    # No client configured (kie_unified.get_text_client_for_tenant will raise
    # or return None in this stubbed environment) -> the classifier branch's
    # own friendly "I just need an API key" reply, NEVER a confirm card for
    # a fake verb, and never a crash.
    assert result.cards in (None, []), (
        f"a bogus explicit_verb must never produce a confirm card, got {result.cards}"
    )
    print("✅ test_explicit_verb_ignores_unrecognized_values_and_falls_through")


def test_no_explicit_verb_hits_the_classifier_path_stash_proof():
    """Stash-proof companion: with explicit_verb unset (the pre-fix shape for
    EVERY caller, since the field didn't exist), the exact same pitch must go
    through the classifier branch — proven by requiring a text client, which
    isn't configured in this pure-unit environment, so it lands on the
    friendly key-prompt reply, never a build confirm card. This is the
    behavior the whole codebase had for this message before explicit_verb
    existed (confirmed via `git stash` during development: chat.py had no
    `explicit_verb` attribute at all, so `getattr(body, "explicit_verb", None)`
    would already return None here too — this test would pass identically on
    main, which is exactly the point: it pins the OLD default path stays
    intact for every caller that doesn't opt in)."""
    body = chat.ChatTurnRequest(message=PITCH, video_id=VIDEO)
    result = _run_copilot_turn(body)
    assert result.cards in (None, []), (
        "with no explicit_verb, this turn must go through the classifier "
        f"(no client configured here) — got a confirm card instead: {result.cards}"
    )
    assert "api key" in result.assistant_text.lower()
    print("✅ test_no_explicit_verb_hits_the_classifier_path_stash_proof")


if __name__ == "__main__":
    test_explicit_verb_build_bypasses_the_classifier_and_quotes_cost()
    test_explicit_verb_ignores_unrecognized_values_and_falls_through()
    test_no_explicit_verb_hits_the_classifier_path_stash_proof()
    print("All tests passed!")
