"""SUPERSEDED by C25a-fix8 (2026-07-20). This file originally pinned
C25a-fix7 Part B's SHEET_REF_CAP=2 (storyboard sheet reference images capped
at 2, dropping the LOCKED LOCATION env ref past that count) as the fix for
gpt-image-2-image-to-image 400s ("The current content could not be
processed", 0 credits) on video cd5d2883-427e-4bfb-854d-8849d025d444.

C25a-fix8 re-derived that conviction against the REAL Kie/OpenAI filter (not
a guess) and found it confounded:
  - The convicted prompt's ALL-CAPS "Professional animation PRODUCTION
    STORYBOARD SHEET" header 400s completely on its own, with ZERO refs
    beyond the trivial control set, regardless of how many input_urls ride
    along (taskId cdb23fdc2df9c230fb0acb481b5d5c4c).
  - Once that header was rewritten (see scripts/coverage_to_app.py's
    _sheet_header), a fresh probe at 3 refs (2 cast + the env ref — the
    EXACT shape fix7 blamed) SUCCEEDED (taskId
    829cfea1f9c95b4f27935375ea5a95a5).
  - Every 3-ref failure fix7's evidence cited was ALSO carrying the
    convicted header — the header rode along on every real prod call that
    day, so the ref-count correlation was real but not causal.

SHEET_REF_CAP is REMOVED. generate_storyboard_sheet_for_scene reverts to
pre-fix7 behavior: every cast ref plus the env ref (when one matches) goes
into input_urls unconditionally, same as before fix7 ever landed. These
tests now pin THAT (the revert), not the cap — same FakeDB harness as
before, so the "no cap" behavior stays regression-guarded going forward.

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c25a_fix7_gpt_sheet_ref_cap.py -q
"""
import asyncio
import json
import os
import sys
import types
from unittest.mock import AsyncMock, patch

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
_PIPELINE_PATH = os.path.join(_BACKEND, "..", "..", "..", "skills", "video-pipeline")
sys.path.insert(0, os.path.abspath(_BACKEND))
sys.path.insert(0, os.path.abspath(_PIPELINE_PATH))


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod


async def _boom(*a, **k):
    raise AssertionError("pure tests must not touch runtime services")


# Placeholders at import time; every real test overrides via
# patch("scripts.coverage_to_app.X", ...).
_stub("database", fetch_one=_boom, fetch_all=_boom, execute=_boom)
_stub("storage", upload_bytes=_boom)
_stub("vault", get_secret=_boom)
_stub("kie_unified", get_text_client_for_tenant=_boom)

from scripts.coverage_to_app import (  # noqa: E402
    generate_storyboard_sheet_for_scene, _scene_text_hash, _sheet_filter_reject,
    _sheet_transient_kie_error, _sheet_fail_class, _sheet_fail_entry,
)

VIDEO_ID = "cd5d2883-427e-4bfb-854d-8849d025d444"
TENANT_ID = "tenant-1"

# Same non-dialogue scene text test_c16b uses — _coverage_shape() deterministically
# returns (3, 2, 3, None) for it, and this directive format is proven to parse
# (test_c16b exercises it through the same parse_coverage/enforce_shot_budget calls).
SCENE_TEXT = "The city lights flicker as rain falls onto empty streets."
DIRECTIVE = (
    "[MOMENT 1 | rain falls on empty streets]\n"
    "- MASTER [WS]: Wide shot of rain-soaked streets, neon reflections shimmering.\n"
    "- ANGLE [MCU]: Close on droplets streaking down a window pane.\n"
)
SCENE_HASH = _scene_text_hash(SCENE_TEXT)

ENV = {
    "name": "Downtown Street",
    "description": "A rain-slicked downtown street at night.",
    "reference_url": "https://fake/env-downtown.png",
}


def _video_row():
    return {
        "id": VIDEO_ID, "tenant_id": TENANT_ID, "video_title": "Test Video",
        "aspect": "16:9", "image_style_override": None, "visual_style": None,
        "image_model_override": None, "render_style": None, "video_model": "grok-imagine",
        "dialogue_audio": "voice_over",
    }


