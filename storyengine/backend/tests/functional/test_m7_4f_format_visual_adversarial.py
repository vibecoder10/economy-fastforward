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
from custom_film_contract import CustomFilmContractError
from test_custom_film_production_runner import _Pool, _adapter


def _spoken(base: str, target: int = 30) -> str:
    return base + " " + " ".join(
        ["evidence"] * (target - production._script_word_count(base))
    )


def _marked(spoken: str) -> str:
    return (
        "[ACT 1 — EVIDENCE | 0:00 - 0:12 | ~30 words]\n"
        + spoken
    )


class _Executor:
    def __init__(self):
        self._pipeline = SimpleNamespace(anthropic=object())

    async def _ensure_initialized(self):
        return None

    async def _get_video(self, _video_id):
        return {"video_title": "Sourced evidence"}


def _passing_quality(scenes):
    return {
        "scenes": copy.deepcopy(scenes),
        "critique": SimpleNamespace(
            verdict="pass",
            score=96,
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


def test_canonical_marker_first_with_narration_after_it_passes_output_boundary():
    canonical = _marked(
        _spoken(
            "A visible record changes on the monitor while the camera follows "
            "the sourced evidence across the room."
        )
    )

    assert production._script_output_format_issues(
        canonical,
        config=production._ExactSectionConfig(12),
    ) == []


@pytest.mark.parametrize("terminal_chrome", ["---", "```", "END", "***"])
def test_terminal_document_chrome_after_narration_is_rejected(terminal_chrome):
    script = _marked(
        _spoken(
            "A visible record changes on the monitor while the camera follows "
            "the sourced evidence across the room."
        )
    )

    issues = production._script_output_format_issues(
        script + "\n" + terminal_chrome,
        config=production._ExactSectionConfig(12),
    )

    assert issues == [
        "script has trailing document chrome after narration; remove the "
        "terminal fence, horizontal rule, or END wrapper"
    ]


@pytest.mark.asyncio
async def test_neutral_angle_preface_is_removed_before_word_count_and_persistence(
    monkeypatch,
):
    adapter = replace(
        _adapter("script", seconds=12, profile="neutral_v1"),
        role="case_study",
        purpose="Follow the approved case study",
    )
    request = production._request(
        adapter,
        (),
        "custom-film-op:" + "6" * 64,
    )
    seams = production.SharedSectionProductionSeams("tenant-1")
    narration = _spoken(
        "Follow the approved case study as a visible record changes on the "
        "monitor and the camera tracks its consequence through the room."
    )
    canonical = _marked(narration)
    generated_with_preface = (
        "# ANGLE SELECTION\n\n"
        "**ANGLE:** Begin with a planning explanation that must never be spoken.\n\n"
        "---\n\n"
        + canonical
    )
    edit_calls = []

    async def generate(*_args, **_kwargs):
        return {
            "script": generated_with_preface,
            "validation": {"valid": True, "issues": []},
        }

    async def edit(_scenes, violations, **_kwargs):
        edit_calls.append(list(violations))
        return [{"scene": 1, "text": canonical}]

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

    seams._executor = _Executor()
    monkeypatch.setattr(
        "script.brief_translator.script_generator.generate_script",
        generate,
    )
    monkeypatch.setattr("script_quality.edit_draft_with_violations", edit)
    monkeypatch.setattr("script_quality.run_critique_and_edit", quality)
    monkeypatch.setattr("database.get_pool", get_pool)

    result = await seams._script(request)

    assert len(edit_calls) == 1
    assert any(
        "canonical ACT marker must be the first non-whitespace content" in issue
        for issue in edit_calls[0]
    )
    assert not any("spoken word count" in issue for issue in edit_calls[0])
    assert conn.saved_text == canonical
    assert result["quality_verdict"] == "pass"


@pytest.mark.asyncio
async def test_deterministic_repair_restores_exact_act_marker_and_removes_end_wrapper(
    monkeypatch,
):
    request = production._request(
        _adapter("script", seconds=12),
        (),
        "custom-film-op:" + "3" * 64,
    )
    seams = production.SharedSectionProductionSeams("tenant-1")
    initial = _marked(_spoken(
        "Sourced evidence appears on a monitor while the camera follows the "
        "visible signal through the room.",
        target=40,
    ))
    repaired_spoken = _spoken(
        "Sourced evidence appears on a monitor while the camera follows the "
        "visible signal through the room."
    )
    malformed = (
        "ACT 1 — EVIDENCE | 0:00 - 0:12 | ~30 words\n"
        + repaired_spoken
        + "\nEND"
    )
    corrected = _marked(repaired_spoken)
    edit_calls = []

    async def generate(*_args, **_kwargs):
        return {"script": initial, "validation": {"valid": True, "issues": []}}

    async def edit(_scenes, violations, **_kwargs):
        edit_calls.append(list(violations))
        return [
            {
                "scene": 1,
                "text": malformed if len(edit_calls) == 1 else corrected,
            }
        ]

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

    seams._executor = _Executor()
    monkeypatch.setattr(
        "script.brief_translator.script_generator.generate_script",
        generate,
    )
    monkeypatch.setattr("script_quality.edit_draft_with_violations", edit)
    monkeypatch.setattr("script_quality.run_critique_and_edit", quality)
    monkeypatch.setattr("database.get_pool", get_pool)

    await seams._script(request)

    assert len(edit_calls) == 2
    assert any("shared bracketed ACT marker" in issue for issue in edit_calls[1])
    for violations in edit_calls:
        contract = violations[-1]
        assert "OUTPUT FORMAT LAW" in contract
        assert (
            "[ACT 1 — <SHORT SECTION TITLE> | "
            "0:00 - 0:12 | ~30 words]"
        ) in contract
        assert "Do not replace the bracketed marker with ACT/END prose" in contract
        assert "Open on the strongest concrete visible proof" in contract
        assert "Escalate across distinct approved evidence types" in contract
    assert conn.saved_text == corrected
    assert "\nEND" not in conn.saved_text


@pytest.mark.asyncio
async def test_visually_generic_nonconvergence_remains_fail_closed(
    monkeypatch,
):
    request = production._request(
        _adapter("script", seconds=12),
        (),
        "custom-film-op:" + "2" * 64,
    )
    seams = production.SharedSectionProductionSeams("tenant-1")
    generic = _marked(_spoken(
        "Sourced evidence matters and the story continues with important "
        "stakes that become more meaningful for everyone."
    ))
    quality_calls = []

    async def generate(*_args, **_kwargs):
        return {"script": generic, "validation": {"valid": True, "issues": []}}

    async def nonconverged_quality(_tenant, _video, scenes, **kwargs):
        quality_calls.append((copy.deepcopy(scenes), kwargs))
        return {
            "scenes": copy.deepcopy(scenes),
            "critique": SimpleNamespace(
                verdict="revise",
                score=42,
                failing_gates=["visual_story_readiness"],
                violations=["visual_story_readiness"],
                rule_verdicts=[
                    SimpleNamespace(
                        rule="visual_story_readiness",
                        passed=False,
                    )
                ],
                needs_revision=True,
            ),
            "needs_review": True,
            "edit_rounds": production._SCRIPT_REPAIR_ATTEMPTS,
            "regenerated": False,
            "changed": False,
        }

    async def forbidden_pool():
        raise AssertionError("visually generic script cannot reach persistence")

    seams._executor = _Executor()
    monkeypatch.setattr(
        "script.brief_translator.script_generator.generate_script",
        generate,
    )
    monkeypatch.setattr(
        "script_quality.run_critique_and_edit",
        nonconverged_quality,
    )
    monkeypatch.setattr("database.get_pool", forbidden_pool)

    with pytest.raises(
        CustomFilmContractError,
        match="failed visual-story quality before voice or imagery",
    ):
        await seams._script(request)

    assert len(quality_calls) == 1
    rules = quality_calls[0][1]["rules_text"]
    constraints = quality_calls[0][1]["edit_constraints"][0]
    assert "visual_story_readiness" in rules
    assert "role_structure_quality" in rules
    assert "story_arc_continuity" not in rules
    assert "story_arc_continuity" not in quality_calls[0][1]["severity_by_rule"]
    assert "Open on the strongest concrete visible proof" in rules
    assert "Escalate across distinct approved evidence types" in rules
    assert "Every narrative beat must name a concrete visible subject" in constraints
    assert "Replace abstract summary, generic stakes, promises" in constraints
    assert "Open on the strongest concrete visible proof" in constraints
    assert "Escalate across distinct approved evidence types" in constraints
