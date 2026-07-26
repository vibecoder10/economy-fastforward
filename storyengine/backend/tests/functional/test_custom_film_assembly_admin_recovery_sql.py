"""Static contract tests for migration 133's privileged recovery lane.

The migration is intentionally not exercised against production by this test.
These checks pin the security boundary, mutation surface, and schema parity so
later edits cannot quietly turn a one-time admin repair into a general retry.
"""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[3]
MIGRATION = (
    ROOT / "backend/migrations/133_custom_film_assembly_admin_recovery.sql"
).read_text()
SCHEMA = (ROOT / "schema.sql").read_text()
SCHEMA_BEGIN = "-- CUSTOM_FILM_ASSEMBLY_ADMIN_RECOVERY_BEGIN\n"
SCHEMA_END = "-- CUSTOM_FILM_ASSEMBLY_ADMIN_RECOVERY_END"


def _migration_body() -> str:
    body = MIGRATION.removeprefix(
        "-- Audited, one-time recovery for an assembly that product code incorrectly\n"
        "-- classified as terminal. Normal terminal assemblies remain immutable.\n"
        "BEGIN;\n\n"
    )
    return body.removesuffix("\nCOMMIT;\n")


def test_schema_sql_is_exact_migration_133_parity():
    assert SCHEMA.count(SCHEMA_BEGIN) == 1
    assert SCHEMA.count(SCHEMA_END) == 1
    parity = SCHEMA.split(SCHEMA_BEGIN, 1)[1].split(SCHEMA_END, 1)[0]
    assert parity == _migration_body()


def test_recovery_is_privileged_one_time_and_audited():
    assert "SECURITY DEFINER\nSTRICT\nSET search_path = pg_catalog, public" in MIGRATION
    assert (
        "REVOKE ALL ON FUNCTION recover_custom_film_assembly_misclassification("
        in MIGRATION
    )
    assert ") FROM PUBLIC, anon, authenticated;" in MIGRATION
    assert "UNIQUE (tenant_id, video_id, runtime_hash)" in MIGRATION
    assert "transaction_id = txid_current()" in MIGRATION
    assert "requested_by, transaction_id" in MIGRATION
    assert "session_user, txid_current()" in MIGRATION
    assert "Custom Film assembly recovery audit is immutable" in MIGRATION
    assert "BEFORE UPDATE OR DELETE ON custom_film_assembly_recoveries" in MIGRATION
    assert "ON CONFLICT" not in MIGRATION


def test_global_terminal_immutability_has_only_the_audited_exception():
    assert (
        "OLD.state = 'terminal_failed' AND NEW.state = 'retryable_failed'"
        in MIGRATION
    )
    assert "AND NOT authorized_terminal_recovery" in MIGRATION
    assert "Custom Film terminal assembly is immutable" in MIGRATION
    assert "FROM public.custom_film_assembly_recoveries recovery" in MIGRATION
    assert "recovery.transaction_id = txid_current()" in MIGRATION
    assert "DISABLE TRIGGER" not in MIGRATION
    assert "session_replication_role" not in MIGRATION
    assert "DELETE FROM custom_film_assemblies" not in MIGRATION


def test_admin_function_locks_and_rechecks_paid_runtime_law():
    required = (
        "current_setting('transaction_isolation') <> 'serializable'",
        "pg_advisory_xact_lock",
        "FROM public.background_tasks",
        "FROM public.videos",
        "FROM public.custom_film_assemblies",
        "FROM public.custom_film_provider_operations",
        "FROM public.generation_ledger",
        "FROM public.generation_claims",
        "FOR UPDATE",
        "FOR SHARE",
        "task_row.status <> 'failed'",
        "task_row.attempt <> p_expected_task_attempt",
        "p_expected_completed_stage_count",
        "task_row.runtime_progress->'in_flight' <> 'null'::jsonb",
        "NOT LIKE '%:quality'",
        "'custom-film-cumulative-authority-v1'",
        "'creator_exact_cumulative_approval'",
        "'upload_authorized' <> 'false'",
        "'publication_authorized' <> 'false'",
        "provider_completed <> p_expected_provider_operation_count",
        "ledger_cost IS DISTINCT FROM p_expected_ledger_cost",
        "claims_count <> 0",
        "active_count <> 0",
    )
    for value in required:
        assert value in MIGRATION


def test_exact_failure_fix_manifest_and_storage_identity_are_required():
    required = (
        "p_expected_task_error_sha256",
        "p_expected_failure_detail_sha256",
        "p_fixed_by_commit !~ '^[0-9a-f]{40}$'",
        "assembly_row.state <> 'terminal_failed'",
        "assembly_row.manifest_version <> p_manifest_version",
        "assembly_row.manifest_hash <> p_manifest_hash",
        "assembly_row.manifest->>'render_engine' <> p_render_engine",
        "assembly_row.manifest->>'max_spend'",
        "assembly_row.storage_path <> (",
        "assembly_row.progress <> jsonb_build_object(",
        "'phase', 'terminal_failed'",
        "assembly_row.retry_count <> p_expected_retry_count",
        "assembly_row.artifact_sha256 IS NOT NULL",
        "assembly_row.artifact_probe IS NOT NULL",
        "assembly_row.final_video_url IS NOT NULL",
        "assembly_row.rendered_at IS NOT NULL",
        "assembly_row.uploaded_at IS NOT NULL",
        "assembly_row.finalized_at IS NOT NULL",
    )
    for value in required:
        assert value in MIGRATION


def test_recovery_updates_only_recovery_fields_and_requires_one_row():
    match = re.search(
        r"UPDATE public\.custom_film_assemblies\s+SET (?P<set>.*?)"
        r"\s+WHERE tenant_id = p_tenant_id",
        MIGRATION,
        re.DOTALL,
    )
    assert match
    assigned = set(re.findall(r"^\s*([a-z_]+)\s*=", match.group("set"), re.MULTILINE))
    assert assigned == {
        "state",
        "failure_kind",
        "failure_detail",
        "progress",
        "updated_at",
    }
    assert "GET DIAGNOSTICS updated_count = ROW_COUNT" in MIGRATION
    assert "updated_count <> 1" in MIGRATION
    assert "SET state = 'retryable_failed'" in MIGRATION
    assert "'phase', 'retryable_failed'" in MIGRATION
