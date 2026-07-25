from __future__ import annotations

import copy
import json
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


def _bilingual_screenplay() -> str:
    return "\n".join(
        (
            "[AV SECTION — SIGNAL | 0:00 - 0:12]",
            "[BEAT 1 | 0:00 - 0:06]",
            "VISUAL: Mara studies a pulsing signal on the console.",
            "SOUND: A relay clicks beneath quiet room tone.",
            "DIALOGUE Mara [en | pair=signal-1]: The signal is back.",
            "CARRY-IN: silent console",
            "CARRY-OUT: pulsing signal",
            "[BEAT 2 | 0:06 - 0:12]",
            "VISUAL: Mara turns the display toward her partner.",
            "SOUND: The relay tone steadies.",
            "DIALOGUE Mara [es | pair=signal-1]: La señal ha vuelto.",
            "CARRY-IN: pulsing signal",
            "CARRY-OUT: shared signal",
        )
    )


def test_all_narrated_character_actions_fail_closed():
    bad = "\n".join(
        (
            "[AV SECTION — SIGNAL | 0:00 - 0:12]",
            "[BEAT 1 | 0:00 - 0:12]",
            "VISUAL: A dark console fills the frame.",
            "SOUND: Tape reels scrape under low room tone.",
            "VO [en]: Mara sits at the console. She rewinds the tape and looks up.",
            "CARRY-IN: silent console",
            "CARRY-OUT: rewound tape",
        )
    )

    parsed, issues = production._parse_custom_film_av_screenplay(
        bad,
        exact_seconds=12,
        language_mode="bilingual",
        approved_languages=("en", "es"),
    )

    assert parsed is None
    assert "visual/action direction leaked into an audible segment" in issues
    assert any("on-screen speaker performing in two languages" in issue for issue in issues)


def test_corrected_bilingual_visual_dialogue_sound_split_parses_for_persistence():
    parsed, issues = production._parse_custom_film_av_screenplay(
        _bilingual_screenplay(),
        exact_seconds=12,
        language_mode="bilingual",
        approved_languages=("en", "es"),
    )

    assert issues == []
    assert parsed["exact_seconds"] == 12
    assert [beat["end_seconds"] for beat in parsed["visual_beats"]] == [6, 12]
    assert [segment["speaker"] for segment in parsed["dialogue_segments"]] == [
        "Mara",
        "Mara",
    ]
    assert {segment["language"] for segment in parsed["dialogue_segments"]} == {
        "en",
        "es",
    }
    assert production._custom_film_av_narration_text(
        parsed["dialogue_segments"]
    ) == ""
    from scripts.coverage_to_app import _dialogue_turns

    assert _dialogue_turns(_bilingual_screenplay()) == [
        ("Mara", "The signal is back."),
        ("Mara", "La señal ha vuelto."),
    ]


def test_voice_extractor_carries_only_sparse_vo_never_visual_or_dialogue():
    segments = [
        {"type": "narration", "language": "en", "text": "The signal returns."},
        {
            "type": "dialogue",
            "speaker": "Mara",
            "language": "es",
            "text": "La señal ha vuelto.",
        },
    ]

    assert production._custom_film_av_narration_text(segments) == (
        "The signal returns."
    )


def test_gap_or_carry_break_rejects_disconnected_beats():
    broken = _bilingual_screenplay().replace(
        "[BEAT 2 | 0:06 - 0:12]",
        "[BEAT 2 | 0:07 - 0:12]",
    ).replace(
        "CARRY-IN: pulsing signal",
        "CARRY-IN: unrelated object",
    )

    parsed, issues = production._parse_custom_film_av_screenplay(
        broken,
        exact_seconds=12,
        language_mode="bilingual",
        approved_languages=("en", "es"),
    )

    assert parsed is None
    assert "AV beat timing must be contiguous and positive" in issues
    assert "AV beat carry-out must exactly match the next carry-in" in issues


