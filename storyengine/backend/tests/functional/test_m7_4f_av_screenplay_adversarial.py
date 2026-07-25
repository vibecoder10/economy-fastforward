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


def _with_boundary_carries(
    screenplay: str,
    *,
    carry_in: str,
    carry_out: str,
) -> str:
    lines = screenplay.splitlines()
    first_in = next(index for index, line in enumerate(lines) if line.startswith("CARRY-IN: "))
    last_out = max(
        index for index, line in enumerate(lines) if line.startswith("CARRY-OUT: ")
    )
    lines[first_in] = f"CARRY-IN: {carry_in}"
    lines[last_out] = f"CARRY-OUT: {carry_out}"
    return "\n".join(lines)


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


def test_av_grounding_rejects_sentence_initial_acronym_deterministically():
    parsed, issues = production._parse_custom_film_av_screenplay(
        _bilingual_screenplay().replace(
            "A relay clicks beneath quiet room tone.",
            "ERCOT relays click beneath quiet room tone.",
        ),
        exact_seconds=12,
        language_mode="bilingual",
        approved_languages=("en", "es"),
    )
    assert issues == []
    grounding = production._custom_film_av_grounding_issues(
        parsed,
        approved_context="case_study\nFollow Mara and the approved signal",
    )
    assert any("ERCOT" in issue for issue in grounding)


@pytest.mark.parametrize("ordinary_noun", ["Control", "Lights", "Map"])
def test_av_grounding_allows_ordinary_sentence_initial_visual_nouns(
    ordinary_noun,
):
    parsed, issues = production._parse_custom_film_av_screenplay(
        _bilingual_screenplay().replace(
            "Mara studies a pulsing signal on the console.",
            f"{ordinary_noun} shifts as the approved signal returns.",
        ),
        exact_seconds=12,
        language_mode="bilingual",
        approved_languages=("en", "es"),
    )
    assert issues == []

    assert production._custom_film_av_grounding_issues(
        parsed,
        approved_context="case_study\nFollow Mara and the approved signal",
    ) == []


def test_sentence_initial_title_case_entity_is_deferred_to_semantic_gate():
    parsed, issues = production._parse_custom_film_av_screenplay(
        _bilingual_screenplay().replace(
            "Mara studies a pulsing signal on the console.",
            "Texas routes the approved signal through the console.",
        ),
        exact_seconds=12,
        language_mode="bilingual",
        approved_languages=("en", "es"),
    )
    assert issues == []

    assert production._custom_film_av_grounding_issues(
        parsed,
        approved_context="case_study\nFollow Mara and the approved signal",
    ) == []


def test_lowercase_greek_and_contextual_code_designations_require_approval():
    text = _bilingual_screenplay().replace(
        "Mara studies a pulsing signal on the console.",
        (
            "Mara routes circuit alpha past node beta, panel gamma, and unit "
            "bravo."
        ),
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

    designation_issue = next(
        issue for issue in grounding if "designation anchors" in issue
    )
    for anchor in ("alpha", "beta", "gamma", "bravo"):
        assert anchor in designation_issue


def test_approved_designations_and_ordinary_lowercase_nouns_remain_valid():
    text = _bilingual_screenplay().replace(
        "Mara studies a pulsing signal on the console.",
        (
            "Mara routes circuit alpha past node beta and panel gamma while "
            "the control map and signal remain visible."
        ),
    )
    parsed, issues = production._parse_custom_film_av_screenplay(
        text,
        exact_seconds=12,
        language_mode="bilingual",
        approved_languages=("en", "es"),
    )
    assert issues == []

    assert production._custom_film_av_grounding_issues(
        parsed,
        approved_context=(
            "case_study\nFollow Mara through circuit alpha, node beta, and "
            "panel gamma using the approved control map and signal"
        ),
    ) == []


@pytest.mark.parametrize(
    ("probe", "expected"),
    [
        (
            "unit echo station golf sector hotel team india channel lima",
            {"echo", "golf", "hotel", "india", "lima"},
        ),
        (
            (
                "node mike site november code oscar phase papa unit uniform "
                "station x-ray"
            ),
            {"mike", "november", "oscar", "papa", "uniform", "x-ray"},
        ),
        (
            "unit alfa node alpha sector xray",
            {"alfa", "alpha", "xray"},
        ),
    ],
)
def test_full_contextual_nato_designation_vocabulary(probe, expected):
    assert production._script_designation_word_anchors(probe) == expected


def test_contextual_nato_words_remain_ordinary_when_standalone():
    ordinary = (
        "an echo fades through the hotel lobby beside a golf course while "
        "uniform fabric, india ink, and whiskey sit on display"
    )

    assert production._script_designation_word_anchors(ordinary) == set()


def test_approved_context_subtracts_contextual_nato_designations():
    factual = "unit echo meets station x-ray beside node mike"
    approved = "Follow unit echo, station x-ray, and node mike"

    assert (
        production._script_designation_word_anchors(factual)
        - production._script_designation_word_anchors(approved)
    ) == set()


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


@pytest.mark.parametrize(
    ("screenplay", "expected_issue"),
    [
        (
            _bilingual_screenplay().replace(
                "DIALOGUE Mara [es | pair=signal-1]",
                "DIALOGUE Marco [es | pair=signal-1]",
            ),
            "bilingual translation pair turns must use one exact speaker",
        ),
        (
            _bilingual_screenplay().replace(
                "DIALOGUE Mara [es | pair=signal-1]: La señal ha vuelto.",
                "\n".join(
                    (
                        "DIALOGUE Mara [en | pair=signal-1]: The signal remains.",
                        "DIALOGUE Mara [es | pair=signal-1]: La señal ha vuelto.",
                    )
                ),
            ),
            "bilingual translation pairs must contain exactly both approved languages",
        ),
    ],
)
def test_translation_pair_rejects_cross_speaker_or_duplicate_language_turns(
    screenplay,
    expected_issue,
):
    parsed, issues = production._parse_custom_film_av_screenplay(
        screenplay,
        exact_seconds=12,
        language_mode="bilingual",
        approved_languages=("en", "es"),
    )

    assert parsed is None
    assert expected_issue in issues


def test_exact_mara_en_es_translation_pair_is_valid():
    parsed, issues = production._parse_custom_film_av_screenplay(
        _bilingual_screenplay(),
        exact_seconds=12,
        language_mode="bilingual",
        approved_languages=("en", "es"),
    )

    assert issues == []
    assert [
        (
            segment["speaker"],
            segment["language"],
            segment["translation_pair"],
        )
        for segment in parsed["dialogue_segments"]
    ] == [
        ("Mara", "en", "signal-1"),
        ("Mara", "es", "signal-1"),
    ]


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
    assert "DIALOGUE <speaker> [es | pair=<id>]:" in contract
    assert "DIALOGUE <same speaker> [en | pair=<same id>]:" in contract


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        ({"mode": "narrator"}, "EXACT NARRATOR TAG: VO [en]:"),
        (
            {"mode": "narrator", "target_language": "Spanish"},
            "EXACT NARRATOR TAG: VO [es]:",
        ),
        (
            {"mode": "simple_single_language", "language": "Spanish"},
            "EXACT PERFORMED TAG: DIALOGUE <speaker> [es]:",
        ),
    ],
)
def test_av_contract_emits_exact_canonical_tag_for_every_language_mode(
    language,
    expected,
):
    request = production._request(
        replace(
            _adapter("script"),
            language=language,
            dialogue_audio=(
                "grok_native"
                if language["mode"] == "simple_single_language"
                else "voice_over"
            ),
            segmentation={
                "mode": (
                    "speaker_turn"
                    if language["mode"] == "simple_single_language"
                    else "visual_cue"
                )
            },
        ),
        (),
        "custom-film-op:" + "3" * 64,
    )

    contract = production._custom_film_av_contract(request)
    assert expected in contract
    assert "SILENT-BEAT LAW: Omit the entire audible-track line" in contract
    assert "Never emit dash, None, N/A, N-A, silence" in contract
    if language["mode"] == "narrator":
        assert "use only VO [" in contract
        assert "Never emit DIALOGUE" in contract
    elif language["mode"] == "simple_single_language":
        assert "use only DIALOGUE <speaker>" in contract
        assert "Never emit VO or a translation pair ID" in contract


