"""Functional test for Stage 3.4 / Cycle 51: hardcoded localhost fallback
in the frontend — regression lock.

The bug (pre-fix): `frontend/src/lib/api.ts` and several ad-hoc call-sites
each did `process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001"`. If a
production deploy shipped without `NEXT_PUBLIC_API_URL` set, every API call
silently went to localhost — the browser made requests to a host that
doesn't exist in prod, and the UI just showed empty dashboards. No error,
no toast, no Sentry hit (we don't have Sentry yet either).

The fix (landed):
1. Single source of truth `frontend/src/lib/env.ts` reads
   `process.env.NEXT_PUBLIC_API_URL` once at module scope — Next.js only
   inlines NEXT_PUBLIC_* for literal property access, so reading it once
   at module top is the only shape that reaches the client bundle.
2. `requireInProd()` throws at build/run time if the var is empty and
   `NODE_ENV === "production"`. Dev gets the `http://localhost:8001`
   fallback explicitly.
3. Every other file imports `API_URL` from `@/lib/env` — no direct
   `process.env.NEXT_PUBLIC_API_URL` reads, no inline localhost fallbacks.

This test pins the fix three ways so a refactor can't silently re-introduce
the footgun:
  - `env.ts` still reads `NEXT_PUBLIC_API_URL` as a literal property access
    AND still has the `NODE_ENV === "production"` throw gate.
  - No other file in `frontend/src/` reads `process.env.NEXT_PUBLIC_API_URL`
    directly — the centralization is load-bearing.
  - No file in `frontend/src/` outside `env.ts` hardcodes a localhost URL
    with the API ports (8001 / 5050) as a fallback or default.
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _frontend_src() -> Path:
    return Path(__file__).resolve().parents[3] / "frontend" / "src"


def _env_ts() -> Path:
    return _frontend_src() / "lib" / "env.ts"


def test_env_ts_reads_literal_and_guards_prod():
    """env.ts must read the env var as a literal property access (only shape
    Next.js inlines into the browser bundle) AND must refuse to fall back to
    localhost in production."""
    text = _env_ts().read_text()

    # Literal access — the exact expression Next.js recognizes as inlinable
    assert re.search(
        r"process\.env\.NEXT_PUBLIC_API_URL\b", text
    ), (
        "lib/env.ts no longer reads `process.env.NEXT_PUBLIC_API_URL` as a "
        "literal property access. Dynamic reads (`process.env[name]`) are "
        "NOT inlined by Next.js into the client bundle — the URL becomes "
        "undefined at runtime in the browser."
    )

    # Production throw gate — the fix hinges on this
    assert re.search(
        r'NODE_ENV\s*===\s*["\']production["\']', text
    ), (
        "lib/env.ts no longer gates on `NODE_ENV === \"production\"`. The "
        "localhost fallback must ONLY apply in dev — any prod deploy missing "
        "NEXT_PUBLIC_API_URL must throw, not silently hit localhost."
    )
    assert "throw new Error" in text, (
        "lib/env.ts `requireInProd` no longer throws on missing-in-prod. "
        "Silent fallback to localhost was the original Stage 3.4 bug."
    )
    print("✅ test_env_ts_reads_literal_and_guards_prod")


def test_no_other_file_reads_next_public_api_url():
    """Centralization is the point. If any other file reads
    `process.env.NEXT_PUBLIC_API_URL` directly, it bypasses the prod-guard in
    env.ts and can re-introduce the silent-localhost-in-prod bug."""
    offenders: list[str] = []
    src = _frontend_src()
    for p in src.rglob("*.ts"):
        if p.resolve() == _env_ts().resolve():
            continue
        text = p.read_text()
        if "process.env.NEXT_PUBLIC_API_URL" in text:
            offenders.append(f"  - {p.relative_to(src.parent)}")
    for p in src.rglob("*.tsx"):
        text = p.read_text()
        if "process.env.NEXT_PUBLIC_API_URL" in text:
            offenders.append(f"  - {p.relative_to(src.parent)}")
    assert not offenders, (
        "Stage 3.4 regression — frontend file reads "
        "`process.env.NEXT_PUBLIC_API_URL` directly, bypassing the prod "
        "guard in lib/env.ts:\n" + "\n".join(offenders)
        + "\n\nImport `API_URL` from `@/lib/env` instead. Only env.ts reads "
        "the raw env var (the Next.js inline rule requires one literal "
        "property access at module scope)."
    )
    print("✅ test_no_other_file_reads_next_public_api_url")


def test_no_hardcoded_localhost_api_fallback():
    """No .ts/.tsx outside lib/env.ts may mention the dev API port (8001)
    or RUBRIC port (5050). If one sneaks back in — even as a fallback on
    `||` — the centralized guard is bypassed and prod silently breaks."""
    patterns = [
        re.compile(r"http://localhost:8001"),
        re.compile(r"http://localhost:5050"),
    ]
    offenders: list[str] = []
    src = _frontend_src()
    for p in list(src.rglob("*.ts")) + list(src.rglob("*.tsx")):
        if p.resolve() == _env_ts().resolve():
            continue
        text = p.read_text()
        for pat in patterns:
            for m in pat.finditer(text):
                # Report line context
                line_num = text[: m.start()].count("\n") + 1
                line = text.splitlines()[line_num - 1] if line_num <= len(text.splitlines()) else ""
                offenders.append(
                    f"  - {p.relative_to(src.parent)}:{line_num} — "
                    f"{line.strip()[:120]}"
                )
    assert not offenders, (
        "Stage 3.4 regression — hardcoded localhost URL found outside "
        "lib/env.ts. The centralized guard in env.ts is the only allowed "
        "place for a dev-fallback:\n" + "\n".join(offenders)
    )
    print("✅ test_no_hardcoded_localhost_api_fallback")


def test_api_ts_imports_from_env_module():
    """Positive check: lib/api.ts is the primary API-call surface — if it
    stops importing API_URL from the centralized env module, it has
    probably been changed to read the env var directly again."""
    api_ts = _frontend_src() / "lib" / "api.ts"
    text = api_ts.read_text()
    assert re.search(r'from\s+["\']\./env["\']', text) or re.search(
        r'from\s+["\']@/lib/env["\']', text
    ), (
        "lib/api.ts no longer imports from the centralized `./env` module. "
        "It almost certainly reads `process.env.NEXT_PUBLIC_API_URL` "
        "directly now — Stage 3.4 regression risk."
    )
    assert re.search(
        r"\bAPI_URL\b", text
    ), (
        "lib/api.ts no longer references `API_URL`. If the name changed, "
        "update this test to track the new name — but keep the "
        "centralization invariant."
    )
    print("✅ test_api_ts_imports_from_env_module")


TESTS = [
    test_env_ts_reads_literal_and_guards_prod,
    test_no_other_file_reads_next_public_api_url,
    test_no_hardcoded_localhost_api_fallback,
    test_api_ts_imports_from_env_module,
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
