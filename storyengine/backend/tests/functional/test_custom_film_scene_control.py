from __future__ import annotations

import copy
import inspect
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4

import pytest

import custom_film_scene_control as control
import routes.custom_film_scene_control as control_routes
from scripts.seed_custom_film_scene_control_synthetic import serialize_result


def _scene_contract(shot_ids=None):
    return {
        "scene_number": 1,
        "purpose": "Force the two characters to choose whether to reveal the route.",
        "target_duration_frames": 120,
        "story_time": "continuous storm night",
        "opening_state": "The route is hidden and neither character trusts the other.",
        "state_change": "The route is exposed and both characters commit to the reveal.",
        "character_ids": ["hero", "guide"],
        "environment_id": "service_station",
        "active_prop_ids": ["entry_token"],
        "continuity_in": "The token remains in the hero's right hand.",
        "continuity_out": "The route is open and the token remains visible.",
        "dialogue_turns": [
            {
                "speaker_id": "hero",
                "text": "Who owns this route?",
                "performance_intent": "quiet accusation",
                "timing": "shot one",
            },
            {
                "speaker_id": "guide",
                "text": "The people who wrote the map.",
                "performance_intent": "ashamed confession",
                "timing": "shot two",
            },
        ],
        "silent_action_beats": ["The hero presses the token to the panel."],
        "shot_ids": shot_ids or [str(uuid4()), str(uuid4())],
    }


def _complete_locks():
    return [
        {
            "lock_kind": kind,
            "revision": 1,
            "content_hash": chr(97 + index) * 64,
            "approval_hash": chr(102 - index) * 64,
        }
        for index, kind in enumerate(control.LOCK_KINDS)
    ]


def test_synthetic_cli_result_with_timestamps_is_json_serializable():
    payload = {
        "control": {
            "film_locks": {
                "locks": [{"approved_at": datetime(2026, 7, 26, tzinfo=timezone.utc)}]
            }
        }
    }
    encoded = serialize_result(payload)
    assert '"approved_at": "2026-07-26 00:00:00+00:00"' in encoded


def test_scene_contract_and_revision_hash_are_deterministic_and_strict():
    raw = _scene_contract()
    compiled = control.compile_scene_contract(raw)
    first = control.compile_scene_revision(
        compiled,
        film_lock_set_hash="a" * 64,
        revision=1,
    )
    second = control.compile_scene_revision(
        copy.deepcopy(compiled),
        film_lock_set_hash="a" * 64,
        revision=1,
    )
    assert first == second
    assert len(first["revision_hash"]) == 64

    drifted = copy.deepcopy(raw)
    drifted["provider"] = "not allowed"
    with pytest.raises(control.SceneControlError, match="extra"):
        control.compile_scene_contract(drifted)


def test_scene_artifact_manifest_is_revision_bound_and_same_origin_only():
    contract = control.compile_scene_contract(_scene_contract())
    shot_ids = contract["shot_ids"]
    manifest = {
        "version": 1,
        "synthetic": True,
        "shots": [
            {
                "shot_id": shot_id,
                "kind": "video",
                "url": control.SYNTHETIC_SHOT_MEDIA_URLS[index],
                "start_frame": index * 60,
                "end_frame": index * 60 + 59,
                "sha256": chr(97 + index) * 64,
            }
            for index, shot_id in enumerate(shot_ids)
        ],
        "assembly": {
            "kind": "video",
            "url": control.SYNTHETIC_ASSEMBLY_MEDIA_URL,
            "duration_frames": 120,
            "sha256": "f" * 64,
        },
    }
    compiled = control.compile_artifact_manifest(
        manifest,
        scene_contract=contract,
    )
    with_manifest = control.compile_scene_revision(
        contract,
        film_lock_set_hash="a" * 64,
        revision=1,
        artifact_manifest=manifest,
    )
    without_manifest = control.compile_scene_revision(
        contract,
        film_lock_set_hash="a" * 64,
        revision=1,
    )
    assert with_manifest["artifact_manifest"] == compiled
    assert with_manifest["revision_hash"] != without_manifest["revision_hash"]

    external = copy.deepcopy(manifest)
    external["shots"][0]["url"] = "https://example.com/untrusted.mp4"
    with pytest.raises(control.SceneControlError, match="allowlisted"):
        control.compile_artifact_manifest(external, scene_contract=contract)


def test_shared_remotion_control_manifest_uses_backend_canonical_hashes():
    root = Path(__file__).resolve().parents[3]
    path = (
        root.parent
        / "remotion-video/src/custom-film/scene-control-proof-control-manifest.json"
    )
    manifest = json.loads(path.read_text())
    hash_entries = (
        "asset_evidence",
        "director_contract",
        "storyboard_gate",
        "picture_gate",
        "visual_gate",
        "admission",
    )
    for key in hash_entries:
        assert control.canonical_hash(manifest[key]["payload"]) == manifest[key][
            "sha256"
        ]
    assert control.canonical_hash(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    ) == manifest["manifest_sha256"]

    hashes = {key: manifest[key]["sha256"] for key in hash_entries}
    assert manifest["storyboard_gate"]["payload"]["director_contract_hash"] == hashes[
        "director_contract"
    ]
    for key in ("picture_gate", "visual_gate", "admission"):
        payload = manifest[key]["payload"]
        assert payload["director_contract_hash"] == hashes["director_contract"]
        assert payload["storyboard_gate_hash"] == hashes["storyboard_gate"]
        assert payload["asset_evidence_hash"] == hashes["asset_evidence"]
    assert manifest["visual_gate"]["payload"]["picture_gate_hash"] == hashes[
        "picture_gate"
    ]
    admission = manifest["admission"]["payload"]
    assert admission["picture_gate_hash"] == hashes["picture_gate"]
    assert admission["visual_gate_hash"] == hashes["visual_gate"]

    section_id = str(uuid4())
    draft = control.synthetic_director_draft(section_id)
    director_payload = manifest["director_contract"]["payload"]
    assert [row["id"] for row in director_payload["character_locks"]] == [
        row["character_id"] for row in draft["film_bible"]["characters"]
    ]
    assert director_payload["environment_lock"]["id"] == draft["film_bible"][
        "environments"
    ][0]["environment_id"]
    assert [row[1] for row in manifest["storyboard_gate"]["payload"]["shots"]] == [
        row["shot_key"] for row in draft["shots"][:5]
    ]


