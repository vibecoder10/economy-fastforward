import copy
from uuid import uuid4

import custom_film_contract as contract
import custom_film_director as director
import pytest

SECTION_A = str(uuid4())
SECTION_B = str(uuid4())
PLAN_ID = str(uuid4())
PLAN_HASH = "a" * 64


def _state(
    fact,
    *,
    hero_position,
    guide_position=None,
    token_state="in_hero_hand",
    hero_emotion="alert",
    guide_emotion=None,
):
    positions = {"hero": hero_position}
    emotions = {"hero": hero_emotion}
    if guide_position is not None:
        positions["guide"] = guide_position
    if guide_emotion is not None:
        emotions["guide"] = guide_emotion
    return {
        "story_facts": [fact],
        "character_positions": positions,
        "prop_states": {"entry_token": token_state},
        "emotional_state": emotions,
    }


def _draft():
    opening = "The hero discovers the sealed transit tube beneath the city."
    ending = "The hero exposes the tube system to the watching city."
    first_close = _state(
        "The guide blocks the tube entrance and demands the entry token.",
        hero_position="left of the sealed tube",
        guide_position="between the hero and the tube",
        hero_emotion="defiant",
        guide_emotion="guarded",
    )
    second_close = _state(
        "The guide reveals the token opens a route reserved for the wealthy.",
        hero_position="left of the open tube",
        guide_position="beside the control panel",
        token_state="pressed_to_control_panel",
        hero_emotion="shocked",
        guide_emotion="ashamed",
    )
    return {
        "film_bible": {
            "title": "The Tubes",
            "logline": (
                "A courier discovers that the city's miraculous transit tubes "
                "are a private escape route built for the powerful."
            ),
            "throughline": (
                "The courier follows one forbidden token from a sealed station "
                "to the public proof that changes who controls the route."
            ),
            "central_question": (
                "Will the courier reveal the system before its owners erase the evidence?"
            ),
            "beginning_state": opening,
            "ending_state": ending,
            "visual_motif": (
                "A thin amber route line grows from a private mark into a citywide network."
            ),
            "timeline_law": (
                "The film unfolds during one stormy night and never jumps backward in time."
            ),
            "geography_law": (
                "The service station sits below the tower and connects eastward to the plaza."
            ),
            "narrator_mode": "third_person",
            "narrator_character_id": None,
            "style": {
                "medium": "cinematic photoreal live-action",
                "rendering_approach": (
                    "grounded near-future production design with restrained spectacle"
                ),
                "palette": ["charcoal", "oxidized amber", "cold concrete"],
                "texture": "wet metal, worn fabric, practical haze",
                "lens_language": (
                    "anamorphic close coverage, motivated wides, shallow portrait depth"
                ),
                "lighting_law": (
                    "cold overhead service light cut by one amber tube glow"
                ),
                "aspect_ratio": "16:9",
                "negative_constraints": [
                    "animation",
                    "illustration",
                    "plastic skin",
                    "wardrobe changes",
                ],
            },
            "characters": [
                {
                    "character_id": "hero",
                    "display_name": "Mara",
                    "story_role": "courier who chooses to expose the route",
                    "identity_prompt": (
                        "Black woman, early thirties, oval face, close-cropped natural hair"
                    ),
                    "face_body_lock": (
                        "deep brown skin, compact athletic build, small scar over left eyebrow"
                    ),
                    "wardrobe_lock": (
                        "weathered charcoal courier coat, amber shoulder strap, black boots"
                    ),
                    "voice_lock": "low warm alto, controlled pace, clipped when threatened",
                    "performance_law": "stillness under pressure followed by decisive movement",
                    "forbidden_drift": ["lighter skin", "long hair", "different coat"],
                },
                {
                    "character_id": "guide",
                    "display_name": "Ilan",
                    "story_role": "station guide who knows the system's true owners",
                    "identity_prompt": (
                        "Middle Eastern man, late forties, lined face, salt-and-pepper beard"
                    ),
                    "face_body_lock": (
                        "olive skin, tall narrow frame, tired dark eyes, crooked nose"
                    ),
                    "wardrobe_lock": (
                        "navy maintenance uniform, silver access badge, grey work gloves"
                    ),
                    "voice_lock": "soft baritone, careful consonants, breath catches before lies",
                    "performance_law": "avoids eye contact until he chooses to confess",
                    "forbidden_drift": ["clean shaven", "different uniform", "younger face"],
                },
            ],
            "environments": [
                {
                    "environment_id": "service_station",
                    "display_name": "Subterranean Service Station",
                    "story_function": "the private threshold where the secret becomes personal",
                    "identity_prompt": (
                        "circular concrete station beneath a luxury tower with one glass transit tube"
                    ),
                    "architecture_lock": (
                        "ribbed concrete walls, tube on east wall, control panel immediately south"
                    ),
                    "lighting_time_weather_lock": (
                        "storm night, cold ceiling strips, rain pulsing through street grates"
                    ),
                    "geography_lock": (
                        "west stair enters station; tube travels east toward civic plaza"
                    ),
                    "palette_lock": "charcoal concrete with narrow oxidized-amber light",
                    "props": [
                        {
                            "prop_id": "entry_token",
                            "description": "brass hexagonal transit token with a cut route symbol",
                            "home_position": "in Mara's right hand until pressed to the panel",
                            "continuity_law": "never duplicates and never changes material or symbol",
                        }
                    ],
                },
                {
                    "environment_id": "civic_plaza",
                    "display_name": "Civic Plaza",
                    "story_function": "the public arena where private proof becomes shared knowledge",
                    "identity_prompt": (
                        "rain-soaked plaza below the tower with tube routes visible under glass paving"
                    ),
                    "architecture_lock": (
                        "tower to west, public screens north, glass route floor across center"
                    ),
                    "lighting_time_weather_lock": (
                        "same storm night, amber route glow reflects in standing water"
                    ),
                    "geography_lock": (
                        "service tube exits from west tower and fans east under the plaza"
                    ),
                    "palette_lock": "cold slate rain punctured by expanding amber paths",
                    "props": [
                        {
                            "prop_id": "entry_token",
                            "description": "the same brass hexagonal route token",
                            "home_position": "held above Mara's head facing the public screens",
                            "continuity_law": "same scratches, cut symbol, scale, and orientation",
                        }
                    ],
                },
            ],
        },
        "shots": [
            {
                "shot_key": "tube_arrival",
                "section_id": SECTION_A,
                "duration_frames": 48,
                "technique": "cinematic_action",
                "performance_mode": "silent_action",
                "narrative_purpose": "Mara physically discovers the forbidden threshold.",
                "caused_by": [],
                "progression_kinds": ["story", "action", "spatial"],
                "story_value": "The abstract route becomes a real place she can enter.",
                "opening_state": _state(
                    opening,
                    hero_position="at the bottom of the west stair",
                    token_state="in_hero_hand",
                    hero_emotion="alert",
                ),
                "action_beats": [
                    "Mara runs down the west stair",
                    "she brakes at the sealed glowing tube",
                    "Ilan steps from shadow and blocks the threshold",
                ],
                "closing_state": first_close,
                "transition_from_previous": "opening",
                "continuity_bridge": None,
                "environment_id": "service_station",
                "character_ids": ["hero", "guide"],
                "active_prop_ids": ["entry_token"],
                "screen_direction": "Mara travels left to right toward the east-wall tube",
                "shot_size": "wide moving into a tense two-shot",
                "camera_move": "low tracking run, then a controlled stop",
                "spoken_lines": [],
                "storyboard_composition": (
                    "three readable action phases: stair descent, tube discovery, Ilan blocking"
                ),
                "final_picture_intent": (
                    "Mara entering from the west stair with Ilan still hidden beside the tube"
                ),
                "motion_intent": (
                    "Mara completes the run and stop while Ilan crosses into her path"
                ),
            },
            {
                "shot_key": "choice_exchange",
                "section_id": SECTION_A,
                "duration_frames": 72,
                "technique": "poco_dialogue",
                "performance_mode": "dialogue",
                "narrative_purpose": (
                    "A back-and-forth exchange forces Ilan to reveal what the token controls."
                ),
                "caused_by": ["tube_arrival"],
                "progression_kinds": ["story", "information", "emotion"],
                "story_value": (
                    "Mara learns the route is private and Ilan chooses confession over concealment."
                ),
                "opening_state": first_close,
                "action_beats": [
                    "Mara raises the token between them",
                    "Ilan refuses, then looks toward the hidden camera",
                    "Mara presses the token to the panel and the tube opens",
                ],
                "closing_state": second_close,
                "transition_from_previous": "continuous",
                "continuity_bridge": None,
                "environment_id": "service_station",
                "character_ids": ["hero", "guide"],
                "active_prop_ids": ["entry_token"],
                "screen_direction": "Mara holds frame left; Ilan holds frame right",
                "shot_size": "alternating close singles with one resolving two-shot",
                "camera_move": "subtle push toward each speaker, settle on the opening tube",
                "spoken_lines": [
                    {
                        "speaker_id": "hero",
                        "kind": "dialogue",
                        "text": "Why does my delivery token open a door no map admits exists?",
                        "language": "English",
                        "delivery": "quiet accusation",
                        "addressee_id": "guide",
                    },
                    {
                        "speaker_id": "guide",
                        "kind": "dialogue",
                        "text": "Because the map was made for people who never wait with us.",
                        "language": "English",
                        "delivery": "ashamed confession",
                        "addressee_id": "hero",
                    },
                    {
                        "speaker_id": "hero",
                        "kind": "dialogue",
                        "text": "Then tonight they lose the secret.",
                        "language": "English",
                        "delivery": "decisive",
                        "addressee_id": "guide",
                    },
                ],
                "storyboard_composition": (
                    "eyelines and token geography remain exact across alternating dialogue coverage"
                ),
                "final_picture_intent": (
                    "Mara and Ilan face each other across the brass token before the sealed tube"
                ),
                "motion_intent": (
                    "natural body acting, exact speaker turns, panel activation, then tube doors open"
                ),
            },
            {
                "shot_key": "city_reveal",
                "section_id": SECTION_B,
                "duration_frames": 120,
                "technique": "power_doctrine_exposition",
                "performance_mode": "exposition",
                "narrative_purpose": (
                    "Third-person exposition turns Mara's specific proof into the system-wide reveal."
                ),
                "caused_by": ["choice_exchange"],
                "progression_kinds": ["story", "information", "spatial"],
                "story_value": (
                    "The audience sees the complete network and the public now controls the truth."
                ),
                "opening_state": _state(
                    "Mara exits the west tower tube into the storm-dark civic plaza.",
                    hero_position="center plaza facing north screens",
                    guide_position="at west tube exit",
                    token_state="raised_in_hero_hand",
                    hero_emotion="resolved",
                    guide_emotion="relieved",
                ),
                "action_beats": [
                    "Mara raises the token toward the public screens",
                    "the amber route propagates beneath the glass plaza",
                    "screens reveal every private station while the crowd turns to look",
                ],
                "closing_state": _state(
                    ending,
                    hero_position="center plaza facing the gathered crowd",
                    guide_position="at west tube exit",
                    token_state="raised_in_hero_hand",
                    hero_emotion="resolved",
                    guide_emotion="relieved",
                ),
                "transition_from_previous": "location_cut",
                "continuity_bridge": (
                    "Follow the same token through the eastbound tube and land on it in Mara's hand."
                ),
                "environment_id": "civic_plaza",
                "character_ids": ["hero", "guide"],
                "active_prop_ids": ["entry_token"],
                "screen_direction": "the route continues west to east beneath the plaza",
                "shot_size": "hero medium expanding to a high citywide reveal",
                "camera_move": "rise from token to crowd to the complete illuminated network",
                "spoken_lines": [
                    {
                        "speaker_id": "third_person_narrator",
                        "kind": "narration",
                        "text": (
                            "One token made the hidden network visible, and private escape became public evidence."
                        ),
                        "language": "English",
                        "delivery": "restrained third-person conclusion",
                        "addressee_id": None,
                    }
                ],
                "storyboard_composition": (
                    "token foreground, Mara midground, route propagation and public screens reveal"
                ),
                "final_picture_intent": (
                    "Mara holds the token beneath the public screens before the route activates"
                ),
                "motion_intent": (
                    "route light spreads across the plaza, screens expose stations, camera rises"
                ),
            },
        ],
    }


