"""D5 chunk A3b — Frame Arbiter judge quality eval harness (the GATE for
A5's auto-repair wiring). storyengine/FRAME-ARBITER-PLAN.md, D5-A3b entry in
tasks/loop-checklist.md.

$0 suite by default: every test below feeds crafted reply text through the
REAL judge_scene_batch / judge_board_sheet / score_frames_fixture /
score_board_fixture functions with call_vision and download_image
dependency-injected (same "real module imported directly, boundary
patched/passed-in" convention test_d5_a3_frame_arbiter.py already uses) —
NO live DB, NO network, NO vision spend.

A live run (real Anthropic vision calls against the fixture images, real
$) only happens when D5_A3B_LIVE_EVAL=1 is set in the environment AND a
real tenant Anthropic key is resolvable — both tests below are skipped
otherwise, so `pytest` with no special env never spends a cent. See the
chunk report for the actual live-run history and total spend (hard-capped
at $0.30 for this chunk, tracked by hand across a separate isolated-scratch
driver used for the iterative tuning passes — these two tests are the
checked-in regression confirmation, not the tuning loop itself).

Run (mocked, $0): cd storyengine/backend && ./venv/bin/python -m pytest \
    tests/functional/test_d5_a3b_eval_harness.py -q
Run (live, real $): D5_A3B_LIVE_EVAL=1 ./venv/bin/python -m pytest \
    tests/functional/test_d5_a3b_eval_harness.py -q -k live
"""
from __future__ import annotations

import asyncio
import os
import sys

import pytest

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

import frame_arbiter as fa  # noqa: E402
import frame_arbiter_eval as ev  # noqa: E402
from frame_arbiter_budget import FRAME_QA_STAGE  # noqa: E402

TENANT = "tenant-a3b"
VIDEO = "video-a3b"


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


async def _no_breach(*args, **kwargs):
    return None


async def _sink_ledger(**kwargs):
    _sink_ledger.calls.append(kwargs)  # type: ignore[attr-defined]


_sink_ledger.calls = []  # type: ignore[attr-defined]


async def _sink_finding(tenant_id, *, rule_id, stage, failure_class, classification):
    _sink_finding.calls.append(locals())  # type: ignore[attr-defined]
    return {"crossed_threshold": False, "violation_count": 1, "frozen": False}


_sink_finding.calls = []  # type: ignore[attr-defined]


def _reset_sinks():
    _sink_ledger.calls = []  # type: ignore[attr-defined]
    _sink_finding.calls = []  # type: ignore[attr-defined]


@pytest.fixture(autouse=True)
def _stub_quality_rules(monkeypatch):
    """judge_scene_batch/judge_board_sheet read the tenant's active
    quality_rules straight off the DB (frame_arbiter.list_all_rules, a
    plain read, same as A3's own judge_frame path) — none of this
    fixture's fixtures configure any tenant rules, so every test here
    stubs it to an empty list rather than needing a real DB connection.
    Same monkeypatch-the-module-level-name convention
    test_d5_a3_frame_arbiter.py's own judge_scene_batch test already used."""
    async def _no_rules(tenant_id, *, active_only=False):
        return []
    monkeypatch.setattr(fa, "list_all_rules", _no_rules)


# =============================================================================
# 1. Fixture loading + spec parsing sanity — proves the fixture JSON/spec
#    text this whole harness depends on is actually well-formed BEFORE any
#    scoring logic runs against it.
# =============================================================================

def test_frames_fixture_loads_and_has_all_ten_labeled_frames():
    fixture = ev.load_frames_fixture()
    assert fixture["scene"] == 1
    indices = [f["image_index"] for f in fixture["frames"]]
    assert indices == list(range(100, 110))
    for f in fixture["frames"]:
        assert f["image_prompt"], f"frame {f['image_index']} has an empty prompt"
    assert set(fixture["labels"].keys()) == {"100", "101", "102", "108", "109"}


