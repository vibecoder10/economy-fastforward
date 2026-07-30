"""Tests for D8 chunk 3b: the per-instance persistence gap D8-3 found.

frame_arbiter.py's judge calls (judge_frame / judge_scene_batch /
judge_board_sheet) return a per-frame/per-panel "findings" list every time
they run, but nothing ever wrote it anywhere — only class-level
arbiter_fingerprints (migration 139) and generation_ledger frame_qa spend
(migration 140) were real. This chunk adds:
  * migrations/146_arbiter_findings.sql — the per-instance table.
  * backend/arbiter_findings.py — record_finding_instances, the thin writer.
  * backend/frame_arbiter_hook.py — wires that writer into
    run_after_storyboard_sheet, advisory-only (a write failure must never
    fail the storyboard stage or skip the freeze/budget logic around it).

$0 suite: every DB boundary is either dependency-injected (write_findings_fn
on run_after_storyboard_sheet, same convention fetch_sheets/judge_fn/
repair_fn/rejudge_fn already use) or monkeypatched at the module level
(arbiter_findings.execute). NO live DB, NO network, NO paid calls.

Proves the three things this chunk's brief requires:
  (a) a judgment with findings writes matching rows (record_finding_
      instances' own field-mapping, AND the hook actually calling it with
      the right arguments after judge_fn / rejudge_fn)
  (b) a persistence failure never fails the stage or skips the freeze/
      budget logic downstream (repair_fn/rejudge_fn still run, the next
      sheet in the loop still gets judged)
  (c) covered by test_d8_3_review_findings.py's own update (the endpoint
      side) — not duplicated here.

Non-vacuous / stash-proof: this chunk's own report documents the patch-file
stash-proof run against a neutered copy of frame_arbiter_hook.py's
try/except around the write call (the `except Exception` body replaced with
`raise`) — the neutered copy makes
test_persistence_failure_never_fails_the_stage_or_the_next_sheet fail with a
real, propagated AssertionError-wrapping exception instead of a clean pass,
confirming the advisory wrapping is real, then reverted via the patch file
(never `git stash` — see tasks/lessons.md's fleet rule on cross-worktree
stash collisions).

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_d8_3b_findings_persist.py -q
"""
from __future__ import annotations

import asyncio
import os
import sys

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

import arbiter_findings as afi  # noqa: E402
import frame_arbiter_hook as hook  # noqa: E402

TENANT = "tenant-d8-3b"
VIDEO = "video-d8-3b"
SCENE = 7


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_execute_recorder(fail_on: "set[int]" = frozenset()):
    """Fakes backend.database.execute — records every call's args, and
    raises for the Nth call (1-indexed) when N is in fail_on, so tests can
    prove one bad row never blocks the rest of the batch."""
    calls: list = []

    async def fake_execute(query, *args):
        calls.append((query, args))
        if len(calls) in fail_on:
            raise RuntimeError(f"simulated DB failure on call {len(calls)}")

    fake_execute.calls = calls
    return fake_execute


def _board_finding(panel=1, classification="MODEL_DEFECT", failure_class="set_bleed", **over):
    base = {
        "skipped": False,
        "panel": panel,
        "label": "M1 WS",
        "expected_set": "a plain interior room",
        "classification": classification,
        "failure_class": failure_class,
        "rule_id": None,
        "rubric_level": "hard_gate",
        "decisive_prompt_fragment": None,
        "description": "wrong location drawn",
        "new_vs_previous": "FIRST_PANEL",
    }
    base.update(over)
    return base


# =============================================================================
# record_finding_instances — the field-mapping / write-shape layer.
# =============================================================================

def test_writes_one_row_per_judged_finding_and_maps_board_fields(monkeypatch):
    fake_execute = _make_execute_recorder()
    monkeypatch.setattr(afi, "execute", fake_execute)

    findings = [_board_finding(panel=1), _board_finding(panel=2, classification="OK", failure_class="ok")]
    written = _run(afi.record_finding_instances(
        TENANT, VIDEO, SCENE, "board", findings, call_cost=0.03, image_url="https://x/sheet-1.png",
    ))

    assert len(written) == 2
    assert len(fake_execute.calls) == 2
    query, args = fake_execute.calls[0]
    assert "INSERT INTO arbiter_findings" in query
    (tenant_id, video_id, scene, station, reference, label, image_url,
     classification, failure_class, rule_id, fingerprint_key,
     rubric_level, decisive_prompt_fragment, description,
     new_vs_previous, cost) = args
    assert tenant_id == TENANT
    assert video_id == VIDEO
    assert scene == SCENE
    assert station == "board"
    assert reference == "panel 1"
    assert label == "M1 WS"
    assert image_url == "https://x/sheet-1.png"
    assert classification == "MODEL_DEFECT"
    assert failure_class == "set_bleed"
    assert rule_id is None
    assert fingerprint_key == "set_bleed"  # COALESCE(rule_id, failure_class), no rule authored yet
    assert rubric_level == "hard_gate"
    assert description == "wrong location drawn"
    assert new_vs_previous == "FIRST_PANEL"
    assert cost == 0.03  # call-level cost (board station has no per-finding cost)

    # Second row: an OK verdict is still a delivered judgment, still a row.
    _, args2 = fake_execute.calls[1]
    assert args2[4] == "panel 2"
    assert args2[7] == "OK"


