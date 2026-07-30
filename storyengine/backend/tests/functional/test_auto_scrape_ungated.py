"""Functional test for Stage 6.4 sub-fix #2: prove _auto_scrape_competitors
no longer gates on autopilot_config.enabled. Cycle 33 made `hours_old`
dynamic, but if the underlying view/VPH data is never re-pulled the
numbers are still stale. This cycle removes the gate so every tenant
with competitor channels gets a daily scrape.

Pre-fix (Cycle 33 and earlier), `main.py:_auto_scrape_competitors` had:
    if not config.get("enabled"):
        continue
Only tenants with autopilot explicitly enabled benefited. Everyone else
saw a scraped-once-ever snapshot that aged forever.

Cycle 34 fix: drop the autopilot gate; require only ≥1 active competitor
channel. Regressing this (putting the gate back) is a subtle behavior
change that would silently re-stagnate the competitors tab for 99% of
users — so it deserves a pinned test.

Source-audit pattern, same as Cycle 33 — no live DB required. The
actual behavior is validated on VPS deploy via a backend restart + log
check.
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _main_py() -> Path:
    return Path(__file__).resolve().parents[2] / "main.py"


def _source() -> str:
    return _main_py().read_text()


def _scrape_block() -> str:
    """Extract the _auto_scrape_competitors function body."""
    src = _source()
    m = re.search(
        r"async def _auto_scrape_competitors\(\):(.*?)(?=\nasync def |\Z)",
        src,
        re.DOTALL,
    )
    assert m, "could not locate _auto_scrape_competitors in main.py"
    return m.group(0)


def test_main_py_exists():
    assert _main_py().exists(), f"main.py not at {_main_py()}"
    print("✅ test_main_py_exists")


def test_scrape_no_longer_gates_on_autopilot_enabled():
    """The old gate `if not config.get("enabled"): continue` must be gone
    from _auto_scrape_competitors. If someone re-adds it, this fails."""
    block = _scrape_block()
    # Specifically the boolean enabled-gate on the scrape loop. Other
    # auto-* tasks still legitimately gate on autopilot (YT sync,
    # title analysis, learning extraction) — those are separate funcs.
    offender = re.search(
        r'if\s+not\s+config\.get\(["\']enabled["\']\)\s*:\s*\n\s*continue',
        block,
    )
    assert not offender, (
        "autopilot-enabled gate resurrected in _auto_scrape_competitors:\n"
        + (offender.group(0) if offender else "")
        + "\n\nCycle 34 explicitly removed this gate. If autopilot-only "
        "scraping is wanted again, ship it as a new config flag, not a "
        "silent revert."
    )
    # And also guard against the `_is_autopilot_enabled()` helper being
    # added to the scrape loop (equivalent shape, different spelling)
    helper_offender = re.search(
        r'_is_autopilot_enabled\([^\)]*\)', block
    )
    assert not helper_offender, (
        "_is_autopilot_enabled() call reintroduced into scrape loop — "
        "same autopilot gate, different wording."
    )
    print("✅ test_scrape_no_longer_gates_on_autopilot_enabled")


def test_scrape_skips_tenants_with_zero_competitor_channels():
    """Positive counterpart: scraping a tenant that has no competitor
    channels is pointless — verify the short-circuit is there. This
    keeps the log + DB noise level flat even as we unconditionally
    iterate all tenants."""
    block = _scrape_block()
    # Python split-string tolerance: the SQL spans two adjacent string
    # literals (closing quote, whitespace/newline, opening quote), so we
    # match each piece separately within the same block.
    assert "competitor_channels" in block, (
        "Scrape block doesn't reference competitor_channels at all — "
        "did the short-circuit query get deleted?"
    )
    assert re.search(r"active\s*=\s*true", block, re.IGNORECASE), (
        "Missing `active = true` filter on competitor_channels count — "
        "scrape loop will include soft-deleted channels."
    )
    # And a continue when count is zero (tolerant to int() wrapping)
    zero_skip = re.search(
        r"==\s*0\s*:\s*\n\s*continue",
        block,
    )
    assert zero_skip, (
        "Missing 'if zero → continue' after the competitor_channels count."
    )
    print("✅ test_scrape_skips_tenants_with_zero_competitor_channels")


def test_videos_per_scrape_default_preserved():
    """Regression: the `videos_per_scrape` config lookup (with default 10)
    must still be there. Without it the default max_videos_per_channel
    fallback in _run_scrape takes over — could be different."""
    block = _scrape_block()
    assert re.search(
        r"config\.get\(['\"]videos_per_scrape['\"],\s*10\)",
        block,
    ), "videos_per_scrape default (10) lookup missing"
    print("✅ test_videos_per_scrape_default_preserved")


def test_other_autopilot_gates_remain_intact():
    """Cycle 34 only removed the gate from _auto_scrape_competitors.
    _auto_analyze_competitor_titles and _auto_extract_learnings should
    still gate on autopilot. If Cycle 34 accidentally removed one of
    those, this test fails.

    Note: _auto_sync_youtube's autopilot gate was ALSO deliberately
    removed later (commit 5f135af3) — that removal has its own
    authoritative lock in test_youtube_auto_sync_ungated_lock.py, so it's
    intentionally excluded from this check.

    Why: the remaining auto-* tasks trigger user-charged work (YT API
    calls, Anthropic analysis of competitor data). Ungating those would
    blow cost caps. Only the no-cost scrape (and, separately, YouTube
    sync) was safe to ungate.
    """
    src = _source()
    for func_name in (
        "_auto_analyze_competitor_titles",
        "_auto_extract_learnings",
    ):
        m = re.search(
            rf"async def {func_name}\(\):(.*?)(?=\nasync def |\Z)",
            src,
            re.DOTALL,
        )
        assert m, f"could not locate {func_name} in main.py"
        body = m.group(0)
        # Each must still reference autopilot (via _is_autopilot_enabled
        # or config.get("enabled"))
        has_gate = bool(
            re.search(r"_is_autopilot_enabled\(", body)
            or re.search(r'config\.get\(["\']enabled["\']\)', body)
        )
        assert has_gate, (
            f"{func_name} no longer gates on autopilot — Cycle 34 was "
            "ONLY supposed to ungate _auto_scrape_competitors."
        )
    print("✅ test_other_autopilot_gates_remain_intact")


def test_scrape_interval_still_daily():
    """Guardrail: don't accidentally shorten the scrape interval while
    editing. 86400s = once daily. If someone changes this to 600s the
    VPS will be begging for help."""
    block = _scrape_block()
    assert "asyncio.sleep(86400)" in block, (
        "Scrape interval is no longer 86400 (daily) — check main.py for "
        "an accidental sleep() value change."
    )
    print("✅ test_scrape_interval_still_daily")


TESTS = [
    test_main_py_exists,
    test_scrape_no_longer_gates_on_autopilot_enabled,
    test_scrape_skips_tenants_with_zero_competitor_channels,
    test_videos_per_scrape_default_preserved,
    test_other_autopilot_gates_remain_intact,
    test_scrape_interval_still_daily,
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