def test_av_tracks_keep_current_section_grounding_exclusive():
    text = _bilingual_screenplay().replace(
        "Mara studies a pulsing signal on the console.",
        "Mara studies 47 Chicago signals on the console.",
    )
    parsed, issues = production._parse_custom_film_av_screenplay(
        text,
        exact_seconds=12,
        language_mode="bilingual",
        approved_languages=("en", "es"),
    )
    assert issues == []

    grounding = production._custom_film_av_grounding_issues(
        parsed,
        approved_context="case_study\nFollow Mara and the approved signal",
    )

    assert any("47" in issue for issue in grounding)
    assert any("Chicago" in issue for issue in grounding)


def test_av_grounding_allows_sentence_starts_but_rejects_mid_sentence_names():
    parsed, issues = production._parse_custom_film_av_screenplay(
        _bilingual_screenplay(),
        exact_seconds=12,
        language_mode="bilingual",
        approved_languages=("en", "es"),
    )
    assert issues == []
    assert production._custom_film_av_grounding_issues(
        parsed,
        approved_context="case_study\nFollow Mara and the approved signal",
    ) == []

    drifted, drift_issues = production._parse_custom_film_av_screenplay(
        _bilingual_screenplay().replace(
            "a pulsing signal",
            "a Chicago signal routed through ERCOT",
        ),
        exact_seconds=12,
        language_mode="bilingual",
        approved_languages=("en", "es"),
    )
    assert drift_issues == []
    grounding = production._custom_film_av_grounding_issues(
        drifted,
        approved_context="case_study\nFollow Mara and the approved signal",
    )
    assert any("Chicago" in issue and "ERCOT" in issue for issue in grounding)


@pytest.mark.parametrize(
    ("old", "new", "anchor"),
    [
        (
            "Mara studies a pulsing signal on the console.",
            "Chicago signals pulse on the console.",
            "Chicago",
        ),
        (
            "A relay clicks beneath quiet room tone.",
            "ERCOT relays click beneath quiet room tone.",
            "ERCOT",
        ),
        ("CARRY-IN: silent console", "CARRY-IN: Chicago console", "Chicago"),
        (
            "The signal is back.",
            "Chicago confirms the signal is back.",
            "Chicago",
        ),
    ],
)
def test_av_grounding_rejects_entities_at_start_of_every_factual_track(
    old,
    new,
    anchor,
):
    parsed, issues = production._parse_custom_film_av_screenplay(
        _bilingual_screenplay().replace(old, new),
        exact_seconds=12,
        language_mode="bilingual",
        approved_languages=("en", "es"),
    )
    assert issues == []
    grounding = production._custom_film_av_grounding_issues(
        parsed,
        approved_context="case_study\nFollow Mara and the approved signal",
    )
    assert any(anchor in issue for issue in grounding)


def test_dialogue_speaker_requires_exact_approved_identity_not_prefix_alias():
    parsed, issues = production._parse_custom_film_av_screenplay(
        _bilingual_screenplay().replace("DIALOGUE Mara", "DIALOGUE Mar"),
        exact_seconds=12,
        language_mode="bilingual",
        approved_languages=("en", "es"),
    )
    assert issues == []
    grounding = production._custom_film_av_grounding_issues(
        parsed,
        approved_context="case_study\nFollow Mara and the approved signal",
    )
    assert any("Mar" in issue for issue in grounding)


