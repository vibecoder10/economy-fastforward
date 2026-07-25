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
from custom_film_contract import canonical_hash
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
            self.dialogue_segments = None
            self.validation = None

        async def fetchrow(self, sql, *args):
            assert "INSERT INTO scripts" in sql
            self.saved_text = args[4]
            self.validation = args[7]
            self.dialogue_segments = args[8]
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


def test_legacy_interleaved_script_request_hash_remains_2f7b4c9d_compatible():
    adapter = next(
        item
        for item in section_runtime.compile_stage_adapters(_envelope())
        if item.stage == "script" and item.order_index == 0
    )
    assert all(
        set(item) == {"order_index", "role", "purpose"}
        for item in adapter.story_arc
    )
    request = production._request(
        adapter,
        (),
        "custom-film-op:" + "a" * 64,
    )
    expected_request_hash = (
        "9597db1bfb1564500b64ce7e82959d6e9c7948c656d72010eb4b604c182832d1"
    )

    assert canonical_hash(request.payload()) == expected_request_hash
    spec = production.CustomFilmProductionRunner("tenant-1").operation_spec(
        adapter,
        (),
        request.operation_id,
    )
    assert spec.request_hash == expected_request_hash


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


def test_empty_story_arc_does_not_misclassify_direct_adapter_as_final_section():
    assert production._script_story_arc_guidance(
        (),
        current_order_index=0,
    ) == ""
    assert production._script_story_arc_continuity_law(
        (),
        current_order_index=0,
    ) == ""


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


@pytest.mark.asyncio
async def test_resolution_repairs_share_arc_and_handoff_to_next_closing(
    monkeypatch,
):
    arc = (
        {
            "order_index": 0,
            "section_id": "section-a",
            "role": "resolution",
            "purpose": "Show the approved system restored",
            "render_mode": "coverage",
        },
        {
            "order_index": 1,
            "section_id": "section-closing",
            "role": "closing",
            "purpose": "Land the approved final synthesis",
            "render_mode": "coverage",
        },
    )
    adapter = replace(
        _adapter("script", seconds=12),
        role="resolution",
        purpose="Show the approved system restored",
        story_arc=arc,
    )
    request = production._request(
        adapter,
        (),
        "custom-film-op:" + "5" * 64,
    )
    def av_screenplay(*, visual: str, vo: str, carry_out: str) -> str:
        return "\n".join(
            (
                "[AV SECTION — RESTORATION | 0:00 - 0:12]",
                "[BEAT 1 | 0:00 - 0:12]",
                f"VISUAL: {visual}",
                "SOUND: Low electrical ambience rises into a clear tone.",
                f"VO [en]: {vo}",
                (
                    "CARRY-IN: approved opening state — Show the approved "
                    "system restored"
                ),
                f"CARRY-OUT: {carry_out}",
            )
        )

    invented = av_screenplay(
        visual="The approved system waits in darkness.",
        vo="Mara sits at the console and rewinds the restored signal.",
        carry_out=(
            "approved transition state — Land the approved final synthesis"
        ),
    )
    generic_threat = av_screenplay(
        visual="The approved system brightens across the visible display.",
        vo="The approved system is restored, but it can be taken down anytime.",
        carry_out=(
            "approved transition state — Land the approved final synthesis"
        ),
    )
    clean_handoff = av_screenplay(
        visual="The restored frame settles and fills the visible display.",
        vo="The approved system is restored, carrying the earned result forward.",
        carry_out=(
            "approved transition state — Land the approved final synthesis"
        ),
    )
    deterministic_calls = []
    semantic_calls = []

    async def generate(_client, _brief, **_kwargs):
        return {"script": invented, "validation": {"valid": True, "issues": []}}

    async def edit(_scenes, violations, **_kwargs):
        deterministic_calls.append(list(violations))
        return [{"scene": 1, "text": generic_threat}]

    async def quality(_tenant, _video, scenes, **kwargs):
        semantic_calls.append((copy.deepcopy(scenes), kwargs))
        return {
            "scenes": [{"scene": 1, "text": clean_handoff}],
            "critique": SimpleNamespace(
                verdict="pass",
                score=97,
                failing_gates=[],
                violations=[],
                rule_verdicts=[],
                needs_revision=False,
            ),
            "needs_review": False,
            "edit_rounds": 1,
            "regenerated": False,
            "changed": True,
        }

    class Connection:
        def __init__(self):
            self.saved_text = None
            self.validation = None
            self.dialogue_segments = None

        async def fetchrow(self, sql, *args):
            assert "INSERT INTO scripts" in sql
            self.saved_text = args[4]
            self.validation = args[7]
            self.dialogue_segments = args[8]
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

    assert len(deterministic_calls) == 1
    deterministic_context = deterministic_calls[0][-1]
    semantic_context = semantic_calls[0][1]["edit_constraints"][0]
    for context in (deterministic_context, semantic_context):
        assert "EXCLUSIVE APPROVED SECTION CONTRACT" in context
        assert "SECTION 1 [CURRENT SECTION] — ROLE: resolution" in context
        assert (
            "SECTION 2 — ROLE: closing; "
            "PURPOSE: Land the approved final synthesis"
        ) in context
        assert "Use that next purpose only as the direction of the handoff" in context
        assert "Do not state, preview, duplicate" in context
    rules = semantic_calls[0][1]["rules_text"]
    assert "story_arc_continuity:" in rules
    assert "Reject a generic threat, warning, or open loop" in rules
    assert (
        semantic_calls[0][1]["severity_by_rule"]["story_arc_continuity"]
        == "hard_gate"
    )
    parsed, issues = production._parse_custom_film_av_screenplay(
        clean_handoff,
        exact_seconds=12,
        language_mode="narrator",
    )
    assert issues == []
    assert parsed["dialogue_segments"][0]["text"].startswith(
        "The approved system is restored"
    )
    assert "taken down anytime" not in conn.saved_text
    assert "Land the approved final synthesis" in conn.saved_text
    assert '"format": "custom_film_av_v1"' in conn.validation
    assert '"type": "narration"' in conn.dialogue_segments
    assert result["quality_verdict"] == "pass"
