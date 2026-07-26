import copy
import inspect
from uuid import uuid4

import custom_film_director_multipass as multipass
import pytest

PLAN_ID = str(uuid4())
PLAN_HASH = "a" * 64
SECTION_ID = str(uuid4())


def _quote_inputs(*, shots=50, seconds=300):
    return {
        "contract_kind": "director_planning_scaffold",
        "forecast_only": True,
        "requested_duration_seconds": seconds,
        "target_shot_seconds": 6,
        "totals": {
            "duration_seconds": seconds,
            "planned_shots": shots,
        },
        "sections": [
            {
                "section_id": SECTION_ID,
                "order_index": 0,
                "duration_seconds": seconds,
                "still_images": shots,
            }
        ],
    }


def _price_book():
    return {
        "film_bible": 3,
        "shot_outline": 4,
        "shot_batch": 2,
        "film_bible_repair": 5,
        "shot_outline_repair": 6,
        "shot_batch_repair": 3,
    }


def _stage_contract():
    return multipass.build_multipass_stage_contract(
        plan_id=PLAN_ID,
        plan_hash=PLAN_HASH,
        quote_inputs=_quote_inputs(),
        prior_cumulative_cents=857,
        price_book=_price_book(),
    )


def test_five_minute_manifest_has_exact_bounded_call_graph_and_quote():
    contract = _stage_contract()
    manifest = contract["manifest"]
    quote = contract["stage_quote"]
    authority = contract["stage_authority"]
    schedule = contract["schedule"]

    assert manifest["execution_model"] == multipass.MULTIPASS_EXECUTION_MODEL
    assert manifest["planning_contract"]["totals"] == {
        "duration_seconds": 300,
        "planned_shots": 50,
    }
    assert manifest["initial_model_calls"] == 9
    assert manifest["conditional_repair_calls"] == 9
    assert manifest["maximum_model_calls"] == 18
    assert quote["maximum_model_calls"] == schedule["task_count"] == 18

    operations = manifest["operations"]
    assert len({row["operation_id"] for row in operations}) == 18
    assert [row["order_index"] for row in operations] == list(range(18))
    assert all(
        0 < row["max_tokens"] <= multipass.MAX_PROVIDER_OUTPUT_TOKENS
        for row in operations
    )

    batches = [
        row for row in operations if row["operation_kind"] == "shot_batch"
    ]
    assert [
        (row["shot_start_index"], row["shot_end_index"]) for row in batches
    ] == [
        (0, 7),
        (8, 15),
        (16, 23),
        (24, 31),
        (32, 39),
        (40, 47),
        (48, 49),
    ]
    assert all(
        row["shot_end_index"] - row["shot_start_index"] + 1
        <= multipass.MAX_SHOTS_PER_BATCH
        for row in batches
    )
    assert batches[0]["depends_on_result_slots"] == [
        "film_bible",
        "shot_outline",
    ]
    assert batches[1]["depends_on_result_slots"][-1] == batches[0][
        "result_slot_id"
    ]

    initials = {
        row["operation_id"]: row
        for row in operations
        if row["conditional"] is False
    }
    repairs = [row for row in operations if row["conditional"] is True]
    assert len(initials) == len(repairs) == 9
    assert all(row["repairs_operation_id"] in initials for row in repairs)
    assert {
        row["result_slot_id"] for row in repairs
    } == {
        row["result_slot_id"] for row in initials.values()
    }
    assert not any("whole_contract" in row["subject_id"] for row in operations)

    # 3 + 5 + 4 + 6 + (7 * 2) + (7 * 3) = 53 cents.
    assert quote["stage_max_cents"] == 53
    assert quote["prior_cumulative_cents"] == 857
    assert quote["approved_cumulative_cents"] == 910
    assert quote["media_generation_included"] is False
    assert sum(
        row["count"] * row["unit_max_cents"]
        for row in authority["operations"]
    ) == 53
    assert schedule["stage_max_cents"] == 53
    assert sum(row["unit_max_cents"] for row in schedule["tasks"]) == 53
    assert schedule["provider_calls_started"] is False
    assert schedule["spend_recorded_cents"] == 0

    assert (
        multipass.validate_multipass_stage_contract(contract)
        == contract
    )