def test_all_state_transitions_are_exactly_one_gate():
    for current, target in zip(control.SCENE_STATES, control.SCENE_STATES[1:]):
        control.validate_transition(current, target)
    for current, target in (
        ("draft", "storyboard_approved"),
        ("plan_approved", "accepted"),
        ("assembled", "audio_approved"),
        ("accepted", "accepted"),
    ):
        with pytest.raises(control.SceneControlError, match="cannot move directly"):
            control.validate_transition(current, target)


@pytest.mark.parametrize(
    ("target_state", "artifact_gate"),
    [
        ("storyboard_approved", "storyboard"),
        ("imagery_approved", "imagery"),
        ("animation_approved", "animation"),
        ("audio_approved", "audio"),
        ("assembled", "assembly"),
        ("accepted", "assembly"),
    ],
)
def test_transition_evidence_is_bound_to_exact_artifact_hash(
    target_state,
    artifact_gate,
):
    artifacts = {
        "storyboard": "b" * 64,
        "imagery": "c" * 64,
        "animation": "d" * 64,
        "audio": "e" * 64,
        "assembly": "f" * 64,
    }
    scene = {
        "revision_hash": "a" * 64,
        "artifact_hashes": artifacts,
    }
    assert (
        control.required_transition_evidence(scene, target_state)
        == artifacts[artifact_gate]
    )
    assert (
        control.required_transition_evidence(scene, "plan_approved")
        == scene["revision_hash"]
    )

    scene["artifact_hashes"] = {
        key: value for key, value in artifacts.items() if key != artifact_gate
    }
    with pytest.raises(control.SceneControlError, match="artifact hash is required"):
        control.required_transition_evidence(scene, target_state)


@pytest.mark.asyncio
async def test_transition_service_rejects_unbound_evidence_before_any_write():
    revision_hash = "a" * 64
    scene_id = str(uuid4())

    class Conn:
        def __init__(self):
            self.writes = []

        async def fetchrow(self, query, *args):
            return {
                "id": scene_id,
                "tenant_id": "tenant-1",
                "plan_id": str(uuid4()),
                "video_id": "video-1",
                "director_contract_id": str(uuid4()),
                "scene_number": 1,
                "scene_contract": _scene_contract(),
                "revision": 1,
                "revision_hash": revision_hash,
                "film_lock_set_hash": "f" * 64,
                "artifact_hashes": {},
                "state": "draft",
                "accepted_revision_hash": None,
                "synthetic": True,
                "created_at": None,
                "updated_at": None,
            }

        async def fetchval(self, query, *args):
            return 0

        async def execute(self, query, *args):
            self.writes.append((query, args))
            return "UPDATE 1"

    conn = Conn()
    with pytest.raises(control.SceneControlError, match="does not match"):
        await control.transition_scene(
            conn,
            tenant_id="tenant-1",
            video_id="video-1",
            scene_id=scene_id,
            expected_revision_hash=revision_hash,
            target_state="plan_approved",
            evidence_hash="b" * 64,
        )
    assert conn.writes == []

    result = await control.transition_scene(
        conn,
        tenant_id="tenant-1",
        video_id="video-1",
        scene_id=scene_id,
        expected_revision_hash=revision_hash,
        target_state="plan_approved",
        evidence_hash=revision_hash,
    )
    assert result["state"] == "plan_approved"
    assert len(conn.writes) == 2


@pytest.mark.asyncio
async def test_transition_service_requires_current_gate_artifact_before_write():
    revision_hash = "a" * 64
    scene_id = str(uuid4())

    class Conn:
        def __init__(self, artifact_hashes):
            self.artifact_hashes = artifact_hashes
            self.writes = []

        async def fetchrow(self, query, *args):
            return {
                "id": scene_id,
                "tenant_id": "tenant-1",
                "plan_id": str(uuid4()),
                "video_id": "video-1",
                "director_contract_id": str(uuid4()),
                "scene_number": 1,
                "scene_contract": _scene_contract(),
                "revision": 2,
                "revision_hash": revision_hash,
                "film_lock_set_hash": "f" * 64,
                "artifact_hashes": self.artifact_hashes,
                "state": "plan_approved",
                "accepted_revision_hash": None,
                "synthetic": True,
                "created_at": None,
                "updated_at": None,
            }

        async def fetchval(self, query, *args):
            return 0

        async def execute(self, query, *args):
            self.writes.append((query, args))
            return "UPDATE 1"

    missing = Conn({})
    with pytest.raises(control.SceneControlError, match="storyboard artifact hash"):
        await control.transition_scene(
            missing,
            tenant_id="tenant-1",
            video_id="video-1",
            scene_id=scene_id,
            expected_revision_hash=revision_hash,
            target_state="storyboard_approved",
            evidence_hash="b" * 64,
        )
    assert missing.writes == []

    mismatched = Conn({"storyboard": "b" * 64})
    with pytest.raises(control.SceneControlError, match="does not match"):
        await control.transition_scene(
            mismatched,
            tenant_id="tenant-1",
            video_id="video-1",
            scene_id=scene_id,
            expected_revision_hash=revision_hash,
            target_state="storyboard_approved",
            evidence_hash="c" * 64,
        )
    assert mismatched.writes == []