def test_noncanonical_language_name_has_actionable_exact_tag_diagnostic():
    text = "\n".join(
        (
            "[AV SECTION — SIGNAL | 0:00 - 0:12]",
            "[BEAT 1 | 0:00 - 0:12]",
            "VISUAL: The approved signal fills the control screen.",
            "SOUND: Low room tone continues.",
            "VO [English]: The approved signal returns.",
            "CARRY-IN: approved opening state",
            "CARRY-OUT: approved final state",
        )
    )

    parsed, issues = production._parse_custom_film_av_screenplay(
        text,
        exact_seconds=12,
        language_mode="narrator",
        canonical_languages=("en",),
    )

    assert parsed is None
    assert any(
        "noncanonical VO language label 'English'; use exactly VO [en]:"
        in issue
        for issue in issues
    )
    assert "AV screenplay contains a malformed or unknown track tag" not in issues


def test_local_placeholder_cleanup_is_exact_and_unknown_text_remains():
    raw = "\n".join(
        (
            "VO [en]: —",
            "DIALOGUE: N/A",
            "DIALOGUE Mara [en]: silence",
            "VO [en]: TBD",
            "DIALOGUE: actual words",
            "---",
        )
    )

    cleaned, removed = (
        production._remove_custom_film_av_empty_audible_placeholders(raw)
    )

    assert removed == 3
    assert cleaned.splitlines() == [
        "VO [en]: TBD",
        "DIALOGUE: actual words",
        "---",
    ]


def test_surviving_placeholder_text_is_rejected_actionably():
    text = "\n".join(
        (
            "[AV SECTION — SIGNAL | 0:00 - 0:12]",
            "[BEAT 1 | 0:00 - 0:12]",
            "VISUAL: The approved signal fills the screen.",
            "SOUND: Low room tone continues.",
            "VO [en]: None",
            "CARRY-IN: opening signal",
            "CARRY-OUT: final signal",
        )
    )

    parsed, issues = production._parse_custom_film_av_screenplay(
        text,
        exact_seconds=12,
        language_mode="narrator",
        canonical_languages=("en",),
    )

    assert parsed is not None
    assert any(
        "AV audible placeholder text is forbidden" in issue
        for issue in issues
    )


def test_explicit_target_language_parser_requires_its_canonical_tag():
    spanish = _bilingual_screenplay().replace(
        "DIALOGUE Mara [en | pair=signal-1]: The signal is back.",
        "VO [es]: La señal aprobada ha vuelto.",
    ).replace(
        "DIALOGUE Mara [es | pair=signal-1]: La señal ha vuelto.",
        "",
    )

    parsed, issues = production._parse_custom_film_av_screenplay(
        spanish,
        exact_seconds=12,
        language_mode="narrator",
        canonical_languages=("es",),
    )

    assert issues == []
    assert parsed["dialogue_segments"][0]["language"] == "es"


@pytest.mark.parametrize(
    ("screenplay", "mode", "labels", "expected_issue"),
    [
        (
            "\n".join(
                (
                    "[AV SECTION — SIGNAL | 0:00 - 0:12]",
                    "[BEAT 1 | 0:00 - 0:12]",
                    "VISUAL: The approved signal fills the screen.",
                    "SOUND: Low room tone continues.",
                    "DIALOGUE Mara [en]: The approved signal returns.",
                    "CARRY-IN: opening signal",
                    "CARRY-OUT: final signal",
                )
            ),
            "narrator",
            ("en",),
            "narrator AV mode permits VO tracks only",
        ),
        (
            "\n".join(
                (
                    "[AV SECTION — SIGNAL | 0:00 - 0:12]",
                    "[BEAT 1 | 0:00 - 0:12]",
                    "VISUAL: La señal aprobada llena la pantalla.",
                    "SOUND: Un tono bajo continúa.",
                    "VO [es]: La señal aprobada ha vuelto.",
                    "CARRY-IN: señal inicial",
                    "CARRY-OUT: señal final",
                )
            ),
            "simple_single_language",
            ("es",),
            "simple single-language AV mode permits DIALOGUE tracks only",
        ),
        (
            "\n".join(
                (
                    "[AV SECTION — SIGNAL | 0:00 - 0:12]",
                    "[BEAT 1 | 0:00 - 0:12]",
                    "VISUAL: La señal aprobada llena la pantalla.",
                    "SOUND: Un tono bajo continúa.",
                    "DIALOGUE Mara [es | pair=signal-1]: La señal ha vuelto.",
                    "CARRY-IN: señal inicial",
                    "CARRY-OUT: señal final",
                )
            ),
            "simple_single_language",
            ("es",),
            "must not include a translation pair ID",
        ),
        (
            _bilingual_screenplay().replace(
                "DIALOGUE Mara [en | pair=signal-1]: The signal is back.",
                "\n".join(
                    (
                        "DIALOGUE Mara [en | pair=signal-1]: The signal is back.",
                        "VO [en]: The approved signal returns.",
                    )
                ),
            ),
            "bilingual",
            ("en", "es"),
            "bilingual AV mode permits paired DIALOGUE tracks only",
        ),
    ],
)
def test_av_language_modes_reject_wrong_audible_track_types(
    screenplay,
    mode,
    labels,
    expected_issue,
):
    parsed, issues = production._parse_custom_film_av_screenplay(
        screenplay,
        exact_seconds=12,
        language_mode=mode,
        approved_languages=(
            (labels[0], labels[1]) if len(labels) == 2 else None
        ),
        canonical_languages=labels,
    )

    assert parsed is None
    assert any(expected_issue in issue for issue in issues)


def _four_beat_narrator_screenplay(*, audible_beats: set[int]) -> str:
    lines = ["[AV SECTION — BLACKOUT | 0:00 - 0:40]"]
    carries = [
        "opening map",
        "lit console",
        "stable signal",
        "restored room",
        "final map",
    ]
    for index in range(4):
        beat = index + 1
        lines.extend(
            (
                f"[BEAT {beat} | 0:{index * 10:02d} - 0:{(index + 1) * 10:02d}]",
                "VISUAL: The approved map changes visibly.",
                "SOUND: Low electrical ambience shifts.",
            )
        )
        if beat in audible_beats:
            lines.append("VO [en]: The approved blackout signal changes.")
        lines.extend(
            (
                f"CARRY-IN: {carries[index]}",
                f"CARRY-OUT: {carries[index + 1]}",
            )
        )
    return "\n".join(lines)


