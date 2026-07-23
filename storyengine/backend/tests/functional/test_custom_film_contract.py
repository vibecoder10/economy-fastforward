import asyncio
import copy
import json
from pathlib import Path
from uuid import UUID

import pytest

import custom_film_contract as contract
from models import VideoDetail


def _profiles():
    rows = {
        "bilingual_character_animation": {
            "render_mode": "coverage",
            "script_profile": "neutral_v1",
            "visual_profile": "neutral_v1",
            "image_density": {"mode": "dialogue_shape", "target_per_minute": 8},
            "animation": {"enabled": True, "mode": "grok_native"},
            "language": {"mode": "bilingual"},
            "dubbing": {"enabled": True, "mode": "speech_to_speech"},
            "segmentation": {"mode": "speaker_turn"},
            "camera": {"mode": "dialogue_coverage"},
            "quality_laws": [
                "character_continuity",
                "lip_sync",
                "translation_fidelity",
            ],
            "image_source": "generate",
        },
        "simple_language_animation": {
            "render_mode": "coverage",
            "script_profile": "neutral_v1",
            "visual_profile": "neutral_v1",
            "image_density": {"mode": "dialogue_shape", "target_per_minute": 8},
            "animation": {"enabled": True, "mode": "grok_native"},
            "language": {"mode": "simple_single_language"},
            "dubbing": {"enabled": False, "mode": "none"},
            "segmentation": {"mode": "speaker_turn"},
            "camera": {"mode": "dialogue_coverage"},
            "quality_laws": [
                "character_continuity",
                "clear_language",
                "lip_sync",
            ],
            "image_source": "generate",
        },
        "photo_documentary": {
            "render_mode": "static_docu",
            "script_profile": "neutral_v1",
            "visual_profile": "neutral_v1",
            "image_density": {"mode": "per_item", "target": 3, "minimum": 2},
            "animation": {"enabled": False, "mode": "ken_burns"},
            "language": {"mode": "narrator"},
            "dubbing": {"enabled": False, "mode": "none"},
            "segmentation": {"mode": "item"},
            "camera": {"mode": "three_complementary_views"},
            "quality_laws": [
                "verified_reference",
                "variant_accuracy",
                "caption_grounding",
            ],
            "image_source": "generate",
        },
        "animated_investigative_documentary": {
            "render_mode": "coverage",
            "script_profile": "power_doctrine_v2",
            "visual_profile": "cinematic_illustration",
            "image_density": {"mode": "visual_cue", "target_per_minute": 10},
            "animation": {"enabled": True, "mode": "grok_native"},
            "language": {"mode": "narrator"},
            "dubbing": {"enabled": False, "mode": "none"},
            "segmentation": {"mode": "visual_cue"},
            "camera": {"mode": "investigative_coverage"},
            "quality_laws": [
                "source_grounding",
                "visual_cue_fidelity",
                "motion_prompt_presence",
            ],
            "image_source": "generate",
        },
    }
    return [
        {
            "id": style_id,
            "version": 1,
            "label": style_id,
            "description": style_id,
            "knobs": knobs,
            "estimate": {},
            "requires_byok": True,
            "sort": index,
        }
        for index, (style_id, knobs) in enumerate(rows.items())
    ]


@pytest.fixture
def manifest():
    return contract.build_capability_manifest(_profiles())


def _section(manifest, style_id, *, section_id, weight="1", purpose="Explain"):
    return {
        "section_id": section_id,
        "role": "explanation",
        "purpose": purpose,
        "duration_weight": weight,
        "knobs": copy.deepcopy(manifest.profiles[style_id]["knobs"]),
        "estimated_media": {
            "still_images": 2,
            "animation_clips": 1,
            "voice_tracks": 1,
            "duration_seconds": 30,
        },
    }