class FakeDB:
    def __init__(self, cast_refs, coverage_directive=None, coverage_directive_hash=None):
        self.cast_refs = cast_refs
        # Simulates scripts.storyboard_errors (migration 113) for script-1 —
        # a plain dict keyed by beat NUMBER AS STRING, mirroring the jsonb
        # merge (COALESCE(...) || $1::jsonb) and subtract (col - $1) the real
        # UPDATEs perform, so tests can assert on final persisted state
        # instead of just call counts.
        self.storyboard_errors: dict = {}
        # A pre-saved plan (directive + matching hash) — required for the
        # PER-BOARD REDO path (beat=N): generate_storyboard_sheet_for_scene
        # refuses to redraw a single board without one already on file.
        self.coverage_directive = coverage_directive
        self.coverage_directive_hash = coverage_directive_hash

    async def fetch_one(self, query, *args):
        if "FROM videos WHERE id=$1" in query:
            return _video_row()
        if "coverage_directive, coverage_directive_hash FROM scripts" in query:
            return {"id": "script-1", "coverage_directive": self.coverage_directive,
                    "coverage_directive_hash": self.coverage_directive_hash}
        raise AssertionError(f"unexpected fetch_one query: {query}")

    async def fetch_all(self, query, *args):
        if "SELECT scene, scene_text FROM scripts" in query:
            return [{"scene": 1, "scene_text": SCENE_TEXT}]
        if "FROM video_characters" in query:
            return [{"reference_url": u} for u in self.cast_refs]
        raise AssertionError(f"unexpected fetch_all query: {query}")

    async def execute(self, query, *args):
        # A board landing: "...storyboard_{bi}_url=$1, storyboard_errors =
        # storyboard_errors - $2, updated_at=now() WHERE id=$3" — args =
        # (stable_url, beat_str, script_id). Clear that beat's entry.
        if "storyboard_errors = storyboard_errors - " in query:
            beat_key = args[-2]
            self.storyboard_errors.pop(str(beat_key), None)
        # A board exhausting the ladder: "storyboard_errors = COALESCE(...)
        # || $1::jsonb ... WHERE id=$2" — args = (json_str, script_id). Merge
        # the one-beat payload in, same as the real jsonb `||` union.
        elif "COALESCE(storyboard_errors, '{}'::jsonb) || " in query:
            self.storyboard_errors.update(json.loads(args[0]))
        # A full replan (beat=None, the STREAMING CONTRACT persist-plan step)
        # resets storyboard_errors=NULL alongside the board URLs.
        elif "storyboard_errors=NULL" in query:
            self.storyboard_errors = {}
        return "OK"


def _run(cast_refs, envs):
    """Runs generate_storyboard_sheet_for_scene end to end (real parse_coverage /
    enforce_shot_budget / _plan_sheet_prompts / _match_scene_env), capturing every
    call made to generate_scene_image_for_model — the ONE call site that actually
    ships reference_urls to Kie as input_urls."""
    fakedb = FakeDB(cast_refs)
    captured_calls = []

    async def _fake_generate_scene_image_for_model(ic, model_override, prompt,
                                                     reference_urls=None, aspect_ratio="16:9",
                                                     **kwargs):
        captured_calls.append({"prompt": prompt, "reference_urls": list(reference_urls or [])})
        return "https://fake-storage.example/board.png", "gpt-image-2"

    patches = [
        patch("scripts.coverage_to_app.fetch_one", fakedb.fetch_one),
        patch("scripts.coverage_to_app.fetch_all", fakedb.fetch_all),
        patch("scripts.coverage_to_app.execute", fakedb.execute),
        patch("scripts.coverage_to_app.get_secret", AsyncMock(return_value="fake-kie-key")),
        patch("scripts.coverage_to_app.get_text_client_for_tenant", AsyncMock(return_value=object())),
        patch("scripts.coverage_to_app.claude_model_for_direct_client", lambda c: "fake-model"),
        patch("scripts.coverage_to_app.scene_aware_bible", AsyncMock(return_value=None)),
        patch("scripts.coverage_to_app._approved_envs", AsyncMock(return_value=envs)),
        patch("scripts.coverage_to_app.generate_coverage_directive", AsyncMock(return_value=DIRECTIVE)),
        patch("scripts.coverage_to_app.generate_scene_image_for_model",
              _fake_generate_scene_image_for_model),
        patch("scripts.coverage_to_app._stable_url", AsyncMock(return_value="https://stable/final.png")),
    ]
    for p in patches:
        p.start()
    try:
        result = asyncio.run(
            generate_storyboard_sheet_for_scene(VIDEO_ID, TENANT_ID, scene=1, plan_only=False))
    finally:
        for p in patches:
            p.stop()
    assert result["status"] == "completed", result
    assert captured_calls, "generate_scene_image_for_model was never called"
    return captured_calls