def test_narrator_av_rejects_four_of_four_audible_beats():
    parsed, issues = production._parse_custom_film_av_screenplay(
        _four_beat_narrator_screenplay(audible_beats={1, 2, 3, 4}),
        exact_seconds=40,
        language_mode="narrator",
        canonical_languages=("en",),
    )

    assert parsed is not None
    assert any("use VO in at most 2 of 4 timed beats" in issue for issue in issues)


def test_narrator_av_accepts_two_of_four_audible_beats():
    parsed, issues = production._parse_custom_film_av_screenplay(
        _four_beat_narrator_screenplay(audible_beats={1, 3}),
        exact_seconds=40,
        language_mode="narrator",
        canonical_languages=("en",),
    )

    assert issues == []
    assert parsed["spoken_words"] == 10


@pytest.mark.asyncio
async def test_local_english_tag_repair_exposes_grounding_and_occupancy_together(
    monkeypatch,
):
    purpose = "Show the approved blackout map"
    next_purpose = "Restore the approved StoryEngine system"
    arc = (
        {
            "order_index": 0,
            "section_id": "section-a",
            "role": "evidence",
            "purpose": purpose,
            "render_mode": "coverage",
        },
        {
            "order_index": 1,
            "section_id": "section-b",
            "role": "resolution",
            "purpose": next_purpose,
            "render_mode": "coverage",
        },
    )
    request = production._request(
        replace(
            _adapter("script", seconds=40),
            role="evidence",
            purpose=purpose,
            story_arc=arc,
        ),
        (),
        "custom-film-op:" + "2" * 64,
    )
    bad = _with_boundary_carries(
        _four_beat_narrator_screenplay(audible_beats={1, 2, 3, 4})
        .replace("VO [en]:", "VO [English]:")
        .replace(
            "The approved map changes visibly.",
            (
                "The approved map marks 47 FBI substations on February 14th "
                "2027."
            ),
            1,
        ),
        carry_in=f"approved opening state — {purpose}",
        carry_out=f"approved transition state — {next_purpose}",
    )
    repaired = _with_boundary_carries(
        _four_beat_narrator_screenplay(audible_beats={1, 3}),
        carry_in=f"approved opening state — {purpose}",
        carry_out=f"approved transition state — {next_purpose}",
    )
    deterministic_calls = []
    inserted = []

    class Connection:
        async def fetchrow(self, _sql, *args):
            inserted.append(args[4])
            return {"id": args[0]}

        async def execute(self, _sql, *_args):
            return "UPDATE 1"

    async def get_pool():
        return _Pool(Connection())

    async def generate(*_args, **_kwargs):
        return {"script": bad, "validation": {"valid": True, "issues": []}}

    async def edit(scenes, violations, **_kwargs):
        deterministic_calls.append((copy.deepcopy(scenes), list(violations)))
        return [{"scene": 1, "text": repaired}]

    async def quality(_tenant, _video, scenes, **_kwargs):
        return _quality_pass(scenes)

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
    repaired_locally, violations = deterministic_calls[0]
    assert "VO [English]:" not in repaired_locally[0]["text"]
    assert repaired_locally[0]["text"].count("VO [en]:") == 4
    issue_text = "\n".join(violations)
    assert "47" in issue_text
    assert "FBI" in issue_text
    assert "2027" in issue_text
    assert "use VO in at most 2 of 4 timed beats" in issue_text
    assert "noncanonical VO language label" not in issue_text
    assert inserted == [repaired]
    assert result["quality_verdict"] == "pass"


@pytest.mark.asyncio
async def test_live_shape_placeholders_are_removed_before_grounding_repair(
    monkeypatch,
):
    purpose = "Show the approved outage map"
    next_purpose = "Restore the approved control signal"
    arc = (
        {
            "order_index": 0,
            "section_id": "section-a",
            "role": "evidence",
            "purpose": purpose,
            "render_mode": "coverage",
        },
        {
            "order_index": 1,
            "section_id": "section-b",
            "role": "resolution",
            "purpose": next_purpose,
            "render_mode": "coverage",
        },
    )
    request = production._request(
        replace(
            _adapter("script", seconds=40),
            role="evidence",
            purpose=purpose,
            story_arc=arc,
        ),
        (),
        "custom-film-op:" + "f" * 64,
    )
    bad_lines = _four_beat_narrator_screenplay(
        audible_beats={1, 2, 3, 4}
    ).splitlines()
    live_shape_lines = []
    visual_replaced = False
    for line in bad_lines:
        if line.startswith("VO [en]:"):
            live_shape_lines.extend(("VO [en]: —", "DIALOGUE: —"))
        elif line.startswith("VISUAL:") and not visual_replaced:
            live_shape_lines.append(
                "VISUAL: The approved map marks 17 FBI outage points at "
                "12:04 after seven seconds."
            )
            visual_replaced = True
        else:
            live_shape_lines.append(line)
    live_shape_lines.append("---")
    bad = _with_boundary_carries(
        "\n".join(live_shape_lines),
        carry_in=f"approved opening state — {purpose}",
        carry_out=f"approved transition state — {next_purpose}",
    )
    repaired = _with_boundary_carries(
        _four_beat_narrator_screenplay(audible_beats={1, 3}),
        carry_in=f"approved opening state — {purpose}",
        carry_out=f"approved transition state — {next_purpose}",
    )
    deterministic_calls = []
    inserted = []

    class Connection:
        async def fetchrow(self, _sql, *args):
            inserted.append(args[4])
            return {"id": args[0]}

        async def execute(self, _sql, *_args):
            return "UPDATE 1"

    async def get_pool():
        return _Pool(Connection())

    async def generate(*_args, **_kwargs):
        return {"script": bad, "validation": {"valid": True, "issues": []}}

    async def edit(scenes, violations, **_kwargs):
        deterministic_calls.append((copy.deepcopy(scenes), list(violations)))
        return [{"scene": 1, "text": repaired}]

    async def quality(_tenant, _video, scenes, **_kwargs):
        return _quality_pass(scenes)

    seams = production.SharedSectionProductionSeams("tenant-1")
    seams._executor = _Executor()
    monkeypatch.setattr(
        "script.brief_translator.script_generator.generate_script",
        generate,
    )
    monkeypatch.setattr("script_quality.edit_draft_with_violations", edit)
    monkeypatch.setattr("script_quality.run_critique_and_edit", quality)
    monkeypatch.setattr("database.get_pool", get_pool)

    await seams._script(request)

    assert len(deterministic_calls) == 1
    locally_cleaned, violations = deterministic_calls[0]
    cleaned_text = locally_cleaned[0]["text"]
    assert "VO [en]: —" not in cleaned_text
    assert "DIALOGUE: —" not in cleaned_text
    assert "---" in cleaned_text
    issue_text = "\n".join(violations)
    assert "insufficient cinematic spoken coverage" in issue_text
    assert "terminal separator lines" in issue_text
    assert "17" in issue_text
    assert "FBI" in issue_text
    assert "12" in issue_text
    assert "04" in issue_text
    assert "seven" in issue_text
    assert "SILENT-BEAT LAW" in issue_text
    assert inserted == [repaired]