def test_bilingual_language_contract_rejects_third_or_unapproved_labels():
    third = _bilingual_screenplay().replace(
        "DIALOGUE Mara [es | pair=signal-1]: La señal ha vuelto.",
        "\n".join(
            (
                "DIALOGUE Mara [es | pair=signal-1]: La señal ha vuelto.",
                "DIALOGUE Mara [fr | pair=signal-1]: Le signal est revenu.",
            )
        ),
    )
    parsed, issues = production._parse_custom_film_av_screenplay(
        third,
        exact_seconds=12,
        language_mode="bilingual",
        approved_languages=("en", "es"),
    )
    assert parsed is None
    assert "bilingual dialogue must use exactly the two approved languages" in issues
    assert (
        "bilingual translation pairs must contain exactly both approved languages"
        in issues
    )

    _, default_issues = production._parse_custom_film_av_screenplay(
        _bilingual_screenplay(),
        exact_seconds=12,
        language_mode="bilingual",
    )
    assert "bilingual dialogue must use exactly the two approved languages" in default_issues


def test_generated_av_contract_names_exact_configured_language_labels():
    request = production._request(
        replace(
            _adapter("script"),
            language={"mode": "bilingual", "languages": ["es", "en"]},
            dubbing={"enabled": True, "mode": "speech_to_speech"},
            segmentation={"mode": "speaker_turn"},
        ),
        (),
        "custom-film-op:" + "7" * 64,
    )

    contract = production._custom_film_av_contract(request)

    assert "labels 'es' and 'en'" in contract
    assert "No third language label is allowed" in contract


def test_whole_arc_requires_concrete_carry_between_sections():
    first, first_issues = production._parse_custom_film_av_screenplay(
        _bilingual_screenplay(),
        exact_seconds=12,
        language_mode="bilingual",
        approved_languages=("en", "es"),
    )
    second_text = _bilingual_screenplay().replace(
        "CARRY-IN: silent console",
        "CARRY-IN: unrelated report",
        1,
    )
    second, second_issues = production._parse_custom_film_av_screenplay(
        second_text,
        exact_seconds=12,
        language_mode="bilingual",
        approved_languages=("en", "es"),
    )
    assert first_issues == second_issues == []

    assert production._validate_custom_film_av_arc([first, second]) == [
        "AV section 1 carry-out does not match section 2 carry-in"
    ]


def test_five_disconnected_sections_fail_whole_arc_cause_and_effect():
    parsed, issues = production._parse_custom_film_av_screenplay(
        _bilingual_screenplay(),
        exact_seconds=12,
        language_mode="bilingual",
        approved_languages=("en", "es"),
    )
    assert issues == []
    sections = []
    for index in range(5):
        section = copy.deepcopy(parsed)
        section["visual_beats"][0]["carry_in"] = f"input-{index}"
        section["visual_beats"][-1]["carry_out"] = f"output-{index}"
        sections.append(section)

    assert len(production._validate_custom_film_av_arc(sections)) == 4


def test_single_exact_five_minute_beat_uses_cinematic_not_wall_to_wall_vo():
    spoken = " ".join(["approved signal returns"] * 25)
    screenplay = "\n".join(
        (
            "[AV SECTION — LONG FORM | 0:00 - 5:00]",
            "[BEAT 1 | 0:00 - 5:00]",
            "VISUAL: The approved signal moves through a changing environment.",
            "SOUND: Evolving ambience follows the visible state.",
            f"VO [en]: {spoken}",
            "CARRY-IN: opening signal",
            "CARRY-OUT: resolved signal",
        )
    )

    parsed, issues = production._parse_custom_film_av_screenplay(
        screenplay,
        exact_seconds=300,
        language_mode="narrator",
    )

    assert issues == []
    assert parsed["exact_seconds"] == 300
    assert parsed["spoken_words"] == 75


def test_legacy_narration_contract_remains_available_outside_coverage_av_mode():
    legacy = (
        "[ACT 1 — EVIDENCE | 0:00 - 0:12 | ~30 words]\n"
        + "approved evidence "
        + " ".join(["evidence"] * 28)
    )

    assert production._script_grounding_issues(
        legacy,
        approved_context="evidence\nShow approved evidence",
        config=production._ExactSectionConfig(12),
        generator_validation={"valid": True, "issues": []},
    ) == []