def test_board_fixture_loads_with_set_bleed_label():
    fixture = ev.load_board_fixture()
    assert fixture["scene"] == 4
    assert fixture["label"]["classification"] == "MODEL_DEFECT"
    assert fixture["label"]["failure_class"] == "set_bleed"
    assert fixture["label"]["expected_panels_affected"] == [1, 2, 3, 4, 5]


def test_parse_sheet_panels_matches_real_scene4_spec():
    """Regression pin on _parse_sheet_panels against the REAL
    scenes.storyboard_prompts text pulled for scene 4 (not a synthetic
    stand-in) — sheet 1 is entirely pod-interior per spec (5 panels, no
    location override), sheet 2 mixes pod (panel 6) with an explicit
    ELITE VIEWING HALL override (panels 7-9), proving the parser correctly
    reads the per-panel ``(SETUP X — LOCATION)`` override syntax the real
    prompt generator emits."""
    fixture = ev.load_board_fixture()
    fixed_set, panels = fa._parse_sheet_panels(fixture["spec_text"], 1)
    assert fixed_set is not None and "Bubble-Pod" in fixed_set
    assert [p["panel"] for p in panels] == [1, 2, 3, 4, 5]
    for p in panels:
        assert "Bubble-Pod" in p["expected_set"]

    fixed_set2, panels2 = fa._parse_sheet_panels(fixture["spec_text"], 2)
    assert [p["panel"] for p in panels2] == [6, 7, 8, 9]
    assert "Bubble-Pod" in panels2[0]["expected_set"]  # panel 6, no override
    for p in panels2[1:]:  # panels 7,8,9
        assert p["expected_set"] == "ELITE VIEWING HALL"


def test_parse_sheet_panels_returns_empty_for_unknown_sheet_index():
    fixture = ev.load_board_fixture()
    fixed_set, panels = fa._parse_sheet_panels(fixture["spec_text"], 99)
    assert fixed_set is None
    assert panels == []


# =============================================================================
# 2. Scorer stash-proof — a judge that returns NOTHING must score 0, never
#    an accidental pass. This is the DoC the chunk brief states verbatim.
# =============================================================================

def test_frames_scorer_scores_zero_on_empty_findings():
    for empty in (None, [], [{"image_index": 100, "skipped": True, "reason": "vision_error"}]):
        score = ev.score_frames_fixture(empty)
        assert score["classes_passed"] == 0
        assert score["graduated"] is False
        assert score["false_positive_count"] == 0  # skipped frames are never counted as findings either way


def test_board_scorer_scores_zero_on_empty_findings():
    for empty in (None, [], [{"panel": 1, "skipped": True, "reason": "vision_error"}]):
        score = ev.score_board_fixture(empty)
        assert score["panels_caught"] == 0
        assert score["graduated"] is False


def test_frames_scorer_rejects_garbage_shaped_input_without_raising():
    # Not a list of dicts at all — the scorer must fail closed (score 0),
    # never raise, since a garbled judge reply is exactly the failure mode
    # this whole chunk exists to catch, not crash on.
    score = ev.score_frames_fixture(["not", "a", "dict", 42, None])
    assert score["graduated"] is False
    assert score["classes_passed"] == 0


# =============================================================================
# 3. Scorer correctness — a perfect verdict set graduates; a REPRODUCTION
#    of A3's actual measured live-test failure (1/3 named, dup 101/102
#    missed, false positive on healthy 100) does NOT graduate. The second
#    test is a regression pin: if a future prompt change regresses back to
#    A3's failure mode, this test catches it even if nobody remembers the
#    original incident.
# =============================================================================

def _finding(image_index, classification, failure_class=None, description=""):
    return {
        "skipped": False, "image_index": image_index, "classification": classification,
        "failure_class": failure_class, "description": description,
    }