def _plan(manifest):
    return {
        "compatibility_version": manifest.version,
        "sections": [
            _section(
                manifest,
                "photo_documentary",
                section_id="11111111-1111-4111-8111-111111111111",
                weight="1",
                purpose="Establish the evidence",
            ),
            _section(
                manifest,
                "animated_investigative_documentary",
                section_id="22222222-2222-4222-8222-222222222222",
                weight="2",
                purpose="Explain the mechanism",
            ),
        ],
    }


def _recipe(manifest, style_ids=("photo_documentary", "animated_investigative_documentary")):
    return {
        "compatibility_version": manifest.version,
        "sections": [
            {
                "role": "evidence" if index == 0 else "explanation",
                "duration_weight": index + 1,
                "knobs": copy.deepcopy(manifest.profiles[style_id]["knobs"]),
            }
            for index, style_id in enumerate(style_ids)
        ],
    }


def test_manifest_is_derived_from_exactly_four_public_profiles(manifest):
    assert set(manifest.profiles) == contract.PUBLIC_PRODUCTION_STYLE_IDS
    assert manifest.version.startswith("public-profile-semantic-v1:")
    assert manifest.allowed_values["render_mode"][json.dumps("coverage")] == (
        "animated_investigative_documentary",
        "bilingual_character_animation",
        "simple_language_animation",
    )
    with pytest.raises(contract.CustomFilmContractError, match="exactly the four"):
        contract.build_capability_manifest(_profiles()[:-1])
    funded = _profiles()
    funded[0]["requires_byok"] = False
    with pytest.raises(contract.CustomFilmContractError, match="must require BYOK"):
        contract.build_capability_manifest(funded)


def test_valid_plan_normalizes_weights_provenance_and_stable_section_ids(manifest):
    normalized = contract.normalize_plan(_plan(manifest), manifest)
    assert [s["duration_units"] for s in normalized["sections"]] == [333333, 666667]
    assert sum(s["duration_units"] for s in normalized["sections"]) == 1_000_000
    assert normalized["sections"][0]["section_id"] == (
        "11111111-1111-4111-8111-111111111111"
    )
    assert normalized["sections"][0]["provenance"]["render_mode"] == [
        "photo_documentary"
    ]
    assert normalized["sections"][1]["estimated_media"]["animation_clips"] == 1

    underflow = _plan(manifest)
    underflow["sections"][0]["duration_weight"] = "1e-20"
    underflow["sections"][1]["duration_weight"] = "1"
    tiny = contract.normalize_plan(underflow, manifest)
    assert [section["duration_units"] for section in tiny["sections"]] == [
        1,
        999999,
    ]


def test_unknown_fields_values_and_incompatible_combinations_fail_closed(manifest):
    unknown_field = _plan(manifest)
    unknown_field["sections"][0]["provider_id"] = "hidden-provider"
    with pytest.raises(contract.CustomFilmContractError, match="extra_forbidden"):
        contract.normalize_plan(unknown_field, manifest)

    unknown_value = _plan(manifest)
    unknown_value["sections"][0]["knobs"]["render_mode"] = "invented"
    with pytest.raises(contract.CustomFilmContractError, match="Unsupported render_mode"):
        contract.normalize_plan(unknown_value, manifest)

    incompatible = _plan(manifest)
    incompatible["sections"][0]["knobs"]["animation"] = copy.deepcopy(
        manifest.profiles["animated_investigative_documentary"]["knobs"]["animation"]
    )
    with pytest.raises(contract.CustomFilmContractError, match="Incompatible"):
        contract.normalize_plan(incompatible, manifest)

    bad_media = _plan(manifest)
    bad_media["sections"][0]["estimated_media"]["provider"] = "kie"
    with pytest.raises(contract.CustomFilmContractError, match="extra_forbidden"):
        contract.normalize_plan(bad_media, manifest)


