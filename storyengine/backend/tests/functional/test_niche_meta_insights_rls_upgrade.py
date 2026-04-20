"""Functional test for Cycle 40 / Stage 2.2 follow-up.

Migration 040 shipped niche_meta_insights with a GUC-only RLS policy:
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
Every other tenant-scoped table in this app uses the combined pattern:
    (tenant_id IN (memberships join) OR tenant_id = current_setting(...))
Migration 044 upgrades niche_meta_insights to match — both for internal
consistency and for defense-in-depth (an authenticated client session
where app.tenant_id isn't set can match via the memberships path).

Source-audit tests:
  1. Migration 044 exists
  2. Migration drops old policy + creates the combined one
  3. Migration specifies FOR ALL TO authenticated (other tables use this)
  4. schema.sql policy on niche_meta_insights uses the combined pattern
     (memberships clause is present, NOT GUC-only anymore)

Runtime prod verification happens via Supabase MCP pg_policies query.
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _storyengine_dir() -> Path:
    return Path(__file__).resolve().parents[3]


def _migrations_dir() -> Path:
    return _storyengine_dir() / "backend" / "migrations"


def _schema_sql() -> Path:
    return _storyengine_dir() / "schema.sql"


MIGRATION_BASENAME = "044_niche_meta_insights_rls_upgrade.sql"


def test_migration_file_exists():
    path = _migrations_dir() / MIGRATION_BASENAME
    assert path.exists(), (
        f"Migration {MIGRATION_BASENAME} missing. A revert of Cycle 40 "
        "dropped the file — restore it or prod will drift back to the "
        "GUC-only policy."
    )
    print("✅ test_migration_file_exists")


def test_migration_drops_old_policy_and_creates_combined():
    src = (_migrations_dir() / MIGRATION_BASENAME).read_text()
    assert re.search(
        r"DROP\s+POLICY\s+IF\s+EXISTS\s+niche_meta_insights_tenant_isolation",
        src,
        re.IGNORECASE,
    ), "Migration must DROP the old niche_meta_insights_tenant_isolation policy."
    assert re.search(
        r"CREATE\s+POLICY\s+niche_meta_insights_tenant_isolation\s+ON\s+niche_meta_insights",
        src,
        re.IGNORECASE,
    ), "Migration must CREATE the replacement policy (same name)."
    # Must include the memberships path
    assert re.search(
        r"tenant_id\s+IN\s*\(\s*SELECT[^)]*FROM\s+memberships",
        src,
        re.IGNORECASE | re.DOTALL,
    ), "New policy must include the memberships-based USING clause."
    # Must include the GUC path (still kept for server-side)
    assert re.search(
        r"current_setting\(\s*'app\.tenant_id'",
        src,
        re.IGNORECASE,
    ), "New policy must keep the app.tenant_id GUC fallback (server code uses it)."
    # Must have OR between them
    assert re.search(
        r"memberships[\s\S]*?\bOR\b[\s\S]*?current_setting",
        src,
        re.IGNORECASE,
    ), "Memberships and GUC clauses must be combined with OR."
    print("✅ test_migration_drops_old_policy_and_creates_combined")


def test_migration_targets_authenticated_role():
    src = (_migrations_dir() / MIGRATION_BASENAME).read_text()
    assert re.search(
        r"FOR\s+ALL\s+TO\s+authenticated",
        src,
        re.IGNORECASE,
    ), (
        "Policy must target the `authenticated` role explicitly to match "
        "the pattern used on every other tenant-scoped table."
    )
    print("✅ test_migration_targets_authenticated_role")


def test_schema_sql_policy_has_combined_pattern():
    src = _schema_sql().read_text()
    # Find the niche_meta_insights policy block
    m = re.search(
        r"CREATE\s+POLICY\s+niche_meta_insights_tenant_isolation\s+ON\s+niche_meta_insights[\s\S]*?;",
        src,
        re.IGNORECASE,
    )
    assert m, "schema.sql missing niche_meta_insights_tenant_isolation policy."
    block = m.group(0)
    assert re.search(r"memberships", block, re.IGNORECASE), (
        "schema.sql policy on niche_meta_insights still missing memberships "
        "clause. After Cycle 40 it must use the combined pattern."
    )
    assert re.search(r"current_setting\(\s*'app\.tenant_id'", block, re.IGNORECASE), (
        "schema.sql policy on niche_meta_insights must keep the GUC fallback."
    )
    assert re.search(r"FOR\s+ALL\s+TO\s+authenticated", block, re.IGNORECASE), (
        "schema.sql policy on niche_meta_insights must target authenticated role."
    )
    print("✅ test_schema_sql_policy_has_combined_pattern")


TESTS = [
    test_migration_file_exists,
    test_migration_drops_old_policy_and_creates_combined,
    test_migration_targets_authenticated_role,
    test_schema_sql_policy_has_combined_pattern,
]


def main() -> int:
    failed = 0
    for t in TESTS:
        try:
            t()
        except AssertionError as e:
            print(f"❌ {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"❌ {t.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
