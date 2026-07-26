import copy
import json
import re
from uuid import uuid4

import pytest

import custom_film_contract as contract
import custom_film_director as director
import custom_film_director_remotion as director_remotion
import custom_film_director_runtime as director_runtime
import custom_film_remotion
import database

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
            "narrator_voice_lock": (
                "measured older contralto, observational distance, no melodrama"
            ),
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
                "ambient_sound": "rainwater ticks through the service-station vents",
                "score_intent": "a restrained low pulse begins under the discovery",
                "sfx_cues": ["boots strike wet concrete", "tube relay snaps awake"],
                "caption_mode": "none",
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
                "ambient_sound": "the sealed tube hums behind the close conversation",
                "score_intent": "the low pulse holds beneath the character performances",
                "sfx_cues": ["brass token presses into the control panel"],
                "caption_mode": "dialogue",
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
                "ambient_sound": "rain, crowd breath, and public-address feedback",
                "score_intent": "the pulse opens into a resolved sustained chord",
                "sfx_cues": ["public screens switch on across the plaza"],
                "caption_mode": "narration",
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
        section_frame_counts={SECTION_A: 120, SECTION_B: 120},
        section_shot_counts={SECTION_A: 2, SECTION_B: 1},
    )


def _planning_contract():
    plan = {
        "compatibility_version": "test-v1",
        "sections": [
            {
                "section_id": SECTION_A,
                "order_index": 0,
                "role": "opening",
                "purpose": "Discover the private threshold",
                "duration_units": 500_000,
                "knobs": {
                    "language": {"mode": "simple_single_language"},
                    "segmentation": {"mode": "speaker_turn"},
                    "visual_profile": "cinematic_illustration",
                    "script_profile": "neutral_v1",
                },
            },
            {
                "section_id": SECTION_B,
                "order_index": 1,
                "role": "resolution",
                "purpose": "Make the private system public",
                "duration_units": 500_000,
                "knobs": {
                    "language": {"mode": "narrator"},
                    "segmentation": {"mode": "visual_cue"},
                    "visual_profile": "cinematic_illustration",
                    "script_profile": "power_doctrine_v2",
                },
            },
        ],
    }
    quote = {
        "requested_duration_seconds": 10,
        "sections": [
            {
                "section_id": SECTION_A,
                "order_index": 0,
                "duration_seconds": 5,
                "still_images": 2,
            },
            {
                "section_id": SECTION_B,
                "order_index": 1,
                "duration_seconds": 5,
                "still_images": 1,
            },
        ],
    }
    return plan, quote


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


def _picture_reviews(compiled, storyboard_gate):
    return [
        {
            "shot_id": shot["shot_id"],
            "contract_hash": compiled["contract_hash"],
            "storyboard_gate_hash": storyboard_gate["storyboard_gate_hash"],
            "final_picture_artifact_id": f"picture:{shot['shot_key']}",
            "final_picture_sha256": f"{index + 20:064x}",
            "final_picture_prompt_hash": contract.canonical_hash(
                shot["final_picture_prompt"]
            ),
            "style_match": True,
            "character_lock_match": True,
            "environment_lock_match": True,
            "opening_state_match": True,
            "storyboard_composition_match": True,
            "verdict": "approved",
            "notes": "",
        }
        for index, shot in enumerate(compiled["shots"])
    ]


