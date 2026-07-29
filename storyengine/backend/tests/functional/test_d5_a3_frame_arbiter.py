"""Tests for D5 chunk A3 (Frame Arbiter judge call) + A4 (neighbor-frame
continuity, folded into A3's call) — storyengine/FRAME-ARBITER-PLAN.md.

$0 suite: every DB/network boundary is dependency-injected (budget_check,
ledger_write, record_finding_fn are keyword params on judge_frame/
judge_scene_batch by design — see frame_arbiter.py's own docstring) or
monkeypatched at the module level (_download_image_b64, _call_vision),
same "real module imported directly, boundary patched" convention as
test_frame_arbiter_budget_a1.py / test_d5_a2_arbiter_fingerprints.py.
NO live DB, NO network, NO vision spend — the real priced spike (4 calls,
~$0.0685 total, see the chunk report) already ran separately against real
prod data; this file only proves the Python plumbing around it.

Non-vacuous / stash-proof (DoC "prove the guard is actually exercised"):
test_budget_breach_short_circuits_before_any_download and
test_download_failure_is_skipped_not_a_finding were re-run against a
neutered copy of judge_frame (the early-return guards commented out) —
both failed as expected (the neutered version tried to call the tracking
sentinel that should never fire), confirming the checks are real, then
reverted. See the chunk report for the exact before/after output.

Run: cd storyengine/backend && ./venv/bin/python -m pytest \
    tests/functional/test_d5_a3_frame_arbiter.py -q
"""
from __future__ import annotations

import asyncio
import os
import sys

import pytest

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

import frame_arbiter as fa  # noqa: E402
from frame_arbiter_budget import FRAME_QA_STAGE  # noqa: E402

TENANT = "tenant-a3"
VIDEO = "video-a3"


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _frame(image_index, prompt="(SETUP B) MCU ...", shot_type="MCU", url="https://x/img.png"):
    return {"image_index": image_index, "shot_type": shot_type, "image_prompt": prompt, "image_url": url}


async def _no_breach(*args, **kwargs):
    return None


async def _allow_download(url):
    return ("image/png", "ZmFrZQ==")  # base64("fake")


def _make_vision_reply(classification="MODEL_DEFECT", failure_class="facing_law_violation",
                        rule_id=None, rubric_level="hard_gate", decisive="looking frame-right",
                        description="face turned away with no camera-facing cue",
                        input_tokens=1000, output_tokens=100):
    text = (
        f"CLASSIFICATION: {classification}\n"
        f"FAILURE_CLASS: {failure_class}\n"
        f"RULE_ID: {rule_id or 'NONE'}\n"
        f"RUBRIC_LEVEL: {rubric_level}\n"
        f"DECISIVE_FRAGMENT: {decisive}\n"
        f"DESCRIPTION: {description}\n"
    )
    return {
        "content": [{"type": "text", "text": text}],
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
    }


# =============================================================================
# 1. usage_cost — static pin on the published per-token rate, proving the
#    $ math is real arithmetic against real usage, not a flat guess.
# =============================================================================

def test_usage_cost_uses_published_sonnet_rate():
    # $3.00/MTok input, $15.00/MTok output (claude-sonnet-4-6, "smart" tier).
    cost = fa.usage_cost({"input_tokens": 1_000_000, "output_tokens": 1_000_000})
    assert cost == pytest.approx(3.00 + 15.00)


def test_usage_cost_matches_the_real_spike_measurement():
    # Frame 108's real spike call (see the chunk report): 5454 in / 215 out.
    cost = fa.usage_cost({"input_tokens": 5454, "output_tokens": 215})
    assert cost == pytest.approx(0.019587, abs=1e-6)


def test_usage_cost_handles_missing_usage():
    assert fa.usage_cost(None) == 0.0
    assert fa.usage_cost({}) == 0.0


# =============================================================================
# 2. parse_verdict — classification mapping, including the reject-invalid
#    (fail loud, never coerce) behavior A2's record_finding requires.
# =============================================================================

