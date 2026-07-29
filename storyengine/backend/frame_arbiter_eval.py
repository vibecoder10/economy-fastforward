"""D5 chunk A3b — Frame Arbiter judge quality eval harness.

This is the GATE that decides whether frame_arbiter.py's judge_scene_batch
(A3b redesign: one vision call per scene, see that module's docstring) and
judge_board_sheet (the new board station, Ryan's 2026-07-29 ruling that the
board gate is the arbiter's PRIMARY station) can be trusted. A5 (auto-repair
wiring) does not start until this harness's graduation bar passes.

Pure fixture-loading + scoring functions live here, $0 to import and run.
The actual pytest suite (tests/functional/test_d5_a3b_eval_harness.py)
exercises them two ways:
  * MOCKED (always runs in CI, $0): a fake call_vision/download_image pair
    feeds crafted reply text through the real judge_scene_batch/
    judge_board_sheet functions, proving the parsing + scoring plumbing is
    correct and non-vacuous (a judge that returns nothing scores 0, never
    an accidental pass — see test_scorer_scores_zero_on_empty_findings).
  * LIVE (opt-in only, behind the D5_A3B_LIVE_EVAL=1 env flag): real
    Anthropic vision calls against the fixture images below. This is the
    only path that spends real money. Capped at $0.30 total across every
    live run for this chunk (see the chunk report for the running total).

Fixtures (see storyengine/tasks/evidence/d5-eval-fixtures/):
  * scene1_frames_fixture.json — the immutable scene-1 snapshot (D3-64's
    director-pass ground truth): 3 known defect classes (facing on 108,
    duplicate-setup on 101+102, rogue-figure on 109) + frame 100 explicitly
    labeled healthy (must not be flagged).
  * scene4_board1_fixture.json — the scene-4 sheet-1 set-bleed defect: all
    5 panels spec'd for the pod interior, drawn in the elite theater.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Callable, Optional, Union

_BACKEND_DIR = Path(__file__).resolve().parent
_FIXTURES_DIR = _BACKEND_DIR.parent / "tasks" / "evidence" / "d5-eval-fixtures"
_FRAMES_IMAGE_DIR = _BACKEND_DIR.parent / "tasks" / "evidence" / "d3-53-proof"

FRAMES_FIXTURE_PATH = _FIXTURES_DIR / "scene1_frames_fixture.json"
BOARD_FIXTURE_PATH = _FIXTURES_DIR / "scene4_board1_fixture.json"

# Live-eval spend guard (D5-A3b brief: "LIVE EVAL SPEND HARD CAP: $0.30
# total across all iterations"). Not enforced automatically inside a
# single process (each live pytest run is a fresh process with no shared
# state) — the discipline is: read this constant, track spend by hand run
# to run, stop before it's crossed. See the chunk report for the running
# total actually spent.
LIVE_EVAL_SPEND_CAP = 0.30


def load_frames_fixture() -> dict:
    return json.loads(FRAMES_FIXTURE_PATH.read_text())


def load_board_fixture() -> dict:
    return json.loads(BOARD_FIXTURE_PATH.read_text())


def local_file_downloader(fixture_dir: Path, max_edge: int = 980) -> Callable[[str], Any]:
    """Builds a ``download_image``-shaped async callable (matches
    frame_arbiter._download_image_b64's own ``url -> (media_type, b64) |
    None`` contract) that reads a LOCAL fixture PNG off disk instead of
    self-fetching over HTTP.

    This is the money-guard from the chunk brief made concrete: the eval's
    frame/board images are read from the immutable local snapshot only —
    this harness never constructs a URL that could hit prod, so it cannot
    race the concurrent driver agent redrawing these same assets live.

    Also downscales to ``max_edge`` on the long side (re-encoded as JPEG
    q87) before returning — the fixture PNGs are 1672x941 (measured), and
    Anthropic's vision token cost is a direct function of pixel count
    (~width*height/750 tokens/image), NOT file size. At full resolution,
    10 frames in one judge_scene_batch call alone project to roughly
    $0.07-0.09 in image tokens before a single word of rubric text — over
    budget on image cost alone. 1024 long edge measured $0.053/scene live
    but was too soft to catch a small background rogue-figure detail in a
    pod window (see the chunk report's first live run); 1280 long edge
    (~0.58x the pixel count) is the tuned default — enough resolution for
    fine background detail while still projecting comfortably under the
    <=$0.07/scene bar. Recorded here as a real finding for A5/A6: the
    PRODUCTION self-fetch path (static_docu._download_image_b64) does NOT
    downscale today — this eval proves it should, before frame_arbiter
    goes live at any real cost, and that the downscale factor is a real
    accuracy/cost tradeoff worth tuning, not a free win."""
    from io import BytesIO

    from PIL import Image

    async def _download(path: str):
        p = fixture_dir / path
        if not p.exists():
            return None
        with Image.open(p) as im:
            im = im.convert("RGB")
            w, h = im.size
            edge = max(w, h)
            if edge > max_edge:
                scale = max_edge / edge
                im = im.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
            buf = BytesIO()
            im.save(buf, format="JPEG", quality=87)
            return "image/jpeg", base64.b64encode(buf.getvalue()).decode("ascii")
    return _download


def fetch_frames_from_fixture(fixture: dict) -> Callable[..., Any]:
    """Builds a ``fetch_frames``-shaped async callable for judge_scene_batch
    that returns the fixture's frame list verbatim (no DB)."""
    frames = fixture["frames"]

    async def _fetch(tenant_id: str, video_id: str, scene: int):
        return frames
    return _fetch


async def _noop_budget_check(*args, **kwargs) -> Optional[dict]:
    return None


async def _noop_ledger_write(**kwargs) -> None:
    return None


async def _noop_record_finding(tenant_id, *, rule_id, stage, failure_class, classification) -> dict:
    return {"crossed_threshold": False, "violation_count": 1, "frozen": False}


def noop_di_kwargs() -> dict:
    """Shared no-op budget/ledger/fingerprint kwargs for an eval run — the
    eval measures the JUDGE's eyesight, not the budget guard or the
    ledger/fingerprint plumbing (those already have their own tests in
    test_d5_a3_frame_arbiter.py / test_frame_arbiter_budget_a1.py /
    test_d5_a2_arbiter_fingerprints.py). Real cost is still read back from
    the live API response's own usage block regardless of these no-ops —
    this only bypasses the DB-backed spend guard so a live eval run
    doesn't need a real tenant row wired up to succeed."""
    return {
        "budget_check": _noop_budget_check,
        "ledger_write": _noop_ledger_write,
        "record_finding_fn": _noop_record_finding,
    }


# ---------------------------------------------------------------------------
# Frames-fixture scorer
# ---------------------------------------------------------------------------

# The 3 known DEFECT CLASSES from D3-64's director pass — the unit the
# graduation bar's ">=3/3 known defects" counts. duplicate_101_102
# requires BOTH 101 AND 102 correctly flagged for the class to pass: A3's
# live test missed this pair ENTIRELY (not partially), so partial credit
# would understate exactly the failure this chunk exists to fix.
KNOWN_DEFECT_CLASSES: dict[str, dict] = {
    "facing_108": {"frames": [108], "failure_keyword": ["facing"]},
    "duplicate_101_102": {"frames": [101, 102], "failure_keyword": ["duplicate"]},
    "rogue_109": {"frames": [109], "failure_keyword": ["rogue", "extra", "second_figure", "second figure"]},
}
HEALTHY_FRAME_INDEX = 100  # explicit "must NOT be flagged" label in the D5-A3b brief


def _keyword_hit(failure_class: Optional[str], keywords: list[str]) -> bool:
    fc = (failure_class or "").lower()
    return any(k in fc for k in keywords)


def score_frames_fixture(findings: Optional[list[dict]]) -> dict:
    """Scores a judge_scene_batch-shaped ``findings`` list (list of dicts
    keyed by image_index, see frame_arbiter.judge_scene_batch's own
    docstring for the shape) against the labeled ground truth.

    Deliberately tolerant of a garbage/empty input — ``None``, ``[]``, or a
    list of only ``skipped`` dicts all score 0 known-defects-found and 0
    false positives, never raise. This is the stash-proof the chunk brief
    requires: "a judge that returns nothing must score 0, not pass" — see
    test_scorer_scores_zero_on_empty_findings."""
    by_index: dict[Any, dict] = {}
    for f in (findings or []):
        if isinstance(f, dict) and "image_index" in f:
            by_index[f["image_index"]] = f

    class_results = {}
    for name, spec in KNOWN_DEFECT_CLASSES.items():
        hits = []
        for idx in spec["frames"]:
            f = by_index.get(idx)
            correct = bool(
                f and not f.get("skipped")
                and f.get("classification") == "MODEL_DEFECT"
                and _keyword_hit(f.get("failure_class"), spec["failure_keyword"])
            )
            hits.append({
                "image_index": idx,
                "correct": correct,
                "classification": (f or {}).get("classification"),
                "failure_class": (f or {}).get("failure_class"),
                "description": (f or {}).get("description"),
            })
        class_results[name] = {"all_correct": all(h["correct"] for h in hits), "hits": hits}

    known_defect_indices = {idx for spec in KNOWN_DEFECT_CLASSES.values() for idx in spec["frames"]}
    false_positives = []
    for idx, f in by_index.items():
        if idx in known_defect_indices:
            continue
        classification = f.get("classification")
        if not f.get("skipped") and classification not in (None, "OK"):
            false_positives.append({
                "image_index": idx, "classification": classification,
                "failure_class": f.get("failure_class"), "description": f.get("description"),
            })

    classes_passed = sum(1 for r in class_results.values() if r["all_correct"])
    classes_total = len(KNOWN_DEFECT_CLASSES)
    fp_count = len(false_positives)
    return {
        "class_results": class_results,
        "classes_passed": classes_passed,
        "classes_total": classes_total,
        "false_positives": false_positives,
        "false_positive_count": fp_count,
        "graduated_defects": classes_passed == classes_total,
        "graduated_false_positives": fp_count <= 1,
        "graduated": classes_passed == classes_total and fp_count <= 1,
    }


# ---------------------------------------------------------------------------
# Board-fixture scorer
# ---------------------------------------------------------------------------

def score_board_fixture(findings: Optional[list[dict]]) -> dict:
    """Scores a judge_board_sheet-shaped ``findings`` list (one dict per
    panel, keyed by ``panel``) against the scene-4 sheet-1 ground truth:
    EVERY panel is spec'd for the pod interior but drawn in the elite
    theater, so every panel SHOULD read MODEL_DEFECT/set_bleed.

    Same tolerant-of-nothing law as score_frames_fixture: an empty/None
    findings list scores 0 panels caught, never raises, never passes."""
    by_panel: dict[Any, dict] = {}
    for f in (findings or []):
        if isinstance(f, dict) and "panel" in f:
            by_panel[f["panel"]] = f

    panel_results = []
    for panel in sorted(by_panel.keys()):
        f = by_panel[panel]
        correct = bool(
            not f.get("skipped")
            and f.get("classification") == "MODEL_DEFECT"
            and _keyword_hit(f.get("failure_class"), ["set_bleed", "set bleed", "location", "wrong_set", "wrong set"])
        )
        panel_results.append({
            "panel": panel, "correct": correct,
            "classification": f.get("classification"), "failure_class": f.get("failure_class"),
            "description": f.get("description"),
        })

    caught = sum(1 for r in panel_results if r["correct"])
    total = len(panel_results)
    return {
        "panel_results": panel_results,
        "panels_caught": caught,
        "panels_total": total,
        # Graduation bar text: "the set bleed caught, correct class,
        # per-panel specificity". Read as: the judge must catch the defect
        # on a MAJORITY of the sheet's panels with the right class — this
        # fixture has zero correctly-set panels, so a judge flagging only
        # 1 of 5 as an outlier would be under-catching a whole-sheet bleed.
        "graduated": total > 0 and caught > total / 2,
        "graduated_all_panels": total > 0 and caught == total,
    }