@pytest.mark.asyncio
async def test_unknown_malformed_language_tag_fails_before_persistence(
    monkeypatch,
):
    purpose = "Show the approved signal"
    arc = (
        {
            "order_index": 0,
            "section_id": "section-a",
            "role": "evidence",
            "purpose": purpose,
            "render_mode": "coverage",
        },
        {
            "order_index": 1,
            "section_id": "section-b",
            "role": "closing",
            "purpose": "Land the approved signal",
            "render_mode": "coverage",
        },
    )
    request = production._request(
        replace(
            _adapter("script", seconds=12),
            purpose=purpose,
            story_arc=arc,
        ),
        (),
        "custom-film-op:" + "1" * 64,
    )
    malformed = "\n".join(
        (
            "[AV SECTION — SIGNAL | 0:00 - 0:12]",
            "[BEAT 1 | 0:00 - 0:12]",
            "VISUAL: The approved signal fills the screen.",
            "SOUND: Low room tone continues.",
            "VO Klingon: The approved signal returns.",
            f"CARRY-IN: approved opening state — {purpose}",
            "CARRY-OUT: approved transition state — Land the approved signal",
        )
    )
    repair_contexts = []
    database_touched = False

    async def generate(*_args, **_kwargs):
        return {
            "script": malformed,
            "validation": {"valid": True, "issues": []},
        }

    async def edit(_scenes, violations, **_kwargs):
        repair_contexts.extend(violations)
        return []

    async def get_pool():
        nonlocal database_touched
        database_touched = True
        raise AssertionError("malformed AV must fail before persistence")

    seams = production.SharedSectionProductionSeams("tenant-1")
    seams._executor = _Executor()
    monkeypatch.setattr(
        "script.brief_translator.script_generator.generate_script",
        generate,
    )
    monkeypatch.setattr("script_quality.edit_draft_with_violations", edit)
    monkeypatch.setattr("database.get_pool", get_pool)

    with pytest.raises(
        CustomFilmContractError,
        match="failed approved timing/grounding before voice or imagery",
    ):
        await seams._script(request)

    assert any("malformed or unknown track tag" in item for item in repair_contexts)
    assert any("EXACT NARRATOR TAG: VO [en]:" in item for item in repair_contexts)
    assert database_touched is False


@pytest.mark.asyncio
async def test_terminal_wrong_track_repairs_fail_before_persistence(
    monkeypatch,
):
    purpose = "Show the approved signal"
    arc = (
        {
            "order_index": 0,
            "section_id": "section-a",
            "role": "evidence",
            "purpose": purpose,
            "render_mode": "coverage",
        },
        {
            "order_index": 1,
            "section_id": "section-b",
            "role": "closing",
            "purpose": "Land the approved signal",
            "render_mode": "coverage",
        },
    )
    request = production._request(
        replace(
            _adapter("script", seconds=12),
            purpose=purpose,
            story_arc=arc,
        ),
        (),
        "custom-film-op:" + "0" * 64,
    )
    wrong_track = "\n".join(
        (
            "[AV SECTION — SIGNAL | 0:00 - 0:12]",
            "[BEAT 1 | 0:00 - 0:12]",
            "VISUAL: The approved signal fills the screen.",
            "SOUND: Low room tone continues.",
            "DIALOGUE Mara [en]: The approved signal returns.",
            f"CARRY-IN: approved opening state — {purpose}",
            "CARRY-OUT: approved transition state — Land the approved signal",
        )
    )
    repair_calls = []
    database_touched = False

    async def generate(*_args, **_kwargs):
        return {
            "script": wrong_track,
            "validation": {"valid": True, "issues": []},
        }

    async def edit(scenes, violations, **_kwargs):
        repair_calls.append((copy.deepcopy(scenes), list(violations)))
        return copy.deepcopy(scenes)

    async def get_pool():
        nonlocal database_touched
        database_touched = True
        raise AssertionError("wrong AV track type must fail before persistence")

    seams = production.SharedSectionProductionSeams("tenant-1")
    seams._executor = _Executor()
    monkeypatch.setattr(
        "script.brief_translator.script_generator.generate_script",
        generate,
    )
    monkeypatch.setattr("script_quality.edit_draft_with_violations", edit)
    monkeypatch.setattr("database.get_pool", get_pool)

    with pytest.raises(
        CustomFilmContractError,
        match="failed approved timing/grounding before voice or imagery",
    ):
        await seams._script(request)

    assert len(repair_calls) == production._SCRIPT_REPAIR_ATTEMPTS
    assert all(
        any(
            "narrator AV mode permits VO tracks only" in violation
            for violation in violations
        )
        for _scenes, violations in repair_calls
    )
    assert all(
        "EXACT NARRATOR TAG: VO [en]:" in violations[-1]
        for _scenes, violations in repair_calls
    )
    assert database_touched is False


def _resolution_screenplay(*, staged: bool) -> str:
    if staged:
        visuals = (
            "The engineer isolates the approved fault branch.",
            "The diagnostic panel visibly confirms branch isolation.",
            "The engineer routes the approved backup signal through the console.",
            "The load panel steadies as the approved system lights return.",
        )
        sounds = (
            "A breaker opens and the fault hum stops.",
            "A diagnostic tone confirms the isolated state.",
            "Relays engage in a rising sequence.",
            "The room tone settles under a stable signal.",
        )
        carries = (
            "approved fault map",
            "isolated branch",
            "confirmed isolation",
            "routed backup signal",
            "approved restored system",
        )
    else:
        visuals = (
            "The engineer pulls the approved restore switch once.",
            "Every control panel automatically returns online.",
            "A montage shows the approved system lights returning.",
            "The final display announces the approved system is restored.",
        )
        sounds = (
            "A switch clicks.",
            "A single automatic tone rises.",
            "Music swells beneath the montage.",
            "A bright confirmation chime rings.",
        )
        carries = (
            "approved fault map",
            "pulled restore switch",
            "automatic recovery",
            "returning light montage",
            "approved restored system",
        )
    lines = ["[AV SECTION — RESTORE | 0:00 - 0:40]"]
    for index, (visual, sound) in enumerate(zip(visuals, sounds), start=1):
        lines.extend(
            (
                f"[BEAT {index} | 0:{(index - 1) * 10:02d} - "
                f"0:{index * 10:02d}]",
                f"VISUAL: {visual}",
                f"SOUND: {sound}",
            )
        )
        if index in {1, 3}:
            lines.append(
                "VO [en]: The approved restoration advances through visible "
                "confirmation."
            )
        lines.extend(
            (
                f"CARRY-IN: {carries[index - 1]}",
                f"CARRY-OUT: {carries[index]}",
            )
        )
    return "\n".join(lines)