def _verifications(compiled, storyboard_gate, picture_gate):
    values = []
    for index, shot in enumerate(compiled["shots"]):
        values.append(
            {
                "shot_id": shot["shot_id"],
                "contract_hash": compiled["contract_hash"],
                "storyboard_gate_hash": storyboard_gate["storyboard_gate_hash"],
                "picture_gate_hash": picture_gate["picture_gate_hash"],
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


@pytest.mark.asyncio
async def test_planning_inference_writes_complete_script_before_storyboards():
    plan, quote = _planning_contract()

    class Client:
        def __init__(self):
            self.calls = []

        async def generate(self, **kwargs):
            self.calls.append(kwargs)
            return json.dumps(_draft())

    client = Client()
    compiled = await director.plan_custom_film_director(
        "Create a coherent film about a courier exposing a private transit system.",
        plan,
        quote,
        client,
        prospective_plan_id=PLAN_ID,
    )
    assert compiled["plan_id"] == PLAN_ID
    assert compiled["section_frame_counts"] == {
        SECTION_A: 120,
        SECTION_B: 120,
    }
    assert compiled["section_shot_counts"] == {SECTION_A: 2, SECTION_B: 1}
    assert len(client.calls) == 1
    assert client.calls[0]["max_tokens"] == 48_000
    prompt = client.calls[0]["prompt"]
    assert "film bible is the highest law" in prompt
    assert "Narration may not impersonate dialogue" in prompt
    assert "Every shot must advance" in prompt
    assert SECTION_A in prompt and SECTION_B in prompt


@pytest.mark.asyncio
async def test_planning_inference_gets_one_bounded_contract_repair():
    plan, quote = _planning_contract()
    invalid = _draft()
    invalid["shots"][0]["closing_state"] = copy.deepcopy(
        invalid["shots"][0]["opening_state"]
    )

    class Client:
        def __init__(self):
            self.responses = [json.dumps(invalid), json.dumps(_draft())]
            self.calls = []

        async def generate(self, **kwargs):
            self.calls.append(kwargs)
            return self.responses.pop(0)

    client = Client()
    compiled = await director.plan_custom_film_director(
        "Create a coherent film about a courier exposing a private transit system.",
        plan,
        quote,
        client,
        prospective_plan_id=PLAN_ID,
    )
    assert compiled["contract_hash"]
    assert len(client.calls) == 2
    assert "Repair this screenplay/director JSON" in client.calls[1]["prompt"]


@pytest.mark.asyncio
async def test_director_persistence_normalizes_exact_shots_and_loads_hashes(
    monkeypatch,
):
    compiled = _compile()

    class Conn:
        def __init__(self):
            self.executed = []

        async def fetchrow(self, query, *args):
            if "FROM custom_film_plans" in query:
                return {"id": PLAN_ID, "plan_hash": PLAN_HASH}
            if "FROM custom_film_director_contracts" in query:
                return None
            raise AssertionError(query)

        async def fetch(self, query, *args):
            assert "FROM custom_film_sections" in query
            return [{"section_id": SECTION_A}, {"section_id": SECTION_B}]

        async def fetchval(self, query, *args):
            assert "MAX(revision)" in query
            return 1

        async def execute(self, query, *args):
            self.executed.append((query, args))
            return "INSERT 0 1"

    conn = Conn()
    persisted = await director.persist_director_contract(
        conn,
        tenant_id="tenant-a",
        video_id=str(uuid4()),
        plan_id=PLAN_ID,
        plan_hash=PLAN_HASH,
        director_contract=compiled,
    )
    assert persisted["created"] is True
    assert persisted["revision"] == 1
    assert len(conn.executed) == 4
    assert "INSERT INTO custom_film_director_contracts" in conn.executed[0][0]
    assert all(
        "INSERT INTO custom_film_shots" in query
        for query, _args in conn.executed[1:]
    )

    async def fake_fetch_one(query, *args):
        assert "WHERE tenant_id = $1 AND video_id = $2" in query
        return {
            "id": persisted["id"],
            "plan_id": PLAN_ID,
            "revision": 1,
            "plan_hash": PLAN_HASH,
            "director_contract": json.dumps(compiled),
        }

    monkeypatch.setattr(database, "fetch_one", fake_fetch_one)
    loaded = await director.load_latest_director_contract(
        "tenant-a", "video-a"
    )
    assert loaded["id"] == persisted["id"]
    assert loaded["contract"] == compiled


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
    pictures = director.compile_picture_gate(
        compiled, storyboards, _picture_reviews(compiled, storyboards)
    )
    verifications = _verifications(compiled, storyboards, pictures)
    visual_gate = director.compile_visual_gate(
        compiled, storyboards, pictures, verifications
    )
    admission = director.build_remotion_admission(
        compiled, storyboards, pictures, visual_gate
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
        director.compile_visual_gate(compiled, storyboards, pictures, drifted)

    bad_lip_sync = copy.deepcopy(verifications)
    bad_lip_sync[1]["lip_sync_match"] = False
    bad_lip_sync[1]["repair_instruction"] = "Re-time Ilan's exact speaker turn."
    with pytest.raises(contract.CustomFilmContractError, match="lip_sync_mismatch"):
        director.compile_visual_gate(
            compiled, storyboards, pictures, bad_lip_sync
        )


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


def _stage_authority(
    compiled,
    stage,
    upstream_hash,
    *,
    prior_cents=857,
    helper=None,
):
    counts = director_runtime.expected_stage_bom(compiled, stage)
    operations = [
        {
            "operation_kind": kind,
            "count": count,
            "unit_max_cents": 0 if stage == "assembly" else 7,
            "helper_operation": False,
        }
        for kind, count in counts.items()
        if count
    ]
    if helper:
        operations.append(helper)
    stage_max = sum(
        row["count"] * row["unit_max_cents"] for row in operations
    )
    return {
        "stage": stage,
        "stage_binding_hash": compiled["contract_hash"],
        "upstream_gate_hash": upstream_hash,
        "quote_hash": "c" * 64,
        "prior_cumulative_cents": prior_cents,
        "approved_cumulative_cents": prior_cents + stage_max,
        "operations": operations,
    }


def test_director_runtime_schedules_every_gate_bound_stage_without_execution():
    compiled = _compile()
    reference_authority = _stage_authority(
        compiled,
        "references",
        compiled["contract_hash"],
        helper={
            "operation_kind": "reference_contact_sheet",
            "count": 1,
            "unit_max_cents": 3,
            "helper_operation": True,
        },
    )
    reference_schedule = director_runtime.compile_director_stage_schedule(
        compiled,
        reference_authority,
    )
    assert reference_schedule["provider_calls_started"] is False
    assert reference_schedule["spend_recorded_cents"] == 0
    assert reference_schedule["task_count"] == 5
    assert reference_schedule["stage_max_cents"] == 31
    assert {task["subject_kind"] for task in reference_schedule["tasks"]} == {
        "character",
        "environment",
        "helper",
    }

    references = director.compile_reference_gate(
        compiled, _reference_reviews(compiled)
    )
    storyboard_schedule = director_runtime.compile_director_stage_schedule(
        compiled,
        _stage_authority(
            compiled,
            "storyboards",
            references["reference_gate_hash"],
        ),
        reference_gate=references,
    )
    assert storyboard_schedule["task_count"] == 3
    assert all(
        task["input_payload"]["lock_reference_artifacts"]
        for task in storyboard_schedule["tasks"]
    )

    storyboards = director.compile_storyboard_gate(
        compiled, references, _storyboard_reviews(compiled, references)
    )
    picture_schedule = director_runtime.compile_director_stage_schedule(
        compiled,
        _stage_authority(
            compiled,
            "final_pictures",
            storyboards["storyboard_gate_hash"],
        ),
        storyboard_gate=storyboards,
    )
    assert [
        task["input_payload"]["storyboard_artifact_id"]
        for task in picture_schedule["tasks"]
    ] == ["board:tube_arrival", "board:choice_exchange", "board:city_reveal"]

    pictures = director.compile_picture_gate(
        compiled, storyboards, _picture_reviews(compiled, storyboards)
    )
    animation_schedule = director_runtime.compile_director_stage_schedule(
        compiled,
        _stage_authority(
            compiled,
            "animation_voice",
            pictures["picture_gate_hash"],
        ),
        picture_gate=pictures,
    )
    animation_tasks = [
        task
        for task in animation_schedule["tasks"]
        if task["operation_kind"] == "animation_clip"
    ]
    voice_tasks = [
        task
        for task in animation_schedule["tasks"]
        if task["operation_kind"] == "voice_line"
    ]
    assert len(animation_tasks) == 3
    assert len(voice_tasks) == 4
    assert all(task["input_payload"]["voice_lock"] for task in voice_tasks)
    assert {
        task["input_payload"]["caption_mode"] for task in voice_tasks
    } == {"dialogue", "narration"}
    assert all(task["input_payload"]["ambient_sound"] for task in animation_tasks)

    visual_gate = director.compile_visual_gate(
        compiled,
        storyboards,
        pictures,
        _verifications(compiled, storyboards, pictures),
    )
    assembly_schedule = director_runtime.compile_director_stage_schedule(
        compiled,
        _stage_authority(
            compiled,
            "assembly",
            visual_gate["visual_gate_hash"],
        ),
        reference_gate=references,
        storyboard_gate=storyboards,
        picture_gate=pictures,
        visual_gate=visual_gate,
    )
    assert assembly_schedule["stage_max_cents"] == 0
    assembly_input = assembly_schedule["tasks"][0]["input_payload"]
    assert len(assembly_input["remotion_admission"]["shots"]) == 3
    assert assembly_input["remotion_admission"]["shots"][0]["ambient_sound"]
    assert "measured_captions" in assembly_input["layer_requirements"]


def test_director_runtime_rejects_wrong_bom_and_stale_gate_before_tasks():
    compiled = _compile()
    references = director.compile_reference_gate(
        compiled, _reference_reviews(compiled)
    )
    authority = _stage_authority(
        compiled,
        "storyboards",
        references["reference_gate_hash"],
    )
    authority["operations"][0]["count"] = 2
    authority["approved_cumulative_cents"] -= 7
    with pytest.raises(contract.CustomFilmContractError, match="count changed"):
        director_runtime.compile_director_stage_schedule(
            compiled,
            authority,
            reference_gate=references,
        )

    stale = copy.deepcopy(references)
    stale["approvals"][0]["reference_artifact_id"] = "changed"
    with pytest.raises(contract.CustomFilmContractError, match="changed"):
        director_runtime.compile_director_stage_schedule(
            compiled,
            _stage_authority(
                compiled,
                "storyboards",
                references["reference_gate_hash"],
            ),
            reference_gate=stale,
        )


def test_script_director_schedule_uses_plan_binding_before_contract_exists():
    raw_authority = {
        "stage": "script_director",
        "stage_binding_hash": PLAN_HASH,
        "upstream_gate_hash": PLAN_HASH,
        "quote_hash": "d" * 64,
        "prior_cumulative_cents": 857,
        "approved_cumulative_cents": 868,
        "operations": [
            {
                "operation_kind": "director_plan",
                "count": 1,
                "unit_max_cents": 11,
                "helper_operation": False,
            }
        ],
    }
    schedule = director_runtime.compile_script_director_schedule(
        plan_id=PLAN_ID,
        plan_hash=PLAN_HASH,
        raw_authority=raw_authority,
    )
    assert schedule["stage"] == "script_director"
    assert schedule["approved_cumulative_cents"] == 868
    assert schedule["tasks"][0]["subject_id"] == PLAN_ID
    assert schedule["provider_calls_started"] is False


class _StageScheduleConn:
    def __init__(self, authority):
        self.authority = authority
        self.stored = None

    async def fetchrow(self, query, *args):
        if "FROM custom_film_stage_authorities" in query:
            return self.authority
        if "INSERT INTO custom_film_director_stage_schedules" in query:
            self.stored = {
                "id": str(uuid4()),
                "schedule_hash": args[10],
                "task_count": args[11],
            }
            return {"id": self.stored["id"]}
        if "FROM custom_film_director_stage_schedules" in query:
            return self.stored
        raise AssertionError(query)

    async def execute(self, query, *args):
        assert "UPDATE custom_film_stage_authorities" in query
        self.authority["consumed_at"] = "now"
        self.authority["consumed_by"] = args[2]
        return "UPDATE 1"


@pytest.mark.asyncio
async def test_stage_schedule_persistence_consumes_authority_once_and_replays():
    compiled = _compile()
    director_contract_id = str(uuid4())
    video_id = str(uuid4())
    raw_authority = _stage_authority(
        compiled,
        "references",
        compiled["contract_hash"],
    )
    schedule = director_runtime.compile_director_stage_schedule(
        compiled,
        raw_authority,
    )
    authority_id = str(uuid4())
    tenant_id = str(uuid4())
    conn = _StageScheduleConn(
        {
            "id": authority_id,
            "plan_id": PLAN_ID,
            "video_id": video_id,
            "director_contract_id": director_contract_id,
            "stage": schedule["stage"],
            "stage_binding_hash": schedule["stage_binding_hash"],
            "upstream_gate_hash": schedule["upstream_gate_hash"],
            "quote_hash": schedule["quote_hash"],
            "prior_cumulative_cents": schedule["prior_cumulative_cents"],
            "approved_cumulative_cents": schedule[
                "approved_cumulative_cents"
            ],
            "authority_hash": schedule["authority_hash"],
            "consumed_at": None,
            "consumed_by": None,
        }
    )
    first = await director_runtime.persist_stage_schedule(
        conn,
        tenant_id=tenant_id,
        plan_id=PLAN_ID,
        video_id=video_id,
        director_contract_id=director_contract_id,
        authority_id=authority_id,
        schedule=schedule,
    )
    assert first["created"] is True
    replay = await director_runtime.persist_stage_schedule(
        conn,
        tenant_id=tenant_id,
        plan_id=PLAN_ID,
        video_id=video_id,
        director_contract_id=director_contract_id,
        authority_id=authority_id,
        schedule=schedule,
    )
    assert replay == {**first, "created": False}

    tampered = copy.deepcopy(schedule)
    tampered["tasks"][0]["status"] = "started"
    with pytest.raises(contract.CustomFilmContractError, match="schedule changed"):
        director_runtime.validate_stage_schedule(tampered)


class _VerificationConn:
    def __init__(self):
        self.by_hash = {}
        self.attempts = []

    async def execute(self, query, *args):
        assert "pg_advisory_xact_lock" in query
        return "SELECT 1"

    async def fetchrow(self, query, *args):
        if "verification_hash = $4" in query:
            return self.by_hash.get(args[3])
        if "MAX(attempt)" in query:
            return {"next_attempt": len(self.attempts) + 1}
        if "INSERT INTO custom_film_visual_verifications" in query:
            row = {
                "id": str(uuid4()),
                "attempt": args[3],
                "verdict": args[11],
            }
            self.attempts.append(row)
            self.by_hash[args[10]] = row
            return {"id": row["id"]}
        raise AssertionError(query)


@pytest.mark.asyncio
async def test_rejected_visual_attempt_is_persisted_with_bounded_repair():
    compiled = _compile()
    references = director.compile_reference_gate(
        compiled, _reference_reviews(compiled)
    )
    storyboards = director.compile_storyboard_gate(
        compiled, references, _storyboard_reviews(compiled, references)
    )
    pictures = director.compile_picture_gate(
        compiled, storyboards, _picture_reviews(compiled, storyboards)
    )
    failed = _verifications(compiled, storyboards, pictures)[0]
    failed["motion_visible"] = False
    failed["repair_instruction"] = (
        "Regenerate only this shot with the locked run-and-stop action visible."
    )
    evaluation = director.evaluate_shot_verification(
        compiled,
        storyboards,
        pictures,
        failed,
    )
    assert evaluation["verdict"] == "rejected"
    assert evaluation["issue_codes"] == ["motion_missing"]

    conn = _VerificationConn()
    tenant_id = str(uuid4())
    director_contract_id = str(uuid4())
    stored = await director.persist_shot_verification(
        conn,
        tenant_id=tenant_id,
        director_contract_id=director_contract_id,
        director_contract=compiled,
        storyboard_gate=storyboards,
        picture_gate=pictures,
        raw_verification=failed,
    )
    assert stored["created"] is True
    assert stored["attempt"] == 1
    assert stored["verdict"] == "rejected"
    replay = await director.persist_shot_verification(
        conn,
        tenant_id=tenant_id,
        director_contract_id=director_contract_id,
        director_contract=compiled,
        storyboard_gate=storyboards,
        picture_gate=pictures,
        raw_verification=failed,
    )
    assert replay == {**stored, "created": False}


def _measured_words(text, start_frame, end_frame):
    tokens = re.findall(r"\S+\s*", text)
    available = end_frame - start_frame
    assert available >= len(tokens)
    rows = []
    cursor = start_frame
    for index, token in enumerate(tokens):
        remaining_tokens = len(tokens) - index
        token_end = (
            end_frame
            if remaining_tokens == 1
            else cursor + max(1, (end_frame - cursor) // remaining_tokens)
        )
        rows.append(
            {
                "text": token,
                "from_frame": cursor,
                "to_frame": token_end,
            }
        )
        cursor = token_end
    return rows


def test_director_remotion_props_bind_approved_clips_audio_and_captions():
    compiled = _compile()
    references = director.compile_reference_gate(
        compiled, _reference_reviews(compiled)
    )
    storyboards = director.compile_storyboard_gate(
        compiled, references, _storyboard_reviews(compiled, references)
    )
    pictures = director.compile_picture_gate(
        compiled, storyboards, _picture_reviews(compiled, storyboards)
    )
    visual = director.compile_visual_gate(
        compiled,
        storyboards,
        pictures,
        _verifications(compiled, storyboards, pictures),
    )
    clip_sources = {
        row["clip_artifact_id"]: {
            "source_key": f"clip-source:{row['shot_id']}",
            "local_path": f"director/{row['shot_id']}.mp4",
            "source_sha256": f"{index + 40:064x}",
        }
        for index, row in enumerate(visual["approved_verifications"])
    }
    voice_sources = {}
    sound_sources = {}
    for shot_index, shot in enumerate(compiled["shots"]):
        line_count = len(shot["spoken_lines"])
        for line_index, line in enumerate(shot["spoken_lines"]):
            start = shot["start_frame"] + (
                line_index * shot["duration_frames"] // line_count
            )
            end = (
                shot["end_frame"] + 1
                if line_index == line_count - 1
                else shot["start_frame"]
                + ((line_index + 1) * shot["duration_frames"] // line_count)
            )
            voice_sources[f"{shot['shot_id']}:{line_index}"] = {
                "source_key": f"voice:{shot['shot_id']}:{line_index}",
                "local_path": f"director/{shot['shot_id']}-{line_index}.wav",
                "source_sha256": f"{shot_index * 10 + line_index + 50:064x}",
                "start_frame": start,
                "end_frame": end,
                "measured_words": _measured_words(line["text"], start, end),
            }
        sound_sources[str(shot["shot_id"])] = [
            {
                "layer_id": f"ambient:{shot['shot_id']}",
                "kind": "ambient",
                "source_key": f"ambient-source:{shot['shot_id']}",
                "local_path": f"director/{shot['shot_id']}-ambient.wav",
                "source_sha256": f"{shot_index + 80:064x}",
                "start_frame": shot["start_frame"],
                "end_frame": shot["end_frame"] + 1,
                "gain_db": -24,
                "loop": True,
            }
        ]
    props = director_remotion.build_director_remotion_props(
        compiled,
        storyboards,
        pictures,
        visual,
        clip_sources=clip_sources,
        voice_sources=voice_sources,
        sound_sources=sound_sources,
    )
    assert props["schema_version"] == "custom-film-director-remotion-v1"
    assert props["video"] == {
        "fps": 24,
        "width": 1920,
        "height": 1080,
        "total_frames": 240,
    }
    assert [shot["start_frame"] for shot in props["shots"]] == [0, 48, 120]
    assert props["shots"][1]["caption_mode"] == "dialogue"
    assert props["shots"][2]["caption_mode"] == "narration"
    assert props["props_hash"] == custom_film_remotion.remotion_props_hash(
        {key: value for key, value in props.items() if key != "props_hash"}
    )

    missing_voice = copy.deepcopy(voice_sources)
    missing_voice.pop(next(iter(missing_voice)))
    with pytest.raises(contract.CustomFilmContractError, match="do not match"):
        director_remotion.build_director_remotion_props(
            compiled,
            storyboards,
            pictures,
            visual,
            clip_sources=clip_sources,
            voice_sources=missing_voice,
            sound_sources=sound_sources,
        )