def test_frames_scorer_graduates_on_a_perfect_verdict_set():
    findings = [
        _finding(100, "OK"),
        _finding(101, "MODEL_DEFECT", "duplicate_setup", "same hand-on-glass pose as 103, nothing new"),
        _finding(102, "MODEL_DEFECT", "duplicate_setup", "same hand-on-glass pose as 103, nothing new"),
        _finding(103, "OK"), _finding(104, "OK"), _finding(105, "OK"),
        _finding(106, "OK"), _finding(107, "OK"),
        _finding(108, "MODEL_DEFECT", "facing_law_violation", "prompt says looking frame-right, face turned fully away"),
        _finding(109, "MODEL_DEFECT", "rogue_figure", "second figure repeating Nyla's gesture in the background"),
    ]
    score = ev.score_frames_fixture(findings)
    assert score["classes_passed"] == 3
    assert score["false_positive_count"] == 0
    assert score["graduated"] is True


def test_frames_scorer_fails_on_a3s_actual_measured_failure_mode():
    """A3's live test (see frame_arbiter.py's module docstring / the chunk
    report): named only 1 of 3 known defects (108's facing violation),
    MISSED 101/102 entirely (both come back OK), and false-positived on
    healthy frame 100 with a vague 'consistency' complaint."""
    findings = [
        _finding(100, "TASTE_QUESTION", "general_consistency", "something about the lighting feels slightly off"),
        _finding(101, "OK"), _finding(102, "OK"),
        _finding(103, "OK"), _finding(104, "OK"), _finding(105, "OK"),
        _finding(106, "OK"), _finding(107, "OK"),
        _finding(108, "MODEL_DEFECT", "facing_law_violation", "face turned away from camera"),
        _finding(109, "OK"),
    ]
    score = ev.score_frames_fixture(findings)
    assert score["classes_passed"] == 1  # only facing_108
    assert score["class_results"]["duplicate_101_102"]["all_correct"] is False
    assert score["class_results"]["rogue_109"]["all_correct"] is False
    assert score["false_positive_count"] == 1  # frame 100
    assert score["graduated"] is False


def test_frames_scorer_requires_both_101_and_102_for_duplicate_class_credit():
    findings = [_finding(100, "OK")]
    findings += [_finding(101, "MODEL_DEFECT", "duplicate_setup")]  # 102 missing/OK
    findings += [_finding(108, "MODEL_DEFECT", "facing_law_violation")]
    findings += [_finding(109, "MODEL_DEFECT", "rogue_figure")]
    score = ev.score_frames_fixture(findings)
    assert score["class_results"]["duplicate_101_102"]["all_correct"] is False
    assert score["classes_passed"] == 2
    assert score["graduated"] is False


def test_board_scorer_graduates_when_every_panel_flags_set_bleed():
    findings = [
        {"panel": i, "skipped": False, "classification": "MODEL_DEFECT",
         "failure_class": "set_bleed", "description": "drawn in the elite theater, not the pod"}
        for i in range(1, 6)
    ]
    score = ev.score_board_fixture(findings)
    assert score["panels_caught"] == 5
    assert score["graduated"] is True
    assert score["graduated_all_panels"] is True


# =============================================================================
# 4. judge_scene_batch — the redesigned ONE-call-per-scene shape, exercised
#    end to end through crafted mock replies (DI'd call_vision/
#    download_image, matching test_d5_a3_frame_arbiter.py's own
#    monkeypatch-the-boundary convention).
# =============================================================================

def _scene_reply_text(verdicts: dict) -> str:
    """verdicts: {image_index: (classification, failure_class, description)}"""
    parts = []
    for idx, (cls, fclass, desc) in verdicts.items():
        parts.append(
            f"===FRAME {idx}===\n"
            f"CLASSIFICATION: {cls}\n"
            f"FAILURE_CLASS: {fclass or 'NONE'}\n"
            "RULE_ID: NONE\n"
            "RUBRIC_LEVEL: warn\n"
            "DECISIVE_FRAGMENT: NONE\n"
            f"DESCRIPTION: {desc}\n"
        )
    return "\n".join(parts)