@pytest.mark.asyncio
async def test_magic_button_resolution_semantic_failure_never_persists(
    monkeypatch,
):
    purpose = "Restore the approved system safely"
    next_purpose = "Land the approved restored system"
    arc = (
        {
            "order_index": 0,
            "section_id": "section-a",
            "role": "resolution",
            "purpose": purpose,
            "render_mode": "coverage",
            "approved_visual_beats": (
                {
                    "narrative_function": "reveal",
                    "presentation": "NetworkExplainer",
                    "intents": ("network", "recovery"),
                    "handoff": "network_to_master",
                    "transition": "transform-carry",
                    "motion_capabilities": (
                        "motion.network_explainer",
                        "motion.incident_timeline",
                    ),
                },
            ),
        },
        {
            "order_index": 1,
            "section_id": "section-b",
            "role": "closing",
            "purpose": next_purpose,
            "render_mode": "coverage",
        },
    )
    request = production._request(
        replace(
            _adapter("script", seconds=40),
            role="resolution",
            purpose=purpose,
            story_arc=arc,
        ),
        (),
        "custom-film-op:" + "e" * 64,
    )
    candidate = _with_boundary_carries(
        _resolution_screenplay(staged=False),
        carry_in=f"approved opening state — {purpose}",
        carry_out=f"approved transition state — {next_purpose}",
    )
    observed = {}
    database_touched = False

    async def generate(_client, brief, **_kwargs):
        observed["guidance"] = brief["writer_guidance"]
        return {"script": candidate, "validation": {"valid": True, "issues": []}}

    async def quality(_tenant, _video, scenes, **kwargs):
        observed["rules"] = kwargs["rules_text"]
        observed["repair"] = kwargs["edit_constraints"][0]
        return {
            "scenes": copy.deepcopy(scenes),
            "critique": SimpleNamespace(
                verdict="fail",
                score=35,
                failing_gates=["role_structure_quality"],
                violations=[
                    "one switch plus automatic recovery does not prove a "
                    "dependent causal resolution"
                ],
                rule_verdicts=[],
                needs_revision=True,
            ),
            "needs_review": True,
            "edit_rounds": 2,
            "regenerated": False,
            "changed": False,
        }

    async def get_pool():
        nonlocal database_touched
        database_touched = True
        raise AssertionError("failed resolution must not persist")

    seams = production.SharedSectionProductionSeams("tenant-1")
    seams._executor = _Executor()
    monkeypatch.setattr(
        "script.brief_translator.script_generator.generate_script",
        generate,
    )
    monkeypatch.setattr("script_quality.run_critique_and_edit", quality)
    monkeypatch.setattr("database.get_pool", get_pool)

    with pytest.raises(
        CustomFilmContractError,
        match="failed visual-story quality before voice or imagery",
    ):
        await seams._script(request)

    for context in (
        observed["guidance"],
        observed["repair"],
        observed["rules"],
    ):
        assert "multiple dependent visible actions or decisions" in context
        assert "single switch, button, command, automatic recovery, or montage" in context
        assert "observable confirmation before the next step" in context
        assert "Repeated console commands" in context
        assert "parallel operators performing the same action" in context
        assert "Convert concrete evidence or state earned in earlier approved sections" in context
        assert "Do not invent technical labels, component counts, sectors, geographic" in context
        assert "directional qualifiers" in context
        assert "Use unlabeled relative visual state" in context
        assert "APPROVED VISUAL BEAT PLAN" in context
        assert "NetworkExplainer" in context
        assert "motion.network_explainer" in context
        assert "Never speak, caption, diagram, or expose raw component names" in context
        assert "authorizes that visual form only" in context
        assert "does not authorize new locations, directional geography" in context
    assert "approved_visual_plan_fidelity" in observed["rules"]
    assert database_touched is False


@pytest.mark.asyncio
async def test_staged_multi_step_resolution_passes_and_persists(
    monkeypatch,
):
    purpose = "Restore the approved system safely"
    next_purpose = "Land the approved restored system"
    arc = (
        {
            "order_index": 0,
            "section_id": "section-a",
            "role": "resolution",
            "purpose": purpose,
            "render_mode": "coverage",
        },
        {
            "order_index": 1,
            "section_id": "section-b",
            "role": "closing",
            "purpose": next_purpose,
            "render_mode": "coverage",
        },
    )
    request = production._request(
        replace(
            _adapter("script", seconds=40),
            role="resolution",
            purpose=purpose,
            story_arc=arc,
        ),
        (),
        "custom-film-op:" + "d" * 64,
    )
    candidate = _with_boundary_carries(
        _resolution_screenplay(staged=True),
        carry_in=f"approved opening state — {purpose}",
        carry_out=f"approved transition state — {next_purpose}",
    )
    inserted = []

    class Connection:
        async def fetchrow(self, _sql, *args):
            inserted.append(args[4])
            return {"id": args[0]}

        async def execute(self, _sql, *_args):
            return "UPDATE 1"

    async def get_pool():
        return _Pool(Connection())

    async def generate(*_args, **_kwargs):
        return {"script": candidate, "validation": {"valid": True, "issues": []}}

    async def quality(_tenant, _video, scenes, **kwargs):
        assert "multiple dependent visible actions or decisions" in kwargs[
            "rules_text"
        ]
        assert "Each middle beat must materially change the kind of work on screen" in kwargs[
            "rules_text"
        ]
        return _quality_pass(scenes)

    seams = production.SharedSectionProductionSeams("tenant-1")
    seams._executor = _Executor()
    monkeypatch.setattr(
        "script.brief_translator.script_generator.generate_script",
        generate,
    )
    monkeypatch.setattr("script_quality.run_critique_and_edit", quality)
    monkeypatch.setattr("database.get_pool", get_pool)

    result = await seams._script(request)

    assert inserted == [candidate]
    assert result["quality_verdict"] == "pass"


