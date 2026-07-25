from __future__ import annotations

import copy
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

VIDEO_PIPELINE = Path(__file__).parents[4] / "skills" / "video-pipeline"
if str(VIDEO_PIPELINE) not in sys.path:
    sys.path.insert(0, str(VIDEO_PIPELINE))

import custom_film_production_runner as production
import custom_film_section_runtime as section_runtime
from test_custom_film_production_runner import _Pool, _adapter
from test_custom_film_section_runtime import _envelope


def _marked(spoken: str) -> str:
    padded = spoken + " " + " ".join(
        ["evidence"] * (30 - production._script_word_count(spoken))
    )
    return "[ACT 1 — EVIDENCE | 0:00 - 0:12 | ~30 words]\n" + padded


def _issues(script: str, approved_context: str) -> list[str]:
    return production._script_grounding_issues(
        script,
        approved_context=approved_context,
        config=production._ExactSectionConfig(12),
        generator_validation={"valid": True, "issues": []},
    )


def test_spelled_number_invention_is_rejected_but_approved_number_words_pass():
    script = _marked(
        "Show evidence as the first twelve panels become three rows, six lights "
        "pulse, and ninety marks appear across the monitor."
    )

    rejected = _issues(script, "evidence\nShow evidence on the monitor")
    assert any(
        all(
            word in issue
            for word in ("first", "twelve", "three", "six", "ninety")
        )
        for issue in rejected
    )

    approved = _issues(
        script,
        (
            "evidence\nShow evidence as the first twelve panels become three "
            "rows, six lights pulse, and ninety marks appear across the monitor"
        ),
    )
    assert not any("number-word anchors" in issue for issue in approved)


@pytest.mark.asyncio
async def test_spelled_number_drift_can_converge_through_bounded_repair(
    monkeypatch,
):
    request = production._request(
        _adapter("script", seconds=12),
        (),
        "custom-film-op:" + "4" * 64,
    )
    initial = _marked(
        "Show sourced evidence as the first twelve panels become three rows "
        "while six lights pulse across the monitor."
    )
    repaired = _marked(
        "Show sourced evidence as panels align across the monitor while visible "
        "lights pulse and the camera follows the changing display."
    )
    edit_violations = []

    async def generate(_client, _brief, **_kwargs):
        return {"script": initial, "validation": {"valid": True, "issues": []}}

    async def edit(_scenes, violations, **_kwargs):
        edit_violations.append(list(violations))
        return [{"scene": 1, "text": repaired}]

    async def quality(_tenant, _video, scenes, **_kwargs):
        return _passing_quality(scenes)

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

    seams = production.SharedSectionProductionSeams("tenant-1")
    seams._executor = _Executor()
    monkeypatch.setattr(
        "script.brief_translator.script_generator.generate_script",
        generate,
    )
    monkeypatch.setattr("script_quality.edit_draft_with_violations", edit)
    monkeypatch.setattr("script_quality.run_critique_and_edit", quality)
    monkeypatch.setattr("database.get_pool", get_pool)

    result = await seams._script(request)

    assert len(edit_violations) == 1
    assert any(
        all(word in issue for word in ("first", "twelve", "three", "six"))
        for issue in edit_violations[0]
    )
    assert conn.saved_text == repaired
    assert result["quality_verdict"] == "pass"


def test_story_arc_is_script_only_and_does_not_churn_non_script_request_identity():
    arc = (
        {"order_index": 0, "role": "opening", "purpose": "Open the question"},
        {"order_index": 1, "role": "evidence", "purpose": "Show the proof"},
    )
    voice = _adapter("voice")
    voice_with_arc = replace(voice, story_arc=arc)

    original = production._request(
        voice,
        ("scene-1",),
        "custom-film-op:" + "1" * 64,
    )
    enriched = production._request(
        voice_with_arc,
        ("scene-1",),
        "custom-film-op:" + "1" * 64,
    )

    assert original.payload() == enriched.payload()
    assert voice.provider_values() == voice_with_arc.provider_values()
    script = production._request(
        replace(_adapter("script"), story_arc=arc),
        (),
        "custom-film-op:" + "2" * 64,
    )
    assert script.payload()["story_arc"] == list(arc)


def test_other_story_arc_sections_never_authorize_current_section_facts():
    arc = (
        {"order_index": 0, "role": "evidence", "purpose": "Show evidence"},
        {
            "order_index": 1,
            "role": "case_study",
            "purpose": "Follow twelve Chicago witnesses",
        },
    )
    guidance = production._script_story_arc_guidance(
        arc,
        current_order_index=0,
    )
    invented = _marked(
        "Show evidence on the monitor while twelve signals from Chicago move "
        "across the visible display."
    )

    assert "STRUCTURE ONLY — NOT A FACTUAL SOURCE" in guidance
    assert "Other sections' purposes do not authorize" in guidance
    issues = _issues(invented, "evidence\nShow evidence")
    assert any("twelve" in issue for issue in issues)
    assert any("Chicago" in issue for issue in issues)


class _Executor:
    def __init__(self):
        self._pipeline = SimpleNamespace(anthropic=object())

    async def _ensure_initialized(self):
        return None

    async def _get_video(self, _video_id):
        return {"video_title": "Approved film"}


def _passing_quality(scenes):
    return {
        "scenes": copy.deepcopy(scenes),
        "critique": SimpleNamespace(
            verdict="pass",
            score=98,
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


@pytest.mark.asyncio
async def test_full_envelope_arc_reaches_script_prompt_with_current_section_marked(
    monkeypatch,
):
    adapters = section_runtime.compile_stage_adapters(_envelope())
    adapter = next(item for item in adapters if item.stage == "script")
    request = production._request(
        adapter,
        (),
        "custom-film-op:" + "3" * 64,
    )
    captured_briefs = []
    script = _marked(
        "Show evidence on a monitor as the camera follows the visible record "
        "through the room and reveals its changing pattern."
    )

    async def generate(_client, brief, **_kwargs):
        captured_briefs.append(copy.deepcopy(brief))
        return {"script": script, "validation": {"valid": True, "issues": []}}

    async def quality(_tenant, _video, scenes, **_kwargs):
        return _passing_quality(scenes)

    class Connection:
        async def fetchrow(self, sql, *args):
            assert "INSERT INTO scripts" in sql
            return {"id": args[0]}

        async def execute(self, sql, *_args):
            assert "UPDATE videos" in sql
            return "UPDATE 1"

    async def get_pool():
        return _Pool(Connection())

    seams = production.SharedSectionProductionSeams("tenant-1")
    seams._executor = _Executor()
    monkeypatch.setattr(
        "script.brief_translator.script_generator.generate_script",
        generate,
    )
    monkeypatch.setattr("script_quality.run_critique_and_edit", quality)
    monkeypatch.setattr("database.get_pool", get_pool)

    await seams._script(request)

    guidance = captured_briefs[0]["writer_guidance"]
    assert len(request.story_arc) == len(_envelope()["sections"])
    assert "SECTION 1 [CURRENT SECTION] — ROLE: evidence" in guidance
    assert "SECTION 2 — ROLE: explanation" in guidance
    assert "Use this ordered arc only for continuity, non-duplication" in guidance