def test_judge_scene_batch_fires_exactly_one_vision_call_for_the_whole_scene():
    fixture = ev.load_frames_fixture()
    frames = fixture["frames"]
    call_count = {"n": 0}

    async def fake_vision(tenant_id, content, **kwargs):
        call_count["n"] += 1
        verdicts = {f["image_index"]: ("OK", None, "clean") for f in frames}
        return {
            "content": [{"type": "text", "text": _scene_reply_text(verdicts)}],
            "usage": {"input_tokens": 8000, "output_tokens": 900},
        }

    async def fake_download(url):
        return ("image/png", "ZmFrZQ==")

    _reset_sinks()
    result = _run(fa.judge_scene_batch(
        TENANT, VIDEO, 1, fetch_frames=ev.fetch_frames_from_fixture(fixture),
        download_image=fake_download, call_vision=fake_vision,
        budget_check=_no_breach, ledger_write=_sink_ledger, record_finding_fn=_sink_finding,
    ))

    assert call_count["n"] == 1  # THE central claim of the A3b redesign
    assert result["skipped"] is False
    assert len(result["findings"]) == 10
    assert len(_sink_ledger.calls) == 1  # one ledger row for the whole call
    assert _sink_ledger.calls[0]["fingerprint"] is None


def test_judge_scene_batch_content_shape_is_header_plus_image_per_frame_then_rubric():
    fixture = ev.load_frames_fixture()
    frames = fixture["frames"]
    seen = {}

    async def fake_vision(tenant_id, content, **kwargs):
        seen["content"] = content
        verdicts = {f["image_index"]: ("OK", None, "clean") for f in frames}
        return {"content": [{"type": "text", "text": _scene_reply_text(verdicts)}],
                "usage": {"input_tokens": 100, "output_tokens": 100}}

    async def fake_download(url):
        return ("image/png", "ZmFrZQ==")

    _run(fa.judge_scene_batch(
        TENANT, VIDEO, 1, fetch_frames=ev.fetch_frames_from_fixture(fixture),
        download_image=fake_download, call_vision=fake_vision,
        budget_check=_no_breach, ledger_write=_sink_ledger, record_finding_fn=_sink_finding,
    ))

    content = seen["content"]
    # 10 frames -> 20 header+image blocks + 1 trailing rubric text block.
    assert len(content) == 21
    assert content[0]["type"] == "text" and "IMAGE 1" in content[0]["text"] and "image_index=100" in content[0]["text"]
    assert content[1]["type"] == "image"
    assert content[-1]["type"] == "text" and "===FRAME <image_index>===" in content[-1]["text"]


def test_judge_scene_batch_correctly_maps_each_verdict_to_its_real_image_index():
    fixture = ev.load_frames_fixture()
    frames = fixture["frames"]

    async def fake_vision(tenant_id, content, **kwargs):
        verdicts = {f["image_index"]: ("OK", None, "clean") for f in frames}
        verdicts[108] = ("MODEL_DEFECT", "facing_law_violation", "face turned away")
        verdicts[101] = ("MODEL_DEFECT", "duplicate_setup", "same pose as 103")
        verdicts[102] = ("MODEL_DEFECT", "duplicate_setup", "same pose as 103")
        verdicts[109] = ("MODEL_DEFECT", "rogue_figure", "extra figure in background")
        return {"content": [{"type": "text", "text": _scene_reply_text(verdicts)}],
                "usage": {"input_tokens": 100, "output_tokens": 100}}

    async def fake_download(url):
        return ("image/png", "ZmFrZQ==")

    _reset_sinks()
    result = _run(fa.judge_scene_batch(
        TENANT, VIDEO, 1, fetch_frames=ev.fetch_frames_from_fixture(fixture),
        download_image=fake_download, call_vision=fake_vision,
        budget_check=_no_breach, ledger_write=_sink_ledger, record_finding_fn=_sink_finding,
    ))

    score = ev.score_frames_fixture(result["findings"])
    assert score["graduated"] is True
    assert len(_sink_finding.calls) == 4  # 101, 102, 108, 109 — the four real defects