def test_skips_entries_with_no_delivered_judgment(monkeypatch):
    """skipped:True entries (budget refusal, download/vision/parse failure)
    carry no real classification — never a fabricated verdict, never a row."""
    fake_execute = _make_execute_recorder()
    monkeypatch.setattr(afi, "execute", fake_execute)

    findings = [
        {"skipped": True, "reason": "download_failed", "panel": 1},
        _board_finding(panel=2),
    ]
    written = _run(afi.record_finding_instances(TENANT, VIDEO, SCENE, "board", findings))
    assert len(written) == 1
    assert len(fake_execute.calls) == 1


def test_frame_station_reference_uses_image_index_not_panel(monkeypatch):
    fake_execute = _make_execute_recorder()
    monkeypatch.setattr(afi, "execute", fake_execute)

    finding = {
        "skipped": False, "image_index": 108, "shot_type": "MCU",
        "classification": "MODEL_DEFECT", "failure_class": "facing_law_violation",
        "rule_id": "rule-5g", "rubric_level": "hard_gate",
        "decisive_prompt_fragment": "looking frame-right", "description": "gaze wrong",
        "cost": 0.019,  # frame station: per-finding cost IS present
    }
    _run(afi.record_finding_instances(TENANT, VIDEO, SCENE, "frame", [finding], call_cost=999.0))

    _, args = fake_execute.calls[0]
    assert args[3] == "frame"
    assert args[4] == "image_index 108"
    assert args[5] == "MCU"
    assert args[9] == "rule-5g"
    assert args[10] == "rule-5g"  # fingerprint_key prefers rule_id over failure_class
    assert args[15] == 0.019  # per-finding cost wins over call_cost


def test_invalid_station_raises_valueerror(monkeypatch):
    fake_execute = _make_execute_recorder()
    monkeypatch.setattr(afi, "execute", fake_execute)
    try:
        _run(afi.record_finding_instances(TENANT, VIDEO, SCENE, "not_a_real_station", [_board_finding()]))
        raise AssertionError("expected ValueError for an unrecognized station")
    except ValueError:
        pass
    assert fake_execute.calls == []


def test_one_bad_row_does_not_block_the_rest_of_the_batch(monkeypatch):
    fake_execute = _make_execute_recorder(fail_on={1})  # first insert blows up
    monkeypatch.setattr(afi, "execute", fake_execute)

    findings = [_board_finding(panel=1), _board_finding(panel=2)]
    written = _run(afi.record_finding_instances(TENANT, VIDEO, SCENE, "board", findings))

    assert len(fake_execute.calls) == 2  # both attempted
    assert len(written) == 1  # only the second one actually succeeded
    assert written[0]["panel"] == 2


# =============================================================================
# frame_arbiter_hook wiring — (a) writes fire with the right shape, (b) a
# persistence failure never fails the stage or skips freeze/budget logic.
# =============================================================================

def _sheet(sheet_index=1):
    return {"image_url": f"https://x/sheet-{sheet_index}.png", "sheet_index": sheet_index, "spec_text": "spec"}


def _set_scope(monkeypatch):
    monkeypatch.setenv("FRAME_ARBITER_A6_ENABLED", "true")
    monkeypatch.setenv("FRAME_ARBITER_A6_VIDEO_ID", VIDEO)
    monkeypatch.setenv("FRAME_ARBITER_A6_SCENE", str(SCENE))
    monkeypatch.delenv("FRAME_ARBITER_A6_REDRAW_ENABLED", raising=False)


def _make_write_tracker(raise_error=False):
    calls: list = []

    async def tracker(tenant_id, video_id, scene, station, findings, *, call_cost=None, image_url=None):
        calls.append({
            "tenant_id": tenant_id, "video_id": video_id, "scene": scene,
            "station": station, "findings": findings, "call_cost": call_cost, "image_url": image_url,
        })
        if raise_error:
            raise RuntimeError("simulated persistence failure")
        return findings

    tracker.calls = calls
    return tracker


