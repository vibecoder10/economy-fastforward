import copy
import json
from uuid import uuid4

import custom_film_director_multipass as multipass
import custom_film_director_multipass_executor as executor
import pytest

PLAN_ID = str(uuid4())
PLAN_HASH = "b" * 64
SECTION_ID = str(uuid4())
BEGINNING = "Mara enters the sealed transit archive with one unanswered warning."
ENDING = "Mara broadcasts the archive proof and the city understands the hidden route."


def _price_book():
    return {key: 2 for key in multipass.PRICE_BOOK_KEYS}


def _quote_inputs():
    return {
        "requested_duration_seconds": 300,
        "target_shot_seconds": 6,
        "totals": {
            "duration_seconds": 300,
            "planned_shots": 50,
        },
        "sections": [
            {
                "section_id": SECTION_ID,
                "order_index": 0,
                "duration_seconds": 300,
                "still_images": 50,
            }
        ],
    }


def _stage_contract():
    return multipass.build_multipass_stage_contract(
        plan_id=PLAN_ID,
        plan_hash=PLAN_HASH,
        quote_inputs=_quote_inputs(),
        prior_cumulative_cents=857,
        price_book=_price_book(),
    )


def _film_bible():
    return {
        "title": "The Hidden Route",
        "logline": (
            "An archive courier follows one sealed warning through a transit "
            "network built to move powerful people beyond public view."
        ),
        "throughline": (
            "Mara and Ivo trace the warning from a locked archive shelf to a "
            "broadcast that reveals who built the hidden route and why."
        ),
        "central_question": (
            "Can Mara expose the route before its owners erase the archive?"
        ),
        "beginning_state": BEGINNING,
        "ending_state": ENDING,
        "visual_motif": (
            "A thin amber transit line grows into a visible citywide network."
        ),
        "timeline_law": (
            "The story advances continuously through one night unless a visible "
            "archive projection explicitly identifies an earlier event."
        ),
        "geography_law": (
            "The archive desk remains west of the sealed tunnel door, and every "
            "movement into the tunnel travels screen-left to screen-right."
        ),
        "narrator_mode": "third_person",
        "narrator_character_id": None,
        "narrator_voice_lock": (
            "Measured investigative alto, controlled pace, never omniscient."
        ),
        "style": {
            "medium": "cinematic animated illustration",
            "rendering_approach": (
                "Grounded dimensional ink illustration with stable anatomy."
            ),
            "palette": ["charcoal", "amber", "oxidized teal"],
            "texture": "Fine paper grain with restrained atmospheric haze.",
            "lens_language": (
                "Natural 35mm perspective with deliberate dialogue coverage."
            ),
            "lighting_law": (
                "Amber practical light always motivates faces from frame left."
            ),
            "aspect_ratio": "16:9",
            "negative_constraints": [
                "no photoreal live action",
                "no flat cartoon drift",
            ],
        },
        "characters": [
            {
                "character_id": "mara",
                "display_name": "Mara Vale",
                "story_role": "Archive courier who chooses to expose the route.",
                "identity_prompt": (
                    "Thirty-two-year-old South Asian woman with an oval face, "
                    "brown eyes, and a short black undercut."
                ),
                "face_body_lock": (
                    "Oval face, compact athletic frame, five feet six inches."
                ),
                "wardrobe_lock": (
                    "Charcoal courier jacket, amber archive badge, dark trousers."
                ),
                "voice_lock": "Low warm alto with clipped urgency.",
                "performance_law": (
                    "Stillness under pressure, then decisive forward movement."
                ),
                "forbidden_drift": [
                    "no hairstyle change",
                    "no wardrobe change",
                ],
            },
            {
                "character_id": "ivo",
                "display_name": "Ivo Renn",
                "story_role": "Archive custodian who knows why the route exists.",
                "identity_prompt": (
                    "Forty-eight-year-old Black man with a narrow face, gray "
                    "temples, deep-set eyes, and a careful upright posture."
                ),
                "face_body_lock": (
                    "Narrow face, lean frame, gray temples, six feet tall."
                ),
                "wardrobe_lock": (
                    "Oxidized-teal archive coat with brass key chain."
                ),
                "voice_lock": "Precise baritone with restrained remorse.",
                "performance_law": (
                    "Guarded eye contact that opens into direct confession."
                ),
                "forbidden_drift": [
                    "no age drift",
                    "no coat color change",
                ],
            },
        ],
        "environments": [
            {
                "environment_id": "archive_tunnel",
                "display_name": "Transit Archive and Sealed Tunnel",
                "story_function": (
                    "The archive turns documentary proof into a physical escape route."
                ),
                "identity_prompt": (
                    "A vaulted municipal archive joined to a sealed ceramic "
                    "transit tunnel, brass shelves, amber task lamps, wet stone."
                ),
                "architecture_lock": (
                    "Archive desk west, tunnel door east, projection wall north."
                ),
                "lighting_time_weather_lock": (
                    "One rainy night; amber lamps inside, cold teal rain outside."
                ),
                "geography_lock": (
                    "Movement toward the tunnel is always screen-left to screen-right."
                ),
                "palette_lock": "Charcoal stone, oxidized teal, amber practicals.",
                "props": [],
            }
        ],
    }


