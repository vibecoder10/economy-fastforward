"""Functional test for Stage 2.3: background_tasks.created_at index.

Shipped Cycle 38. The index isn't critical TODAY (small table, no live
cleanup query yet) but it's the kind of thing that silently bites at
scale — you notice when the table hits 500k rows and the "show me
recent failed tasks" query suddenly takes 2 seconds. Pinning it here
means nobody can revert the migration + drop the schema line without
this test flagging it.

Three checks:
  1. Migration file exists and creates the index
  2. schema.sql mirrors the index in BOTH background_tasks definitions
     (schema.sql has duplicate defs — drift from Stage 2.2 — and a
     Stage 2.3 fix that only covers one half would be silently broken
     for fresh Supabase-via-schema.sql deploys)
  3. tenant_usage index (the other Stage 2.3 concern) is actually
     present — documents why we didn't add a second index this cycle

Source-audit. Runtime index verification happens on VPS via
`\\d background_tasks` after the migration runs.
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _storyengine_dir() -> Path:
    # tests/functional/this -> backend -> storyengine
    return Path(__file__).resolve().parents[3]


def _migrations_dir() -> Path:
    return _storyengine_dir() / "backend" / "migrations"


def _schema_sql() -> Path:
    return _storyengine_dir() / "schema.sql"


MIGRATION_BASENAME = "042_background_tasks_created_at_idx.sql"
INDEX_NAME = "idx_bg_tasks_created_at"


def test_migration_file_exists():
    path = _migrations_dir() / MIGRATION_BASENAME
    assert path.exists(), (
        f"Migration {MIGRATION_BASENAME} missing. A revert of Stage 2.3 "
        "dropped the file — restore it or the index will be absent in "
        "fresh deploys."
    )
    print("✅ test_migration_file_exists")


def test_migration_creates_the_index():
    path = _migrations_dir() / MIGRATION_BASENAME
    src = path.read_text()
    # Must mention CREATE INDEX (IF NOT EXISTS is optional but preferred)
    m = re.search(
        rf"CREATE\s+INDEX(?:\s+IF\s+NOT\s+EXISTS)?\s+{INDEX_NAME}\s+ON\s+background_tasks\s*\(\s*created_at",
        src,
        re.IGNORECASE,
    )
    assert m, (
        f"Migration doesn't CREATE INDEX {INDEX_NAME} ON "
        "background_tasks(created_at ...). Check for renames or typos."
    )
    # Prefer IF NOT EXISTS so re-runs don't explode
    assert re.search(r"IF\s+NOT\s+EXISTS", src, re.IGNORECASE), (
        "Migration missing IF NOT EXISTS — re-running will error on "
        "idempotency. Cheap guard, add it."
    )
    print("✅ test_migration_creates_the_index")


def test_schema_sql_mirrors_index_in_all_definitions():
    """schema.sql has TWO background_tasks CREATE TABLE blocks (the
    drift Stage 2.2 is eventually supposed to clean up). Both must
    include the new index — otherwise a fresh deploy using the second
    block ships without it."""
    src = _schema_sql().read_text()
    # Count CREATE TABLE background_tasks occurrences
    table_defs = re.findall(
        r"CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+background_tasks\b",
        src,
        re.IGNORECASE,
    )
    # If the schema ever gets deduplicated (Stage 2.2 ships), this
    # drops to 1 — that's fine. Floor at 1.
    assert len(table_defs) >= 1, "schema.sql has no background_tasks table def"
    # Count CREATE INDEX ... idx_bg_tasks_created_at occurrences. Must
    # match the count of table defs (one index per def).
    index_lines = re.findall(
        rf"CREATE\s+INDEX(?:\s+IF\s+NOT\s+EXISTS)?\s+{INDEX_NAME}\s+ON\s+background_tasks",
        src,
        re.IGNORECASE,
    )
    assert len(index_lines) == len(table_defs), (
        f"schema.sql has {len(table_defs)} background_tasks CREATE TABLE "
        f"block(s) but only {len(index_lines)} CREATE INDEX {INDEX_NAME} "
        "line(s). Each table def must carry the index, otherwise a fresh "
        "deploy that only evaluates one block ships without it."
    )
    print("✅ test_schema_sql_mirrors_index_in_all_definitions")


def test_tenant_usage_period_start_already_indexed():
    """Stage 2.3's second concern. Documents why we didn't add a
    second new index — the composite (tenant_id, period_start) from
    migration 024 answers every real query shape. If someone ever
    drops that composite, this test flags the gap."""
    src = (_migrations_dir() / "024_tenant_usage.sql").read_text()
    assert re.search(
        r"CREATE\s+INDEX[^;]*tenant_usage\s*\(\s*tenant_id\s*,\s*period_start",
        src,
        re.IGNORECASE,
    ), (
        "Composite (tenant_id, period_start) index on tenant_usage is "
        "missing from migration 024. Stage 2.3 assumed this covered "
        "monthly-lookup needs — if it's gone, add a new migration."
    )
    print("✅ test_tenant_usage_period_start_already_indexed")


def test_index_uses_desc_ordering():
    """Hot path for this index is ORDER BY created_at DESC (recent
    activity, cleanup scans from oldest with < comparisons). Pg can
    scan either direction but DESC matches the natural read pattern
    and avoids a reverse scan for the common 'recent tasks' query."""
    path = _migrations_dir() / MIGRATION_BASENAME
    src = path.read_text()
    assert re.search(
        r"created_at\s+DESC",
        src,
        re.IGNORECASE,
    ), (
        "Index should be created with (created_at DESC). ASC works for "
        "cleanup but the activity-feed query is the hot path. If this "
        "was an intentional change, update the comment explaining why."
    )
    print("✅ test_index_uses_desc_ordering")


TESTS = [
    test_migration_file_exists,
    test_migration_creates_the_index,
    test_schema_sql_mirrors_index_in_all_definitions,
    test_tenant_usage_period_start_already_indexed,
    test_index_uses_desc_ordering,
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