def _scripted_image_fn(fail_sequence, success_url="https://fake-storage.example/board.png"):
    """A generate_scene_image_for_model stand-in that fails with each
    fail_info in `fail_sequence`, IN ORDER, one entry per call — then
    succeeds forever after the sequence is exhausted. `None` in the sequence
    means "fails with NO fail_info at all" (e.g. every attempt died before
    Kie ever reported a code). Records every call for assertions via the
    returned function's `.calls` attribute."""
    calls = []

    async def _fn(ic, model_override, prompt, reference_urls=None, aspect_ratio="16:9",
                  fail_info_out=None, **kwargs):
        calls.append({"prompt": prompt, "reference_urls": list(reference_urls or [])})
        idx = len(calls) - 1
        if idx < len(fail_sequence):
            info = fail_sequence[idx]
            if info is not None and fail_info_out is not None:
                fail_info_out.append(dict(info))
            return None, None
        return success_url, "gpt-image-2"

    _fn.calls = calls
    return _fn


def _run_with_image_fn(image_fn, cast_refs=("https://fake/cast-a.png",), envs=(), pre_errors=None,
                        beat=None):
    """Like _run(), but the caller controls generate_scene_image_for_model's
    behavior directly (to script a board exhausting the retry ladder, or
    landing after N failures) and gets the FakeDB back so its simulated
    storyboard_errors state (migration 113) can be asserted on.

    beat=N runs the PER-BOARD REDO path instead of a full replan — the only
    way to test "a board landing clears ITS entry" in isolation, since a
    full replan (beat=None) resets the WHOLE storyboard_errors column
    before the draw loop even starts (see FakeDB.execute's storyboard_
    errors=NULL branch), which would otherwise confound that assertion.
    Requires a pre-saved plan, so this seeds FakeDB with DIRECTIVE/SCENE_HASH
    (the same fixture _run() plans fresh) as the "already on file" plan."""
    fakedb = FakeDB(
        list(cast_refs),
        coverage_directive=DIRECTIVE if beat is not None else None,
        coverage_directive_hash=SCENE_HASH if beat is not None else None,
    )
    if pre_errors:
        fakedb.storyboard_errors.update(pre_errors)
    patches = [
        patch("scripts.coverage_to_app.fetch_one", fakedb.fetch_one),
        patch("scripts.coverage_to_app.fetch_all", fakedb.fetch_all),
        patch("scripts.coverage_to_app.execute", fakedb.execute),
        patch("scripts.coverage_to_app.get_secret", AsyncMock(return_value="fake-kie-key")),
        patch("scripts.coverage_to_app.get_text_client_for_tenant", AsyncMock(return_value=object())),
        patch("scripts.coverage_to_app.claude_model_for_direct_client", lambda c: "fake-model"),
        patch("scripts.coverage_to_app.scene_aware_bible", AsyncMock(return_value=None)),
        patch("scripts.coverage_to_app._approved_envs", AsyncMock(return_value=list(envs))),
        patch("scripts.coverage_to_app.generate_coverage_directive", AsyncMock(return_value=DIRECTIVE)),
        patch("scripts.coverage_to_app.generate_scene_image_for_model", image_fn),
        patch("scripts.coverage_to_app._stable_url", AsyncMock(return_value="https://stable/final.png")),
        # The transient-Kie reroll pauses 15s for real infra to recover —
        # irrelevant to a scripted fake, and would make these tests glacial.
        patch("scripts.coverage_to_app.asyncio.sleep", AsyncMock(return_value=None)),
    ]
    for p in patches:
        p.start()
    try:
        result = asyncio.run(
            generate_storyboard_sheet_for_scene(
                VIDEO_ID, TENANT_ID, scene=1, beat=beat, plan_only=False))
    finally:
        for p in patches:
            p.stop()
    return fakedb, result