def _compile():
    return director.compile_director_contract(
        _draft(),
        plan_id=PLAN_ID,
        plan_hash=PLAN_HASH,
        section_ids=[SECTION_A, SECTION_B],
        total_frames=240,
    )


def _reference_reviews(compiled):
    rows = []
    index = 1
    for lock_kind, key, values in (
        ("character", "character_id", compiled["film_bible"]["characters"]),
        ("environment", "environment_id", compiled["film_bible"]["environments"]),
    ):
        for value in values:
            rows.append(
                {
                    "lock_kind": lock_kind,
                    "lock_id": value[key],
                    "contract_hash": compiled["contract_hash"],
                    "reference_artifact_id": (
                        f"reference:{lock_kind}:{value[key]}"
                    ),
                    "reference_image_sha256": f"{index:064x}",
                    "lock_prompt_hash": contract.canonical_hash(value),
                    "identity_match": True,
                    "style_match": True,
                    "verdict": "approved",
                    "notes": "",
                }
            )
            index += 1
    return rows


def _storyboard_reviews(compiled, reference_gate):
    return [
        {
            "shot_id": shot["shot_id"],
            "contract_hash": compiled["contract_hash"],
            "reference_gate_hash": reference_gate["reference_gate_hash"],
            "storyboard_artifact_id": f"board:{shot['shot_key']}",
            "storyboard_image_sha256": f"{index + 1:064x}",
            "storyboard_prompt_hash": contract.canonical_hash(
                shot["storyboard_prompt"]
            ),
            "style_match": True,
            "character_lock_match": True,
            "environment_lock_match": True,
            "action_progresses": True,
            "continuity_match": True,
            "verdict": "approved",
            "notes": "",
        }
        for index, shot in enumerate(compiled["shots"])
    ]


