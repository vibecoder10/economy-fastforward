"""Static schema-law tests for migration 135's director loop.

These tests do not apply a migration or touch a live database.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MIGRATION = (
    ROOT / "backend/migrations/135_custom_film_director_loop.sql"
).read_text()
SCHEMA = (ROOT / "schema.sql").read_text()
SCHEMA_BEGIN = "-- CUSTOM_FILM_DIRECTOR_LOOP_BEGIN\n"
SCHEMA_END = "-- CUSTOM_FILM_DIRECTOR_LOOP_END"


def _migration_body() -> str:
    return MIGRATION.split("BEGIN;\n\n", 1)[1].rsplit("\n\nCOMMIT;", 1)[0] + "\n"


def test_fresh_schema_is_exact_migration_135_parity():
    assert SCHEMA.count(SCHEMA_BEGIN) == 1
    assert SCHEMA.count(SCHEMA_END) == 1
    parity = SCHEMA.split(SCHEMA_BEGIN, 1)[1].split(SCHEMA_END, 1)[0]
    assert parity == _migration_body()


def test_director_schema_normalizes_all_review_and_admission_boundaries():
    for table in (
        "custom_film_director_contracts",
        "custom_film_shots",
        "custom_film_lock_references",
        "custom_film_storyboard_reviews",
        "custom_film_visual_verifications",
        "custom_film_stage_authorities",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in MIGRATION
        assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" in MIGRATION
        assert f"REVOKE ALL ON {table} FROM anon, authenticated" in MIGRATION
    assert "REFERENCES video_characters(tenant_id, id)" in MIGRATION
    assert "REFERENCES video_environments(tenant_id, id)" in MIGRATION
    assert (
        "REFERENCES custom_film_shots(tenant_id, director_contract_id, shot_id)"
        in MIGRATION
    )
    assert "reference_gate_hash" in MIGRATION
    assert "storyboard_gate_hash" in MIGRATION
    assert "clip_artifact_id" in MIGRATION


def test_director_evidence_is_append_only_and_authority_consumes_once():
    append_only = (
        "'custom_film_director_contracts'",
        "'custom_film_shots'",
        "'custom_film_lock_references'",
        "'custom_film_storyboard_reviews'",
        "'custom_film_visual_verifications'",
    )
    for table in append_only:
        assert table in MIGRATION
    assert "BEFORE UPDATE OR DELETE" in MIGRATION
    assert "protect_custom_film_director_append_only()" in MIGRATION
    assert "OLD.consumed_at IS NOT NULL" in MIGRATION
    assert "NEW.consumed_at IS NULL" in MIGRATION
    assert "Custom Film stage authority is immutable" in MIGRATION
    assert "Custom Film stage authorities cannot be deleted" in MIGRATION


def test_stage_authority_lists_every_profile_independent_spend_boundary():
    for stage in (
        "'script_director'",
        "'storyboards'",
        "'final_pictures'",
        "'animation_voice'",
        "'assembly'",
    ):
        assert stage in MIGRATION
    assert "prior_cumulative_cents" in MIGRATION
    assert "approved_cumulative_cents" in MIGRATION
    assert "bill_of_materials JSONB NOT NULL" in MIGRATION
    assert "approval_hash TEXT NOT NULL" in MIGRATION
    assert "stage_binding_hash TEXT NOT NULL" in MIGRATION
    assert "stage = 'script_director' AND director_contract_id IS NULL" in MIGRATION