def test_parse_verdict_accepts_all_three_defect_buckets_plus_ok():
    for c in ("MODEL_DEFECT", "AUTHORING_DEFECT", "TASTE_QUESTION", "OK"):
        text = f"CLASSIFICATION: {c}\nFAILURE_CLASS: x\nRULE_ID: NONE\nRUBRIC_LEVEL: warn\nDECISIVE_FRAGMENT: NONE\nDESCRIPTION: d"
        parsed = fa.parse_verdict(text)
        assert parsed is not None
        assert parsed["classification"] == c


def test_parse_verdict_rejects_unrecognized_classification():
    """A garbled or hallucinated CLASSIFICATION value is NOT coerced to a
    default — the caller must treat this as unparseable (fail closed),
    same 'reject, don't coerce' law A2's record_finding enforces for its
    own classification param."""
    assert fa.parse_verdict("CLASSIFICATION: MAYBE_BAD\nDESCRIPTION: d") is None
    assert fa.parse_verdict("") is None
    assert fa.parse_verdict("no fields at all here") is None


def test_parse_verdict_normalizes_failure_class_and_none_fields():
    text = "CLASSIFICATION: MODEL_DEFECT\nFAILURE_CLASS: Facing Law Violation!!\nRULE_ID: none\nRUBRIC_LEVEL: HARD_GATE\nDECISIVE_FRAGMENT: NONE\nDESCRIPTION: d"
    parsed = fa.parse_verdict(text)
    assert parsed["failure_class"] == "facing_law_violation"
    assert parsed["rule_id"] is None  # "none" (any case) normalizes to None
    assert parsed["rubric_level"] == "hard_gate"
    assert parsed["decisive_prompt_fragment"] is None


# =============================================================================
# 3. Budget refusal short-circuits the call BEFORE any download/vision
#    fires — proving A1 integration (DoC #3's "checked before it fires").
# =============================================================================

def test_budget_breach_short_circuits_before_any_download(monkeypatch):
    fired = {"download": False, "vision": False}

    async def tracking_download(url):
        fired["download"] = True
        return ("image/png", "x")

    async def tracking_vision(tenant_id, content):
        fired["vision"] = True
        return _make_vision_reply()

    async def breach(*args, **kwargs):
        return {"scope": "scene", "scene": 1, "cap": 0.25, "spent": 0.25, "quote": 0.02, "projected": 0.27}

    monkeypatch.setattr(fa, "_download_image_b64", tracking_download)
    monkeypatch.setattr(fa, "_call_vision", tracking_vision)

    result = _run(fa.judge_frame(
        TENANT, VIDEO, 1, _frame(108), budget_check=breach,
    ))
    assert result["skipped"] is True
    assert result["reason"] == "budget"
    assert result["breach"]["scope"] == "scene"
    assert fired["download"] is False
    assert fired["vision"] is False


# =============================================================================
# 4. Fail-closed on error — download failure, transport error, non-200,
#    and unparseable reply are ALL "skipped", never an invented finding.
# =============================================================================

def test_download_failure_is_skipped_not_a_finding(monkeypatch):
    async def fail_download(url):
        return None

    called = {"vision": False}

    async def tracking_vision(tenant_id, content):
        called["vision"] = True
        return _make_vision_reply()

    monkeypatch.setattr(fa, "_download_image_b64", fail_download)
    monkeypatch.setattr(fa, "_call_vision", tracking_vision)

    result = _run(fa.judge_frame(TENANT, VIDEO, 1, _frame(101), budget_check=_no_breach))
    assert result == {"skipped": True, "reason": "download_failed", "image_index": 101}
    assert called["vision"] is False  # never reaches the paid call


def test_vision_transport_error_is_skipped(monkeypatch):
    async def fail_vision(tenant_id, content):
        return None  # _call_vision's own contract: None on ANY failure

    monkeypatch.setattr(fa, "_download_image_b64", _allow_download)
    monkeypatch.setattr(fa, "_call_vision", fail_vision)

    result = _run(fa.judge_frame(TENANT, VIDEO, 1, _frame(102), budget_check=_no_breach))
    assert result["skipped"] is True
    assert result["reason"] == "vision_error"