def _story_fact(index):
    if index == 0:
        return BEGINNING
    if index == 50:
        return ENDING
    return (
        f"After shot {index:02d}, Mara and Ivo possess one more visible link "
        "between the archive warning and the hidden transit route."
    )


def _outline_and_shots():
    outline = []
    shots = []
    for index in range(50):
        shot_key = f"shot_{index + 1:02d}"
        previous_key = f"shot_{index:02d}" if index else None
        technique_index = index % 4
        if technique_index == 0:
            technique = "poco_dialogue"
            performance_mode = "dialogue"
        elif technique_index == 1:
            technique = "dvsu_documentary"
            performance_mode = "exposition"
        elif technique_index == 2:
            technique = "power_doctrine_exposition"
            performance_mode = "exposition"
        else:
            technique = "cinematic_action"
            performance_mode = "silent_action"
        opening_fact = _story_fact(index)
        closing_fact = _story_fact(index + 1)
        narrative_purpose = (
            f"Advance link {index + 1:02d} in the route investigation through "
            "visible evidence, performance, or physical action."
        )
        story_value = (
            f"The audience understands investigation link {index + 1:02d} and "
            "why it forces Mara toward the final broadcast."
        )
        caused_by = [] if previous_key is None else [previous_key]
        outline.append(
            {
                "shot_key": shot_key,
                "section_id": SECTION_ID,
                "duration_frames": 144,
                "technique": technique,
                "performance_mode": performance_mode,
                "narrative_purpose": narrative_purpose,
                "caused_by": caused_by,
                "progression_kinds": ["story", "information"],
                "story_value": story_value,
                "opening_story_fact": opening_fact,
                "closing_story_fact": closing_fact,
                "environment_id": "archive_tunnel",
                "character_ids": ["mara", "ivo"],
            }
        )
        opening_state = {
            "story_facts": [opening_fact],
            "character_positions": {
                "mara": "west side of the archive desk",
                "ivo": "north side of the archive desk",
            },
            "prop_states": {},
            "emotional_state": {
                "mara": f"determined at link {index:02d}",
                "ivo": f"guarded at link {index:02d}",
            },
        }
        closing_state = {
            "story_facts": [closing_fact],
            "character_positions": {
                "mara": "west side of the archive desk",
                "ivo": "north side of the archive desk",
            },
            "prop_states": {},
            "emotional_state": {
                "mara": f"determined at link {index + 1:02d}",
                "ivo": f"guarded at link {index + 1:02d}",
            },
        }
        if performance_mode == "dialogue":
            spoken_lines = [
                {
                    "speaker_id": "mara",
                    "kind": "dialogue",
                    "text": f"I can prove link {index + 1:02d}; tell me what it opens.",
                    "language": "English",
                    "delivery": "Low and direct.",
                    "addressee_id": "ivo",
                },
                {
                    "speaker_id": "ivo",
                    "kind": "dialogue",
                    "text": f"Link {index + 1:02d} opens the route they kept off every map.",
                    "language": "English",
                    "delivery": "Measured, then ashamed.",
                    "addressee_id": "mara",
                },
            ]
            caption_mode = "dialogue"
        elif performance_mode == "exposition":
            spoken_lines = [
                {
                    "speaker_id": "third_person_narrator",
                    "kind": "narration",
                    "text": (
                        f"Link {index + 1:02d} turns the archive warning into "
                        "evidence of a privately controlled public route."
                    ),
                    "language": "English",
                    "delivery": "Measured investigative emphasis.",
                    "addressee_id": None,
                }
            ]
            caption_mode = "narration"
        else:
            spoken_lines = []
            caption_mode = "none"
        shots.append(
            {
                **{
                    key: value
                    for key, value in outline[-1].items()
                    if key
                    not in {
                        "opening_story_fact",
                        "closing_story_fact",
                    }
                },
                "opening_state": opening_state,
                "action_beats": [
                    (
                        f"Mara and Ivo physically reveal archive link "
                        f"{index + 1:02d} in one continuous movement."
                    )
                ],
                "closing_state": closing_state,
                "transition_from_previous": "opening" if index == 0 else "continuous",
                "continuity_bridge": None,
                "active_prop_ids": [],
                "screen_direction": (
                    "Evidence and attention move screen-left to screen-right."
                ),
                "shot_size": "Medium two-shot with readable evidence plane.",
                "camera_move": "Slow eight-inch push toward the revealed link.",
                "spoken_lines": spoken_lines,
                "storyboard_composition": (
                    f"Mara and Ivo share the archive frame while link "
                    f"{index + 1:02d} becomes legible in the foreground."
                ),
                "final_picture_intent": (
                    f"Hold the exact opening state for link {index + 1:02d}, "
                    "with locked faces, wardrobe, lighting, and geography."
                ),
                "motion_intent": (
                    f"Reveal link {index + 1:02d} through visible hand, eye, "
                    "evidence, and camera movement that lands the closing state."
                ),
                "ambient_sound": "Rain on stone, archive ventilation, distant rail hum.",
                "score_intent": (
                    "Restrained low strings add one pulse as the evidence changes."
                ),
                "sfx_cues": [
                    f"Paper or mechanism accent for link {index + 1:02d}."
                ],
                "caption_mode": caption_mode,
            }
        )
    return outline, shots