class _Executor:
    def __init__(self):
        self._pipeline = SimpleNamespace(anthropic=object())

    async def _ensure_initialized(self):
        return None

    async def _get_video(self, _video_id):
        return {"video_title": "AV film"}


def _quality_pass(scenes):
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
@pytest.mark.parametrize("matching_carry", [True, False])
async def test_last_script_barrier_is_preinsert_exact_and_selects_dialogue_route(
    monkeypatch,
    matching_carry,
):
    first_id = "section-first"
    closing_id = "section-closing"
    arc = (
        {
            "order_index": 0,
            "section_id": first_id,
            "role": "case_study",
            "purpose": "Follow Mara and the approved signal",
            "render_mode": "coverage",
        },
        {
            "order_index": 1,
            "section_id": closing_id,
            "role": "closing",
            "purpose": "Land Mara and the approved ending",
            "render_mode": "coverage",
        },
    )
    request = production._request(
        replace(
            _adapter("script", section_id=closing_id, seconds=12),
            order_index=1,
            role="closing",
            purpose="Land Mara and the approved ending",
            language={"mode": "bilingual", "languages": ["en", "es"]},
            dubbing={"enabled": True, "mode": "speech_to_speech"},
            segmentation={"mode": "speaker_turn"},
            story_arc=arc,
        ),
        (),
        "custom-film-op:" + "8" * 64,
    )
    candidate = _bilingual_screenplay()
    prior_text = _bilingual_screenplay().replace(
        "CARRY-OUT: shared signal",
        (
            "CARRY-OUT: silent console"
            if matching_carry
            else "CARRY-OUT: unrelated evidence"
        ),
    )
    prior_parsed, prior_issues = production._parse_custom_film_av_screenplay(
        prior_text,
        exact_seconds=12,
        language_mode="bilingual",
        approved_languages=("en", "es"),
    )
    assert prior_issues == []
    inserted = []
    dialogue_modes = []

    class Connection:
        async def fetch(self, sql, *args):
            assert "custom_film_section_scenes css" in sql
            assert "css.plan_id = $3" in sql
            assert "css.section_id = ANY($4::text[])" in sql
            assert args[2] == request.plan_id
            assert args[3] == [first_id]
            return [
                {
                    "section_id": first_id,
                    "script_validation": "legacy non-json validation",
                },
                {
                    "section_id": first_id,
                    "script_validation": json.dumps(
                        {
                            "custom_film": {
                                "runtime_hash": request.runtime_hash,
                                "section_id": first_id,
                            },
                            "shared_validation": {"parsed": prior_parsed},
                        }
                    ),
                }
            ]

        async def fetchrow(self, sql, *args):
            inserted.append(args[4])
            return {"id": args[0]}

        async def execute(self, sql, *args):
            assert "UPDATE videos" in sql
            dialogue_modes.append(args[2])
            return "UPDATE 1"

    async def get_pool():
        return _Pool(Connection())

    async def generate(*_args, **_kwargs):
        return {"script": candidate, "validation": {"valid": True, "issues": []}}

    async def quality(_tenant, _video, scenes, **kwargs):
        assert kwargs["severity_by_rule"]["bilingual_performance_fidelity"] == "hard_gate"
        return _quality_pass(scenes)

    seams = production.SharedSectionProductionSeams("tenant-1")
    seams._executor = _Executor()
    monkeypatch.setattr(
        "script.brief_translator.script_generator.generate_script",
        generate,
    )
    monkeypatch.setattr("script_quality.run_critique_and_edit", quality)
    monkeypatch.setattr("database.get_pool", get_pool)

    if matching_carry:
        await seams._script(request)
        assert inserted == [candidate]
        assert dialogue_modes == ["character_dialogue"]
    else:
        with pytest.raises(
            CustomFilmContractError,
            match="whole-arc AV screenplay failed continuity",
        ):
            await seams._script(request)
        assert inserted == []
        assert dialogue_modes == []
