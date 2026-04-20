"""Functional test for Stage 2.2 / Cycle 39: background_tasks RLS consolidation.

Two drift issues fixed here:
  1. Migration 032 shipped a broken RLS policy on background_tasks:
       CREATE POLICY bg_tasks_tenant_read ... USING (tenant_id = auth.uid())
     That compares a tenant_id (UUID on the tenants table) against the
     authenticated user's id — they're never equal in multi-tenant Supabase,
     so the policy silently denies every client read. App works only because
     the backend uses service_role, which bypasses RLS. Migration 043 drops
     that policy and installs the standard memberships-based "Tenant
     isolation" policy that every other tenant-scoped table uses.
  2. schema.sql had TWO background_tasks blocks — the first (correct,
     memberships-based) near the main tables, the second (duplicate of the
     broken migration-032 shape) near the end. Cycle 39 removed the
     duplicate so schema.sql has exactly one definition and one policy.

Three source-audit checks:
  - Migration 043 exists and drops the old policy + creates the memberships one
  - schema.sql has exactly ONE background_tasks table def + one memberships
    policy, not the broken auth.uid() one
  - No file in migrations/ or schema.sql still contains the broken qual
    `tenant_id = auth.uid()` on background_tasks (regression guard)

Runtime verification (policy in prod DB) lives in the deploy step —
Supabase MCP `pg_policies` query.
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


MIGRATION_BASENAME = "043_background_tasks_rls_fix.sql"


def test_migration_file_exists():
    path = _migrations_dir() / MIGRATION_BASENAME
    assert path.exists(), (
        f"Migration {MIGRATION_BASENAME} missing. A revert of Cycle 39 "
        "dropped the file — restore it or prod will still carry the "
        "broken bg_tasks_tenant_read policy."
    )
    print("✅ test_migration_file_exists")


def test_migration_drops_broken_policy_and_installs_correct_one():
    src = (_migrations_dir() / MIGRATION_BASENAME).read_text()
    assert re.search(
        r"DROP\s+POLICY\s+IF\s+EXISTS\s+bg_tasks_tenant_read\s+ON\s+background_tasks",
        src,
        re.IGNORECASE,
    ), "Migration must DROP the broken bg_tasks_tenant_read policy."
    # The new policy uses the memberships pattern that every other tenant
    # table uses. Match loosely so formatting changes don't break the test.
    assert re.search(
        r'CREATE\s+POLICY\s+"Tenant isolation"\s+ON\s+background_tasks\s+FOR\s+ALL\s+TO\s+authenticated',
        src,
        re.IGNORECASE,
    ), "Migration must create the 'Tenant isolation' FOR ALL policy."
    assert re.search(
        r"tenant_id\s+IN\s*\(\s*SELECT[^)]*FROM\s+memberships",
        src,
        re.IGNORECASE | re.DOTALL,
    ), "New policy must use the memberships-based USING clause."
    print("✅ test_migration_drops_broken_policy_and_installs_correct_one")


def test_schema_sql_has_single_background_tasks_definition():
    src = _schema_sql().read_text()
    table_defs = re.findall(
        r"CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+background_tasks\b",
        src,
        re.IGNORECASE,
    )
    assert len(table_defs) == 1, (
        f"schema.sql should have EXACTLY ONE background_tasks CREATE TABLE "
        f"block after Cycle 39, got {len(table_defs)}. The duplicate "
        "migration-032 block was removed; if it's back, someone regenerated "
        "schema.sql from a bad dump."
    )
    print("✅ test_schema_sql_has_single_background_tasks_definition")


def test_schema_sql_has_memberships_policy_not_broken_one():
    src = _schema_sql().read_text()
    # The correct policy must be present
    assert re.search(
        r'CREATE\s+POLICY\s+"Tenant isolation"\s+ON\s+background_tasks',
        src,
        re.IGNORECASE,
    ), "schema.sql missing 'Tenant isolation' policy on background_tasks."
    # The broken policy from migration 032 must NOT be present
    assert not re.search(
        r"CREATE\s+POLICY\s+bg_tasks_tenant_read",
        src,
        re.IGNORECASE,
    ), (
        "schema.sql still has the broken bg_tasks_tenant_read policy. "
        "Delete it — migration 043 is the source of truth now."
    )
    print("✅ test_schema_sql_has_memberships_policy_not_broken_one")


def test_no_file_uses_broken_tenant_id_equals_auth_uid_on_background_tasks():
    """Regression guard. The pattern `tenant_id = auth.uid()` is always
    wrong for this table — catch it if it ever comes back in a new
    migration or schema edit."""
    offenders = []
    # Check schema.sql
    schema_src = _schema_sql().read_text()
    if re.search(
        r"tenant_id\s*=\s*(?:\(\s*SELECT\s+)?auth\.uid\(\)",
        schema_src,
        re.IGNORECASE,
    ):
        # Walk the schema to see if it's near a background_tasks block
        # Cheap proxy: the broken policy sat in the bg_tasks section.
        if "background_tasks" in schema_src.lower():
            # Find the specific pattern near background_tasks
            for m in re.finditer(
                r"background_tasks[\s\S]{0,500}?tenant_id\s*=\s*(?:\(\s*SELECT\s+)?auth\.uid\(\)",
                schema_src,
                re.IGNORECASE,
            ):
                offenders.append(("schema.sql", m.group(0)[:80]))
    # 032 is the historical migration that SHIPPED the bad policy. It's
    # frozen in git — migration 043 drops its policy and installs a fix.
    # Skip it from the regression scan so new offenders stand out.
    HISTORICAL_BROKEN = {"032_background_tasks.sql"}
    for mig in _migrations_dir().glob("*.sql"):
        if mig.name in HISTORICAL_BROKEN:
            continue
        src = mig.read_text()
        # Find CREATE POLICY blocks mentioning background_tasks with the
        # broken qual. A DROP POLICY line doesn't contain a USING clause
        # so this regex won't match drops.
        for m in re.finditer(
            r"CREATE\s+POLICY[\s\S]*?ON\s+background_tasks[\s\S]*?tenant_id\s*=\s*(?:\(\s*SELECT\s+)?auth\.uid\(\)",
            src,
            re.IGNORECASE,
        ):
            offenders.append((mig.name, m.group(0)[:80]))
    assert not offenders, (
        "Broken RLS pattern `tenant_id = auth.uid()` found on "
        f"background_tasks in: {offenders}. This compares tenant_id to "
        "user_id — always false in multi-tenant Supabase. Use the "
        "memberships-based pattern instead."
    )
    print("✅ test_no_file_uses_broken_tenant_id_equals_auth_uid_on_background_tasks")


TESTS = [
    test_migration_file_exists,
    test_migration_drops_broken_policy_and_installs_correct_one,
    test_schema_sql_has_single_background_tasks_definition,
    test_schema_sql_has_memberships_policy_not_broken_one,
    test_no_file_uses_broken_tenant_id_equals_auth_uid_on_background_tasks,
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