class FakeSingleAttemptClient:
    def __init__(
        self,
        *,
        invalid_initial_ids=None,
        invalid_repair_ids=None,
        raise_ids=None,
        attempt_count=1,
        actual_cost_cents=1,
        finish_reason="stop",
        output_tokens=1_000,
    ):
        self.invalid_initial_ids = set(invalid_initial_ids or ())
        self.invalid_repair_ids = set(invalid_repair_ids or ())
        self.raise_ids = set(raise_ids or ())
        self.attempt_count = attempt_count
        self.actual_cost_cents = actual_cost_cents
        self.finish_reason = finish_reason
        self.output_tokens = output_tokens
        self.calls = []
        self.outline, self.shots = _outline_and_shots()

    async def execute_once(
        self,
        *,
        operation,
        prompt,
        system_prompt,
        max_tokens,
    ):
        self.calls.append(
            {
                "operation": copy.deepcopy(operation),
                "prompt": prompt,
                "system_prompt": system_prompt,
                "max_tokens": max_tokens,
            }
        )
        operation_id = operation["operation_id"]
        if operation_id in self.raise_ids:
            raise RuntimeError("ambiguous transport failure")
        if (
            operation_id in self.invalid_initial_ids
            or operation_id in self.invalid_repair_ids
        ):
            payload = {"invalid": "candidate"}
        elif operation["operation_kind"] in {
            "film_bible",
            "film_bible_repair",
        }:
            payload = {"film_bible": _film_bible()}
        elif operation["operation_kind"] in {
            "shot_outline",
            "shot_outline_repair",
        }:
            payload = {"shots": self.outline}
        else:
            start = operation["shot_start_index"]
            end = operation["shot_end_index"]
            payload = {"shots": self.shots[start : end + 1]}
        return {
            "request_id": f"request-{len(self.calls):02d}",
            "model": "fake-single-attempt-text",
            "attempt_count": self.attempt_count,
            "input_tokens": 500,
            "output_tokens": self.output_tokens,
            "actual_cost_cents": self.actual_cost_cents,
            "finish_reason": self.finish_reason,
            "text": json.dumps(payload),
        }