def _verifications(compiled, storyboard_gate):
    values = []
    for index, shot in enumerate(compiled["shots"]):
        values.append(
            {
                "shot_id": shot["shot_id"],
                "contract_hash": compiled["contract_hash"],
                "storyboard_gate_hash": storyboard_gate["storyboard_gate_hash"],
                "clip_artifact_id": f"clip:{shot['shot_key']}",
                "observations": [
                    {
                        "checkpoint": "start",
                        "frame_sha256": f"{index * 3 + 1:064x}",
                        "style_lock_hash": shot["style_lock_hash"],
                        "character_lock_hashes": shot["character_lock_hashes"],
                        "environment_lock_hash": shot["environment_lock_hash"],
                        "observed_state": shot["opening_state"],
                        "action_evidence": "opening composition is locked",
                    },
                    {
                        "checkpoint": "middle",
                        "frame_sha256": f"{index * 3 + 2:064x}",
                        "style_lock_hash": shot["style_lock_hash"],
                        "character_lock_hashes": shot["character_lock_hashes"],
                        "environment_lock_hash": shot["environment_lock_hash"],
                        "observed_state": shot["opening_state"],
                        "action_evidence": shot["action_beats"][0],
                    },
                    {
                        "checkpoint": "end",
                        "frame_sha256": f"{index * 3 + 3:064x}",
                        "style_lock_hash": shot["style_lock_hash"],
                        "character_lock_hashes": shot["character_lock_hashes"],
                        "environment_lock_hash": shot["environment_lock_hash"],
                        "observed_state": shot["closing_state"],
                        "action_evidence": "closing state is visibly established",
                    },
                ],
                "motion_visible": True,
                "action_progressed": True,
                "continuity_match": True,
                "lip_sync_match": (
                    True if shot["performance_mode"] == "dialogue" else None
                ),
                "repair_instruction": "",
            }
        )
    return values


