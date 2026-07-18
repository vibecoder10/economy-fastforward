"""Tests for C15a (checklist §1.2 follow-up, tasks/storyengine-wiring-fix-checklist.md
"MONEY GAP: quote+confirm on the home Producer's 'Make it' tap"):

Before this fix, the home Producer's ProductionPlanCard "Make it" button fired
`_handle_approve` -> `create_video` -> `_make_autobuild_step(..., target="pictures")`
(routes/chat.py) — a real paid autobuild (~scenes * 6 * PICTURE_COST worth of
pictures) with NO cost shown or confirmed anywhere. Every other paid verb in
this file quote-gates via `_confirm_card` (C15's itemized breakdown); this was
the one hole.

The fix (shape (a) — the plan card itself carries the quote, informed consent
on the single "Make it" tap, no second confirm round-trip): `routes.chat.
_stamp_plan_estimate()` stamps `plan["estimated_cost"]` /
`plan["estimated_cost_text"]` right after the producer emits a plan, sourced
ENTIRELY from `actions.estimate_plan_cost()` — itself a thin synthetic-summary
wrapper that hands `actions.estimate_cost`'s own existing "build" verb
pre-pictures math (no shot plan exists before the script is written, so this
is a rough, honestly-labeled figure, not a precise one — same reason
`cost_breakdown` returns None pre-plan).

ORCHESTRATOR REVIEW FOLLOW-UP (2026-07-18): the first pass of this fix used a
flat ~5-scene guess no matter the plan's own `video_length_minutes` — a 20-30
min plan showed the SAME "≈$1.50" a 1-min plan showed, then spent several
times that once pictures actually generated. Fixed by threading
`video_length_minutes` through `estimate_plan_cost`, which derives the real
scene count via `VideoConfig.act_count`
(`skills/video-pipeline/orchestrator/pipeline_config.py:53` —
`max(3, min(6, video_length_minutes // 2)) if video_length_minutes >= 3 else
1`) — the SAME formula the live script generator already targets (traced:
`VideoConfig` -> `generate_script`'s "Structure it in {act_count} acts" ->
`_write_script_records` writes one `scripts` row per act -> that row count IS
`video_summary()`'s "scenes"). No new ratio invented, imported verbatim.
`video_length_minutes=None` keeps the exact pre-existing flat-guess behavior.

Four layers pinned here:
  1. `actions.estimate_plan_cost()` returns EXACTLY what `actions.estimate_cost`
     itself would return for the identical synthetic summary — one resolver,
     no parallel math, no hardcoded price.
  2. Length-aware scaling: a short plan (1 min) and a long plan (20 min)
     produce different, monotonically-scaling estimates; `None` (no length
     picked yet) falls back to the original flat guess unchanged.
  3. `routes.chat._stamp_plan_estimate()` stamps the plan with that exact,
     length-derived cost + scene count when a plan is present, no-ops (no
     KeyError, no mutation) when it isn't — covers the "asking" phase turns
     that never have plan==None.
  4. Source lock: BOTH home-producer plan-emission call sites (`_seed_producer`
     and the main intake turn inside `chat_turn`) call `_stamp_plan_estimate`
     before returning — the "Make it" gap can't reopen by drifting one call
     site out of sync with the other (same pattern C04's
     test_producer_kie_fallback.py uses for `_resolve_producer_client`).

Same stub pattern as test_producer_kie_fallback.py: no network, no DB.
Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c15a_plan_cost_quote.py -q
"""
import asyncio
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

import actions  # noqa: E402
import routes.chat as chat  # noqa: E402

SHOTS_PER_SCENE = 6
FALLBACK_SCENES_GUESS = 5  # actions.estimate_cost's own "scenes or 5" fallback


def _pipeline_root():
    return os.path.abspath(os.path.join(_BACKEND, "..", "..", "skills", "video-pipeline"))


sys.path.insert(0, _pipeline_root())
from orchestrator.pipeline_config import VideoConfig  # noqa: E402  (the REAL derivation, imported not re-implemented)


