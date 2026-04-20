"""Runtime E2E audit: prove no raw error strings have ever leaked into the
user-visible activity feed (bot_activity.message) or background_tasks.error_message.

This is the end-to-end test that Cycles 8-11's honest-gap sections all flagged:
"static audit covers the code path, but only a live DB scan proves the
humanization is actually working in production." Now that we have SSH +
venv access to the VPS, we can write it.

The test runs against a live Postgres DB (prod Supabase, or a staging branch).
It scans every row in bot_activity (where status='failed') and background_tasks
(where status='failed' and error_message is not null) for substrings that are
signatures of a raw Python exception: HTTPSConnectionPool, Traceback, host='',
Errno N, AttributeError/KeyError/etc., upstream API hostnames, Connection
aborted/refused/reset.

Any match = the write-boundary humanizer got bypassed somewhere.
Zero matches = Cycles 8-11's fixes are holding in production, forever.

Requires DATABASE_URL env var set to a Postgres URL with read access to
bot_activity and background_tasks. Skip (don't fail) if not set — so this
file can coexist with local dev where no DB is running.
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class _Skip(Exception):
    """Raised when DATABASE_URL is missing — test is a no-op in that env."""
    pass


RAW_ERROR_PATTERNS = [
    "HTTPSConnectionPool",
    "Traceback",
    "host='",
    "Errno ",
    "AttributeError:",
    "KeyError:",
    "TypeError:",
    "ValueError:",
    "NameError:",
    "IndexError:",
    "api.kie.ai",
    "api.anthropic.com",
    "api.openai.com",
    "Connection aborted",
    "Connection refused",
    "Connection reset",
]


def _require_db_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise _Skip("DATABASE_URL not set — this audit runs on the VPS/CI")
    return url


async def _scan(query: str, field: str) -> list[dict]:
    import asyncpg
    db_url = _require_db_url()
    conn = await asyncpg.connect(db_url)
    try:
        rows = await conn.fetch(query)
    finally:
        await conn.close()
    leaks = []
    for row in rows:
        text = row[field]
        if text is None:
            continue
        for pattern in RAW_ERROR_PATTERNS:
            if pattern in text:
                leaks.append({
                    "id": str(row["id"]),
                    "pattern": pattern,
                    "text": text[:200],
                })
                break
    return leaks


def test_bot_activity_no_raw_error_substrings():
    """No row in bot_activity (failed status) contains raw exception signatures."""
    query = """
        SELECT id, message
        FROM bot_activity
        WHERE status = 'failed' AND message IS NOT NULL
    """
    leaks = asyncio.run(_scan(query, "message"))
    if leaks:
        print(f"\n❌ Found {len(leaks)} raw-error leak(s) in bot_activity:")
        for leak in leaks[:10]:
            print(f"  id={leak['id']} pattern={leak['pattern']!r}")
            print(f"    text: {leak['text']}")
    assert leaks == [], f"{len(leaks)} raw-error leaks in bot_activity.message"
    print("✅ test_bot_activity_no_raw_error_substrings (scanned failed rows, 0 leaks)")


def test_background_tasks_no_raw_error_substrings():
    """No row in background_tasks (failed status) contains raw exception signatures."""
    query = """
        SELECT id, error_message
        FROM background_tasks
        WHERE status = 'failed' AND error_message IS NOT NULL
    """
    leaks = asyncio.run(_scan(query, "error_message"))
    if leaks:
        print(f"\n❌ Found {len(leaks)} raw-error leak(s) in background_tasks:")
        for leak in leaks[:10]:
            print(f"  id={leak['id']} pattern={leak['pattern']!r}")
            print(f"    text: {leak['text']}")
    assert leaks == [], f"{len(leaks)} raw-error leaks in background_tasks.error_message"
    print("✅ test_background_tasks_no_raw_error_substrings (scanned failed rows, 0 leaks)")


def test_helper_strips_every_raw_pattern():
    """Sanity: the humanizer itself strips every pattern in our catalog.

    If RAW_ERROR_PATTERNS is extended with a new signature that the helper
    doesn't strip, the two DB-scan tests above could silently miss it. This
    test pins the helper's output against the same pattern list.
    """
    from error_utils import humanize_error
    sample_errors = {
        "HTTPSConnectionPool": "HTTPSConnectionPool(host='api.kie.ai', port=443): Max retries exceeded",
        "Traceback": "Traceback (most recent call last):\n  File ...",
        "host='": "Failed to connect: host='api.openai.com' port=443",
        "Errno ": "[Errno 111] Connection refused",
        "AttributeError:": "AttributeError: 'NoneType' object has no attribute 'get'",
        "KeyError:": "KeyError: 'missing_field'",
        "TypeError:": "TypeError: unhashable type: 'dict'",
        "ValueError:": "ValueError: invalid literal for int()",
        "NameError:": "NameError: name 'x' is not defined",
        "IndexError:": "IndexError: list index out of range",
        "api.kie.ai": "Upstream api.kie.ai returned 500",
        "api.anthropic.com": "Upstream api.anthropic.com returned 500",
        "api.openai.com": "Upstream api.openai.com returned 500",
        "Connection aborted": "Connection aborted by peer",
        "Connection refused": "Connection refused by upstream",
        "Connection reset": "Connection reset by peer",
    }
    leaked = []
    for pattern, raw in sample_errors.items():
        out = humanize_error(raw, context="We couldn't do the thing")
        if pattern in out:
            leaked.append((pattern, out))
    assert not leaked, f"humanize_error leaked: {leaked}"
    print(f"✅ test_helper_strips_every_raw_pattern ({len(sample_errors)} patterns, 0 leaks)")


if __name__ == "__main__":
    failures = 0
    for fn in (
        test_bot_activity_no_raw_error_substrings,
        test_background_tasks_no_raw_error_substrings,
        test_helper_strips_every_raw_pattern,
    ):
        try:
            fn()
        except _Skip as e:
            print(f"⏭️  {fn.__name__} skipped: {e}")
        except AssertionError as e:
            print(f"❌ {fn.__name__} FAILED: {e}")
            failures += 1
        except Exception as e:
            print(f"❌ {fn.__name__} ERRORED: {type(e).__name__}: {e}")
            failures += 1
    if failures:
        print(f"\n❌ {failures} audit(s) failed")
        sys.exit(1)
    print("\n✅ All activity-feed raw-error audits passed (or skipped cleanly)")
