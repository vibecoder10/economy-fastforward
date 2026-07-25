from __future__ import annotations

import copy
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

VIDEO_PIPELINE = Path(__file__).parents[4] / "skills" / "video-pipeline"
if str(VIDEO_PIPELINE) not in sys.path:
    sys.path.insert(0, str(VIDEO_PIPELINE))

import custom_film_production_runner as production
from custom_film_contract import CustomFilmContractError
from test_custom_film_production_runner import _Pool, _adapter


def _passing_quality_result():
    return {
        "scenes": [{"scene": 1, "text": "A grounded visual story."}],
        "critique": SimpleNamespace(
            verdict="pass",
            score=95,
            failing_gates=[],
            violations=[],
            rule_verdicts=[],
            needs_revision=False,
        ),
        "needs_review": False,
        "edit_rounds": 0,
        "regenerated": False,
        "changed": False,
    }


def test_early_quality_result_rejects_every_contradictory_shape():
    original = [{"scene": 1, "text": "A grounded visual story."}]
    cases = []

    missing_key = _passing_quality_result()
    missing_key.pop("changed")
    cases.append(missing_key)

    scene_drift = _passing_quality_result()
    scene_drift["scenes"][0]["scene"] = 2
    cases.append(scene_drift)

    changed_lie = _passing_quality_result()
    changed_lie["changed"] = True
    cases.append(changed_lie)

    review_lie = _passing_quality_result()
    review_lie["needs_review"] = True
    cases.append(review_lie)

    fail_open = _passing_quality_result()
    fail_open["critique"].failing_gates = [
        "grade unavailable - failed open"
    ]
    cases.append(fail_open)

    failed_rule = _passing_quality_result()
    failed_rule["critique"].rule_verdicts = [
        SimpleNamespace(
            rule="visual_story_readiness",
            passed=False,
        )
    ]
    cases.append(failed_rule)

    for result in cases:
        with pytest.raises(
            CustomFilmContractError,
            match="failed visual-story quality before voice or imagery",
        ):
            production._validated_early_quality_result(
                result,
                original_scenes=original,
            )


@pytest.mark.asyncio
async def test_contradictory_quality_shape_fails_closed_before_persistence(monkeypatch):
    request = production._request(
        _adapter("script", seconds=12),
        (),
        "custom-film-op:" + "7" * 64,
    )
    seams = production.SharedSectionProductionSeams("tenant-1")
    script = (
        "[ACT 1 — EVIDENCE | 0:00 - 0:12 | ~30 words]\n"
        "Sourced evidence appears on a monitor while a camera follows the "
        "visible signal through the room and reveals each concrete connection "
        "for the waiting audience."
    )
    assert 25 <= production._script_word_count(script) <= 35

    class Executor:
        def __init__(self):
            self._pipeline = SimpleNamespace(anthropic=object())

        async def _ensure_initialized(self):
            return None

        async def _get_video(self, _video_id):
            return {"video_title": "Sourced evidence"}

    async def generate(*_args, **_kwargs):
        return {"script": script, "validation": {"valid": True, "issues": []}}

    async def contradictory_quality(*_args, **_kwargs):
        return {
            "scenes": copy.deepcopy(_args[2]),
            "critique": SimpleNamespace(
                verdict="revise",
                score=40,
                failing_gates=["approved_purpose_grounding"],
                violations=["approved_purpose_grounding"],
                rule_verdicts=[],
                needs_revision=True,
            ),
            "needs_review": False,
            "edit_rounds": 0,
            "regenerated": False,
            "changed": False,
        }

    class Connection:
        async def fetchrow(self, sql, *args):
            assert "INSERT INTO scripts" in sql
            return {"id": args[0]}

        async def execute(self, sql, *_args):
            assert "UPDATE videos" in sql
            return "UPDATE 1"

    async def get_pool():
        return _Pool(Connection())

    seams._executor = Executor()
    monkeypatch.setattr(
        "script.brief_translator.script_generator.generate_script",
        generate,
    )
    monkeypatch.setattr(
        "script.brief_translator.script_generator.validate_script",
        lambda *_args, **_kwargs: {"valid": True, "issues": []},
    )
    monkeypatch.setattr(
        "script_quality.run_critique_and_edit",
        contradictory_quality,
    )
    monkeypatch.setattr("database.get_pool", get_pool)

    with pytest.raises(
        CustomFilmContractError,
        match="failed visual-story quality before voice or imagery",
    ):
        await seams._script(request)