def test_upstream_revision_invalidates_every_downstream_gate():
    assert control.invalidated_states("audio_approved", "storyboard") == [
        "storyboard_approved",
        "imagery_approved",
        "animation_approved",
        "audio_approved",
    ]
    assert control.invalidated_states("imagery_approved", "imagery") == [
        "imagery_approved"
    ]
    assert control.invalidated_states("plan_approved", "animation") == []
    with pytest.raises(control.SceneControlError, match="accepted scene is immutable"):
        control.invalidated_states("accepted", "plan")


def test_scene_rail_locks_scene_two_until_scene_one_is_accepted():
    scene_one = {"id": "scene-1", "state": "draft"}
    scene_two = {"id": "scene-2", "state": "draft"}
    scene_three = {"id": "scene-3", "state": "draft"}

    access, current = control.derive_scene_access(
        [scene_one, scene_two, scene_three]
    )
    assert access == ["current", "locked", "locked"]
    assert current == "scene-1"

    scene_one["state"] = "accepted"
    access, current = control.derive_scene_access(
        [scene_one, scene_two, scene_three]
    )
    assert access == ["accepted", "current", "locked"]
    assert current == "scene-2"


@pytest.mark.asyncio
async def test_server_rechecks_later_scene_lock_under_transaction():
    class Conn:
        def __init__(self, blocking):
            self.blocking = blocking
            self.calls = []

        async def fetchval(self, query, *args):
            self.calls.append((query, args))
            return self.blocking

    blocked = Conn(1)
    with pytest.raises(control.SceneControlError, match="later scene remains locked"):
        await control._assert_scene_accessible(
            blocked,
            "tenant-1",
            "video-1",
            2,
        )
    assert "tenant_id = $1 AND video_id = $2" in blocked.calls[0][0]

    unlocked = Conn(0)
    await control._assert_scene_accessible(
        unlocked,
        "tenant-1",
        "video-1",
        2,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("requested_scene_number", "current_max", "required"),
    [
        (999, None, 1),
        (3, 1, 2),
    ],
)
async def test_create_scene_rejects_noncontiguous_numbers_under_advisory_lock(
    monkeypatch,
    requested_scene_number,
    current_max,
    required,
):
    director_id = str(uuid4())
    contract = _scene_contract()
    contract["scene_number"] = requested_scene_number

    async def load(_conn, _tenant_id, _video_id):
        return {
            "id": director_id,
            "plan_id": str(uuid4()),
            "contract_hash": "a" * 64,
        }

    class Conn:
        def __init__(self):
            self.calls = []

        async def execute(self, query, *args):
            self.calls.append(("execute", query, args))
            return "SELECT 1"

        async def fetchrow(self, query, *args):
            self.calls.append(("fetchrow", query, args))
            return None

        async def fetchval(self, query, *args):
            self.calls.append(("fetchval", query, args))
            assert "MAX(scene_number)" in query
            return current_max

    monkeypatch.setattr(control, "_load_director", load)
    conn = Conn()
    with pytest.raises(
        control.SceneControlError,
        match=f"exactly {required}",
    ):
        await control.create_scene(
            conn,
            tenant_id="tenant-1",
            video_id="video-1",
            raw_scene_contract=contract,
        )
    assert "pg_advisory_xact_lock" in conn.calls[0][1]
    assert "tenant_id = $1 AND director_contract_id = $2" in conn.calls[1][1]
    assert "MAX(scene_number)" in conn.calls[2][1]