def test_judge_scene_batch_empty_vision_reply_scores_zero_end_to_end():
    """THE stash-proof, run through the REAL judge_scene_batch parsing
    path (not just the scorer in isolation): a vision reply with no
    recognizable ===FRAME n=== blocks at all must produce findings that
    score 0 known-defects-found, never an accidental pass."""
    fixture = ev.load_frames_fixture()

    async def empty_vision(tenant_id, content, **kwargs):
        return {"content": [{"type": "text", "text": "I'm not able to help with that."}],
                "usage": {"input_tokens": 100, "output_tokens": 20}}

    async def fake_download(url):
        return ("image/png", "ZmFrZQ==")

    _reset_sinks()
    result = _run(fa.judge_scene_batch(
        TENANT, VIDEO, 1, fetch_frames=ev.fetch_frames_from_fixture(fixture),
        download_image=fake_download, call_vision=empty_vision,
        budget_check=_no_breach, ledger_write=_sink_ledger, record_finding_fn=_sink_finding,
    ))

    assert result["skipped"] is False  # the CALL succeeded — it's the CONTENT that was empty
    assert all(f["skipped"] and f["reason"] == "unparseable_reply" for f in result["findings"])
    score = ev.score_frames_fixture(result["findings"])
    assert score["graduated"] is False
    assert score["classes_passed"] == 0
    assert len(_sink_finding.calls) == 0  # never invents a finding from unparseable text


def test_judge_scene_batch_budget_breach_short_circuits_before_download_or_vision():
    fired = {"download": False, "vision": False}

    async def tracking_download(url):
        fired["download"] = True
        return ("image/png", "x")

    async def tracking_vision(tenant_id, content, **kwargs):
        fired["vision"] = True
        return {"content": [], "usage": {}}

    async def breach(*args, **kwargs):
        return {"scope": "scene", "scene": 1, "cap": 0.25, "spent": 0.25, "quote": 0.07, "projected": 0.32}

    fixture = ev.load_frames_fixture()
    result = _run(fa.judge_scene_batch(
        TENANT, VIDEO, 1, fetch_frames=ev.fetch_frames_from_fixture(fixture),
        download_image=tracking_download, call_vision=tracking_vision, budget_check=breach,
    ))
    assert result["skipped"] is True
    assert result["reason"] == "budget"
    assert len(result["findings"]) == 10
    assert all(f["skipped"] for f in result["findings"])
    assert fired["download"] is False
    assert fired["vision"] is False


def test_judge_scene_batch_vision_transport_failure_skips_every_frame_not_a_finding():
    async def fail_vision(tenant_id, content, **kwargs):
        return None

    async def fake_download(url):
        return ("image/png", "x")

    fixture = ev.load_frames_fixture()
    result = _run(fa.judge_scene_batch(
        TENANT, VIDEO, 1, fetch_frames=ev.fetch_frames_from_fixture(fixture),
        download_image=fake_download, call_vision=fail_vision, budget_check=_no_breach,
    ))
    assert result["skipped"] is True
    assert result["reason"] == "vision_error"
    assert [f["image_index"] for f in result["findings"]] == list(range(100, 110))
    assert all(f["reason"] == "vision_error" for f in result["findings"])


