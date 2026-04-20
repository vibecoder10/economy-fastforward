"""Functional test for Stage 6.4 (sub-fixes #1 + #4): prove
GET /api/niche/videos calculates `hours_old` at query time (not from the
stale stored column) and supports a `max_hours_old` filter.

Pre-fix (as of 2026-04-19), `cv.hours_old` was a static snapshot computed
at scrape time in niche.py:796. A video scraped 5 days ago showing
"24 hours old" would show "24 hours old" forever. The competitors tab
became useless for "what's hot right now" because yesterday's 6-hour-old
video is today's 30-hour-old video — but the card still showed 6 hours.

Cycle 33 fix:
  1. SELECT replaces `cv.hours_old` with
     `EXTRACT(EPOCH FROM (NOW() - cv.published_date)) / 3600 AS hours_old`
  2. New `max_hours_old` query param filters WHERE published_date >= NOW() - '<N> hours'

This test is source-audit style — it doesn't stand up Postgres. Instead
it inspects `backend/routes/niche.py` to verify the contract, because
the alternative (spinning up a real DB with fixture rows) is
disproportionate for what is ultimately a SQL-text change. If someone
reverts the fix (puts `cv.hours_old` back in the SELECT), this catches
it deterministically.
"""
import inspect
import os
import re
import sys
from pathlib import Path
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Stub DB + auth so we can import the route module without a live Postgres.
for stub_mod in ("database", "auth"):
    if stub_mod not in sys.modules:
        m = types.ModuleType(stub_mod)
        if stub_mod == "database":
            async def _noop(*a, **kw):
                return None
            m.fetch_one = _noop
            m.fetch_all = _noop
            m.execute = _noop
        if stub_mod == "auth":
            async def _get_tenant_id(*a, **kw):
                return "stub"
            m.get_tenant_id = _get_tenant_id
        sys.modules[stub_mod] = m


def _niche_path() -> Path:
    return Path(__file__).resolve().parents[2] / "routes" / "niche.py"


def _niche_source() -> str:
    return _niche_path().read_text()


def test_niche_file_exists():
    assert _niche_path().exists(), f"niche.py not at {_niche_path()}"
    print("✅ test_niche_file_exists")


def test_list_videos_signature_has_max_hours_old():
    """The endpoint function must accept `max_hours_old: Optional[float]`."""
    from routes import niche as niche_mod

    sig = inspect.signature(niche_mod.list_videos)
    params = sig.parameters
    assert "max_hours_old" in params, (
        f"list_videos missing max_hours_old param. Actual: {list(params)}"
    )
    # Optional + has a None default (no param = no filter)
    p = params["max_hours_old"]
    assert p.default is None, (
        f"max_hours_old should default to None so omitting the param = no filter. "
        f"got default={p.default!r}"
    )
    print(f"✅ test_list_videos_signature_has_max_hours_old (params: {list(params)})")


def test_select_uses_live_epoch_calc_not_stored_column():
    """The SELECT that builds the page result must compute hours_old from
    NOW() - published_date. If someone reverts to `cv.hours_old` in the
    SELECT projection, this test fails."""
    src = _niche_source()
    # Locate the paginated-list fetch. Simplest proxy: find the block
    # around "cv.vph," + "hours_old" inside the same SELECT.
    # Look for the EXTRACT(EPOCH FROM expression near hours_old.
    assert re.search(
        r"EXTRACT\s*\(\s*EPOCH\s+FROM\s*\(\s*NOW\(\)\s*-\s*cv\.published_date\s*\)\s*\)\s*/\s*3600",
        src,
        re.IGNORECASE,
    ), (
        "niche.py missing the live-age SQL expression "
        "EXTRACT(EPOCH FROM (NOW() - cv.published_date)) / 3600. "
        "If someone reverted this to use the stored cv.hours_old column, "
        "the static-snapshot bug is back."
    )
    # AND the projection still aliases it as hours_old so the frontend
    # contract is preserved (card still reads `video.hours_old`).
    assert re.search(r"\bAS\s+hours_old\b", src, re.IGNORECASE), (
        "Live expression must alias to `hours_old` to keep frontend contract"
    )
    print("✅ test_select_uses_live_epoch_calc_not_stored_column")