@pytest.mark.asyncio
async def test_create_scene_exact_retry_precedes_contiguous_number_check(monkeypatch):
    director_id = str(uuid4())
    scene_id = str(uuid4())
    contract = _scene_contract()
    contract["scene_number"] = 2

    async def load(_conn, _tenant_id, _video_id):
        return {
            "id": director_id,
            "plan_id": str(uuid4()),
            "contract_hash": "a" * 64,
        }

    class Conn:
        def __init__(self):
            self.fetchval_called = False

        async def execute(self, query, *args):
            assert "pg_advisory_xact_lock" in query
            return "SELECT 1"

        async def fetchrow(self, query, *args):
            return {
                "id": scene_id,
                "scene_contract": copy.deepcopy(contract),
                "revision": 4,
                "revision_hash": "b" * 64,
                "film_lock_set_hash": "c" * 64,
                "state": "imagery_approved",
                "synthetic": False,
            }

        async def fetchval(self, query, *args):
            self.fetchval_called = True
            raise AssertionError("Exact idempotent retry must not run gap checks")

    monkeypatch.setattr(control, "_load_director", load)
    conn = Conn()
    result = await control.create_scene(
        conn,
        tenant_id="tenant-1",
        video_id="video-1",
        raw_scene_contract=contract,
    )
    assert result == {
        "scene_id": scene_id,
        "scene_number": 2,
        "state": "imagery_approved",
        "revision": 4,
        "revision_hash": "b" * 64,
        "film_lock_set_hash": "c" * 64,
        "created": False,
        "synthetic": False,
    }
    assert conn.fetchval_called is False

    different_manifest = {
        "version": 1,
        "synthetic": True,
        "shots": [
            {
                "shot_id": shot_id,
                "kind": "video",
                "url": control.SYNTHETIC_SHOT_MEDIA_URLS[index],
                "start_frame": index * 60,
                "end_frame": index * 60 + 59,
                "sha256": chr(97 + index) * 64,
            }
            for index, shot_id in enumerate(contract["shot_ids"])
        ],
        "assembly": {
            "kind": "video",
            "url": control.SYNTHETIC_ASSEMBLY_MEDIA_URL,
            "duration_frames": 120,
            "sha256": "f" * 64,
        },
    }
    with pytest.raises(control.SceneControlError, match="artifact manifest"):
        await control.create_scene(
            conn,
            tenant_id="tenant-1",
            video_id="video-1",
            raw_scene_contract=contract,
            artifact_manifest=different_manifest,
        )


@pytest.mark.asyncio
async def test_read_scene_control_returns_tenant_director_bound_ordered_shots(
    monkeypatch,
):
    director_id = str(uuid4())
    scene_id = str(uuid4())
    first_shot_id = str(uuid4())
    second_shot_id = str(uuid4())
    contract = _scene_contract([first_shot_id, second_shot_id])
    scene_row = {
        "id": scene_id,
        "scene_number": 1,
        "scene_contract": contract,
        "revision": 1,
        "revision_hash": "a" * 64,
        "film_lock_set_hash": "b" * 64,
        "artifact_hashes": {},
        "state": "draft",
        "accepted_revision_hash": None,
        "synthetic": False,
    }
    shot_contracts = {
        first_shot_id: {"shot_key": "opening"},
        second_shot_id: {"shot_key": "decision"},
    }

    async def load(_conn, _tenant_id, _video_id):
        return {
            "id": director_id,
            "video_id": "video-1",
            "contract_hash": "c" * 64,
        }

    async def locks(_conn, _tenant_id, _director_id):
        return []

    class Conn:
        def __init__(self):
            self.shot_query = None
            self.shot_args = None

        async def fetch(self, query, *args):
            if "FROM custom_film_scene_controls" in query:
                return [copy.deepcopy(scene_row)]
            if "FROM custom_film_shots" in query:
                self.shot_query = query
                self.shot_args = args
                # Deliberately return reverse order; the response must follow
                # the exact scene_contract shot_ids order.
                return [
                    {
                        "shot_id": second_shot_id,
                        "order_index": 11,
                        "duration_frames": 60,
                        "shot_contract": shot_contracts[second_shot_id],
                    },
                    {
                        "shot_id": first_shot_id,
                        "order_index": 10,
                        "duration_frames": 60,
                        "shot_contract": shot_contracts[first_shot_id],
                    },
                ]
            raise AssertionError(query)

    monkeypatch.setattr(control, "_load_director", load)
    monkeypatch.setattr(control, "_lock_rows", locks)
    conn = Conn()
    result = await control.read_scene_control(
        conn,
        tenant_id="tenant-1",
        video_id="video-1",
    )
    shots = result["scenes"][0]["shots"]
    assert [shot["shot_id"] for shot in shots] == [
        first_shot_id,
        second_shot_id,
    ]
    assert shots == [
        {
            "shot_id": first_shot_id,
            "order_index": 10,
            "duration_frames": 60,
            "shot_contract": {"shot_key": "opening"},
        },
        {
            "shot_id": second_shot_id,
            "order_index": 11,
            "duration_frames": 60,
            "shot_contract": {"shot_key": "decision"},
        },
    ]
    assert result["scenes"][0]["synthetic"] is False
    assert "tenant_id = $1 AND director_contract_id = $2" in conn.shot_query
    assert conn.shot_args == (
        "tenant-1",
        director_id,
        [first_shot_id, second_shot_id],
    )


@pytest.mark.asyncio
async def test_scene_shot_read_models_fail_closed_on_missing_or_drifted_rows():
    first_shot_id = str(uuid4())
    second_shot_id = str(uuid4())
    contract = _scene_contract([first_shot_id, second_shot_id])
    scene_rows = [{"scene_contract": contract}]

    class MissingConn:
        async def fetch(self, query, *args):
            return [
                {
                    "shot_id": first_shot_id,
                    "order_index": 1,
                    "duration_frames": 60,
                    "shot_contract": {"shot_key": "opening"},
                }
            ]

    with pytest.raises(control.SceneControlError, match="does not match"):
        await control._read_scene_shot_models(
            MissingConn(),
            tenant_id="tenant-1",
            director_contract_id=str(uuid4()),
            scene_rows=scene_rows,
        )

    class DriftedConn:
        async def fetch(self, query, *args):
            return [
                {
                    "shot_id": first_shot_id,
                    "order_index": 2,
                    "duration_frames": 60,
                    "shot_contract": {"shot_key": "opening"},
                },
                {
                    "shot_id": second_shot_id,
                    "order_index": 1,
                    "duration_frames": 60,
                    "shot_contract": {"shot_key": "decision"},
                },
            ]

    with pytest.raises(control.SceneControlError, match="synchronous director order"):
        await control._read_scene_shot_models(
            DriftedConn(),
            tenant_id="tenant-1",
            director_contract_id=str(uuid4()),
            scene_rows=scene_rows,
        )