# ---------------------------------------------------------------------------
# The revert: 2 cast + 1 env — the exact prod failure shape fix7 blamed on ref
# count — now reaches Kie as all 3 refs, uncapped, env ref last.
# ---------------------------------------------------------------------------

def test_two_cast_refs_plus_env_sends_all_three_uncapped():
    calls = _run(cast_refs=["https://fake/cast-a.png", "https://fake/cast-b.png"], envs=[ENV])
    refs = calls[0]["reference_urls"]
    assert refs == ["https://fake/cast-a.png", "https://fake/cast-b.png", ENV["reference_url"]], refs


def test_env_locked_location_text_and_ref_both_present():
    calls = _run(cast_refs=["https://fake/cast-a.png", "https://fake/cast-b.png"], envs=[ENV])
    assert "LOCKED LOCATION" in calls[0]["prompt"]
    assert ENV["name"] in calls[0]["prompt"]
    assert ENV["reference_url"] in calls[0]["reference_urls"]


def test_one_cast_ref_plus_env_both_sent():
    calls = _run(cast_refs=["https://fake/cast-a.png"], envs=[ENV])
    refs = calls[0]["reference_urls"]
    assert refs == ["https://fake/cast-a.png", ENV["reference_url"]], refs


def test_no_env_two_cast_refs_unaffected():
    calls = _run(cast_refs=["https://fake/cast-a.png", "https://fake/cast-b.png"], envs=[])
    refs = calls[0]["reference_urls"]
    assert refs == ["https://fake/cast-a.png", "https://fake/cast-b.png"]
    assert "LOCKED LOCATION" not in calls[0]["prompt"]


def test_three_cast_refs_no_env_all_sent_uncapped():
    """Cast alone can exceed the old cap of 2 (3+ characters, no env at all) —
    fix8 proved the cap was never the real fix, so all cast refs now go
    through, same as pre-fix7."""
    calls = _run(
        cast_refs=["https://fake/cast-a.png", "https://fake/cast-b.png", "https://fake/cast-c.png"],
        envs=[])
    refs = calls[0]["reference_urls"]
    assert refs == ["https://fake/cast-a.png", "https://fake/cast-b.png", "https://fake/cast-c.png"]


# ---------------------------------------------------------------------------
# _sheet_filter_reject: widened to the 422 "flagged as sensitive" class
# (2026-07-20 prod sweep, taskId 9b5af734f2455c8cbf39422142396051 — Kie
# rejects with failCode "422", failMsg "CONTENT_POLICY_BLOCKED: The input or
# output was flagged as sensitive...", creditsConsumed 0.0). Same zero-cost
# moderation class as the original failCode "400" signature; previously got
# no fallback-header retry and no free re-rolls. The 0-credit guard must
# still block ANY credit-consuming failure regardless of failCode.
# ---------------------------------------------------------------------------

def test_400_known_msg_zero_credits_accepted():
    assert _sheet_filter_reject({
        "failCode": "400", "failMsg": "The current content could not be processed",
        "creditsConsumed": 0.0,
    }) is True


def test_400_other_known_msg_zero_credits_accepted():
    assert _sheet_filter_reject({
        "failCode": "400",
        "failMsg": "Sorry, but the image we created may violate OpenAI's content policies",
        "creditsConsumed": 0.0,
    }) is True


def test_422_flagged_as_sensitive_zero_credits_accepted():
    assert _sheet_filter_reject({
        "failCode": "422",
        "failMsg": "CONTENT_POLICY_BLOCKED: The input or output was flagged as sensitive.",
        "creditsConsumed": 0.0,
    }) is True