@pytest.mark.asyncio
async def test_long_resolution_with_only_macro_visual_phases_fails_before_quality(
    monkeypatch,
):
    purpose = "Restore the approved system safely"
    next_purpose = "Land the approved restored system"
    arc = (
        {
            "order_index": 0,
            "section_id": "section-a",
            "role": "resolution",
            "purpose": purpose,
            "render_mode": "coverage",
        },
        {
            "order_index": 1,
            "section_id": "section-b",
            "role": "closing",
            "purpose": next_purpose,
            "render_mode": "coverage",
        },
    )
    request = production._request(
        replace(
            _adapter("script", seconds=30),
            role="resolution",
            purpose=purpose,
            story_arc=arc,
        ),
        (),
        "custom-film-op:" + "7" * 64,
    )
    candidate = "\n".join(
        (
            "[AV SECTION — RESTORE | 0:00 - 0:30]",
            "[BEAT 1 | 0:00 - 0:10]",
            "VISUAL: The engineer studies the approved fault map.",
            "SOUND: The approved signal pulses.",
            (
                "VO [en]: The approved evidence sets the sequence; each "
                "connection must visibly confirm before restoration continues."
            ),
            f"CARRY-IN: approved opening state — {purpose}",
            "CARRY-OUT: approved sequence",
            "[BEAT 2 | 0:10 - 0:20]",
            "VISUAL: The engineer applies the approved sequence.",
            "SOUND: The approved connection confirms.",
            "CARRY-IN: approved sequence",
            "CARRY-OUT: approved confirmation",
            "[BEAT 3 | 0:20 - 0:30]",
            "VISUAL: The approved restored system becomes visibly stable.",
            "SOUND: The approved system tone steadies.",
            "CARRY-IN: approved confirmation",
            f"CARRY-OUT: approved transition state — {next_purpose}",
        )
    )
    repair_violations = []
    database_touched = False

    async def generate(*_args, **_kwargs):
        return {"script": candidate, "validation": {"valid": True, "issues": []}}

    async def edit(scenes, violations, **_kwargs):
        repair_violations.extend(violations)
        return copy.deepcopy(scenes)

    async def quality(*_args, **_kwargs):
        raise AssertionError("macro-only resolution must fail before semantic quality")

    async def get_pool():
        nonlocal database_touched
        database_touched = True
        raise AssertionError("macro-only resolution must not persist")

    seams = production.SharedSectionProductionSeams("tenant-1")
    seams._executor = _Executor()
    monkeypatch.setattr(
        "script.brief_translator.script_generator.generate_script",
        generate,
    )
    monkeypatch.setattr("script_quality.edit_draft_with_violations", edit)
    monkeypatch.setattr("script_quality.run_critique_and_edit", quality)
    monkeypatch.setattr("database.get_pool", get_pool)

    with pytest.raises(
        CustomFilmContractError,
        match="failed approved timing/grounding before voice or imagery",
    ):
        await seams._script(request)

    assert any(
        "requires at least four timed beats" in violation
        for violation in repair_violations
    )
    assert database_touched is False


@pytest.mark.asyncio
async def test_two_malformed_strict_critic_responses_fail_before_persistence(
    monkeypatch,
):
    purpose = "Restore the approved system safely"
    next_purpose = "Land the approved restored system"
    arc = (
        {
            "order_index": 0,
            "section_id": "section-a",
            "role": "resolution",
            "purpose": purpose,
            "render_mode": "coverage",
        },
        {
            "order_index": 1,
            "section_id": "section-b",
            "role": "closing",
            "purpose": next_purpose,
            "render_mode": "coverage",
        },
    )
    request = production._request(
        replace(
            _adapter("script", seconds=40),
            role="resolution",
            purpose=purpose,
            story_arc=arc,
        ),
        (),
        "custom-film-op:" + "c" * 64,
    )
    candidate = _with_boundary_carries(
        _resolution_screenplay(staged=True),
        carry_in=f"approved opening state — {purpose}",
        carry_out=f"approved transition state — {next_purpose}",
    )
    database_touched = False

    class CriticClient:
        def __init__(self):
            self.responses = ["", '{"verdict":"pass"']
            self.calls = []

        async def generate(self, **kwargs):
            self.calls.append(kwargs)
            return self.responses.pop(0)

    critic_client = CriticClient()
    executor = _Executor()
    executor._pipeline.anthropic = critic_client

    async def generate(*_args, **_kwargs):
        return {"script": candidate, "validation": {"valid": True, "issues": []}}

    async def get_pool():
        nonlocal database_touched
        database_touched = True
        raise AssertionError("unavailable strict grade must not persist")

    seams = production.SharedSectionProductionSeams("tenant-1")
    seams._executor = executor
    monkeypatch.setattr(
        "script.brief_translator.script_generator.generate_script",
        generate,
    )
    monkeypatch.setattr("database.get_pool", get_pool)

    with pytest.raises(
        CustomFilmContractError,
        match="failed visual-story quality before voice or imagery",
    ):
        await seams._script(request)

    assert len(critic_client.calls) == 2
    assert all(call["max_tokens"] == 1800 for call in critic_client.calls)
    exact_ids = (
        "approved_purpose_grounding",
        "visual_story_readiness",
        "role_structure_quality",
        "story_arc_continuity",
        "shared_film_world_progression",
        "av_screenplay_performance",
    )
    for rule_id in exact_ids:
        assert rule_id in critic_client.calls[0]["system_prompt"]
    assert (
        "nested explanatory prose"
        in critic_client.calls[0]["system_prompt"]
    )
    assert (
        "RETRY CONTRACT: The prior response was empty, malformed, or truncated"
        in critic_client.calls[1]["system_prompt"]
    )
    assert database_touched is False


def _closing_screenplay(*, cinematic: bool) -> str:
    if cinematic:
        visuals = (
            "The completed work echoes the approved opening image.",
            "Match cuts transform approved planning notes into assembled work.",
            "The camera returns to the completed work and decisive final image.",
        )
        sounds = (
            "The opening ambience returns with warmer room tone.",
            "Paper movement becomes the rhythm of assembly.",
            "The assembly sounds resolve into quiet completion.",
        )
        carries = (
            "approved callback image",
            "returned opening image",
            "assembled completed work",
            "decisive final image",
        )
        voice = (
            "The approved plan becomes completed work before the final image "
            "returns."
        )
    else:
        visuals = (
            "A section timeline appears with beat labels and timing marks.",
            "Visual sound and carry tags orbit a rotating blueprint schema.",
            "The framework returns as abstract section labels and diagrams.",
        )
        sounds = (
            "Interface ticks mark each labeled section.",
            "Synthetic pulses follow the rotating diagram.",
            "A generic explanatory tone resolves.",
        )
        carries = (
            "approved callback image",
            "literal section timeline",
            "rotating framework diagram",
            "abstract schema recap",
        )
        voice = (
            "This framework explains how each section and carry state works "
            "together."
        )
    lines = ["[AV SECTION — FINAL IMAGE | 0:00 - 0:30]"]
    for index, (visual, sound) in enumerate(zip(visuals, sounds), start=1):
        lines.extend(
            (
                f"[BEAT {index} | 0:{(index - 1) * 10:02d} - "
                f"0:{index * 10:02d}]",
                f"VISUAL: {visual}",
                f"SOUND: {sound}",
            )
        )
        if index == 2:
            lines.append(f"VO [en]: {voice}")
        lines.extend(
            (
                f"CARRY-IN: {carries[index - 1]}",
                f"CARRY-OUT: {carries[index]}",
            )
        )
    return "\n".join(lines)