def test_exact_operation_card_has_no_hidden_repairs(monkeypatch):
    monkeypatch.setenv("CUSTOM_FILM_SCENE_STORYBOARD_IMAGE_MAX_CENTS", "9")
    shots = [str(uuid4()) for _ in range(5)]
    card = control.compile_operation_quote(
        video_id=str(uuid4()),
        scene_id=str(uuid4()),
        scene_number=1,
        scene_revision_hash="a" * 64,
        operation_type="storyboard_images",
        shot_ids=shots,
        dialogue_line_count=3,
        prior_completed_cumulative_cents=857,
    )
    assert card["provider_operation"] == "storyboard_image"
    assert card["initial_calls"] == 5
    assert card["max_repair_calls"] == 0
    assert card["exact_incremental_max_cents"] == 45
    assert card["prior_completed_cumulative_spend_cents"] == 857
    assert card["new_exact_cumulative_ceiling_cents"] == 902
    assert card["included_media"] == ["storyboard imagery"]
    assert "animation" in card["explicitly_unapproved"]
    assert card["approval_status"] == "not_approved"
    assert len(card["approval_card_hash"]) == 64


@pytest.mark.parametrize(
    ("actual_cost", "expected_cents"),
    [
        ("8.5701", 858),
        ("8.5749", 858),
        ("8.57", 857),
        (0, 0),
    ],
)
def test_prior_spend_conversion_never_understates_fractional_cents(
    actual_cost,
    expected_cents,
):
    assert control.conservative_usd_to_cents(actual_cost) == expected_cents


@pytest.mark.parametrize("actual_cost", ["-0.0001", "NaN", "Infinity", "not-money"])
def test_prior_spend_conversion_rejects_invalid_or_negative_values(actual_cost):
    with pytest.raises(control.SceneControlError, match="spend"):
        control.conservative_usd_to_cents(actual_cost)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("actual_cost", "expected_cents"),
    [("8.5701", 858), ("8.5749", 858), ("8.57", 857)],
)
async def test_quote_service_uses_conservative_completed_spend(
    monkeypatch,
    actual_cost,
    expected_cents,
):
    scene_id = str(uuid4())
    contract = _scene_contract()
    locks = _complete_locks()
    lock_set = control.compile_lock_set(locks)
    scene = {
        "id": scene_id,
        "scene_number": 1,
        "scene_contract": contract,
        "revision_hash": "a" * 64,
        "director_contract_id": str(uuid4()),
        "film_lock_set_hash": lock_set["film_lock_set_hash"],
        "state": "plan_approved",
    }

    async def scene_row(*_args, **_kwargs):
        return copy.deepcopy(scene)

    async def accessible(*_args, **_kwargs):
        return None

    async def lock_rows(*_args, **_kwargs):
        return copy.deepcopy(locks)

    class Conn:
        async def fetch(self, query, *args):
            return [
                {
                    "shot_id": shot_id,
                    "shot_contract": {"spoken_lines": []},
                }
                for shot_id in contract["shot_ids"]
            ]

        async def fetchval(self, query, *args):
            assert "generation_ledger" in query
            return actual_cost

    monkeypatch.setattr(control, "_scene_row", scene_row)
    monkeypatch.setattr(control, "_assert_scene_accessible", accessible)
    monkeypatch.setattr(control, "_lock_rows", lock_rows)
    card = await control.quote_scene_operation(
        Conn(),
        tenant_id="tenant-1",
        video_id=str(uuid4()),
        scene_id=scene_id,
        expected_revision_hash="a" * 64,
        operation_type="storyboard_images",
    )
    assert card["prior_completed_cumulative_spend_cents"] == expected_cents


def test_paid_quote_fails_closed_without_exact_server_price(monkeypatch):
    monkeypatch.delenv(
        "CUSTOM_FILM_SCENE_FINAL_IMAGE_MAX_CENTS",
        raising=False,
    )
    with pytest.raises(control.SceneControlError, match="required before"):
        control.compile_operation_quote(
            video_id=str(uuid4()),
            scene_id=str(uuid4()),
            scene_number=1,
            scene_revision_hash="a" * 64,
            operation_type="final_imagery",
            shot_ids=[str(uuid4())],
            dialogue_line_count=0,
            prior_completed_cumulative_cents=0,
        )


def test_shot_quote_is_exactly_one_current_scene_shot(monkeypatch):
    monkeypatch.setenv("CUSTOM_FILM_SCENE_ANIMATION_MAX_CENTS", "20")
    shots = [str(uuid4()), str(uuid4())]
    with pytest.raises(control.SceneControlError, match="one shot"):
        control.compile_operation_quote(
            video_id=str(uuid4()),
            scene_id=str(uuid4()),
            scene_number=1,
            scene_revision_hash="a" * 64,
            operation_type="animate_shot",
            shot_ids=shots,
            dialogue_line_count=0,
            prior_completed_cumulative_cents=0,
        )
    card = control.compile_operation_quote(
        video_id=str(uuid4()),
        scene_id=str(uuid4()),
        scene_number=1,
        scene_revision_hash="a" * 64,
        operation_type="animate_shot",
        shot_ids=shots,
        dialogue_line_count=0,
        prior_completed_cumulative_cents=0,
        requested_shot_id=shots[1],
    )
    assert card["shot_ids"] == [shots[1]]
    assert card["initial_calls"] == 1


