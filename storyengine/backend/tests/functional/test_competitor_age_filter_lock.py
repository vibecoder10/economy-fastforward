"""Functional test for Stage 6.4 / Cycle 49: Competitors tab dynamic age
filter — regression lock.

Pre-fix: `hours_old` was a static snapshot from scrape time. A video scraped
5 days ago reporting "24 hours old" would still report "24 hours old" today.
Auto-scraping was gated on autopilot being enabled, so most tenants never
refreshed. The competitors UI had no age filter.

The fix landed four coordinated changes that this test pins:
1. `GET /api/niche/videos` accepts `max_hours_old` and filters SQL-side by
   `published_date >= NOW() - INTERVAL`.
2. `hours_old` in the response is computed at query time via
   `EXTRACT(EPOCH FROM (NOW() - cv.published_date)) / 3600.0` — the stored
   column is only a fallback when `published_date` is NULL.
3. `_auto_scrape_competitors` in main.py no longer gates on
   `autopilot_config.enabled` — any tenant with ≥1 active competitor
   channel gets a daily scrape.
4. Frontend competitors page has the 24h / 3d / 7d / All filter pills and
   forwards `max_hours_old` through `getNicheVideos`.

If any one of these reverts, the competitors tab silently goes stagnant
again. This test fails before the regression ships.
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _backend() -> Path:
    return Path(__file__).resolve().parents[2]


def _frontend_src() -> Path:
    return Path(__file__).resolve().parents[3] / "frontend" / "src"


def _niche_py() -> Path:
    return _backend() / "routes" / "niche.py"


def _main_py() -> Path:
    return _backend() / "main.py"


def _competitors_page() -> Path:
    return _frontend_src() / "app" / "competitors" / "page.tsx"


def _api_ts() -> Path:
    return _frontend_src() / "lib" / "api.ts"


def test_niche_videos_accepts_max_hours_old():
    """The route handler for GET /api/niche/videos must accept
    `max_hours_old` as a query param and use it in the SQL WHERE clause."""
    text = _niche_py().read_text()
    # Must appear in a function signature (typed param), not just a comment
    sig_match = re.search(
        r"def\s+\w+\([^)]*max_hours_old\s*:\s*Optional\[float\][^)]*\)", text, re.DOTALL
    )
    assert sig_match, (
        "routes/niche.py no longer declares `max_hours_old: Optional[float]` "
        "on the videos endpoint. Filter UI will break silently."
    )
    # Must be used in a WHERE-clause predicate against published_date.
    # The SQL is built via f-string, so the placeholder is `${idx}` in the
    # source (rendered to `$N` at execution). Accept either shape.
    where_match = re.search(
        r"published_date\s*>=\s*NOW\(\)\s*-\s*\(\s*\$(?:\{[^}]+\}|\d+)\s*\|\|\s*' hours'\s*\)\s*::\s*INTERVAL",
        text,
    )
    assert where_match, (
        "routes/niche.py no longer applies the max_hours_old WHERE clause "
        "(`published_date >= NOW() - ($N || ' hours')::INTERVAL`). Filter "
        "param is accepted but ignored — stagnant-data regression."
    )
    print("✅ test_niche_videos_accepts_max_hours_old")


def test_hours_old_computed_at_query_time():
    """hours_old in the response must be calculated from NOW() at query
    time, not read from the stored snapshot column (which never gets
    recomputed). The stored column may only serve as the NULL fallback."""
    text = _niche_py().read_text()
    # The projection expression must contain EXTRACT(EPOCH FROM (NOW() - ... published_date))
    pat = re.compile(
        r"EXTRACT\s*\(\s*EPOCH\s+FROM\s*\(\s*NOW\(\)\s*-\s*\w+\.published_date\s*\)\s*\)\s*/\s*3600",
        re.IGNORECASE,
    )
    assert pat.search(text), (
        "routes/niche.py no longer computes hours_old at query time with "
        "EXTRACT(EPOCH FROM (NOW() - published_date)) / 3600. The stored "
        "static `hours_old` column would be served — competitor cards would "
        "report the same age forever."
    )
    print("✅ test_hours_old_computed_at_query_time")


def test_auto_scrape_not_gated_on_autopilot_enabled():
    """`_auto_scrape_competitors` in main.py must NOT skip tenants whose
    autopilot is disabled. The only valid skip is 'tenant has no active
    competitor channels' (pure no-op). Any `if not config.get('enabled')
    : continue` style gate re-introduces stagnant-data for non-autopilot
    tenants — most of them."""
    text = _main_py().read_text()
    # Find the body of _auto_scrape_competitors
    m = re.search(
        r"async\s+def\s+_auto_scrape_competitors\s*\([^)]*\)\s*:([\s\S]+?)(?=\nasync\s+def\s|\ndef\s|\Z)",
        text,
    )
    assert m, "_auto_scrape_competitors function not found in main.py"
    body = m.group(1)
    forbidden = re.search(
        r"if\s+not\s+\w*config\w*\.get\(\s*['\"]enabled['\"][^)]*\)\s*:\s*\n\s*continue",
        body,
    )
    assert not forbidden, (
        "_auto_scrape_competitors has reintroduced an autopilot-enabled "
        "gate. Daily scrape must run for every tenant with an active "
        "competitor channel, not just autopilot-enabled ones."
    )
    print("✅ test_auto_scrape_not_gated_on_autopilot_enabled")


def test_frontend_has_age_filter_pills():
    """Competitors page must render the 24h / 3d / 7d / All pills and wire
    them to `maxHoursOld` state. Without this, users can't filter and the
    backend param goes unused."""
    text = _competitors_page().read_text()
    assert 'data-testid="age-filter-pills"' in text, (
        "competitors/page.tsx no longer has the age-filter-pills data-testid. "
        "Either the filter UI was removed or the testid moved — regression risk."
    )
    # Each of the 4 labels must appear
    for label in ('"24h"', '"3d"', '"7d"', '"All"'):
        assert label in text, f"age filter missing {label} option"
    # hour values must be present in the same block (24, 72, 168, undefined)
    for val in ("value: 24", "value: 72", "value: 168", "value: undefined"):
        assert val in text, f"age filter missing {val}"
    print("✅ test_frontend_has_age_filter_pills")


def test_api_client_passes_max_hours_old():
    """getNicheVideos in lib/api.ts must accept max_hours_old and forward
    it as a query param. If this drops, the filter buttons render but do
    nothing — same user-visible failure as no filter at all."""
    text = _api_ts().read_text()
    fn_match = re.search(
        r"export\s+const\s+getNicheVideos\s*=\s*\([^)]*\)\s*=>[\s\S]{0,800}",
        text,
    )
    assert fn_match, "getNicheVideos not found in lib/api.ts"
    chunk = fn_match.group(0)
    assert "max_hours_old" in chunk, (
        "getNicheVideos no longer accepts max_hours_old. Filter pills would "
        "render but never reach the backend."
    )
    # Must actually append it to the query string
    assert re.search(
        r'searchParams\.set\(\s*["\']max_hours_old["\']', chunk
    ), (
        "getNicheVideos accepts max_hours_old but doesn't append it to the "
        "query string — the filter would be silently ignored."
    )
    print("✅ test_api_client_passes_max_hours_old")


TESTS = [
    test_niche_videos_accepts_max_hours_old,
    test_hours_old_computed_at_query_time,
    test_auto_scrape_not_gated_on_autopilot_enabled,
    test_frontend_has_age_filter_pills,
    test_api_client_passes_max_hours_old,
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
