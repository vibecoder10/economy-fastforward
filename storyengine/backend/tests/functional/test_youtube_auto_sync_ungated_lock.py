"""Functional test for Stage 6.7 / Cycle 53: YouTube auto-sync gated on
autopilot — regression lock.

The bug (pre-fix): `_auto_sync_youtube` in main.py only ran the YouTube
metrics sync for tenants with `autopilot_config.enabled = true`. Every
other tenant's analytics drifted silently — videos uploaded yesterday kept
showing yesterday's view count, CTR, watch time, etc. The manual "Sync
YouTube" button also required the user to hit it every time they wanted
fresh numbers.

The fix (this cycle):
1. Removed the `if not await _is_autopilot_enabled(tenant_id): continue`
   gate from `_auto_sync_youtube`. Same shape as the Cycle 34 fix for
   `_auto_scrape_competitors` (Stage 6.4).
2. Added a precondition check for YouTube credentials — the loop skips
   tenants who have no `channel_profiles.youtube_refresh_token` AND no
   legacy vault `google_refresh_token`. Without this, `_run_sync` would
   be called for every tenant and silently return "YouTube not connected"
   — not harmful but noisy in logs.
3. Bumped the interval from 21600 (6h) to 86400 (24h). YouTube metrics
   aggregate slowly; daily is enough and reduces API quota pressure.

This test pins all three so a refactor can't silently reintroduce the bug:
  - No `_is_autopilot_enabled` gate anywhere in `_auto_sync_youtube`.
  - The precondition SELECT on `channel_profiles.youtube_refresh_token`
    still guards the loop.
  - `asyncio.sleep(86400)` still closes the loop — not 21600 or smaller.
"""
import ast
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _main_py() -> Path:
    return Path(__file__).resolve().parents[2] / "main.py"


def _get_auto_sync_body() -> str:
    """Return the source text of the _auto_sync_youtube function body."""
    text = _main_py().read_text()
    m = re.search(
        r"async\s+def\s+_auto_sync_youtube\s*\([^)]*\)\s*:([\s\S]+?)(?=\nasync\s+def\s|\ndef\s|\Z)",
        text,
    )
    assert m, "_auto_sync_youtube function not found in main.py"
    return m.group(1)


def test_no_autopilot_enabled_gate():
    """The exact SEC-SSE-001-shaped regression here would be
    `if not await _is_autopilot_enabled(tenant_id): continue` — that's
    what Cycle 53 removed. Flag it on any form (direct `continue`,
    `return`, or a negated elif branch)."""
    body = _get_auto_sync_body()
    forbidden = re.search(
        r"if\s+not\s+await\s+_is_autopilot_enabled\s*\(",
        body,
    )
    assert not forbidden, (
        "_auto_sync_youtube has reintroduced a `_is_autopilot_enabled` "
        "gate. Stage 6.7 regression — every non-autopilot tenant's YouTube "
        "metrics would go stale. Remove the gate and use the credentials "
        "precondition instead."
    )
    # Also guard against the less-explicit `autopilot_config.enabled` check
    forbidden_config = re.search(
        r"config\s*\.\s*get\s*\(\s*['\"]enabled['\"][^)]*\)\s*[^\n]*\n\s*continue",
        body,
    )
    assert not forbidden_config, (
        "_auto_sync_youtube has reintroduced a `config.get('enabled')` "
        "check followed by `continue`. Same regression, different shape."
    )
    print("✅ test_no_autopilot_enabled_gate")


def test_credentials_precondition_guards_loop():
    """The ungated loop has to skip tenants without YouTube credentials —
    otherwise every boot spams a "YouTube not connected" error per tenant
    in logs. The guard must be: pre-SELECT channel_profiles.youtube_refresh_token
    then fall through to a legacy vault check, and `continue` if neither."""
    body = _get_auto_sync_body()
    # Must read the OAuth token column
    assert re.search(
        r"youtube_refresh_token\s+FROM\s+channel_profiles",
        body,
        re.IGNORECASE,
    ), (
        "_auto_sync_youtube no longer reads "
        "channel_profiles.youtube_refresh_token to pre-filter tenants. "
        "Without this, every boot logs auth errors for every tenant that "
        "hasn't connected YouTube — noise that masks real issues."
    )
    # Must fall back to the legacy vault key — otherwise the legacy-creds
    # code path in _run_sync can never trigger.
    assert re.search(
        r"get_secret\s*\(\s*['\"]google_refresh_token['\"]",
        body,
    ), (
        "_auto_sync_youtube no longer falls back to the legacy vault "
        "google_refresh_token before skipping. Tenants on the old "
        "credential shape would be silently excluded."
    )
    # Must `continue` when neither shape is present
    assert re.search(r"\bcontinue\b", body), (
        "_auto_sync_youtube no longer contains a `continue` — the "
        "credentials precondition must skip tenants without YouTube "
        "connected, not fall through to _run_sync and log an error."
    )
    print("✅ test_credentials_precondition_guards_loop")


def test_interval_is_daily():
    """The loop-end sleep must be 86400 (24h). A sub-daily interval burns
    YouTube API quota for marginal metric freshness, and the roadmap
    explicitly called for the 6h → 24h change."""
    body = _get_auto_sync_body()
    # Find every asyncio.sleep(N) call at the loop boundary (not the
    # warm-up sleep at the top, which is ~60s).
    sleeps = re.findall(r"await\s+asyncio\.sleep\(\s*(\d+)\s*\)", body)
    assert sleeps, "_auto_sync_youtube has no asyncio.sleep calls"
    # The final sleep (loop interval) is the last one in the body
    loop_interval = int(sleeps[-1])
    assert loop_interval == 86400, (
        f"_auto_sync_youtube loop interval is {loop_interval}s, expected "
        "86400 (24h). Sub-daily sync burns YouTube API quota for marginal "
        "freshness gains — daily is the Stage 6.7 target."
    )
    # And nothing sub-daily at the loop boundary (e.g. the old 21600 value)
    assert 21600 not in [int(s) for s in sleeps], (
        "_auto_sync_youtube still contains an asyncio.sleep(21600) (6h) "
        "call. That was the pre-fix interval — remove it."
    )
    print("✅ test_interval_is_daily")


def test_function_still_exists_and_is_scheduled():
    """Positive check: the function must still exist AND still be
    scheduled at startup. If a refactor renamed or removed it, the tests
    above could pass vacuously on an empty string."""
    text = _main_py().read_text()
    assert re.search(r"async\s+def\s+_auto_sync_youtube\s*\(", text), (
        "_auto_sync_youtube is no longer defined. If it was renamed, "
        "update this test to track the new name — but keep the three "
        "invariants (no autopilot gate, credentials precondition, daily "
        "interval) intact."
    )
    # Must be scheduled via asyncio.create_task (or similar) during startup.
    # Allow either direct create_task or a background_tasks.append shape.
    assert re.search(r"_auto_sync_youtube\s*\(\s*\)", text) and re.search(
        r"(create_task\s*\(\s*_auto_sync_youtube|asyncio\.ensure_future\s*\(\s*_auto_sync_youtube|_auto_sync_youtube\s*\(\s*\)\s*\))",
        text,
    ), (
        "_auto_sync_youtube is defined but no longer scheduled during "
        "startup. The coroutine must be kicked off (typically via "
        "asyncio.create_task in the lifespan handler) or it never runs."
    )
    print("✅ test_function_still_exists_and_is_scheduled")


TESTS = [
    test_function_still_exists_and_is_scheduled,
    test_no_autopilot_enabled_gate,
    test_credentials_precondition_guards_loop,
    test_interval_is_daily,
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