def test_director_compiles_one_film_lock_over_mixed_profile_techniques():
    compiled = _compile()
    assert compiled["schema_version"] == 1
    assert compiled["total_frames"] == 240
    assert [shot["technique"] for shot in compiled["shots"]] == [
        "cinematic_action",
        "poco_dialogue",
        "power_doctrine_exposition",
    ]
    assert [shot["start_frame"] for shot in compiled["shots"]] == [0, 48, 120]
    assert [shot["end_frame"] for shot in compiled["shots"]] == [47, 119, 239]
    assert {
        shot["style_lock_hash"] for shot in compiled["shots"]
    } == {contract.canonical_hash(compiled["film_bible"]["style"])}
    assert "GLOBAL STYLE LOCK" in compiled["shots"][1]["storyboard_prompt"]
    assert "CHARACTER LOCKS" in compiled["shots"][1]["motion_prompt"]
    assert director.validate_director_contract(compiled) == compiled


def test_director_rejects_unlocked_character_environment_and_prop():
    cases = [
        ("character_ids", ["hero", "stranger"], "unlocked character"),
        ("environment_id", "different_city", "unlocked environment"),
        ("active_prop_ids", ["entry_token", "second_token"], "unlocked environment prop"),
    ]
    for field, value, message in cases:
        draft = _draft()
        draft["shots"][1][field] = value
        with pytest.raises(contract.CustomFilmContractError, match=message):
            director.compile_director_contract(
                draft,
                plan_id=PLAN_ID,
                plan_hash=PLAN_HASH,
                section_ids=[SECTION_A, SECTION_B],
                total_frames=240,
            )