def _initial_and_repair(contract, kind, batch_index=None):
    operations = contract["schedule"]["tasks"]
    initial_rows = [
        row for row in operations if row["operation_kind"] == kind
    ]
    initial = initial_rows[batch_index or 0]
    repair = next(
        row
        for row in operations
        if row.get("repairs_operation_id") == initial["operation_id"]
    )
    return initial, repair


@pytest.mark.asyncio
async def test_complete_fifty_shot_fake_execution_uses_nine_calls_and_no_repairs():
    contract = _stage_contract()
    client = FakeSingleAttemptClient()
    journal = executor.InMemoryDirectorCallJournal()

    result = await executor.execute_multipass_director(
        stage_contract=contract,
        user_request="Make a five-minute investigative character film.",
        client=client,
        journal=journal,
    )

    assert len(client.calls) == result["terminal_call_count"] == 9
    assert result["repair_operation_count"] == 0
    assert result["actual_spend_cents"] == 9
    assert result["director_contract"]["total_frames"] == 7_200
    assert len(result["director_contract"]["shots"]) == 50
    assert result["director_contract"]["film_bible"]["beginning_state"] == BEGINNING
    assert result["director_contract"]["film_bible"]["ending_state"] == ENDING
    assert all(call["max_tokens"] <= 8_192 for call in client.calls)
    assert all(
        call["operation"]["operation_id"].startswith(
            multipass.DIRECTOR_OPERATION_PREFIX
        )
        for call in client.calls
    )
    assert len(journal.events()) == 18
    assert (
        executor.validate_multipass_execution_result(
            result,
            stage_contract=contract,
        )
        == result
    )


@pytest.mark.asyncio
async def test_only_failed_batch_uses_its_paired_repair_and_final_contract_passes():
    contract = _stage_contract()
    failed_batch, paired_repair = _initial_and_repair(
        contract,
        "shot_batch",
        batch_index=2,
    )
    client = FakeSingleAttemptClient(
        invalid_initial_ids={failed_batch["operation_id"]}
    )
    journal = executor.InMemoryDirectorCallJournal()

    result = await executor.execute_multipass_director(
        stage_contract=contract,
        user_request="Make the route investigation.",
        client=client,
        journal=journal,
    )

    called_ids = [call["operation"]["operation_id"] for call in client.calls]
    repair_ids = [
        operation_id
        for operation_id in called_ids
        if next(
            row
            for row in contract["schedule"]["tasks"]
            if row["operation_id"] == operation_id
        )["operation_kind"]
        in multipass.REPAIR_OPERATION_KINDS
    ]
    assert len(client.calls) == 10
    assert repair_ids == [paired_repair["operation_id"]]
    assert result["repair_operation_count"] == 1
    assert result["actual_spend_cents"] == 10
    assert len(result["director_contract"]["shots"]) == 50


@pytest.mark.asyncio
async def test_completed_receipts_replay_without_another_client_call():
    contract = _stage_contract()
    journal = executor.InMemoryDirectorCallJournal()
    first_client = FakeSingleAttemptClient()
    first = await executor.execute_multipass_director(
        stage_contract=contract,
        user_request="Make the route investigation.",
        client=first_client,
        journal=journal,
    )
    replay_client = FakeSingleAttemptClient()

    replay = await executor.execute_multipass_director(
        stage_contract=contract,
        user_request="Make the route investigation.",
        client=replay_client,
        journal=journal,
    )

    assert len(first_client.calls) == 9
    assert replay_client.calls == []
    assert replay["director_contract_hash"] == first["director_contract_hash"]
    assert replay["actual_spend_cents"] == first["actual_spend_cents"] == 9