def _expected_cost_for_scenes(scenes: int) -> float:
    """The SAME formula actions.estimate_cost's 'build' verb already uses for a
    fresh idea_logged/pre-script video — duplicated here only as the test's own
    independent expectation, never imported into product code."""
    return round(scenes * SHOTS_PER_SCENE * actions.PICTURE_COST, 2)


def test_estimate_plan_cost_matches_estimate_cost_directly_when_length_unknown():
    """No parallel math: with no length given, actions.estimate_plan_cost()
    must return exactly what calling actions.estimate_cost() with the same
    synthetic pre-creation summary returns — proving estimate_plan_cost is a
    thin wrapper, not a second cost formula, and that the None-length path is
    the untouched pre-existing behavior."""
    cost, text, scenes = asyncio.run(actions.estimate_plan_cost())

    summary = {"model": "grok-imagine", "status": "idea_logged", "scenes": 0, "pics": 0}
    direct_cost, direct_text = asyncio.run(
        actions.estimate_cost(None, None, "build", None, summary)
    )

    assert cost == direct_cost, f"estimate_plan_cost drifted from estimate_cost: {cost} != {direct_cost}"
    assert text == direct_text
    assert scenes == FALLBACK_SCENES_GUESS
    assert cost == _expected_cost_for_scenes(FALLBACK_SCENES_GUESS), (
        f"expected the pre-pictures guess (~{FALLBACK_SCENES_GUESS} scenes x "
        f"{SHOTS_PER_SCENE} shots x PICTURE_COST) = {_expected_cost_for_scenes(FALLBACK_SCENES_GUESS)}, got {cost}"
    )
    print("✅ test_estimate_plan_cost_matches_estimate_cost_directly_when_length_unknown")


def test_estimate_plan_cost_never_zero_or_negative():
    """A sanity floor: this is real paid picture generation, the quote must
    read as a real dollar figure, never '$0.00' or negative."""
    cost, text, scenes = asyncio.run(actions.estimate_plan_cost())
    assert cost > 0
    assert scenes > 0
    assert text.startswith("~$")
    print("✅ test_estimate_plan_cost_never_zero_or_negative")


def test_estimate_plan_cost_uses_the_real_video_config_act_count():
    """Scene count is sourced from the SAME VideoConfig.act_count the live
    script generator targets (no independently-invented ratio) — for every
    length, estimate_plan_cost's scenes must equal VideoConfig(minutes).act_count
    exactly, and the dollar figure must equal scenes * 6 * PICTURE_COST."""
    for minutes in (1, 3, 5, 10, 12, 20, 30):
        cost, text, scenes = asyncio.run(actions.estimate_plan_cost(minutes))
        expected_scenes = VideoConfig(video_length_minutes=minutes).act_count
        assert scenes == expected_scenes, (
            f"minutes={minutes}: estimate_plan_cost scenes={scenes} != "
            f"VideoConfig.act_count={expected_scenes}"
        )
        assert cost == _expected_cost_for_scenes(expected_scenes)
        assert text == ("no extra cost" if cost <= 0 else f"~${cost:.2f}")
    print("✅ test_estimate_plan_cost_uses_the_real_video_config_act_count")


def test_estimate_plan_cost_scales_monotonically_with_length():
    """The orchestrator-review fix itself: a long plan must quote AT LEAST as
    much as a short plan, and a genuinely long plan (20 min) must quote MORE
    than a short one (1 min) — pinning that length now actually moves the
    number, not just that the plumbing accepts a minutes argument."""
    lengths = (1, 3, 5, 10, 12, 20, 30)
    costs = [asyncio.run(actions.estimate_plan_cost(m))[0] for m in lengths]
    for earlier, later in zip(costs, costs[1:]):
        assert later >= earlier, f"cost regressed as length grew: {costs} over {lengths}"
    assert costs[-1] > costs[0], (
        f"a 30-min plan ({costs[-1]}) must quote more than a 1-min plan ({costs[0]}) — "
        "this is the exact bug the orchestrator review flagged"
    )
    print("✅ test_estimate_plan_cost_scales_monotonically_with_length")