def test_422_with_credits_consumed_rejected():
    """The 0-credit guard is mandatory — a 422 that actually spent money must
    NEVER qualify for the free retry/re-roll, even with the right message."""
    assert _sheet_filter_reject({
        "failCode": "422",
        "failMsg": "CONTENT_POLICY_BLOCKED: The input or output was flagged as sensitive.",
        "creditsConsumed": 0.5,
    }) is False


def test_400_with_credits_consumed_still_rejected():
    """Pre-existing 400 guard stays intact after widening to 422."""
    assert _sheet_filter_reject({
        "failCode": "400", "failMsg": "The current content could not be processed",
        "creditsConsumed": 1.2,
    }) is False


def test_unknown_failcode_rejected():
    assert _sheet_filter_reject({
        "failCode": "500", "failMsg": "flagged as sensitive", "creditsConsumed": 0.0,
    }) is False


def test_none_fail_info_rejected():
    assert _sheet_filter_reject(None) is False


# ---------------------------------------------------------------------------
# _sheet_transient_kie_error: Kie's transient infra 500 (2026-07-21, taskId
# a6136814f87ff94972011a80dc1e2ce8 — failCode "500", failMsg "Internal Error,
# Please try again later.", creditsConsumed 0.0, costTime 0; Kie's
# Seedance-launch-day instability, 4 of the last 7 sheet failures). Distinct
# from content moderation: it joins the free re-roll ladder (with a pause),
# never the fallback-header retry, and the two predicates must never both
# claim the same failure.
# ---------------------------------------------------------------------------

def test_transient_500_zero_credits_is_transient_not_filter():
    info = {
        "failCode": "500", "failMsg": "Internal Error, Please try again later.",
        "creditsConsumed": 0.0, "costTime": 0,
    }
    assert _sheet_transient_kie_error(info) is True
    assert _sheet_filter_reject(info) is False


def test_transient_500_none_credits_counts_as_zero():
    """None creditsConsumed counts as 0, same as _sheet_filter_reject."""
    assert _sheet_transient_kie_error({
        "failCode": "500", "failMsg": "Internal Error, Please try again later.",
        "creditsConsumed": None,
    }) is True


def test_500_with_credits_consumed_is_neither():
    """The mandatory ~0-credit guard: a 500 that actually spent money must
    never qualify for ANY free retry, transient or filter."""
    info = {
        "failCode": "500", "failMsg": "Internal Error, Please try again later.",
        "creditsConsumed": 0.5,
    }
    assert _sheet_transient_kie_error(info) is False
    assert _sheet_filter_reject(info) is False


def test_400_policy_is_filter_not_transient():
    """The two predicates never both claim a failure: a content-policy 400 is
    the filter's, not the transient predicate's."""
    info = {
        "failCode": "400", "failMsg": "The current content could not be processed",
        "creditsConsumed": 0.0,
    }
    assert _sheet_filter_reject(info) is True
    assert _sheet_transient_kie_error(info) is False


def test_transient_none_and_wrong_msg_rejected():
    assert _sheet_transient_kie_error(None) is False
    # A 500 whose message is NOT the internal-error signature stays unclaimed
    # (e.g. the moderation-worded 500 test_unknown_failcode_rejected pins).
    assert _sheet_transient_kie_error({
        "failCode": "500", "failMsg": "flagged as sensitive", "creditsConsumed": 0.0,
    }) is False


# ---------------------------------------------------------------------------
# _sheet_fail_class / _sheet_fail_entry (migration 113): the per-board
# storyboard_errors classifier. Pure-function pins first, then the
# end-to-end FakeDB tests below prove the SAME classification lands in the
# persisted jsonb column when a board actually exhausts the ladder.
# ---------------------------------------------------------------------------

def test_sheet_fail_class_400_is_moderation():
    assert _sheet_fail_class({
        "failCode": "400", "failMsg": "The current content could not be processed",
        "creditsConsumed": 0.0,
    }) == "moderation"


def test_sheet_fail_class_422_is_sensitive():
    assert _sheet_fail_class({
        "failCode": "422",
        "failMsg": "CONTENT_POLICY_BLOCKED: The input or output was flagged as sensitive.",
        "creditsConsumed": 0.0,
    }) == "sensitive"