def test_director_rejects_narration_substituting_for_dialogue_and_repeated_lines():
    narration = _draft()
    narration["shots"][1]["spoken_lines"][0]["kind"] = "narration"
    with pytest.raises(contract.CustomFilmContractError, match="Narration cannot"):
        director.compile_director_contract(
            narration,
            plan_id=PLAN_ID,
            plan_hash=PLAN_HASH,
            section_ids=[SECTION_A, SECTION_B],
            total_frames=240,
        )

    repeated = _draft()
    repeated["shots"][1]["spoken_lines"][2]["text"] = repeated["shots"][1][
        "spoken_lines"
    ][0]["text"]
    with pytest.raises(contract.CustomFilmContractError, match="repeats"):
        director.compile_director_contract(
            repeated,
            plan_id=PLAN_ID,
            plan_hash=PLAN_HASH,
            section_ids=[SECTION_A, SECTION_B],
            total_frames=240,
        )


def test_director_rejects_nonprogression_and_continuity_breaks():
    unchanged = _draft()
    unchanged["shots"][0]["closing_state"] = copy.deepcopy(
        unchanged["shots"][0]["opening_state"]
    )
    with pytest.raises(contract.CustomFilmContractError, match="visibly change"):
        director.compile_director_contract(
            unchanged,
            plan_id=PLAN_ID,
            plan_hash=PLAN_HASH,
            section_ids=[SECTION_A, SECTION_B],
            total_frames=240,
        )

    continuity = _draft()
    continuity["shots"][1]["opening_state"] = copy.deepcopy(
        continuity["shots"][1]["opening_state"]
    )
    continuity["shots"][1]["opening_state"]["emotional_state"]["hero"] = "calm"
    with pytest.raises(contract.CustomFilmContractError, match="continuous story state"):
        director.compile_director_contract(
            continuity,
            plan_id=PLAN_ID,
            plan_hash=PLAN_HASH,
            section_ids=[SECTION_A, SECTION_B],
            total_frames=240,
        )