def test_estimate_plan_cost_caps_at_six_scenes_past_twelve_minutes():
    """Honest cap, not silently hidden: VideoConfig.act_count maxes at 6, so a
    20-min and a 30-min plan quote the SAME figure as a 12-min plan — a real
    property of the live formula (act_count = max(3, min(6, minutes // 2))),
    not a regression of this fix."""
    cost_12, _, scenes_12 = asyncio.run(actions.estimate_plan_cost(12))
    cost_20, _, scenes_20 = asyncio.run(actions.estimate_plan_cost(20))
    cost_30, _, scenes_30 = asyncio.run(actions.estimate_plan_cost(30))
    assert scenes_12 == scenes_20 == scenes_30 == 6
    assert cost_12 == cost_20 == cost_30
    print("✅ test_estimate_plan_cost_caps_at_six_scenes_past_twelve_minutes")


def test_stamp_plan_estimate_adds_length_scaled_quote_to_plan():
    """The card-facing stamp: given a producer turn with a plan carrying a
    real video_length_minutes, the plan gains an honest, length-scaled,
    actions.estimate_cost-sourced quote that names its own scene count."""
    data = {
        "assistant_text": "Here's the plan.",
        "phase": "plan",
        "plan": {
            "story_concept": "A dragon finds a lonely owner.",
            "spec": {"title": "The Dragon's Friend", "video_length_minutes": 20},
        },
    }
    asyncio.run(chat._stamp_plan_estimate(data))

    plan = data["plan"]
    expected_cost, _, expected_scenes = asyncio.run(actions.estimate_plan_cost(20))
    assert plan.get("estimated_cost") == expected_cost
    assert expected_scenes == 6  # sanity: 20 min hits the act_count cap
    assert isinstance(plan.get("estimated_cost_text"), str) and plan["estimated_cost_text"]
    # Honest, hedged wording (spec: "≈"/"about", never a bare bald number) that
    # names its own scene count so the figure is self-explaining.
    assert "≈" in plan["estimated_cost_text"]
    assert f"${expected_cost:.2f}" in plan["estimated_cost_text"]
    assert f"~{expected_scenes} scenes" in plan["estimated_cost_text"]
    # The spec/title fields the producer wrote are untouched.
    assert plan["spec"]["title"] == "The Dragon's Friend"
    print("✅ test_stamp_plan_estimate_adds_length_scaled_quote_to_plan")


def test_stamp_plan_estimate_short_vs_long_plan_quote_differently():
    """The exact regression the orchestrator review caught: a 1-min plan and
    a 20-min plan must NOT show the same estimated_cost_text."""
    def _stamped(minutes):
        data = {"phase": "plan", "plan": {"spec": {"video_length_minutes": minutes}}}
        asyncio.run(chat._stamp_plan_estimate(data))
        return data["plan"]["estimated_cost"], data["plan"]["estimated_cost_text"]

    short_cost, short_text = _stamped(1)
    long_cost, long_text = _stamped(20)
    assert short_cost < long_cost, f"expected 1-min < 20-min, got {short_cost} vs {long_cost}"
    assert short_text != long_text
    print("✅ test_stamp_plan_estimate_short_vs_long_plan_quote_differently")


def test_stamp_plan_estimate_falls_back_to_default_when_length_missing():
    """No video_length_minutes on the spec (or no spec at all) -> the exact
    pre-existing flat-guess behavior, not a crash or a zero."""
    data_no_spec = {"phase": "plan", "plan": {"story_concept": "x"}}
    asyncio.run(chat._stamp_plan_estimate(data_no_spec))
    fallback_cost, _, fallback_scenes = asyncio.run(actions.estimate_plan_cost())
    assert data_no_spec["plan"]["estimated_cost"] == fallback_cost
    assert f"~{fallback_scenes} scenes" in data_no_spec["plan"]["estimated_cost_text"]

    data_no_minutes = {"phase": "plan", "plan": {"spec": {"title": "no length yet"}}}
    asyncio.run(chat._stamp_plan_estimate(data_no_minutes))
    assert data_no_minutes["plan"]["estimated_cost"] == fallback_cost
    print("✅ test_stamp_plan_estimate_falls_back_to_default_when_length_missing")