def test_semantic_rules_allow_safe_cross_profile_component_mix(manifest):
    visual_cue_simple = _plan(manifest)
    visual_cue_simple["sections"] = [visual_cue_simple["sections"][1]]
    visual_cue_simple["sections"][0]["knobs"]["language"] = copy.deepcopy(
        manifest.profiles["simple_language_animation"]["knobs"]["language"]
    )
    mixed = contract.normalize_plan(visual_cue_simple, manifest)
    assert mixed["sections"][0]["provenance"]["language"] == [
        "simple_language_animation"
    ]
    assert mixed["sections"][0]["provenance"]["image_density"] == [
        "animated_investigative_documentary"
    ]

    static_with_independent_engines = _plan(manifest)
    static_with_independent_engines["sections"] = [
        static_with_independent_engines["sections"][0]
    ]
    knobs = static_with_independent_engines["sections"][0]["knobs"]
    knobs["script_profile"] = copy.deepcopy(
        manifest.profiles["animated_investigative_documentary"]["knobs"][
            "script_profile"
        ]
    )
    knobs["visual_profile"] = copy.deepcopy(
        manifest.profiles["animated_investigative_documentary"]["knobs"][
            "visual_profile"
        ]
    )
    swapped = contract.normalize_plan(static_with_independent_engines, manifest)
    assert swapped["sections"][0]["provenance"]["script_profile"] == [
        "animated_investigative_documentary"
    ]
    assert swapped["sections"][0]["knobs"]["render_mode"] == "static_docu"

    impossible_dialogue = _plan(manifest)
    impossible_dialogue["sections"] = [impossible_dialogue["sections"][1]]
    impossible_dialogue["sections"][0]["knobs"]["image_density"] = copy.deepcopy(
        manifest.profiles["bilingual_character_animation"]["knobs"]["image_density"]
    )
    with pytest.raises(contract.CustomFilmContractError, match="dialogue"):
        contract.normalize_plan(impossible_dialogue, manifest)


def test_plan_hash_is_deterministic_and_any_plan_edit_changes_it(manifest):
    first = contract.normalize_plan(_plan(manifest), manifest)
    reordered_json = json.loads(json.dumps(_plan(manifest), sort_keys=True))
    second = contract.normalize_plan(reordered_json, manifest)
    assert contract.plan_hash(first) == contract.plan_hash(second)

    edited = _plan(manifest)
    edited["sections"][0]["purpose"] = "Different evidence"
    assert contract.plan_hash(first) != contract.plan_hash(
        contract.normalize_plan(edited, manifest)
    )
    assert contract.approval_binding_hash("a" * 64, {"minutes": 5}) != (
        contract.approval_binding_hash("a" * 64, {"minutes": 6})
    )


def test_recipe_is_topic_free_and_signature_normalizes_proportions(manifest):
    first = _recipe(manifest)
    second = _recipe(manifest)
    second["sections"][0]["duration_weight"] = 2
    second["sections"][1]["duration_weight"] = 4
    normalized = contract.normalize_recipe(first, manifest)
    assert "purpose" not in json.dumps(normalized)
    assert contract.recipe_signature(normalized) == contract.recipe_signature(
        contract.normalize_recipe(second, manifest)
    )

    leaked = _recipe(manifest)
    leaked["title"] = "The source video's topic"
    with pytest.raises(contract.CustomFilmContractError, match="extra_forbidden"):
        contract.normalize_recipe(leaked, manifest)


def test_public_profile_clone_is_duplicate_regardless_of_single_section_role(
    monkeypatch, manifest
):
    async def should_not_read_saved(*_args):
        raise AssertionError("public clone must be caught before tenant lookup")

    monkeypatch.setattr(contract, "fetch_one", should_not_read_saved)
    for role in ("full_film", "opening", "closing"):
        normalized = contract.normalize_recipe(
            {
                "compatibility_version": manifest.version,
                "sections": [
                    {
                        "role": role,
                        "duration_weight": 1,
                        "knobs": manifest.profiles["photo_documentary"]["knobs"],
                    }
                ],
            },
            manifest,
        )
        assert asyncio.run(
            contract.find_recipe_duplicate("tenant-a", normalized, manifest)
        ) == ("public_profile", "photo_documentary")