@pytest.mark.asyncio
async def test_literal_framework_closing_semantic_failure_never_persists(
    monkeypatch,
):
    purpose = (
        "Reveal the approved planning and assembly, then return to the "
        "completed work and final image"
    )
    arc = (
        {
            "order_index": 0,
            "section_id": "section-final",
            "role": "closing",
            "purpose": purpose,
            "render_mode": "coverage",
        },
    )
    request = production._request(
        replace(
            _adapter("script", section_id="section-final", seconds=30),
            order_index=0,
            role="closing",
            purpose=purpose,
            story_arc=arc,
        ),
        (),
        "custom-film-op:" + "b" * 64,
    )
    candidate = _with_boundary_carries(
        _closing_screenplay(cinematic=False),
        carry_in=f"approved opening state — {purpose}",
        carry_out=f"approved final state — {purpose}",
    )
    observed = {}
    database_touched = False

    async def generate(_client, brief, **_kwargs):
        observed["guidance"] = brief["writer_guidance"]
        return {"script": candidate, "validation": {"valid": True, "issues": []}}

    async def quality(_tenant, _video, scenes, **kwargs):
        observed["rules"] = kwargs["rules_text"]
        observed["repair"] = kwargs["edit_constraints"][0]
        return {
            "scenes": copy.deepcopy(scenes),
            "critique": SimpleNamespace(
                verdict="fail",
                score=35,
                failing_gates=[
                    "role_structure_quality",
                    "visual_story_readiness",
                    "av_screenplay_performance",
                ],
                violations=[
                    "literal framework recap replaces the final story payoff"
                ],
                rule_verdicts=[],
                needs_revision=True,
            ),
            "needs_review": True,
            "edit_rounds": 2,
            "regenerated": False,
            "changed": False,
        }

    async def get_pool():
        nonlocal database_touched
        database_touched = True
        raise AssertionError("failed closing must not persist")

    seams = production.SharedSectionProductionSeams("tenant-1")
    seams._executor = _Executor()
    monkeypatch.setattr(
        "script.brief_translator.script_generator.generate_script",
        generate,
    )
    monkeypatch.setattr("script_quality.run_critique_and_edit", quality)
    monkeypatch.setattr("database.get_pool", get_pool)

    with pytest.raises(
        CustomFilmContractError,
        match="failed visual-story quality before voice or imagery",
    ):
        await seams._script(request)

    for context in (
        observed["guidance"],
        observed["repair"],
        observed["rules"],
    ):
        assert "earned final story image" in context
        assert "concrete cinematic transformation or match cuts" in context
        assert "literal framework or schema jargon" in context
        assert "abstract rotating diagrams" in context
        assert "one decisive visual payoff" in context
    assert database_touched is False


@pytest.mark.asyncio
async def test_cinematic_callback_assembly_finished_work_closing_persists(
    monkeypatch,
):
    purpose = (
        "Reveal the approved planning and assembly, then return to the "
        "completed work and final image"
    )
    arc = (
        {
            "order_index": 0,
            "section_id": "section-final",
            "role": "closing",
            "purpose": purpose,
            "render_mode": "coverage",
        },
    )
    request = production._request(
        replace(
            _adapter("script", section_id="section-final", seconds=30),
            order_index=0,
            role="closing",
            purpose=purpose,
            story_arc=arc,
        ),
        (),
        "custom-film-op:" + "a" * 64,
    )
    candidate = _with_boundary_carries(
        _closing_screenplay(cinematic=True),
        carry_in=f"approved opening state — {purpose}",
        carry_out=f"approved final state — {purpose}",
    )
    inserted = []

    class Connection:
        async def fetch(self, _sql, *_args):
            return []

        async def fetchrow(self, _sql, *args):
            inserted.append(args[4])
            return {"id": args[0]}

        async def execute(self, _sql, *_args):
            return "UPDATE 1"

    async def get_pool():
        return _Pool(Connection())

    async def generate(*_args, **_kwargs):
        return {"script": candidate, "validation": {"valid": True, "issues": []}}

    async def quality(_tenant, _video, scenes, **kwargs):
        assert "one decisive visual payoff" in kwargs["rules_text"]
        return _quality_pass(scenes)

    seams = production.SharedSectionProductionSeams("tenant-1")
    seams._executor = _Executor()
    monkeypatch.setattr(
        "script.brief_translator.script_generator.generate_script",
        generate,
    )
    monkeypatch.setattr("script_quality.run_critique_and_edit", quality)
    monkeypatch.setattr("database.get_pool", get_pool)

    result = await seams._script(request)

    assert inserted == [candidate]
    assert result["quality_verdict"] == "pass"


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


def test_arc_derived_carry_binding_is_exact_across_adjacent_sections():
    arc = (
        {"order_index": 0, "purpose": "The blackout begins"},
        {"order_index": 1, "purpose": "Mara finds the control map"},
        {"order_index": 2, "purpose": "The engineer restores StoryEngine"},
    )

    first_contract, first_in, first_out = production._script_av_carry_binding(
        arc,
        current_order_index=0,
    )
    second_contract, second_in, second_out = production._script_av_carry_binding(
        arc,
        current_order_index=1,
    )

    assert first_in == "approved opening state — The blackout begins"
    assert first_out == second_in == (
        "approved transition state — Mara finds the control map"
    )
    assert second_out == (
        "approved transition state — The engineer restores StoryEngine"
    )
    assert f"REQUIRED FINAL CARRY-OUT: {first_out}" in first_contract
    assert f"REQUIRED FIRST CARRY-IN: {second_in}" in second_contract


@pytest.mark.asyncio
async def test_54_second_av_prompt_uses_sparse_band_and_visual_first_narrator_law(
    monkeypatch,
):
    arc = (
        {
            "order_index": 0,
            "section_id": "section-a",
            "role": "opening",
            "purpose": "The blackout reaches the control room",
            "render_mode": "coverage",
        },
        {
            "order_index": 1,
            "section_id": "section-b",
            "role": "resolution",
            "purpose": "The map guides the engineer to StoryEngine",
            "render_mode": "coverage",
        },
    )
    request = production._request(
        replace(
            _adapter("script", seconds=54),
            role="opening",
            purpose="The blackout reaches the control room",
            story_arc=arc,
        ),
        (),
        "custom-film-op:" + "6" * 64,
    )
    spoken = " ".join(["approved control signal returns"] * 5)
    candidate = "\n".join(
        (
            "[AV SECTION — BLACKOUT | 0:00 - 0:54]",
            "[BEAT 1 | 0:00 - 0:54]",
            "VISUAL: Control lights shift across the approved room map.",
            "SOUND: Low electrical ambience steadies.",
            f"VO [en]: {spoken}",
            (
                "CARRY-IN: approved opening state — The blackout reaches the "
                "control room"
            ),
            (
                "CARRY-OUT: approved transition state — The map guides the "
                "engineer to StoryEngine"
            ),
        )
    )
    observed = {}
    inserted = []

    class Connection:
        async def fetchrow(self, _sql, *args):
            inserted.append(args[4])
            return {"id": args[0]}

        async def execute(self, _sql, *_args):
            return "UPDATE 1"

    async def get_pool():
        return _Pool(Connection())

    async def generate(_client, brief, *, config, profile):
        observed["guidance"] = brief["writer_guidance"]
        observed["config"] = config
        return {"script": candidate, "validation": {"valid": True, "issues": []}}

    async def quality(_tenant, _video, scenes, **kwargs):
        observed["rules"] = kwargs["rules_text"]
        return _quality_pass(scenes)

    seams = production.SharedSectionProductionSeams("tenant-1")
    seams._executor = _Executor()
    monkeypatch.setattr(
        "script.brief_translator.script_generator.generate_script",
        generate,
    )
    monkeypatch.setattr("script_quality.run_critique_and_edit", quality)
    monkeypatch.setattr("database.get_pool", get_pool)

    await seams._script(request)

    assert isinstance(observed["config"], production._AVSectionConfig)
    assert (
        observed["config"].script_min_words,
        observed["config"].script_max_words,
    ) == (14, 119)
    assert observed["config"].total_script_words == 66
    assert "CINEMATIC SPARSE SPOKEN BAND: 14-119" in observed["guidance"]
    assert "EXACT SPOKEN WORD BAND: 121-149" not in observed["guidance"]
    assert "visual action and sound must carry the scene" in observed["guidance"]
    assert "narrator-led voice-over" not in observed["guidance"]
    assert "shared_film_world_progression" in observed["rules"]
    assert inserted == [candidate]