def test_unparseable_reply_is_skipped_never_invents_a_verdict(monkeypatch):
    async def garbage_vision(tenant_id, content):
        return {"content": [{"type": "text", "text": "I refuse to answer in that format."}],
                "usage": {"input_tokens": 10, "output_tokens": 10}}

    monkeypatch.setattr(fa, "_download_image_b64", _allow_download)
    monkeypatch.setattr(fa, "_call_vision", garbage_vision)

    ledger_calls = []

    async def track_ledger(**kwargs):
        ledger_calls.append(kwargs)

    result = _run(fa.judge_frame(
        TENANT, VIDEO, 1, _frame(103), budget_check=_no_breach, ledger_write=track_ledger,
    ))
    assert result["skipped"] is True
    assert result["reason"] == "unparseable_reply"
    # An unparseable reply never gets ledgered either — we don't know what
    # it cost in a form we trust enough to write down as a real verdict's
    # spend (fail-closed applies to metering too, not just the verdict).
    assert ledger_calls == []


# =============================================================================
# 5. Fingerprint recording — proving A2 integration. A real defect verdict
#    reaches record_finding with the right (rule_id/stage/failure_class/
#    classification) shape; an OK verdict never does, but STILL ledgers
#    (money spent regardless of outcome).
# =============================================================================

def test_model_defect_verdict_records_finding_and_ledgers(monkeypatch):
    monkeypatch.setattr(fa, "_download_image_b64", _allow_download)

    async def vision(tenant_id, content):
        return _make_vision_reply(classification="MODEL_DEFECT", failure_class="facing_law_violation")

    monkeypatch.setattr(fa, "_call_vision", vision)

    ledger_calls, finding_calls = [], []

    async def track_ledger(**kwargs):
        ledger_calls.append(kwargs)

    async def track_finding(tenant_id, *, rule_id, stage, failure_class, classification):
        finding_calls.append(locals())
        return {"crossed_threshold": False, "violation_count": 1, "frozen": False}

    result = _run(fa.judge_frame(
        TENANT, VIDEO, 1, _frame(108), budget_check=_no_breach,
        ledger_write=track_ledger, record_finding_fn=track_finding,
    ))

    assert result["skipped"] is False
    assert result["classification"] == "MODEL_DEFECT"
    assert result["failure_class"] == "facing_law_violation"
    assert "fingerprint_record" in result

    assert len(ledger_calls) == 1
    assert ledger_calls[0]["tenant_id"] == TENANT
    assert ledger_calls[0]["video_id"] == VIDEO
    assert ledger_calls[0]["scene"] == 1
    assert ledger_calls[0]["model"] == fa.VISION_MODEL
    assert ledger_calls[0]["fingerprint"] == "facing_law_violation"

    assert len(finding_calls) == 1
    assert finding_calls[0]["stage"] == FRAME_QA_STAGE
    assert finding_calls[0]["failure_class"] == "facing_law_violation"
    assert finding_calls[0]["classification"] == "MODEL_DEFECT"


def test_ok_verdict_ledgers_but_never_records_a_finding(monkeypatch):
    """Money spent on a clean frame is still real spend (ledgered); there
    is nothing to remember about a clean frame, so record_finding is never
    called — an OK classification could never pass A2's own pre-flight
    anyway (arbiter_fingerprints.CLASSIFICATIONS has no 'OK' member), so
    this also proves judge_frame doesn't even try."""
    monkeypatch.setattr(fa, "_download_image_b64", _allow_download)

    async def vision(tenant_id, content):
        return _make_vision_reply(classification="OK", failure_class="NONE")

    monkeypatch.setattr(fa, "_call_vision", vision)

    ledger_calls = []

    async def track_ledger(**kwargs):
        ledger_calls.append(kwargs)

    async def must_not_be_called(*args, **kwargs):
        raise AssertionError("record_finding must never fire for an OK verdict")

    result = _run(fa.judge_frame(
        TENANT, VIDEO, 1, _frame(101), budget_check=_no_breach,
        ledger_write=track_ledger, record_finding_fn=must_not_be_called,
    ))

    assert result["skipped"] is False
    assert result["classification"] == "OK"
    assert "fingerprint_record" not in result
    assert len(ledger_calls) == 1  # still metered — the call was still real spend
    assert ledger_calls[0]["fingerprint"] is None


