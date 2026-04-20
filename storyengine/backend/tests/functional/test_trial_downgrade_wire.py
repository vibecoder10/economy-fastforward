"""Functional test for Stage 3.2 trial-downgrade cron wire-up.

Roadmap Cycle 42 audit: Stage 3.2 ("free trial lifecycle — no cron that
downgrades expired trials") is already fully shipped. Pinning the wire
here prevents a revert from silently reintroducing a revenue leak.

Wire-up has 7 links:
  1. Migration 041 adds trial_expired_handled column on accounts
  2. Migration 041 adds partial index on (trial_ends_at) for the cron query
  3. email_tasks.check_trial_expired() selects expired+unhandled+no-sub
  4. email_tasks.check_trial_expired() flips plan to 'starter' + sets handled
  5. email_service.send_trial_expired() email function exists
  6. main._auto_check_trial_expired() lifespan loop exists with 6h sleep
  7. Lifespan startup creates the task; shutdown cancels it

If any of these 7 go missing on a refactor, this test flags it. The
safety filter `stripe_subscription_id IS NULL` is specifically guarded
— losing it would downgrade paying customers.
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _storyengine_dir() -> Path:
    return Path(__file__).resolve().parents[3]


def _repo_read(rel: str) -> str:
    path = _storyengine_dir() / rel
    assert path.exists(), f"Expected file missing: {rel}"
    return path.read_text()


def test_migration_041_adds_handled_column_and_index():
    src = _repo_read("backend/migrations/041_trial_expired_handled.sql")
    assert re.search(
        r"ALTER\s+TABLE\s+accounts[\s\S]{0,100}?ADD\s+COLUMN\s+IF\s+NOT\s+EXISTS\s+trial_expired_handled\s+BOOLEAN",
        src,
        re.IGNORECASE,
    ), "Migration 041 must add trial_expired_handled BOOLEAN column on accounts."
    assert re.search(
        r"CREATE\s+INDEX\s+IF\s+NOT\s+EXISTS[\s\S]{0,200}?ON\s+accounts[\s\S]{0,100}?trial_ends_at",
        src,
        re.IGNORECASE,
    ), "Migration 041 must add an index on accounts(trial_ends_at) for the cron query."
    # Partial index must filter to the cron's WHERE clause
    assert re.search(
        r"WHERE\s+trial_expired_handled\s+IS\s+NOT\s+TRUE[\s\S]{0,100}?stripe_subscription_id\s+IS\s+NULL",
        src,
        re.IGNORECASE,
    ), "Partial index must filter on (NOT handled AND no paid sub) to match the cron query."
    print("✅ test_migration_041_adds_handled_column_and_index")


def test_check_trial_expired_query_safe():
    src = _repo_read("backend/email_tasks.py")
    # Query must exclude paid subs (CRITICAL — otherwise paying customers get downgraded)
    assert re.search(
        r"async\s+def\s+check_trial_expired[\s\S]{0,2000}?stripe_subscription_id\s+IS\s+NULL",
        src,
    ), (
        "check_trial_expired() MUST filter `stripe_subscription_id IS NULL`. "
        "Without this, paying customers get downgraded. Revenue leak."
    )
    # Query must filter expired trials
    assert re.search(
        r"async\s+def\s+check_trial_expired[\s\S]{0,2000}?trial_ends_at\s*<\s*now\(\)",
        src,
    ), "check_trial_expired() must filter trial_ends_at < now()."
    # Query must skip already-handled accounts (idempotency)
    assert re.search(
        r"async\s+def\s+check_trial_expired[\s\S]{0,2000}?trial_expired_handled\s+IS\s+NOT\s+TRUE",
        src,
    ), (
        "check_trial_expired() must filter trial_expired_handled IS NOT TRUE "
        "— otherwise cron re-emails same users every 6h."
    )
    print("✅ test_check_trial_expired_query_safe")


def test_check_trial_expired_flips_plan_and_marks_handled():
    src = _repo_read("backend/email_tasks.py")
    # UPDATE must flip plan to 'starter' AND mark handled in same statement (atomic)
    assert re.search(
        r"UPDATE\s+accounts[\s\S]{0,300}?plan\s*=\s*'starter'[\s\S]{0,200}?trial_expired_handled\s*=\s*TRUE",
        src,
        re.IGNORECASE,
    ), (
        "UPDATE in check_trial_expired must set plan='starter' AND "
        "trial_expired_handled=TRUE in one statement. Splitting them risks "
        "emailing without downgrading, or vice versa."
    )
    print("✅ test_check_trial_expired_flips_plan_and_marks_handled")


def test_send_trial_expired_email_function_exists():
    src = _repo_read("backend/email_service.py")
    assert re.search(
        r"async\s+def\s+send_trial_expired\s*\(\s*email:\s*str[\s\S]{0,100}?display_name:\s*str",
        src,
    ), "email_service.send_trial_expired(email, display_name) must exist."
    print("✅ test_send_trial_expired_email_function_exists")


def test_auto_check_trial_expired_lifespan_task():
    src = _repo_read("backend/main.py")
    # The async lifespan task function exists
    assert re.search(
        r"async\s+def\s+_auto_check_trial_expired\s*\(\s*\)\s*:",
        src,
    ), "main._auto_check_trial_expired() lifespan task function must exist."
    # It must actually call check_trial_expired
    assert re.search(
        r"_auto_check_trial_expired[\s\S]{0,500}?await\s+check_trial_expired\(\)",
        src,
    ), "_auto_check_trial_expired must actually await check_trial_expired()."
    # It must loop (while True) with a sleep (6h = 21600s)
    assert re.search(
        r"_auto_check_trial_expired[\s\S]{0,1000}?while\s+True[\s\S]{0,800}?asyncio\.sleep\(\s*21600",
        src,
    ), (
        "_auto_check_trial_expired must be a while-True loop with "
        "asyncio.sleep(21600) — 6 hour cadence. If the sleep is missing "
        "or too small, the cron hammers the DB."
    )
    print("✅ test_auto_check_trial_expired_lifespan_task")


def test_lifespan_starts_and_cancels_trial_expired_task():
    src = _repo_read("backend/main.py")
    # Startup: asyncio.create_task(_auto_check_trial_expired())
    assert re.search(
        r"asyncio\.create_task\(\s*_auto_check_trial_expired\(\)\s*\)",
        src,
    ), (
        "Lifespan startup must create the task via "
        "asyncio.create_task(_auto_check_trial_expired()). "
        "Without this, the cron never runs."
    )
    # Shutdown: trial_expired_task.cancel()
    assert re.search(
        r"trial_expired_task\.cancel\(\)",
        src,
    ), "Lifespan shutdown must cancel trial_expired_task to avoid task leak."
    print("✅ test_lifespan_starts_and_cancels_trial_expired_task")


def test_schema_has_trial_expired_handled_column():
    src = _repo_read("schema.sql")
    # Either a direct column decl OR an ALTER in schema.sql — whichever path schema.sql uses
    assert re.search(
        r"trial_expired_handled\s+BOOLEAN",
        src,
        re.IGNORECASE,
    ), (
        "schema.sql must declare trial_expired_handled BOOLEAN on accounts. "
        "If this is missing, fresh DB init won't have the column and the "
        "cron's UPDATE will fail silently."
    )
    print("✅ test_schema_has_trial_expired_handled_column")


TESTS = [
    test_migration_041_adds_handled_column_and_index,
    test_check_trial_expired_query_safe,
    test_check_trial_expired_flips_plan_and_marks_handled,
    test_send_trial_expired_email_function_exists,
    test_auto_check_trial_expired_lifespan_task,
    test_lifespan_starts_and_cancels_trial_expired_task,
    test_schema_has_trial_expired_handled_column,
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