def test_sheet_fail_class_500_transient_is_kie_transient():
    assert _sheet_fail_class({
        "failCode": "500", "failMsg": "Internal Error, Please try again later.",
        "creditsConsumed": 0.0,
    }) == "kie_transient"


def test_sheet_fail_class_credit_consuming_failure_is_unknown():
    """A REAL (credit-consuming) failure never qualifies for either free-retry
    predicate — it's a genuine error, not a free coin-flip — so it stays
    'unknown' rather than being mislabeled as moderation/transient."""
    assert _sheet_fail_class({
        "failCode": "400", "failMsg": "The current content could not be processed",
        "creditsConsumed": 1.2,
    }) == "unknown"


def test_sheet_fail_class_none_is_unknown():
    assert _sheet_fail_class(None) == "unknown"


def test_sheet_fail_entry_shape_truncates_msg_and_stamps_timestamp():
    # Real moderation signature, padded well past the ~200-char truncation —
    # a filler suffix that carries none of _sheet_filter_reject's own
    # keywords, so this pins truncation without smuggling in a second signal.
    long_msg = "The current content could not be processed" + (" filler" * 60)
    entry = _sheet_fail_entry(
        {"failCode": "400", "failMsg": long_msg, "creditsConsumed": 0.0}, attempts=2)
    assert entry["class"] == "moderation"
    assert entry["code"] == "400"
    assert len(entry["msg"]) <= 200
    assert entry["msg"] == long_msg[:200]
    assert entry["attempts"] == 2
    assert "T" in entry["at"]  # ISO 8601 timestamp shape


def test_sheet_fail_entry_none_fail_info_has_null_code_and_msg():
    entry = _sheet_fail_entry(None, attempts=1)
    assert entry["class"] == "unknown"
    assert entry["code"] is None
    assert entry["msg"] is None
    assert entry["attempts"] == 1


# ---------------------------------------------------------------------------
# End to end (FakeDB harness): a board that exhausts the full retry/re-roll
# ladder persists a classified entry with the real attempt count; a board
# that lands clears any prior entry. Same SCENE_TEXT/DIRECTIVE fixture as
# above, which plans exactly ONE board (beat "1") for this scene.
# ---------------------------------------------------------------------------

_MODERATION_400 = {
    "failCode": "400", "failMsg": "The current content could not be processed",
    "creditsConsumed": 0.0,
}
_SENSITIVE_422 = {
    "failCode": "422",
    "failMsg": "CONTENT_POLICY_BLOCKED: The input or output was flagged as sensitive.",
    "creditsConsumed": 0.0,
}
_TRANSIENT_500 = {
    "failCode": "500", "failMsg": "Internal Error, Please try again later.",
    "creditsConsumed": 0.0,
}


def test_exhausted_ladder_writes_moderation_entry_with_attempts():
    """A 400 filter-reject on every call rides the WHOLE ladder — primary +
    the fallback-header retry + 3 free re-rolls = 5 calls — and, never
    landing, persists a 'moderation' entry with attempts=5."""
    fn = _scripted_image_fn([_MODERATION_400] * 5)
    fakedb, result = _run_with_image_fn(fn)
    assert result["status"] == "completed", result
    assert len(fn.calls) == 5, len(fn.calls)
    entry = fakedb.storyboard_errors.get("1")
    assert entry, fakedb.storyboard_errors
    assert entry["class"] == "moderation"
    assert entry["code"] == "400"
    assert entry["attempts"] == 5
    assert "could not be processed" in entry["msg"]
    assert entry["at"]


def test_exhausted_ladder_writes_sensitive_entry_for_422():
    """The 422 'flagged as sensitive' signature classifies as 'sensitive',
    not 'moderation' — same _sheet_filter_reject gate, split by failCode."""
    fn = _scripted_image_fn([_SENSITIVE_422] * 5)
    fakedb, result = _run_with_image_fn(fn)
    assert result["status"] == "completed", result
    entry = fakedb.storyboard_errors.get("1")
    assert entry["class"] == "sensitive"
    assert entry["code"] == "422"
    assert entry["attempts"] == 5