@pytest.mark.asyncio
async def test_ambiguous_started_attempt_is_never_retried():
    contract = _stage_contract()
    film_bible, _repair = _initial_and_repair(contract, "film_bible")
    journal = executor.InMemoryDirectorCallJournal()
    crashing_client = FakeSingleAttemptClient(
        raise_ids={film_bible["operation_id"]}
    )

    with pytest.raises(
        executor.DirectorReconciliationRequired,
        match="without a terminal receipt",
    ):
        await executor.execute_multipass_director(
            stage_contract=contract,
            user_request="Make the route investigation.",
            client=crashing_client,
            journal=journal,
        )
    assert len(crashing_client.calls) == 1
    assert [row["event_kind"] for row in journal.events()] == [
        "attempt_started"
    ]

    safe_client = FakeSingleAttemptClient()
    with pytest.raises(
        executor.DirectorReconciliationRequired,
        match="spend reconciliation",
    ):
        await executor.execute_multipass_director(
            stage_contract=contract,
            user_request="Make the route investigation.",
            client=safe_client,
            journal=journal,
        )
    assert safe_client.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "client,match",
    [
        (
            FakeSingleAttemptClient(attempt_count=2),
            "hid multiple attempts",
        ),
        (
            FakeSingleAttemptClient(actual_cost_cents=3),
            "exceeded its ceiling",
        ),
        (
            FakeSingleAttemptClient(output_tokens=8_193),
            "exceeded its token ceiling",
        ),
    ],
)
async def test_hidden_retry_cost_or_token_overage_is_authorization_failure(
    client,
    match,
):
    journal = executor.InMemoryDirectorCallJournal()

    with pytest.raises(Exception, match=match):
        await executor.execute_multipass_director(
            stage_contract=_stage_contract(),
            user_request="Make the route investigation.",
            client=client,
            journal=journal,
        )

    assert len(client.calls) == 1
    assert [row["event_kind"] for row in journal.events()] == [
        "attempt_started",
        "attempt_failed",
    ]
    assert journal.events()[-1]["failure_code"] == "authorization_violation"


@pytest.mark.asyncio
async def test_authorization_violation_replay_cannot_consume_repair_slot():
    journal = executor.InMemoryDirectorCallJournal()
    bad_client = FakeSingleAttemptClient(attempt_count=2)
    contract = _stage_contract()
    with pytest.raises(executor.DirectorReconciliationRequired):
        await executor.execute_multipass_director(
            stage_contract=contract,
            user_request="Make the route investigation.",
            client=bad_client,
            journal=journal,
        )

    resumed_client = FakeSingleAttemptClient()
    with pytest.raises(
        executor.DirectorReconciliationRequired,
        match="authorization violation",
    ):
        await executor.execute_multipass_director(
            stage_contract=contract,
            user_request="Make the route investigation.",
            client=resumed_client,
            journal=journal,
        )

    assert len(bad_client.calls) == 1
    assert resumed_client.calls == []


@pytest.mark.asyncio
async def test_malformed_attempt_receipt_records_conservative_unit_exposure():
    class MalformedReceiptClient(FakeSingleAttemptClient):
        async def execute_once(self, **kwargs):
            await super().execute_once(**kwargs)
            return {"request_id": "bad-receipt", "actual_cost_cents": "unknown"}

    contract = _stage_contract()
    journal = executor.InMemoryDirectorCallJournal()
    with pytest.raises(executor.DirectorReconciliationRequired):
        await executor.execute_multipass_director(
            stage_contract=contract,
            user_request="Make the route investigation.",
            client=MalformedReceiptClient(),
            journal=journal,
        )

    terminal = journal.events()[-1]
    assert terminal["failure_code"] == "authorization_violation"
    assert terminal["actual_cost_cents"] == contract["schedule"]["tasks"][0][
        "unit_max_cents"
    ]


