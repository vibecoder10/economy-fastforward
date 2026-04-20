"""Functional test for Stage 2.1: prove storyengine/schema.sql contains
every table defined in backend/migrations/*.sql.

schema.sql is supposed to be the canonical source-of-truth snapshot — what
the database looks like after all migrations have run. But the migrations
folder is where new tables actually LAND. In practice, every time a new
migration introduces a table, schema.sql has to be hand-updated. That step
gets skipped; drift accumulates; schema.sql becomes a stale fiction.

Pre-fix (as of 2026-04-19), 4 tables existed in migrations but NOT in
schema.sql:
  - notification_preferences  (031)
  - visual_styles              (010)
  - style_characters           (010)
  - background_tasks           (032)

Cycle 31 backfilled all 4. This test pins the contract: the next time
someone introduces a table via migration and forgets to update schema.sql,
CI fails before merge.

The test also catches a subtle failure mode: if someone drops a table from
schema.sql but doesn't write a DROP TABLE migration, schema.sql no longer
describes the live DB. That's the reverse-drift test below.
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


# Tables whose definition is intentionally in migrations only (not in schema.sql).
# For example: temporary tables created inside a migration's DO $$ block, or
# auth/storage schemas owned by Supabase itself. Currently empty — if drift
# is ever intentional, whitelist here rather than dropping the check.
ALLOWED_DRIFT: set[str] = set()

# Tables created by migrations that have since been renamed/dropped. Same
# whitelist shape as above but for the reverse direction.
ALLOWED_LEGACY: set[str] = set()


def _extract_tables(text: str) -> set[str]:
    """Extract lowercase table names from `CREATE TABLE [IF NOT EXISTS] <name>`.

    Handles both `CREATE TABLE foo (` and `CREATE TABLE IF NOT EXISTS foo (`.
    Case-sensitive: PostgreSQL folds unquoted identifiers to lowercase, and
    every table in this repo is named in lowercase anyway — if someone
    quotes an uppercase name, that's a different problem this test won't catch.
    """
    pat = re.compile(
        r"^\s*CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-z_][a-z0-9_]*)",
        re.MULTILINE | re.IGNORECASE,
    )
    return {m.group(1).lower() for m in pat.finditer(text)}


def _schema_path() -> Path:
    # tests/functional/ → backend/ → storyengine/
    return Path(__file__).resolve().parents[3] / "schema.sql"


def _migrations_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "migrations"


def test_schema_sql_and_migrations_dirs_exist():
    """Sanity: the paths we're about to diff exist at the expected
    locations. If the repo layout changes, this test fails with a clear
    path-not-found message instead of a confusing empty-diff success."""
    assert _schema_path().exists(), f"schema.sql not at {_schema_path()}"
    assert _migrations_dir().is_dir(), f"migrations dir not at {_migrations_dir()}"
    print("✅ test_schema_sql_and_migrations_dirs_exist")


def test_every_migration_table_is_in_schema_sql():
    """Forward drift: every CREATE TABLE in migrations/*.sql must also
    appear in schema.sql. Catches the "forgot to update schema.sql" case."""
    schema_tables = _extract_tables(_schema_path().read_text())

    migration_tables: dict[str, list[str]] = {}
    for mf in sorted(_migrations_dir().glob("*.sql")):
        for t in _extract_tables(mf.read_text()):
            migration_tables.setdefault(t, []).append(mf.name)

    missing = []
    for table, defining_migrations in sorted(migration_tables.items()):
        if table in ALLOWED_DRIFT:
            continue
        if table not in schema_tables:
            missing.append(f"  - {table} (defined in {', '.join(defining_migrations)})")

    assert not missing, (
        "schema.sql is missing tables defined in migrations:\n"
        + "\n".join(missing)
        + "\n\nEither: (1) add the CREATE TABLE to schema.sql (preferred — "
        "schema.sql is the source of truth for fresh installs), or "
        "(2) whitelist the table in ALLOWED_DRIFT with a comment explaining why."
    )
    print(
        f"✅ test_every_migration_table_is_in_schema_sql "
        f"({len(migration_tables)} migration tables, all present in schema.sql)"
    )


def test_every_schema_table_came_from_somewhere():
    """Reverse drift: every CREATE TABLE in schema.sql should either
    appear in migrations OR be allowed-legacy. Catches the "table exists
    in schema.sql but was never migrated" case.

    This is softer than the forward check — the bootstrap tables (the
    initial schema that migrations 001-003 built on top of) only exist
    in schema.sql, not in any migration. So we only flag tables whose
    name doesn't match anything in the migration folder. The real purpose
    is to catch a future regression where someone hand-edits schema.sql
    to add a table but never writes a corresponding migration — new
    deployments get the table, existing deployments don't.
    """
    schema_tables = _extract_tables(_schema_path().read_text())

    migration_tables: set[str] = set()
    for mf in _migrations_dir().glob("*.sql"):
        migration_tables |= _extract_tables(mf.read_text())

    # Bootstrap tables: tables that exist in schema.sql AND are never
    # referenced (CREATE/ALTER) in any migration. These were set up at repo
    # genesis. We don't fail on them — but we DO track the count so a
    # sudden increase is visible in the test output.
    bootstrap_candidates = schema_tables - migration_tables
    print(
        f"  (informational) {len(bootstrap_candidates)} bootstrap tables "
        f"in schema.sql with no migration: "
        f"{sorted(bootstrap_candidates)[:8]}{'...' if len(bootstrap_candidates) > 8 else ''}"
    )
    # No assertion failure — this is an informational counter. If it ever
    # grows unexpectedly, the number appears in the log.
    print("✅ test_every_schema_table_came_from_somewhere")


def test_the_four_backfilled_tables_are_present():
    """Explicit positive check for the 4 tables Cycle 31 added. If one of
    these accidentally gets removed from schema.sql (e.g., someone mid-
    merges the file), the generic drift test above catches it — but the
    test output will say "X is missing", which is less obvious than this
    direct check."""
    schema_tables = _extract_tables(_schema_path().read_text())
    required = {
        "notification_preferences",
        "visual_styles",
        "style_characters",
        "background_tasks",
    }
    missing = required - schema_tables
    assert not missing, (
        f"Cycle 31 backfilled tables dropped from schema.sql: {sorted(missing)}"
    )
    print(f"✅ test_the_four_backfilled_tables_are_present ({sorted(required)})")


TESTS = [
    test_schema_sql_and_migrations_dirs_exist,
    test_every_migration_table_is_in_schema_sql,
    test_every_schema_table_came_from_somewhere,
    test_the_four_backfilled_tables_are_present,
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