def test_where_clause_supports_max_hours_old_filter():
    """When max_hours_old is passed, the WHERE clause must filter on
    published_date >= NOW() - <N> hours. Source-audit for the exact
    SQL shape so a refactor can't silently drop the filter."""
    src = _niche_source()
    assert re.search(
        r"cv\.published_date\s*>=\s*NOW\(\)\s*-\s*\([^)]*\)::INTERVAL",
        src,
        re.IGNORECASE,
    ) or re.search(
        r"cv\.published_date\s*>=\s*NOW\(\)\s*-\s*INTERVAL",
        src,
        re.IGNORECASE,
    ), (
        "niche.py list_videos missing the max_hours_old WHERE-filter on "
        "cv.published_date. Expected a published_date >= NOW() - INTERVAL '<N> hours' clause."
    )
    # And the check must be guarded by `max_hours_old is not None`
    assert "max_hours_old is not None" in src, (
        "max_hours_old filter must be guarded — otherwise None breaks the query"
    )
    print("✅ test_where_clause_supports_max_hours_old_filter")


def test_max_hours_old_is_parameterized_not_interpolated():
    """SECURITY: max_hours_old must flow through the params list, not
    be f-string-interpolated into the SQL. Same bug class as SEC-SQL-001."""
    src = _niche_source()
    # Grab the lines near the published_date >= NOW() filter and verify
    # a positional placeholder (${idx}) is used — never an inlined float.
    # Look for: f"...published_date >= NOW() - ... ${...}"
    # vs the anti-pattern: f"...published_date >= NOW() - INTERVAL '{max_hours_old}"
    leak_pat = re.compile(
        r"published_date\s*>=\s*NOW\(\)\s*-\s*INTERVAL\s*['\"]\s*\{[^}]*max_hours_old",
        re.IGNORECASE,
    )
    assert not leak_pat.search(src), (
        "max_hours_old is interpolated into SQL string — SQL injection risk. "
        "Use ${idx} parameterization like the other filters."
    )
    # Positive: there's an f-string positional placeholder near published_date
    assert re.search(
        r"published_date\s*>=\s*NOW\(\)\s*-\s*\(?\s*\$\{idx\}",
        src,
        re.IGNORECASE,
    ), (
        "Expected positional placeholder (${idx}) for max_hours_old filter"
    )
    print("✅ test_max_hours_old_is_parameterized_not_interpolated")


def test_sort_map_still_whitelisted():
    """Regression: the _SORT_MAP whitelist must remain intact — this is
    the SEC-SQL-001 defense for the sort param. Cycle 33 only added a new
    filter; it must not have disturbed the sort hardening."""
    from routes import niche as niche_mod
    sm = getattr(niche_mod, "_SORT_MAP", None)
    assert isinstance(sm, dict) and len(sm) >= 5, (
        f"_SORT_MAP whitelist missing or shrunk: {sm!r}"
    )
    # None of the values may contain a semicolon or SQL meta-char
    for k, v in sm.items():
        assert ";" not in v and "--" not in v, (
            f"_SORT_MAP[{k!r}] = {v!r} contains SQL meta-chars"
        )
    print(f"✅ test_sort_map_still_whitelisted ({len(sm)} entries)")


def test_clamp_prevents_absurd_interval():
    """Defense in depth: the endpoint clamps max_hours_old to <=8760 (1yr)
    before putting it in the SQL, so a user passing 10**9 doesn't build a
    bizarre INTERVAL."""
    src = _niche_source()
    assert re.search(r"\bmin\s*\(\s*max_hours_old\s*,\s*8760", src), (
        "max_hours_old must be clamped to <=8760 before binding to SQL"
    )
    print("✅ test_clamp_prevents_absurd_interval")


TESTS = [
    test_niche_file_exists,
    test_list_videos_signature_has_max_hours_old,
    test_select_uses_live_epoch_calc_not_stored_column,
    test_where_clause_supports_max_hours_old_filter,
    test_max_hours_old_is_parameterized_not_interpolated,
    test_sort_map_still_whitelisted,
    test_clamp_prevents_absurd_interval,
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
