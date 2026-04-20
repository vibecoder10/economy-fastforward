"""Functional test for Stage 3.4: prove the frontend has exactly one place
where NEXT_PUBLIC_API_URL / NEXT_PUBLIC_RUBRIC_URL is read, and that place
throws in production if the env is missing.

Pre-fix (as of 2026-04-19), 4 separate files each had their own
    const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";
fallback. Next.js bakes NEXT_PUBLIC_* into the client bundle at BUILD time,
so a misconfigured prod build would ship artifacts that silently called
localhost — users saw broken dashboards; we saw no error.

Cycle 32 centralized the resolution in frontend/src/lib/env.ts with a guard:
in production, a missing env throws at module init (which surfaces during
`next build` or at first server render). Dev keeps the localhost fallback.

This test pins the contract: the next time someone copy-pastes the old
fallback pattern, or reads process.env.NEXT_PUBLIC_API_URL directly outside
of lib/env.ts, CI fails before merge.
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _frontend_src() -> Path:
    # tests/functional/ → backend/ → storyengine/ → frontend/src
    return Path(__file__).resolve().parents[3] / "frontend" / "src"


def _env_ts() -> Path:
    return _frontend_src() / "lib" / "env.ts"


def _all_ts_files() -> list[Path]:
    """Every .ts / .tsx file under frontend/src (excluding test output)."""
    out = []
    for p in _frontend_src().rglob("*.ts"):
        out.append(p)
    for p in _frontend_src().rglob("*.tsx"):
        out.append(p)
    return sorted(out)


def test_env_ts_exists_and_is_the_single_source():
    """lib/env.ts must exist and export API_URL + RUBRIC_URL."""
    path = _env_ts()
    assert path.exists(), f"lib/env.ts not at {path}"
    text = path.read_text()
    assert "export const API_URL" in text, "lib/env.ts missing API_URL export"
    assert "export const RUBRIC_URL" in text, "lib/env.ts missing RUBRIC_URL export"
    print("✅ test_env_ts_exists_and_is_the_single_source")


def test_env_ts_throws_in_production_when_missing():
    """lib/env.ts must throw (not silently fall back) when NODE_ENV is
    production and the env var is unset. This is what converts a
    misconfigured build from 'silent localhost' to 'loud failure'."""
    text = _env_ts().read_text()
    # Look for a guard that checks production AND throws.
    assert "production" in text, "lib/env.ts missing NODE_ENV=production guard"
    assert "throw" in text, "lib/env.ts missing throw for missing prod env"
    # Defense in depth: the guard must reference both env names so adding
    # a new public URL without a guard is caught.
    assert "NEXT_PUBLIC_API_URL" in text
    assert "NEXT_PUBLIC_RUBRIC_URL" in text
    print("✅ test_env_ts_throws_in_production_when_missing")


def test_no_inline_localhost_fallback_anywhere_else():
    """Regression guard: grep for the exact old fallback pattern outside
    lib/env.ts. If someone copy-pastes it back, this fails."""
    pattern = re.compile(
        r"process\.env\.NEXT_PUBLIC_(API|RUBRIC)_URL\s*\|\|\s*['\"]http://localhost:"
    )
    offenders = []
    for p in _all_ts_files():
        if p == _env_ts():
            continue
        text = p.read_text()
        for m in pattern.finditer(text):
            offenders.append(f"  - {p.relative_to(_frontend_src())}: {m.group(0)}")

    assert not offenders, (
        "Inline localhost fallback resurrected outside lib/env.ts:\n"
        + "\n".join(offenders)
        + "\n\nImport from '@/lib/env' (or './env' if inside lib/) instead — "
        "the centralized version throws in prod if the env is missing."
    )
    print(f"✅ test_no_inline_localhost_fallback_anywhere_else "
          f"({len(_all_ts_files())} ts/tsx files scanned)")


def test_no_direct_next_public_url_reads_outside_env_ts():
    """Stronger guard: no file outside lib/env.ts may read
    process.env.NEXT_PUBLIC_API_URL or _RUBRIC_URL directly. Forces all
    callers through the centralized, guarded resolver."""
    pattern = re.compile(r"process\.env\.NEXT_PUBLIC_(API|RUBRIC)_URL")
    offenders = []
    for p in _all_ts_files():
        if p == _env_ts():
            continue
        text = p.read_text()
        for m in pattern.finditer(text):
            # Show the line for context
            line_num = text[:m.start()].count("\n") + 1
            offenders.append(
                f"  - {p.relative_to(_frontend_src())}:{line_num}: "
                f"reads {m.group(0)} directly"
            )

    assert not offenders, (
        "Direct process.env.NEXT_PUBLIC_*_URL read outside lib/env.ts:\n"
        + "\n".join(offenders)
        + "\n\nImport API_URL / RUBRIC_URL from '@/lib/env' instead. "
        "The centralized resolver throws in prod if the env is missing."
    )
    print("✅ test_no_direct_next_public_url_reads_outside_env_ts")


def test_env_ts_is_actually_imported_by_known_callers():
    """Positive check: the 4 files Cycle 32 migrated all import from
    @/lib/env (or ./env). If a migration gets reverted, this catches it."""
    expected = [
        _frontend_src() / "lib" / "api.ts",
        _frontend_src() / "hooks" / "use-pipeline-sse.ts",
        _frontend_src() / "app" / "demo" / "page.tsx",
        _frontend_src() / "app" / "settings" / "drive-callback" / "page.tsx",
    ]
    import_pat = re.compile(
        r'from\s+[\'"](?:@/lib/env|\./env|\.\./lib/env)[\'"]'
    )
    missing = []
    for p in expected:
        if not p.exists():
            missing.append(f"  - {p.relative_to(_frontend_src())} (file missing)")
            continue
        if not import_pat.search(p.read_text()):
            missing.append(
                f"  - {p.relative_to(_frontend_src())} (no import from env)"
            )

    assert not missing, (
        "Known caller(s) no longer import from lib/env — did someone revert "
        "the centralization?\n" + "\n".join(missing)
    )
    print(f"✅ test_env_ts_is_actually_imported_by_known_callers "
          f"({len(expected)} callers verified)")


TESTS = [
    test_env_ts_exists_and_is_the_single_source,
    test_env_ts_throws_in_production_when_missing,
    test_no_inline_localhost_fallback_anywhere_else,
    test_no_direct_next_public_url_reads_outside_env_ts,
    test_env_ts_is_actually_imported_by_known_callers,
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