def test_exhausted_ladder_writes_kie_transient_entry_for_500():
    """A Kie transient 500 never gets the fallback-header retry (filter-only)
    — just primary + 3 re-rolls = 4 calls — and classifies 'kie_transient'."""
    fn = _scripted_image_fn([_TRANSIENT_500] * 4)
    fakedb, result = _run_with_image_fn(fn)
    assert result["status"] == "completed", result
    assert len(fn.calls) == 4, len(fn.calls)
    entry = fakedb.storyboard_errors.get("1")
    assert entry["class"] == "kie_transient"
    assert entry["code"] == "500"
    assert entry["attempts"] == 4


def test_no_fail_info_ever_captured_is_unknown_and_does_not_retry():
    """A failure with NO fail_info at all (every attempt died before Kie ever
    reported a code) classifies 'unknown' rather than guessing — and neither
    free-retry predicate claims a None fail_info, so it's exactly 1 attempt,
    never the full ladder."""
    fn = _scripted_image_fn([None])
    fakedb, result = _run_with_image_fn(fn)
    assert result["status"] == "completed", result
    assert len(fn.calls) == 1, len(fn.calls)
    entry = fakedb.storyboard_errors.get("1")
    assert entry["class"] == "unknown"
    assert entry["code"] is None
    assert entry["attempts"] == 1


def test_board_that_lands_clears_prior_error_entry():
    """A per-board REDO (beat=1) that lands (first try) clears ANY
    pre-existing storyboard_errors entry for that beat — a stale chip must
    never survive a successful redraw. Uses beat=N specifically (not a full
    replan) so the assertion isolates the PER-BOARD clear this chunk adds,
    rather than the full-replan's own storyboard_errors=NULL reset."""
    fn = _scripted_image_fn([])  # succeeds immediately, no failures at all
    fakedb, result = _run_with_image_fn(fn, beat=1, pre_errors={"1": {
        "code": "400", "class": "moderation", "msg": "stale", "attempts": 3,
        "at": "2026-07-20T00:00:00+00:00",
    }})
    assert result["status"] == "completed", result
    assert "1" not in fakedb.storyboard_errors, fakedb.storyboard_errors


def test_board_that_lands_after_failures_still_clears_entry():
    """Same as above (per-board redo, beat=1), but the board fails twice (a
    real moderation signature) before landing on re-roll — the eventual
    SUCCESS still wins and clears the slot, matching 'when a board LANDS,
    delete its key' exactly (no entry is ever written for a board that
    lands, however many tries it took)."""
    fn = _scripted_image_fn([_MODERATION_400, _MODERATION_400])
    fakedb, result = _run_with_image_fn(fn, beat=1, pre_errors={"1": {
        "code": "422", "class": "sensitive", "msg": "stale", "attempts": 1,
        "at": "2026-07-20T00:00:00+00:00",
    }})
    assert result["status"] == "completed", result
    assert len(fn.calls) == 3, len(fn.calls)  # primary + fallback, both fail; re-roll 1 lands
    assert "1" not in fakedb.storyboard_errors, fakedb.storyboard_errors


if __name__ == "__main__":
    test_two_cast_refs_plus_env_sends_all_three_uncapped()
    test_env_locked_location_text_and_ref_both_present()
    test_one_cast_ref_plus_env_both_sent()
    test_no_env_two_cast_refs_unaffected()
    test_three_cast_refs_no_env_all_sent_uncapped()
    test_400_known_msg_zero_credits_accepted()
    test_400_other_known_msg_zero_credits_accepted()
    test_422_flagged_as_sensitive_zero_credits_accepted()
    test_422_with_credits_consumed_rejected()
    test_400_with_credits_consumed_still_rejected()
    test_unknown_failcode_rejected()
    test_none_fail_info_rejected()
    test_transient_500_zero_credits_is_transient_not_filter()
    test_transient_500_none_credits_counts_as_zero()
    test_500_with_credits_consumed_is_neither()
    test_400_policy_is_filter_not_transient()
    test_transient_none_and_wrong_msg_rejected()
    print("\nAll C25a-fix7-Part-B-revert (C25a-fix8) tests passed.")