@pytest.mark.asyncio
async def test_failed_repair_stops_without_whole_contract_reroll():
    contract = _stage_contract()
    initial, repair = _initial_and_repair(contract, "shot_outline")
    client = FakeSingleAttemptClient(
        invalid_initial_ids={initial["operation_id"]},
        invalid_repair_ids={repair["operation_id"]},
    )
    journal = executor.InMemoryDirectorCallJournal()

    with pytest.raises(Exception, match="director repair failed"):
        await executor.execute_multipass_director(
            stage_contract=contract,
            user_request="Make the route investigation.",
            client=client,
            journal=journal,
        )

    assert [row["operation"]["operation_id"] for row in client.calls] == [
        _initial_and_repair(contract, "film_bible")[0]["operation_id"],
        initial["operation_id"],
        repair["operation_id"],
    ]
    assert not any(
        "whole_contract" in call["operation"]["subject_id"]
        for call in client.calls
    )


@pytest.mark.asyncio
async def test_truncated_initial_output_may_use_only_its_authorized_repair():
    contract = _stage_contract()
    initial, repair = _initial_and_repair(contract, "film_bible")

    class RepairingFinishReasonClient(FakeSingleAttemptClient):
        async def execute_once(self, **kwargs):
            result = await super().execute_once(**kwargs)
            if kwargs["operation"]["operation_id"] == initial["operation_id"]:
                result["finish_reason"] = "max_tokens"
            return result

    client = RepairingFinishReasonClient()
    journal = executor.InMemoryDirectorCallJournal()

    result = await executor.execute_multipass_director(
        stage_contract=contract,
        user_request="Make the route investigation.",
        client=client,
        journal=journal,
    )

    assert [call["operation"]["operation_id"] for call in client.calls[:2]] == [
        initial["operation_id"],
        repair["operation_id"],
    ]
    assert result["repair_operation_count"] == 1
    assert len(result["director_contract"]["shots"]) == 50


def test_receipt_event_hash_or_order_drift_fails_closed():
    operation = _stage_contract()["schedule"]["tasks"][0]
    started = executor.build_director_call_event(
        operation,
        event_kind="attempt_started",
    )
    tampered = copy.deepcopy(started)
    tampered["input_hash"] = "c" * 64

    with pytest.raises(Exception, match="receipt changed"):
        executor.InMemoryDirectorCallJournal([tampered])

    terminal_only = executor.build_director_call_event(
        operation,
        event_kind="attempt_completed",
        result={
            "request_id": "r1",
            "model": "fake",
            "input_tokens": 1,
            "output_tokens": 1,
            "actual_cost_cents": 1,
            "finish_reason": "stop",
        },
        output_payload={"film_bible": _film_bible()},
    )
    with pytest.raises(Exception, match="receipt order is invalid"):
        executor.InMemoryDirectorCallJournal([terminal_only])


@pytest.mark.asyncio
async def test_execution_result_receipt_or_spend_drift_fails_before_persistence():
    contract = _stage_contract()
    result = await executor.execute_multipass_director(
        stage_contract=contract,
        user_request="Make the route investigation.",
        client=FakeSingleAttemptClient(),
        journal=executor.InMemoryDirectorCallJournal(),
    )

    spend_drift = copy.deepcopy(result)
    spend_drift["actual_spend_cents"] += 1
    with pytest.raises(Exception, match="receipts do not reconcile"):
        executor.validate_multipass_execution_result(
            spend_drift,
            stage_contract=contract,
        )

    event_drift = copy.deepcopy(result)
    event_drift["receipt_events"][1]["actual_cost_cents"] += 1
    with pytest.raises(Exception, match="receipt changed"):
        executor.validate_multipass_execution_result(
            event_drift,
            stage_contract=contract,
        )