def test_judge_scene_batch_all_downloads_failing_is_skipped_not_a_finding():
    async def fail_download(url):
        return None

    called = {"vision": False}

    async def tracking_vision(tenant_id, content, **kwargs):
        called["vision"] = True
        return {"content": [], "usage": {}}

    fixture = ev.load_frames_fixture()
    result = _run(fa.judge_scene_batch(
        TENANT, VIDEO, 1, fetch_frames=ev.fetch_frames_from_fixture(fixture),
        download_image=fail_download, call_vision=tracking_vision, budget_check=_no_breach,
    ))
    assert result["skipped"] is True
    assert result["reason"] == "download_failed"
    assert called["vision"] is False


# =============================================================================
# 5. judge_board_sheet — the new board station.
# =============================================================================

def _board_reply_text(verdicts: dict) -> str:
    """verdicts: {panel: (classification, failure_class, description)}"""
    parts = []
    for panel, (cls, fclass, desc) in verdicts.items():
        parts.append(
            f"===PANEL {panel}===\n"
            f"CLASSIFICATION: {cls}\n"
            f"FAILURE_CLASS: {fclass or 'NONE'}\n"
            "RULE_ID: NONE\n"
            "RUBRIC_LEVEL: hard_gate\n"
            "DECISIVE_FRAGMENT: NONE\n"
            f"DESCRIPTION: {desc}\n"
        )
    return "\n".join(parts)


def _board_sheet_arg():
    fixture = ev.load_board_fixture()
    return {"image_url": fixture["image_path"], "sheet_index": fixture["sheet_index"], "spec_text": fixture["spec_text"]}


def test_judge_board_sheet_fires_one_call_and_scores_the_set_bleed_correctly():
    call_count = {"n": 0}

    async def fake_vision(tenant_id, content, **kwargs):
        call_count["n"] += 1
        verdicts = {i: ("MODEL_DEFECT", "set_bleed", "elite theater dressing instead of the pod") for i in range(1, 6)}
        return {"content": [{"type": "text", "text": _board_reply_text(verdicts)}],
                "usage": {"input_tokens": 2000, "output_tokens": 400}}

    async def fake_download(url):
        return ("image/jpeg", "ZmFrZQ==")

    _reset_sinks()
    result = _run(fa.judge_board_sheet(
        TENANT, VIDEO, 4, _board_sheet_arg(),
        download_image=fake_download, call_vision=fake_vision,
        budget_check=_no_breach, ledger_write=_sink_ledger, record_finding_fn=_sink_finding,
    ))

    assert call_count["n"] == 1
    assert result["skipped"] is False
    score = ev.score_board_fixture(result["findings"])
    assert score["graduated"] is True
    assert score["graduated_all_panels"] is True
    assert len(_sink_finding.calls) == 5  # every panel is a real defect


def test_judge_board_sheet_unknown_sheet_index_is_skipped_before_any_call():
    fired = {"download": False, "vision": False}

    async def tracking_download(url):
        fired["download"] = True
        return ("image/jpeg", "x")

    async def tracking_vision(tenant_id, content, **kwargs):
        fired["vision"] = True
        return {"content": [], "usage": {}}

    sheet = _board_sheet_arg()
    sheet["sheet_index"] = 99
    result = _run(fa.judge_board_sheet(
        TENANT, VIDEO, 4, sheet, download_image=tracking_download, call_vision=tracking_vision,
        budget_check=_no_breach,
    ))
    assert result["skipped"] is True
    assert result["reason"] == "no_panel_spec"
    assert fired["download"] is False
    assert fired["vision"] is False


def test_judge_board_sheet_budget_breach_short_circuits_before_download():
    fired = {"download": False}

    async def tracking_download(url):
        fired["download"] = True
        return ("image/jpeg", "x")

    async def breach(*args, **kwargs):
        return {"scope": "scene", "scene": 4, "cap": 0.25, "spent": 0.24, "quote": 0.03, "projected": 0.27}

    result = _run(fa.judge_board_sheet(
        TENANT, VIDEO, 4, _board_sheet_arg(), download_image=tracking_download, budget_check=breach,
    ))
    assert result["skipped"] is True
    assert result["reason"] == "budget"
    assert len(result["findings"]) == 5
    assert fired["download"] is False