def test_hook_persists_findings_after_the_first_judgment(monkeypatch):
    _set_scope(monkeypatch)
    sheet = _sheet(1)

    async def fetch_sheets(tenant_id, video_id, scene):
        return [sheet]

    judged = {
        "skipped": False, "sheet_index": 1, "cost": 0.031, "usage": {},
        "findings": [_board_finding(panel=1, classification="OK", failure_class="ok")],
    }

    async def judge_fn(tenant_id, video_id, scene, sheet_arg):
        return judged

    write_tracker = _make_write_tracker()
    repair_probe_calls: list = []

    async def repair_probe(*a, **k):
        repair_probe_calls.append((a, k))
        return {"acted": False}

    result = _run(hook.run_after_storyboard_sheet(
        TENANT, VIDEO, SCENE, fetch_sheets=fetch_sheets, judge_fn=judge_fn,
        repair_fn=repair_probe, write_findings_fn=write_tracker,
    ))

    assert result["scene"] == SCENE
    assert len(write_tracker.calls) == 1
    call = write_tracker.calls[0]
    assert call["tenant_id"] == TENANT
    assert call["video_id"] == VIDEO
    assert call["scene"] == SCENE
    assert call["station"] == "board"
    assert call["findings"] == judged["findings"]
    assert call["call_cost"] == 0.031
    assert call["image_url"] == sheet["image_url"]
    # No MODEL_DEFECT in this scenario -> repair never attempted.
    assert repair_probe_calls == []


def test_hook_persists_findings_again_after_a_successful_rejudge(monkeypatch):
    _set_scope(monkeypatch)
    sheet = _sheet(1)

    async def fetch_sheets(tenant_id, video_id, scene):
        return [sheet]

    first_judged = {
        "skipped": False, "sheet_index": 1, "cost": 0.03, "usage": {},
        "findings": [_board_finding(panel=1, classification="MODEL_DEFECT")],
    }
    rejudged = {
        "skipped": False, "sheet_index": 1, "cost": 0.028, "usage": {},
        "findings": [_board_finding(panel=1, classification="OK", failure_class="ok")],
    }

    async def judge_fn(tenant_id, video_id, scene, sheet_arg):
        return first_judged

    async def repair_fn(tenant_id, video_id, scene, finding, *, sheet_index, reroll_fn):
        return {"acted": True, "action": "rerolled"}

    async def rejudge_fn(tenant_id, video_id, scene, sheet_arg, *, judge_fn):
        return rejudged

    write_tracker = _make_write_tracker()

    result = _run(hook.run_after_storyboard_sheet(
        TENANT, VIDEO, SCENE, fetch_sheets=fetch_sheets, judge_fn=judge_fn,
        repair_fn=repair_fn, rejudge_fn=rejudge_fn, write_findings_fn=write_tracker,
    ))

    assert len(write_tracker.calls) == 2  # first judgment + post-repair rejudge
    assert write_tracker.calls[0]["findings"] == first_judged["findings"]
    assert write_tracker.calls[1]["findings"] == rejudged["findings"]
    assert result["sheets"][0]["repair"]["rejudge"] == rejudged


def test_persistence_failure_never_fails_the_stage_or_the_next_sheet(monkeypatch):
    """(b) the brief's own words: 'Persistence failure must NEVER fail the
    stage or skip the freeze/budget logic.' write_findings_fn raises on
    EVERY call here; the hook must still: not raise itself, still run
    repair_fn for a MODEL_DEFECT finding, and still judge a SECOND sheet in
    the same scene."""
    _set_scope(monkeypatch)
    sheets = [_sheet(1), _sheet(2)]

    async def fetch_sheets(tenant_id, video_id, scene):
        return sheets

    judge_calls: list = []

    async def judge_fn(tenant_id, video_id, scene, sheet_arg):
        judge_calls.append(sheet_arg["sheet_index"])
        return {
            "skipped": False, "sheet_index": sheet_arg["sheet_index"], "cost": 0.02, "usage": {},
            "findings": [_board_finding(panel=1, classification="MODEL_DEFECT")],
        }

    repair_calls: list = []

    async def repair_fn(tenant_id, video_id, scene, finding, *, sheet_index, reroll_fn):
        repair_calls.append(sheet_index)
        return {"acted": False, "action": "reroll_failed"}

    write_tracker = _make_write_tracker(raise_error=True)

    result = _run(hook.run_after_storyboard_sheet(
        TENANT, VIDEO, SCENE, fetch_sheets=fetch_sheets, judge_fn=judge_fn,
        repair_fn=repair_fn, write_findings_fn=write_tracker,
    ))

    # Nothing raised out of run_after_storyboard_sheet despite every write failing.
    assert result["scene"] == SCENE
    assert len(result["sheets"]) == 2
    # Both sheets were judged and both repairs were attempted — the write
    # failure on sheet 1 did not skip sheet 2's judge/repair pass.
    assert judge_calls == [1, 2]
    assert repair_calls == [1, 2]
    # The write was actually attempted (and failed) for both sheets — this
    # proves the try/except is wrapping a REAL call, not skipping it.
    assert len(write_tracker.calls) == 2