def test_stamp_plan_estimate_noop_without_a_plan():
    """An 'asking' phase turn (no plan yet, still gathering the look/length)
    must pass through completely untouched -- no KeyError, no plan conjured
    out of nothing."""
    data = {"assistant_text": "What's the video about?", "phase": "asking"}
    asyncio.run(chat._stamp_plan_estimate(data))
    assert "plan" not in data
    print("✅ test_stamp_plan_estimate_noop_without_a_plan")


def test_stamp_plan_estimate_noop_on_malformed_plan():
    """A plan that isn't a dict (defensive: producer JSON is LLM-authored) must
    not raise -- same fail-soft posture as _annotate_style_recommendation."""
    data = {"assistant_text": "ok", "phase": "plan", "plan": "not-a-dict"}
    asyncio.run(chat._stamp_plan_estimate(data))  # must not raise
    assert data["plan"] == "not-a-dict"  # untouched
    print("✅ test_stamp_plan_estimate_noop_on_malformed_plan")


def test_backward_compat_legacy_plan_payload_has_no_estimate_keys():
    """A plan dict shaped like one persisted BEFORE this fix (no estimated_cost
    keys at all) is exactly what an old conversation's transcript replay looks
    like. Nothing in the stamping helper requires those keys to already exist,
    and the plan dict is otherwise unchanged -- the frontend fail-safe (an
    older or newer build reading an old payload) has a real payload to match
    against, not a hypothetical one."""
    legacy_plan = {
        "story_concept": "An old plan from before C15a.",
        "recommended_titles": ["A Title"],
        "spec": {"title": "A Title", "video_length_minutes": 3},
    }
    assert "estimated_cost" not in legacy_plan
    assert "estimated_cost_text" not in legacy_plan
    # Replaying it through history hydration paths does not go through
    # _stamp_plan_estimate at all (only fresh producer turns do) -- confirmed
    # by source: get_conversation_for_video / _persist never call it.
    src = open(os.path.join(_BACKEND, "routes", "chat.py")).read()
    hydrate_fn = src.split("async def get_conversation_for_video")[1].split("\n\n\n")[0]
    assert "_stamp_plan_estimate" not in hydrate_fn
    print("✅ test_backward_compat_legacy_plan_payload_has_no_estimate_keys")


def test_both_home_producer_plan_paths_stamp_the_estimate():
    """Source lock: BOTH home-producer plan-emission call sites call
    _stamp_plan_estimate before returning -- _seed_producer (onboarding
    hand-off) and the main intake turn inside chat_turn(). Mirrors the
    call-site-count pattern test_producer_kie_fallback.py uses for
    _resolve_producer_client, so this money-gap fix can't quietly regress by
    only covering one of the two entry points."""
    src = open(os.path.join(_BACKEND, "routes", "chat.py")).read()
    assert src.count("await _stamp_plan_estimate(data)") >= 2, (
        "expected both _seed_producer and the chat_turn intake turn to stamp "
        "the plan's cost estimate before returning"
    )
    seed_fn = src.split("async def _seed_producer")[1].split("\nasync def ")[0]
    assert "_stamp_plan_estimate(data)" in seed_fn, "_seed_producer must stamp the plan estimate"
    print("✅ test_both_home_producer_plan_paths_stamp_the_estimate")


if __name__ == "__main__":
    test_estimate_plan_cost_matches_estimate_cost_directly_when_length_unknown()
    test_estimate_plan_cost_never_zero_or_negative()
    test_estimate_plan_cost_uses_the_real_video_config_act_count()
    test_estimate_plan_cost_scales_monotonically_with_length()
    test_estimate_plan_cost_caps_at_six_scenes_past_twelve_minutes()
    test_stamp_plan_estimate_adds_length_scaled_quote_to_plan()
    test_stamp_plan_estimate_short_vs_long_plan_quote_differently()
    test_stamp_plan_estimate_falls_back_to_default_when_length_missing()
    test_stamp_plan_estimate_noop_without_a_plan()
    test_stamp_plan_estimate_noop_on_malformed_plan()
    test_backward_compat_legacy_plan_payload_has_no_estimate_keys()
    test_both_home_producer_plan_paths_stamp_the_estimate()
    print("all C15a plan-cost-quote tests passed")