def test_film_lock_set_requires_every_named_foundation():
    incomplete = control.compile_lock_set(_complete_locks()[:-1])
    complete = control.compile_lock_set(_complete_locks())
    assert incomplete["complete"] is False
    assert incomplete["missing"] == ["techniques"]
    assert complete["complete"] is True
    assert complete["missing"] == []
    assert complete["film_lock_set_hash"] != incomplete["film_lock_set_hash"]


def test_synthetic_pilot_requires_four_to_six_progressive_shots():
    environment = "station"
    rows = []
    for index in range(5):
        rows.append(
            {
                "shot_id": str(uuid4()),
                "duration_frames": 30,
                "shot_contract": {
                    "shot_key": f"shot_{index + 1}",
                    "performance_mode": (
                        "silent_action" if index == 2 else "dialogue"
                    ),
                    "opening_state": {"story_facts": [f"fact {index}"]},
                    "closing_state": {"story_facts": [f"fact {index + 1}"]},
                    "character_ids": ["hero", "guide"],
                    "environment_id": environment,
                    "active_prop_ids": ["token"],
                    "action_beats": [f"visible action {index + 1}"],
                    "spoken_lines": (
                        []
                        if index == 2
                        else [
                            {
                                "speaker_id": "hero" if index % 2 == 0 else "guide",
                                "text": f"line {index + 1}",
                                "delivery": "controlled",
                            }
                        ]
                    ),
                },
            }
        )
    scene = control.synthetic_scene_contract(rows)
    assert len(scene["shot_ids"]) == 5
    assert len(scene["character_ids"]) == 2
    assert scene["environment_id"] == environment
    assert scene["silent_action_beats"]
    assert scene["dialogue_turns"]


def test_canonical_synthetic_manifest_matches_remotion_proof():
    section_id = str(uuid4())
    plan_id = str(uuid4())
    plan_hash = "a" * 64
    draft = control.synthetic_director_draft(section_id)
    compiled = control.compile_director_contract(
        draft,
        plan_id=plan_id,
        plan_hash=plan_hash,
        section_ids=[section_id],
        total_frames=480,
        section_frame_counts={section_id: 480},
        section_shot_counts={section_id: 6},
        fps=24,
    )
    assert compiled["fps"] == 24
    assert compiled["total_frames"] == 480
    assert [shot["duration_frames"] for shot in compiled["shots"]] == [
        72,
        96,
        72,
        96,
        96,
        48,
    ]
    scene_one = control.synthetic_scene_contract(
        [
            {
                "shot_id": shot["shot_id"],
                "duration_frames": shot["duration_frames"],
                "shot_contract": shot,
            }
            for shot in compiled["shots"][:5]
        ]
    )
    assert scene_one["target_duration_frames"] == 432
    assert scene_one["character_ids"] == [
        "scene_control_character_mara",
        "scene_control_character_elias",
    ]
    assert scene_one["environment_id"] == "scene_control_environment_relay_room"
    assert [turn["text"] for turn in scene_one["dialogue_turns"]] == [
        "The signal is inside.",
        "Then it knows we're here.",
        "Kill the transmitter.",
        "Already did.",
    ]
    assert [turn["timing"] for turn in scene_one["dialogue_turns"]] == [
        "frames 78-118",
        "frames 120-164",
        "frames 246-286",
        "frames 288-332",
    ]
    assert "relay expands red" in " ".join(scene_one["silent_action_beats"])


def test_synthetic_scene_artifact_manifest_binds_shared_media_hashes():
    section_id = str(uuid4())
    plan_id = str(uuid4())
    draft = control.synthetic_director_draft(section_id)
    compiled = control.compile_director_contract(
        draft,
        plan_id=plan_id,
        plan_hash="a" * 64,
        section_ids=[section_id],
        total_frames=480,
        section_frame_counts={section_id: 480},
        section_shot_counts={section_id: 6},
        fps=24,
    )
    shot_rows = [
        {
            "shot_id": shot["shot_id"],
            "duration_frames": shot["duration_frames"],
            "shot_contract": shot,
        }
        for shot in compiled["shots"][:5]
    ]
    scene = control.synthetic_scene_contract(shot_rows)
    artifact_manifest = control.synthetic_scene_artifact_manifest(
        shot_rows,
        scene_contract=scene,
    )
    shared = control.load_synthetic_control_manifest()["asset_evidence"]["payload"]
    assert [row["shot_id"] for row in artifact_manifest["shots"]] == scene[
        "shot_ids"
    ]
    assert [row["url"] for row in artifact_manifest["shots"]] == list(
        control.SYNTHETIC_SHOT_MEDIA_URLS
    )
    assert [row["sha256"] for row in artifact_manifest["shots"]] == [
        row[1] for row in shared["clips"]
    ]
    assert artifact_manifest["assembly"] == {
        "kind": "video",
        "url": control.SYNTHETIC_ASSEMBLY_MEDIA_URL,
        "duration_frames": 432,
        "sha256": shared["assembly"][1],
    }