def test_storyboard_gate_requires_exact_approved_shot_contracts():
    compiled = _compile()
    references = director.compile_reference_gate(
        compiled, _reference_reviews(compiled)
    )
    reviews = _storyboard_reviews(compiled, references)
    gate = director.compile_storyboard_gate(compiled, references, reviews)
    assert gate["shot_count"] == 3
    assert gate["storyboard_gate_hash"]

    rejected = copy.deepcopy(reviews)
    rejected[1]["action_progresses"] = False
    rejected[1]["verdict"] = "rejected"
    rejected[1]["notes"] = "The panel repeats the opening pose."
    with pytest.raises(contract.CustomFilmContractError, match="not approved"):
        director.compile_storyboard_gate(compiled, references, rejected)

    stale = copy.deepcopy(reviews)
    stale[0]["storyboard_prompt_hash"] = "f" * 64
    with pytest.raises(contract.CustomFilmContractError, match="prompt binding changed"):
        director.compile_storyboard_gate(compiled, references, stale)


def test_visual_gate_checks_every_start_middle_end_before_remotion():
    compiled = _compile()
    references = director.compile_reference_gate(
        compiled, _reference_reviews(compiled)
    )
    storyboards = director.compile_storyboard_gate(
        compiled, references, _storyboard_reviews(compiled, references)
    )
    verifications = _verifications(compiled, storyboards)
    visual_gate = director.compile_visual_gate(
        compiled, storyboards, verifications
    )
    admission = director.build_remotion_admission(
        compiled, storyboards, visual_gate
    )
    assert admission["total_frames"] == 240
    assert [shot["clip_artifact_id"] for shot in admission["shots"]] == [
        "clip:tube_arrival",
        "clip:choice_exchange",
        "clip:city_reveal",
    ]
    assert admission["admission_hash"]

    drifted = copy.deepcopy(verifications)
    drifted[1]["observations"][1]["style_lock_hash"] = "f" * 64
    drifted[1]["repair_instruction"] = "Regenerate with the photoreal style lock."
    with pytest.raises(contract.CustomFilmContractError, match="style_drift"):
        director.compile_visual_gate(compiled, storyboards, drifted)

    bad_lip_sync = copy.deepcopy(verifications)
    bad_lip_sync[1]["lip_sync_match"] = False
    bad_lip_sync[1]["repair_instruction"] = "Re-time Ilan's exact speaker turn."
    with pytest.raises(contract.CustomFilmContractError, match="lip_sync_mismatch"):
        director.compile_visual_gate(compiled, storyboards, bad_lip_sync)


def test_exact_cumulative_authority_lists_helper_work_and_rejects_old_ceiling():
    compiled = _compile()
    upstream_hash = "b" * 64
    raw = {
        "stage": "storyboards",
        "stage_binding_hash": compiled["contract_hash"],
        "upstream_gate_hash": upstream_hash,
        "quote_hash": "c" * 64,
        "prior_cumulative_cents": 857,
        "approved_cumulative_cents": 917,
        "operations": [
            {
                "operation_kind": "storyboard_draw",
                "count": 3,
                "unit_max_cents": 15,
                "helper_operation": False,
            },
            {
                "operation_kind": "cast_environment_reference",
                "count": 1,
                "unit_max_cents": 15,
                "helper_operation": True,
            },
        ],
    }
    authority = director.compile_stage_authority(
        raw,
        expected_stage="storyboards",
        expected_binding_hash=compiled["contract_hash"],
        expected_upstream_gate_hash=upstream_hash,
    )
    assert authority["stage_max_cents"] == 60
    assert authority["approved_cumulative_cents"] == 917

    old_ceiling = copy.deepcopy(raw)
    old_ceiling["approved_cumulative_cents"] = 857
    with pytest.raises(contract.CustomFilmContractError, match="exact cumulative"):
        director.compile_stage_authority(
            old_ceiling,
            expected_stage="storyboards",
            expected_binding_hash=compiled["contract_hash"],
            expected_upstream_gate_hash=upstream_hash,
        )