def test_54_second_wall_to_wall_vo_is_rejected():
    spoken = " ".join(["approved signal"] * 60)
    screenplay = "\n".join(
        (
            "[AV SECTION — OVERFULL | 0:00 - 0:54]",
            "[BEAT 1 | 0:00 - 0:54]",
            "VISUAL: The approved signal fills the control screen.",
            "SOUND: Low room tone continues.",
            f"VO [en]: {spoken}",
            "CARRY-IN: approved opening state",
            "CARRY-OUT: approved final state",
        )
    )

    parsed, issues = production._parse_custom_film_av_screenplay(
        screenplay,
        exact_seconds=54,
        language_mode="narrator",
    )

    assert parsed is None
    assert "AV screenplay is action-heavy or wall-to-wall spoken narration" in issues


@pytest.mark.asyncio
async def test_sentence_initial_texas_drift_is_rejected_by_semantic_hard_gate(
    monkeypatch,
):
    purpose = "Follow Mara and the approved signal"
    arc = (
        {
            "order_index": 0,
            "section_id": "section-a",
            "role": "case_study",
            "purpose": purpose,
            "render_mode": "coverage",
        },
    )
    request = production._request(
        replace(
            _adapter("script", seconds=12),
            role="case_study",
            purpose=purpose,
            story_arc=arc,
        ),
        (),
        "custom-film-op:" + "5" * 64,
    )
    candidate = "\n".join(
        (
            "[AV SECTION — SIGNAL | 0:00 - 0:12]",
            "[BEAT 1 | 0:00 - 0:12]",
            "VISUAL: Texas routes the approved signal across Mara's console.",
            "SOUND: A relay clicks.",
            "VO [en]: The approved signal returns.",
            (
                "CARRY-IN: approved opening state — Follow Mara and the "
                "approved signal"
            ),
            (
                "CARRY-OUT: approved final state — Follow Mara and the "
                "approved signal"
            ),
        )
    )

    async def generate(*_args, **_kwargs):
        return {"script": candidate, "validation": {"valid": True, "issues": []}}

    async def quality(_tenant, _video, scenes, **kwargs):
        assert (
            "unapproved sentence-initial title-case candidate"
            in kwargs["rules_text"]
        )
        return {
            "scenes": copy.deepcopy(scenes),
            "critique": SimpleNamespace(
                verdict="fail",
                score=20,
                failing_gates=["approved_purpose_grounding"],
                violations=["Texas is absent from the approved film world"],
                rule_verdicts=[],
                needs_revision=True,
            ),
            "needs_review": True,
            "edit_rounds": 0,
            "regenerated": False,
            "changed": False,
        }

    database_touched = False

    async def get_pool():
        nonlocal database_touched
        database_touched = True
        raise AssertionError("semantic rejection must happen before persistence")

    seams = production.SharedSectionProductionSeams("tenant-1")
    seams._executor = _Executor()
    monkeypatch.setattr(
        "script.brief_translator.script_generator.generate_script",
        generate,
    )
    monkeypatch.setattr("script_quality.run_critique_and_edit", quality)
    monkeypatch.setattr("database.get_pool", get_pool)

    with pytest.raises(
        CustomFilmContractError,
        match="failed visual-story quality before voice or imagery",
    ):
        await seams._script(request)
    assert database_touched is False


@pytest.mark.asyncio
async def test_carry_mismatch_repairs_with_exact_arc_derived_binding(
    monkeypatch,
):
    arc = (
        {
            "order_index": 0,
            "section_id": "section-first",
            "role": "opening",
            "purpose": "The blackout reaches the room",
            "render_mode": "coverage",
        },
        {
            "order_index": 1,
            "section_id": "section-middle",
            "role": "evidence",
            "purpose": "Mara finds the control map",
            "render_mode": "coverage",
        },
        {
            "order_index": 2,
            "section_id": "section-final",
            "role": "resolution",
            "purpose": "The engineer restores StoryEngine",
            "render_mode": "coverage",
        },
    )
    request = production._request(
        replace(
            _adapter("script", section_id="section-middle", seconds=12),
            order_index=1,
            role="evidence",
            purpose="Mara finds the control map",
            story_arc=arc,
        ),
        (),
        "custom-film-op:" + "4" * 64,
    )
    base = "\n".join(
        (
            "[AV SECTION — MAP | 0:00 - 0:12]",
            "[BEAT 1 | 0:00 - 0:12]",
            "VISUAL: Mara follows the approved control map.",
            "SOUND: Low electrical ambience steadies.",
            "VO [en]: The approved map reveals the next state.",
            "CARRY-IN: wrong prior state",
            "CARRY-OUT: wrong next state",
        )
    )
    repaired = _with_boundary_carries(
        base,
        carry_in="approved transition state — Mara finds the control map",
        carry_out=(
            "approved transition state — The engineer restores StoryEngine"
        ),
    )
    repair_violations = []
    inserted = []

    class Connection:
        async def fetchrow(self, _sql, *args):
            inserted.append(args[4])
            return {"id": args[0]}

        async def execute(self, _sql, *_args):
            return "UPDATE 1"

    async def get_pool():
        return _Pool(Connection())

    async def generate(*_args, **_kwargs):
        return {"script": base, "validation": {"valid": True, "issues": []}}

    async def edit(_scenes, violations, **_kwargs):
        repair_violations.extend(violations)
        return [{"scene": 1, "text": repaired}]

    async def quality(_tenant, _video, scenes, **_kwargs):
        return _quality_pass(scenes)

    seams = production.SharedSectionProductionSeams("tenant-1")
    seams._executor = _Executor()
    monkeypatch.setattr(
        "script.brief_translator.script_generator.generate_script",
        generate,
    )
    monkeypatch.setattr("script_quality.edit_draft_with_violations", edit)
    monkeypatch.setattr("script_quality.run_critique_and_edit", quality)
    monkeypatch.setattr("database.get_pool", get_pool)

    await seams._script(request)

    repair_text = "\n".join(repair_violations)
    assert "AV first CARRY-IN must exactly match" in repair_text
    assert (
        "REQUIRED FIRST CARRY-IN: approved transition state — Mara finds the "
        "control map"
    ) in repair_text
    assert (
        "REQUIRED FINAL CARRY-OUT: approved transition state — The engineer "
        "restores StoryEngine"
    ) in repair_text
    assert inserted == [repaired]


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
    transition = (
        "approved transition state — Land Mara and the approved ending"
    )
    candidate = _with_boundary_carries(
        _bilingual_screenplay(),
        carry_in=transition,
        carry_out=(
            "approved final state — Land Mara and the approved ending"
        ),
    )
    prior_text = _with_boundary_carries(
        _bilingual_screenplay(),
        carry_in=(
            "approved opening state — Follow Mara and the approved signal"
        ),
        carry_out=transition if matching_carry else "unrelated evidence",
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