def test_saved_duplicate_lookup_is_tenant_scoped(monkeypatch, manifest):
    seen = []

    async def fake_fetch(query, *args):
        seen.append((query, args))
        return {"id": "saved-a"}

    monkeypatch.setattr(contract, "fetch_one", fake_fetch)
    normalized = contract.normalize_recipe(_recipe(manifest), manifest)
    assert asyncio.run(
        contract.find_recipe_duplicate("tenant-a", normalized, manifest)
    ) == ("saved_recipe", "saved-a")
    assert "tenant_id = $1" in seen[0][0]
    assert seen[0][1][0] == "tenant-a"


def test_legacy_video_model_preserves_old_key_set_while_custom_plan_serializes():
    payload = VideoDetail(id="legacy-video").model_dump()
    assert not any(key.startswith("custom_film_") for key in payload)
    # Prove this is field-specific, not a broad exclude-none change.
    assert payload["production_style_snapshot"] is None
    assert payload["video_title"] is None

    custom = VideoDetail(
        id="custom-video",
        custom_film_plan_id="plan-a",
        custom_film_plan_revision=1,
        custom_film_plan_hash="a" * 64,
        custom_film_quote_inputs_hash="b" * 64,
        custom_film_plan={"sections": []},
    ).model_dump()
    assert custom["custom_film_plan_id"] == "plan-a"
    assert custom["custom_film_plan"] == {"sections": []}


def test_load_current_plan_is_tenant_scoped_and_serializes_rows(monkeypatch):
    queries = []

    async def fake_one(query, *args):
        queries.append((query, args))
        return {
            "id": UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
            "tenant_id": "tenant-a",
            "video_id": UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
            "revision": 2,
            "compatibility_version": "v1",
            "plan": '{"sections":[]}',
            "plan_hash": "a" * 64,
            "quote_inputs": "{}",
            "quote_inputs_hash": "b" * 64,
            "approval_hash": None,
            "approved_at": None,
            "created_at": "now",
        }

    async def fake_all(query, *args):
        queries.append((query, args))
        return [
            {
                "section_id": UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc"),
                "order_index": 0,
                "role": "opening",
                "purpose": "Open",
                "duration_units": 1_000_000,
                "knobs": "{}",
                "provenance": "{}",
                "estimated_media": "{}",
            }
        ]

    monkeypatch.setattr(contract, "fetch_one", fake_one)
    monkeypatch.setattr(contract, "fetch_all", fake_all)
    result = asyncio.run(contract.load_current_plan("tenant-a", "video-a"))
    assert result["revision"] == 2
    assert result["sections"][0]["section_id"].startswith("cccc")
    assert all("tenant_id = $1" in query for query, _args in queries)
    assert all(args[0] == "tenant-a" for _query, args in queries)


def test_create_plan_revision_is_atomic_tenant_scoped_and_clears_approval(
    monkeypatch, manifest
):
    calls = []

    class AsyncContext:
        def __init__(self, value=None):
            self.value = value

        async def __aenter__(self):
            return self.value

        async def __aexit__(self, *_args):
            return False

    class FakeConnection:
        def transaction(self):
            return AsyncContext()

        async def fetchrow(self, query, *args):
            calls.append(("fetchrow", query, args))
            return {"id": "video-a"}

        async def fetchval(self, query, *args):
            calls.append(("fetchval", query, args))
            return 3

        async def execute(self, query, *args):
            calls.append(("execute", query, args))
            return "OK"

    class FakePool:
        def acquire(self):
            return AsyncContext(FakeConnection())

    async def fake_pool():
        return FakePool()

    async def fake_load(tenant_id, video_id):
        return {"tenant_id": tenant_id, "video_id": video_id, "revision": 3}

    monkeypatch.setattr(contract, "get_pool", fake_pool)
    monkeypatch.setattr(contract, "load_current_plan", fake_load)
    result = asyncio.run(
        contract.create_plan_revision(
            "tenant-a",
            "video-a",
            _plan(manifest),
            manifest,
            quote_inputs={"duration_minutes": 5},
        )
    )
    assert result["revision"] == 3
    lock = next(call for call in calls if "FOR UPDATE" in call[1])
    assert lock[2] == ("tenant-a", "video-a")
    section_inserts = [
        call for call in calls if "INSERT INTO custom_film_sections" in call[1]
    ]
    assert len(section_inserts) == 2
    assert all(call[2][0] == "tenant-a" and call[2][2] == "video-a" for call in section_inserts)
    pointer_update = next(
        call for call in calls if "UPDATE videos" in call[1]
    )
    assert "custom_film_approval_hash = NULL" in pointer_update[1]
    assert pointer_update[2][0:2] == ("tenant-a", "video-a")