# =============================================================================
# 6. Duplicate-setup detection plumbing — a crafted fixture where the
#    judge's reply names duplicate_setup as the failure class threads
#    through to a correctly-keyed fingerprint (the DETECTION itself is the
#    vision model's judgment, proven live in the priced spike's dup101
#    case — this test proves the CODE PATH, not the model's eyesight).
# =============================================================================

def test_duplicate_setup_verdict_threads_through_with_neighbor_context(monkeypatch):
    monkeypatch.setattr(fa, "_download_image_b64", _allow_download)

    seen_content = {}

    async def vision(tenant_id, content):
        seen_content["content"] = content
        return _make_vision_reply(
            classification="MODEL_DEFECT", failure_class="Duplicate Setup",
            description="frame 101 and neighbor 102 read as the identical composition",
        )

    monkeypatch.setattr(fa, "_call_vision", vision)

    finding_calls = []

    async def track_finding(tenant_id, *, rule_id, stage, failure_class, classification):
        finding_calls.append(failure_class)
        return {"crossed_threshold": True}

    neighbors = [_frame(100), _frame(102)]
    result = _run(fa.judge_frame(
        TENANT, VIDEO, 1, _frame(101), neighbors, budget_check=_no_breach,
        ledger_write=lambda **k: asyncio.sleep(0), record_finding_fn=track_finding,
    ))

    assert result["classification"] == "MODEL_DEFECT"
    assert result["failure_class"] == "duplicate_setup"
    assert finding_calls == ["duplicate_setup"]
    # Both neighbor images were attached (frame image + 2 neighbors = 3
    # content blocks) alongside the rubric text block (4th block) — proves
    # A4's neighbor images actually reach the vision call, not just the text.
    assert len(seen_content["content"]) == 4
    assert result["neighbor_indices"] == [100, 102]


def test_neighbor_download_failure_is_best_effort_not_fatal(monkeypatch):
    """A neighbor that fails to download is simply omitted from the call —
    it never fails the whole judgment (only the FRAME's own download is
    fatal)."""
    calls = {"n": 0}

    async def flaky_download(url):
        calls["n"] += 1
        if calls["n"] == 1:
            return ("image/png", "primary")
        return None  # every neighbor fails

    monkeypatch.setattr(fa, "_download_image_b64", flaky_download)

    seen_content = {}

    async def vision(tenant_id, content):
        seen_content["content"] = content
        return _make_vision_reply(classification="OK")

    monkeypatch.setattr(fa, "_call_vision", vision)

    result = _run(fa.judge_frame(
        TENANT, VIDEO, 1, _frame(105), [_frame(104), _frame(106)],
        budget_check=_no_breach, ledger_write=lambda **k: asyncio.sleep(0),
    ))
    assert result["skipped"] is False
    assert result["neighbor_indices"] == []  # both neighbors failed to download
    assert len(seen_content["content"]) == 2  # primary image + text only


# =============================================================================
# 7. judge_scene_batch — SUPERSEDED by D5 chunk A3b (2026-07-29). The
# one-call-per-frame loop this section originally tested (each frame
# delegated to judge_frame with only its immediate draw-order neighbor
# pair attached) is the exact shape A3's own live test proved too
# expensive AND too blind (missed the 101/102 duplicate two frames apart,
# outside either one's neighbor pair — see frame_arbiter.py's module
# docstring). judge_scene_batch now fires ONE vision call for the whole
# scene with every frame's own header/prompt attached together, so there
# is no more "judge_frame delegation" or "neighbor pair" contract left to
# test here. The new contract (one call, correct image_index mapping,
# fail-closed on budget/download/vision/parse failure, non-vacuous
# scoring) is covered end to end in
# tests/functional/test_d5_a3b_eval_harness.py — see its section 4.
# =============================================================================