def test_manifest_and_quote_are_byte_deterministic_for_same_inputs():
    first = _stage_contract()
    second = _stage_contract()

    assert first == second
    assert first["activation_hash"] == second["activation_hash"]
    assert first["schedule"]["schedule_hash"] == second["schedule"][
        "schedule_hash"
    ]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.pop("film_bible"),
        lambda value: value.__setitem__("unknown_operation", 1),
        lambda value: value.__setitem__("shot_batch", True),
        lambda value: value.__setitem__("shot_batch", 0),
        lambda value: value.__setitem__("shot_batch", -1),
        lambda value: value.__setitem__("shot_batch", "2"),
    ],
)
def test_price_book_never_guesses_or_accepts_non_exact_cents(mutate):
    price_book = _price_book()
    mutate(price_book)

    with pytest.raises(
        Exception,
        match="price book is incomplete|shot_batch price is invalid",
    ):
        multipass.build_multipass_stage_contract(
            plan_id=PLAN_ID,
            plan_hash=PLAN_HASH,
            quote_inputs=_quote_inputs(),
            prior_cumulative_cents=857,
            price_book=price_book,
        )


def test_planning_sections_must_reconcile_to_duration_and_shots():
    drifted = _quote_inputs()
    drifted["sections"][0]["still_images"] = 49

    with pytest.raises(Exception, match="sections do not reconcile"):
        multipass.build_multipass_manifest(
            plan_id=PLAN_ID,
            plan_hash=PLAN_HASH,
            quote_inputs=drifted,
        )


def test_shot_forecast_must_be_derived_from_duration_and_target():
    drifted = _quote_inputs()
    drifted["target_shot_seconds"] = 10

    with pytest.raises(Exception, match="shot forecast changed"):
        multipass.build_multipass_manifest(
            plan_id=PLAN_ID,
            plan_hash=PLAN_HASH,
            quote_inputs=drifted,
        )


@pytest.mark.parametrize(
    "path,changed",
    [
        (("manifest", "operations", 4, "shot_start_index"), 1),
        (("manifest", "operations", 0, "max_tokens"), 8_193),
        (("stage_quote", "maximum_model_calls"), 2),
        (("stage_authority", "approved_cumulative_cents"), 911),
        (("schedule", "tasks", 0, "unit_max_cents"), 99),
    ],
)
def test_any_manifest_quote_authority_or_schedule_drift_fails_closed(
    path,
    changed,
):
    drifted = copy.deepcopy(_stage_contract())
    cursor = drifted
    for part in path[:-1]:
        cursor = cursor[part]
    cursor[path[-1]] = changed

    with pytest.raises(Exception, match="activation changed"):
        multipass.validate_multipass_stage_contract(drifted)


def test_rehashed_manifest_drift_still_fails_deterministic_rebuild():
    drifted = copy.deepcopy(_stage_contract()["manifest"])
    drifted["operations"][4]["depends_on_result_slots"] = []
    drifted["operations"][4]["input_payload"]["depends_on_result_slots"] = []
    drifted["operations"][4]["input_hash"] = multipass.canonical_hash(
        drifted["operations"][4]["input_payload"]
    )
    identity = {
        key: drifted["operations"][4][key]
        for key in (
            "stage",
            "binding_hash",
            "operation_kind",
            "subject_kind",
            "subject_id",
            "order_index",
            "input_hash",
        )
    }
    drifted["operations"][4]["operation_id"] = (
        multipass.DIRECTOR_OPERATION_PREFIX
        + multipass.canonical_hash(identity)
    )
    drifted["manifest_hash"] = multipass.canonical_hash(
        {key: value for key, value in drifted.items() if key != "manifest_hash"}
    )

    with pytest.raises(Exception, match="manifest no longer reconciles"):
        multipass.validate_multipass_manifest(drifted)


def test_v1_two_call_activation_cannot_validate_as_multipass_v2():
    legacy = {
        "activation_version": 1,
        "execution_model": "storyboard_director_v1",
        "maximum_model_calls": 2,
    }
    legacy["activation_hash"] = multipass.canonical_hash(legacy)

    with pytest.raises(Exception, match="activation version changed"):
        multipass.validate_multipass_stage_contract(legacy)


def test_manifest_module_has_no_execution_or_credential_seam():
    source = inspect.getsource(multipass)

    assert "kie_unified" not in source
    assert "from database" not in source
    assert "get_pool" not in source
    assert ".generate(" not in source
    assert "httpx" not in source