def test_judge_board_sheet_empty_reply_scores_zero_end_to_end():
    async def empty_vision(tenant_id, content, **kwargs):
        return {"content": [{"type": "text", "text": "nothing structured here"}],
                "usage": {"input_tokens": 50, "output_tokens": 10}}

    async def fake_download(url):
        return ("image/jpeg", "x")

    result = _run(fa.judge_board_sheet(
        TENANT, VIDEO, 4, _board_sheet_arg(), download_image=fake_download, call_vision=empty_vision,
        budget_check=_no_breach,
    ))
    assert result["skipped"] is False
    assert all(f["skipped"] and f["reason"] == "unparseable_reply" for f in result["findings"])
    score = ev.score_board_fixture(result["findings"])
    assert score["graduated"] is False
    assert score["panels_caught"] == 0


# =============================================================================
# 6. LIVE evals — real Anthropic vision calls, real $. Skipped unless
#    D5_A3B_LIVE_EVAL=1 is set. See the module docstring and the chunk
#    report for the actual spend history.
# =============================================================================

_LIVE = bool(os.environ.get("D5_A3B_LIVE_EVAL"))
_LIVE_TENANT = os.environ.get("D5_A3B_LIVE_TENANT_ID", "ee93e6d1-a9cc-44c3-81e9-84adee8329aa")


@pytest.mark.skipif(not _LIVE, reason="live eval opt-in only (D5_A3B_LIVE_EVAL=1) — spends real $")
def test_live_frames_fixture_graduation():
    fixture = ev.load_frames_fixture()
    downloader = ev.local_file_downloader(ev._FRAMES_IMAGE_DIR)

    async def real_run():
        return await fa.judge_scene_batch(
            _LIVE_TENANT, fixture["video_id"], fixture["scene"],
            fetch_frames=ev.fetch_frames_from_fixture(fixture),
            download_image=downloader, **ev.noop_di_kwargs(),
        )

    result = _run(real_run())
    assert result["skipped"] is False, result
    print(f"\n[live frames eval] cost=${result['cost']:.4f} usage={result['usage']}")
    assert result["cost"] <= 0.07, f"scene-batch call cost ${result['cost']:.4f}, over the $0.07/scene bar"
    score = ev.score_frames_fixture(result["findings"])
    print(f"[live frames eval] classes_passed={score['classes_passed']}/3 fp={score['false_positive_count']}")
    for name, r in score["class_results"].items():
        print(f"  {name}: {'PASS' if r['all_correct'] else 'FAIL'} {r['hits']}")
    assert score["graduated"], score


@pytest.mark.skipif(not _LIVE, reason="live eval opt-in only (D5_A3B_LIVE_EVAL=1) — spends real $")
def test_live_board_fixture_graduation():
    fixture = ev.load_board_fixture()
    downloader = ev.local_file_downloader(ev._FIXTURES_DIR)
    sheet = {"image_url": fixture["image_path"], "sheet_index": fixture["sheet_index"], "spec_text": fixture["spec_text"]}

    async def real_run():
        return await fa.judge_board_sheet(
            _LIVE_TENANT, "eval-video", fixture["scene"], sheet,
            download_image=downloader, **ev.noop_di_kwargs(),
        )

    result = _run(real_run())
    assert result["skipped"] is False, result
    print(f"\n[live board eval] cost=${result['cost']:.4f} usage={result['usage']}")
    score = ev.score_board_fixture(result["findings"])
    print(f"[live board eval] panels_caught={score['panels_caught']}/{score['panels_total']}")
    for r in score["panel_results"]:
        print(f"  panel {r['panel']}: {'PASS' if r['correct'] else 'FAIL'} {r['classification']}/{r['failure_class']}")
    assert score["graduated"], score
