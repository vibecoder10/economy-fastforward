"""Functional test for Stage 6.4 sub-fix #3: competitors page UI exposes
the age filter (max_hours_old) to the user. Cycles 33 + 34 made the
backend dynamic and ungated the scrape; this cycle wires it through to
the frontend so a user can actually filter the grid to "last 24h" /
"3d" / "7d" / "All".

Source-audit pattern (no live browser). Verifies:
  - api.ts accepts max_hours_old on getNicheVideos
  - competitors/page.tsx has the maxHoursOld state
  - maxHoursOld feeds into the getNicheVideos call
  - maxHoursOld is in the react-query queryKey (otherwise the filter
    wouldn't trigger a refetch — silent-bug trap)
  - The "24h" / "3d" / "7d" / "All" pill labels are rendered
  - The useEffect page-reset includes maxHoursOld (otherwise changing
    the filter on page 3 gives an empty grid)
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _frontend_root() -> Path:
    # tests/functional/this -> backend -> storyengine -> frontend
    return Path(__file__).resolve().parents[3] / "frontend"


def _api_ts() -> Path:
    return _frontend_root() / "src" / "lib" / "api.ts"


def _page_tsx() -> Path:
    return _frontend_root() / "src" / "app" / "competitors" / "page.tsx"


def test_files_exist():
    assert _api_ts().exists(), f"api.ts not at {_api_ts()}"
    assert _page_tsx().exists(), f"page.tsx not at {_page_tsx()}"
    print("✅ test_files_exist")


def test_api_getNicheVideos_accepts_max_hours_old():
    """getNicheVideos param type and URLSearchParams branch must both
    handle max_hours_old. Missing either side silently drops the value."""
    src = _api_ts().read_text()
    # Param type declaration
    assert re.search(r"max_hours_old\?:\s*number", src), (
        "api.ts getNicheVideos param type missing max_hours_old?: number"
    )
    # URLSearchParams wiring
    assert re.search(
        r'params\?\.max_hours_old.*searchParams\.set\(\s*["\']max_hours_old["\']',
        src,
        re.DOTALL,
    ), "api.ts missing searchParams.set for max_hours_old"
    print("✅ test_api_getNicheVideos_accepts_max_hours_old")


def test_page_has_maxHoursOld_state():
    """The useState must allow undefined (= 'All') — a plain number
    default would silently apply a filter on first load."""
    src = _page_tsx().read_text()
    assert re.search(
        r"useState<number\s*\|\s*undefined>\(\s*undefined\s*\)",
        src,
    ), "competitors/page.tsx missing useState<number|undefined>(undefined) for age filter"
    assert "setMaxHoursOld" in src, "setMaxHoursOld setter not present"
    print("✅ test_page_has_maxHoursOld_state")


def test_page_passes_max_hours_old_to_query():
    """maxHoursOld must land in both the queryKey (for refetch) and the
    getNicheVideos call (for the actual request)."""
    src = _page_tsx().read_text()
    # queryKey array includes maxHoursOld
    qk = re.search(
        r'queryKey:\s*\["niche-videos"[^\]]*maxHoursOld[^\]]*\]',
        src,
    )
    assert qk, "maxHoursOld missing from niche-videos queryKey — filter won't refetch"
    # The getNicheVideos call passes max_hours_old
    assert re.search(
        r"max_hours_old:\s*maxHoursOld",
        src,
    ), "getNicheVideos call not forwarding max_hours_old: maxHoursOld"
    print("✅ test_page_passes_max_hours_old_to_query")


def test_page_reset_effect_includes_maxHoursOld():
    """useEffect that resets page on filter change must include maxHoursOld,
    otherwise flipping the age filter on page 3 of 5 can show an empty
    grid and confuse the user."""
    src = _page_tsx().read_text()
    m = re.search(
        r"setPage\(0\);\s*\n\s*\}\s*,\s*\[([^\]]+)\]",
        src,
    )
    assert m, "could not find setPage(0) useEffect dep array"
    deps = m.group(1)
    assert "maxHoursOld" in deps, (
        f"page-reset useEffect deps missing maxHoursOld: [{deps}]"
    )
    print("✅ test_page_reset_effect_includes_maxHoursOld")


def test_page_renders_age_filter_pills():
    """All four age pills must be present. Labels are user-facing, so
    exact strings matter."""
    src = _page_tsx().read_text()
    for lbl in ("24h", "3d", "7d", "All"):
        assert re.search(
            rf'label:\s*["\']{lbl}["\']',
            src,
        ), f"age filter pill label {lbl!r} not found"
    # And the numeric mapping (hours) must be 24 / 72 / 168
    for hrs in ("24", "72", "168"):
        assert re.search(rf"value:\s*{hrs}\b", src), (
            f"age filter pill value {hrs} not found — should map to 1d/3d/7d"
        )
    # Guard: also a value: undefined for "All"
    assert re.search(r"value:\s*undefined", src), (
        "age filter pill value: undefined (All) not present — without it the All pill would be a no-op"
    )
    print("✅ test_page_renders_age_filter_pills")


TESTS = [
    test_files_exist,
    test_api_getNicheVideos_accepts_max_hours_old,
    test_page_has_maxHoursOld_state,
    test_page_passes_max_hours_old_to_query,
    test_page_reset_effect_includes_maxHoursOld,
    test_page_renders_age_filter_pills,
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