@pytest.mark.asyncio
async def test_empty_director_baseline_creates_deterministic_fixture(monkeypatch):
    tenant_id = str(uuid4())
    video_id = str(uuid4())

    class Conn:
        def __init__(self):
            self.video = None
            self.director = None
            self.plan = None
            self.plan_hash = None
            self.plan_id = None
            self.section_id = None
            self.shot_inserts = 0
            self.queries = []

        async def fetchrow(self, query, *args):
            self.queries.append(query)
            if "FROM videos" in query:
                return copy.deepcopy(self.video)
            if "FROM custom_film_director_contracts" in query:
                return copy.deepcopy(self.director)
            if "INSERT INTO videos" in query:
                self.video = {
                    "id": args[0],
                    "tenant_id": args[1],
                    "video_title": args[2],
                    "status": args[3],
                    "source": args[4],
                    "max_spend": 0,
                    "writer_guidance": args[5],
                    "custom_film_plan_id": None,
                    "custom_film_plan_revision": None,
                    "custom_film_plan_hash": None,
                    "custom_film_quote_inputs_hash": None,
                }
                return {"id": args[0]}
            if "FROM custom_film_plans" in query:
                return copy.deepcopy(self.plan)
            raise AssertionError(query)

        async def fetch(self, query, *args):
            if "FROM custom_film_sections" in query:
                return [{"section_id": self.section_id}]
            raise AssertionError(query)

        async def fetchval(self, query, *args):
            if "MAX(revision)" in query:
                return 1
            raise AssertionError(query)

        async def execute(self, query, *args):
            self.queries.append(query)
            if "INSERT INTO custom_film_plans" in query:
                self.plan_id = args[0]
                self.plan_hash = args[4]
                self.plan = {
                    "id": args[0],
                    "revision": 1,
                    "compatibility_version": "scene-control-synthetic-v1",
                    "plan": args[3],
                    "plan_hash": args[4],
                    "quote_inputs": args[5],
                    "quote_inputs_hash": args[6],
                }
            elif "INSERT INTO custom_film_sections" in query:
                self.section_id = args[3]
            elif "INSERT INTO custom_film_director_contracts" in query:
                self.director = {
                    "id": args[0],
                        "plan_id": args[2],
                        "video_id": args[3],
                        "revision": args[4],
                        "plan_hash": args[8],
                        "director_contract": args[11],
                        "contract_hash": args[12],
                    }
            elif "INSERT INTO custom_film_shots" in query:
                self.shot_inserts += 1
            elif "UPDATE videos" in query:
                self.video.update(
                    {
                        "custom_film_plan_id": args[2],
                        "custom_film_plan_revision": 1,
                        "custom_film_plan_hash": args[3],
                        "custom_film_quote_inputs_hash": args[4],
                    }
                )
            return "UPDATE 1"

    conn = Conn()
    first = await control.ensure_synthetic_director_fixture(
        conn,
        tenant_id=tenant_id,
        video_id=video_id,
    )
    second = await control.ensure_synthetic_director_fixture(
        conn,
        tenant_id=tenant_id,
        video_id=video_id,
    )

    assert first["created"] is True
    assert first["video_id"] == video_id
    assert second == {
        "video_id": video_id,
        "director_contract_id": first["director_contract_id"],
        "created": False,
    }
    assert conn.shot_inserts == 6
    assert conn.video["video_title"] == control.SYNTHETIC_VIDEO_TITLE
    assert conn.video["source"] == control.SYNTHETIC_VIDEO_SOURCE
    assert conn.video["max_spend"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("has_director", [False, True])
async def test_synthetic_fixture_rejects_existing_real_video_before_writes(
    has_director,
):
    tenant_id = str(uuid4())
    video_id = str(uuid4())

    class Conn:
        def __init__(self):
            self.writes = []
            self.director_queries = 0

        async def fetchrow(self, query, *args):
            if "FROM videos" in query:
                return {
                    "id": video_id,
                    "tenant_id": tenant_id,
                    "video_title": "Customer production",
                    "status": "custom_film_directed",
                    "source": "custom_film",
                    "max_spend": "25.00",
                    "writer_guidance": "real production",
                    "custom_film_plan_id": str(uuid4()) if has_director else None,
                    "custom_film_plan_revision": 1 if has_director else None,
                    "custom_film_plan_hash": "a" * 64 if has_director else None,
                    "custom_film_quote_inputs_hash": (
                        "b" * 64 if has_director else None
                    ),
                }
            if "FROM custom_film_director_contracts" in query:
                self.director_queries += 1
                return {"id": str(uuid4())} if has_director else None
            raise AssertionError(query)

        async def execute(self, query, *args):
            if query.lstrip().startswith(("INSERT", "UPDATE", "DELETE")):
                self.writes.append((query, args))
            return "SELECT 1"

    conn = Conn()
    with pytest.raises(control.SceneControlError, match="Refusing to attach"):
        await control.ensure_synthetic_director_fixture(
            conn,
            tenant_id=tenant_id,
            video_id=video_id,
        )
    assert conn.writes == []
    assert conn.director_queries == 0


@pytest.mark.asyncio
async def test_synthetic_seed_builds_scene_one_and_locked_scene_two(monkeypatch):
    tenant_id = str(uuid4())
    video_id = str(uuid4())
    director_id = str(uuid4())
    section_id = str(uuid4())
    draft = control.synthetic_director_draft(section_id)
    shot_rows = [
        {
            "shot_id": str(uuid4()),
            "duration_frames": 90,
            "shot_contract": shot,
        }
        for shot in draft["shots"]
    ]
    director = {
        "id": director_id,
        "plan_id": str(uuid4()),
        "video_id": video_id,
        "contract_hash": "a" * 64,
        "contract": {
            "film_bible": draft["film_bible"],
            "shots": [
                {**shot, "technique": shot["technique"]}
                for shot in draft["shots"]
            ],
        },
    }
    calls = []

    async def ensure(_conn, **kwargs):
        calls.append(("ensure", kwargs))
        return {
            "video_id": video_id,
            "director_contract_id": director_id,
            "created": True,
        }

    async def load(_conn, _tenant, _video):
        return copy.deepcopy(director)

    async def lock(_conn, **kwargs):
        calls.append(("lock", kwargs["lock_kind"]))
        return {"lock_kind": kwargs["lock_kind"], "created": True}

    async def create(_conn, **kwargs):
        contract = kwargs["raw_scene_contract"]
        calls.append(
            (
                "scene",
                contract["scene_number"],
                len(contract["shot_ids"]),
                bool(kwargs.get("artifact_manifest")),
            )
        )
        return {
            "scene_id": str(uuid4()),
            "scene_number": contract["scene_number"],
            "state": "draft",
            "created": True,
        }

    async def read(_conn, **_kwargs):
        return {
            "current_scene_id": "scene-1",
            "scenes": [
                {"scene_id": "scene-1", "state": "draft", "access": "current"},
                {"scene_id": "scene-2", "state": "draft", "access": "locked"},
            ],
        }

    class Conn:
        async def fetch(self, query, *args):
            assert "FROM custom_film_shots" in query
            return copy.deepcopy(shot_rows)

    monkeypatch.setattr(control, "ensure_synthetic_director_fixture", ensure)
    monkeypatch.setattr(control, "_load_director", load)
    monkeypatch.setattr(control, "approve_film_lock", lock)
    monkeypatch.setattr(control, "create_scene", create)
    monkeypatch.setattr(control, "read_scene_control", read)
    monkeypatch.setattr(
        control,
        "synthetic_scene_artifact_manifest",
        lambda *_args, **_kwargs: {"synthetic": "artifact-proof"},
    )

    result = await control.seed_synthetic_one_scene(
        Conn(),
        tenant_id=tenant_id,
    )
    assert result["provider_calls_started"] is False
    assert result["ledger_writes"] == 0
    assert [call for call in calls if call[0] == "lock"] == [
        ("lock", kind) for kind in control.LOCK_KINDS
    ]
    assert [call for call in calls if call[0] == "scene"] == [
        ("scene", 1, 5, True),
        ("scene", 2, 1, False),
    ]
    access, current = control.derive_scene_access(
        [
            {"id": result["scenes"][0]["scene_id"], "state": "draft"},
            {"id": result["scenes"][1]["scene_id"], "state": "draft"},
        ]
    )
    assert access == ["current", "locked"]
    assert current == result["scenes"][0]["scene_id"]
    assert result["control"]["scenes"][1]["access"] == "locked"


def test_m9_surface_has_quote_but_no_approval_or_provider_execution_seam():
    domain_source = inspect.getsource(control)
    route_source = inspect.getsource(control_routes)
    combined = domain_source + route_source
    for forbidden in (
        "kie_unified",
        "ProductionSingleAttemptTextClient",
        "enqueue_stage",
        "background_tasks",
        "generation_claims",
        "record_ledger_entry",
    ):
        assert forbidden not in combined
    route_paths = [route.path for route in control_routes.router.routes]
    assert any(path.endswith("/operations/quote") for path in route_paths)
    assert not any("approve" in path for path in route_paths)
    main_source = (
        Path(__file__).resolve().parents[2] / "main.py"
    ).read_text()
    assert "CUSTOM_FILM_SCENE_CONTROL_V1" in main_source
    assert "app.include_router(custom_film_scene_control.router)" in main_source


def test_scene_control_migration_has_exact_schema_parity_and_safety_laws():
    root = Path(__file__).resolve().parents[3]
    migration = (
        root / "backend/migrations/137_custom_film_scene_control.sql"
    ).read_text()
    schema = (root / "schema.sql").read_text()
    body = migration.split("BEGIN;\n\n", 1)[1].rsplit("\n\nCOMMIT;", 1)[0] + "\n"
    parity = schema.split(
        "-- CUSTOM_FILM_SCENE_CONTROL_BEGIN\n",
        1,
    )[1].split("-- CUSTOM_FILM_SCENE_CONTROL_END", 1)[0]
    assert parity == body
    for table in (
        "custom_film_film_locks",
        "custom_film_scene_controls",
        "custom_film_scene_events",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in migration
        assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" in migration
        assert f"REVOKE ALL ON {table} FROM anon, authenticated" in migration
    assert "artifact_manifest JSONB NOT NULL DEFAULT '{}'::jsonb" in migration
    assert "Accepted Custom Film scenes are immutable" in migration
    assert "BEFORE UPDATE OR DELETE" in migration
    assert "FOREIGN KEY (tenant_id, director_contract_id, plan_id, video_id)" in migration
    env_example = (root / ".env.example").read_text()
    assert "CUSTOM_FILM_SCENE_CONTROL_V1=false" in env_example
    assert "CUSTOM_FILM_SCENE_STORYBOARD_IMAGE_MAX_CENTS=5" in env_example
