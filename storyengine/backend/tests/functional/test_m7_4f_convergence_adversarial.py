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


def _padded(base: str, target: int = 30) -> str:
    spoken = base + " " + " ".join(
        ["evidence"] * (target - production._script_word_count(base))
    )
    return (
        "[ACT 1 — EVIDENCE | 0:00 - 0:12 | ~30 words]\n"
        + spoken
    )


def _quality_result(input_scenes, output_text: str):
    scenes = [{"scene": 1, "text": output_text}]
    return {
        "scenes": scenes,
        "critique": SimpleNamespace(
            verdict="pass",
            score=96,
            failing_gates=[],
            violations=[],
            rule_verdicts=[],
            needs_revision=False,
        ),
        "needs_review": False,
        "edit_rounds": 1,
        "regenerated": False,
        "changed": scenes != input_scenes,
    }


class _Executor:
    def __init__(self):
        self._pipeline = SimpleNamespace(anthropic=object())

    async def _ensure_initialized(self):
        return None

    async def _get_video(self, _video_id):
        return {"video_title": "Sourced evidence"}


@pytest.mark.asyncio
async def test_post_critic_drift_is_repaired_then_semantically_rechecked(
    monkeypatch,
):
    request = production._request(
        _adapter("script", seconds=12),
        (),
        "custom-film-op:" + "5" * 64,
    )
    seams = production.SharedSectionProductionSeams("tenant-1")
    initial = _padded(
        "Sourced evidence appears on a monitor while the camera follows the "
        "visible signal across the room."
    )
    drift = _padded(
        "The sourced evidence panel changes at 3 AM near Chicago and displays "
        "47 unexplained signals while the camera follows."
    )
    repaired = _padded(
        "Sourced evidence remains on the visible monitor while the camera "
        "follows the approved signal through the dark room."
    )
    semantic_inputs = []
    deterministic_edits = []

    async def generate(*_args, **_kwargs):
        return {"script": initial, "validation": {"valid": True, "issues": []}}

    async def quality(_tenant, _video, scenes, **_kwargs):
        semantic_inputs.append(copy.deepcopy(scenes))
        if len(semantic_inputs) == 1:
            return _quality_result(scenes, drift)
        return _quality_result(scenes, repaired)

    async def edit(_scenes, violations, **_kwargs):
        deterministic_edits.append(list(violations))
        return [{"scene": 1, "text": repaired}]

    class Connection:
        def __init__(self):
            self.saved_text = None

        async def fetchrow(self, sql, *args):
            assert "INSERT INTO scripts" in sql
            self.saved_text = args[4]
            return {"id": args[0]}

        async def execute(self, sql, *_args):
            assert "UPDATE videos" in sql
            return "UPDATE 1"

    conn = Connection()

    async def get_pool():
        return _Pool(conn)

    seams._executor = _Executor()
    monkeypatch.setattr(
        "script.brief_translator.script_generator.generate_script",
        generate,
    )
    monkeypatch.setattr(
        "script.brief_translator.script_generator.validate_script",
        lambda *_args, **_kwargs: {"valid": True, "issues": []},
    )
    monkeypatch.setattr("script_quality.run_critique_and_edit", quality)
    monkeypatch.setattr("script_quality.edit_draft_with_violations", edit)
    monkeypatch.setattr("database.get_pool", get_pool)

    result = await seams._script(request)

    assert len(semantic_inputs) == 2
    assert semantic_inputs[0][0]["text"] == initial
    assert semantic_inputs[1][0]["text"] == repaired
    assert len(deterministic_edits) == 1
    assert any(
        all(anchor in issue for anchor in ("3", "47"))
        for issue in deterministic_edits[0]
    )
    assert any(
        all(anchor in issue for anchor in ("AM", "Chicago"))
        for issue in deterministic_edits[0]
    )
    assert conn.saved_text == repaired
    assert result["quality_verdict"] == "pass"


@pytest.mark.asyncio
async def test_post_critic_fixed_point_fails_closed_after_bounded_nonconvergence(
    monkeypatch,
):
    request = production._request(
        _adapter("script", seconds=12),
        (),
        "custom-film-op:" + "4" * 64,
    )
    seams = production.SharedSectionProductionSeams("tenant-1")
    initial = _padded(
        "Sourced evidence appears on a monitor while the camera follows the "
        "visible signal across the room."
    )
    drift = _padded(
        "The sourced evidence panel changes at 3 AM near Chicago and displays "
        "47 unexplained signals while the camera follows."
    )
    repaired = _padded(
        "Sourced evidence remains on the visible monitor while the camera "
        "follows the approved signal through the dark room."
    )
    semantic_calls = 0
    edit_calls = 0

    async def generate(*_args, **_kwargs):
        return {"script": initial, "validation": {"valid": True, "issues": []}}

    async def quality(_tenant, _video, scenes, **_kwargs):
        nonlocal semantic_calls
        semantic_calls += 1
        return _quality_result(scenes, drift)

    async def edit(*_args, **_kwargs):
        nonlocal edit_calls
        edit_calls += 1
        return [{"scene": 1, "text": repaired}]

    async def forbidden_pool():
        raise AssertionError("nonconverged script cannot reach persistence")

    seams._executor = _Executor()
    monkeypatch.setattr(
        "script.brief_translator.script_generator.generate_script",
        generate,
    )
    monkeypatch.setattr(
        "script.brief_translator.script_generator.validate_script",
        lambda *_args, **_kwargs: {"valid": True, "issues": []},
    )
    monkeypatch.setattr("script_quality.run_critique_and_edit", quality)
    monkeypatch.setattr("script_quality.edit_draft_with_violations", edit)
    monkeypatch.setattr("database.get_pool", forbidden_pool)

    with pytest.raises(
        CustomFilmContractError,
        match="quality gates did not converge before voice or imagery",
    ):
        await seams._script(request)

    assert semantic_calls == production._SCRIPT_CONVERGENCE_PASSES == 2
    assert edit_calls == production._SCRIPT_CONVERGENCE_PASSES == 2