def test_approve_current_plan_locks_and_binds_exact_plan_quote(monkeypatch):
    quote = {"totals": {"estimated_cost": 4.2}}
    digest = "a" * 64
    binding = contract.approval_binding_hash(digest, quote)
    calls = []

    class AsyncContext:
        def __init__(self, value=None):
            self.value = value

        async def __aenter__(self):
            return self.value

        async def __aexit__(self, *_args):
            return False

    class FakeConnection:
        def transaction(self):
            return AsyncContext()

        async def fetchrow(self, query, *args):
            calls.append(("fetchrow", query, args))
            return {
                "custom_film_plan_id": "plan-a",
                "custom_film_plan_hash": digest,
                "custom_film_quote_inputs_hash": contract.canonical_hash(quote),
                "custom_film_approval_hash": None,
                "plan_hash": digest,
                "quote_inputs": json.dumps(quote),
                "quote_inputs_hash": contract.canonical_hash(quote),
                "approval_hash": None,
            }

        async def execute(self, query, *args):
            calls.append(("execute", query, args))
            return "UPDATE 1"

    class FakePool:
        def acquire(self):
            return AsyncContext(FakeConnection())

    async def fake_pool():
        return FakePool()

    async def fake_load(*_args):
        return {"approval_hash": binding}

    monkeypatch.setattr(contract, "get_pool", fake_pool)
    monkeypatch.setattr(contract, "load_current_plan", fake_load)
    approved = asyncio.run(
        contract.approve_current_plan("tenant-a", "video-a", binding)
    )
    assert approved["approval_hash"] == binding
    assert "FOR UPDATE OF v, p" in calls[0][1]
    writes = [call for call in calls if call[0] == "execute"]
    assert len(writes) == 2
    assert all(call[2][-1] == binding for call in writes)

    with pytest.raises(contract.CustomFilmContractError, match="changed"):
        asyncio.run(
            contract.approve_current_plan("tenant-a", "video-a", "b" * 64)
        )


def test_migration_122_and_fresh_schema_match_security_and_scene_foundation():
    root = Path(__file__).resolve().parents[3]
    migration = (root / "backend" / "migrations" / "122_custom_film_contract.sql").read_text()
    schema = (root / "schema.sql").read_text()
    for table in (
        "custom_film_recipes",
        "custom_film_plans",
        "custom_film_sections",
        "custom_film_section_scenes",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in migration
        assert f"CREATE TABLE IF NOT EXISTS {table}" in schema
        assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" in migration
        assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" in schema
        assert f"REVOKE ALL ON {table} FROM anon" in migration
        assert f"REVOKE ALL ON {table} FROM authenticated" in migration
        assert f"REVOKE ALL ON {table} FROM authenticated" in schema
    assert "DEFERRABLE INITIALLY DEFERRED" in migration
    assert "ON DELETE SET NULL" not in migration
    assert "scripts_tenant_video_id_uidx" in migration
    assert "custom_film_sections(tenant_id, plan_id, video_id, section_id)" in migration
    assert "protect_custom_film_immutable_contract" in migration
    migration_numbers = [
        int(path.name.split("_", 1)[0])
        for path in (root / "backend" / "migrations").glob("[0-9][0-9][0-9]_*.sql")
    ]
    # M2-4A's envelope, B1 restart progress, and B2a provider-operation
    # reconciliation journal are additive migrations.
    assert max(migration_numbers) == 125
