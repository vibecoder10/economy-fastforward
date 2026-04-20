"""Functional test for SEC-SQL-001: prove supabase_adapter.py rejects
non-allowlisted column names before they reach dynamic SQL.

Today, column names in f-string UPDATE queries come from fixed FIELD_MAP
dicts — values are hand-written constants, so nothing hostile can reach
the interpolation point. This test doesn't prove that's currently true
(it IS, by inspection); it proves a FUTURE refactor that accidentally
wires a user-controllable string into a column-name position fails fast
with a ValueError rather than producing a SQL-injection vector.

The helper under test is `supabase_adapter._safe_col`. The integration
contract is: every f-string SQL path that interpolates a column name
must pass through _safe_col, and _safe_col must reject anything that
isn't `[a-z][a-z0-9_]*`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import supabase_adapter


MALICIOUS_COLUMN_NAMES = [
    # Classic injection shapes
    "status; DROP TABLE videos;--",
    "status', (SELECT pg_sleep(10))--",
    "status' OR '1'='1",
    "1=1",
    # Subtle — UPPERCASE column names aren't in the allowlist
    "STATUS",
    "Status",
    # Leading digit
    "1col",
    # Leading underscore (also rejected — the regex requires [a-z] first)
    "_internal",
    # Spaces, special chars, null bytes
    "video title",
    "video\x00title",
    "video-title",
    "video.title",
    "",
    "   ",
    # Function calls
    "pg_sleep(10)",
    "now()",
]


SAFE_COLUMN_NAMES = [
    "status",
    "video_title",
    "voice_over_url",
    "avg_view_duration_seconds",
    "views_24h",
    "ctr_48h",
    # Single char is fine
    "a",
    # Trailing digits fine
    "col1",
]


def test_safe_col_rejects_malicious_names():
    for bad in MALICIOUS_COLUMN_NAMES:
        try:
            result = supabase_adapter._safe_col(bad)
        except ValueError:
            continue
        except Exception as e:
            raise AssertionError(
                f"_safe_col({bad!r}) raised {type(e).__name__} instead of ValueError: {e}"
            )
        raise AssertionError(
            f"_safe_col({bad!r}) did not raise — returned {result!r}. "
            f"This column name would have reached dynamic SQL."
        )
    print("✅ test_safe_col_rejects_malicious_names")


def test_safe_col_accepts_real_column_names():
    for good in SAFE_COLUMN_NAMES:
        result = supabase_adapter._safe_col(good)
        assert result == good, f"_safe_col({good!r}) mutated input: {result!r}"
    print("✅ test_safe_col_accepts_real_column_names")


def test_safe_col_rejects_non_string_types():
    """Defense-in-depth: None, ints, bytes must all raise."""
    for bad in [None, 123, 1.0, b"status", ["status"], {"status": 1}, object()]:
        try:
            supabase_adapter._safe_col(bad)
        except ValueError:
            continue
        except Exception as e:
            raise AssertionError(
                f"_safe_col({bad!r}) raised {type(e).__name__} instead of ValueError: {e}"
            )
        raise AssertionError(
            f"_safe_col({bad!r}) did not raise — non-string bypassed validation."
        )
    print("✅ test_safe_col_rejects_non_string_types")


def test_every_field_map_value_is_safe():
    """The column names IN the FIELD_MAP dicts today must all pass _safe_col.
    If they don't, the adapter is shipping broken code — we'd raise on every
    update. This is the positive counterpart to the static audit."""
    maps = {
        "IDEA_FIELD_MAP": supabase_adapter.IDEA_FIELD_MAP,
        "SCRIPT_FIELD_MAP": supabase_adapter.SCRIPT_FIELD_MAP,
    }
    # Include any other FIELD_MAPs defined in the module.
    for attr_name in dir(supabase_adapter):
        if attr_name.endswith("_FIELD_MAP") and attr_name not in maps:
            maps[attr_name] = getattr(supabase_adapter, attr_name)

    failures = []
    for map_name, mapping in maps.items():
        for airtable_name, col_name in mapping.items():
            try:
                supabase_adapter._safe_col(col_name)
            except Exception as e:
                failures.append(f"{map_name}[{airtable_name!r}] = {col_name!r}: {e}")

    assert not failures, (
        "FIELD_MAP column names fail _safe_col — adapter would raise at runtime:\n"
        + "\n".join(failures)
    )
    print(f"✅ test_every_field_map_value_is_safe ({sum(len(m) for m in maps.values())} entries checked)")


# ───────────────────────── static audit ─────────────────────────

def test_no_unguarded_col_interpolation_in_dynamic_sql():
    """Every `sets.append(f"{col} = %s")` pattern in supabase_adapter.py
    must wrap col in _safe_col(). Catches a regression where a future
    edit forgets the wrap."""
    import re
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "supabase_adapter.py"
    text = path.read_text()

    # Unguarded shape: sets.append(f"{col} = %s")  — no _safe_col wrap
    unguarded = re.findall(
        r'sets\.append\(f["\']\{col\}\s*=',
        text,
    )
    assert not unguarded, (
        "supabase_adapter.py has unguarded column-name interpolation "
        f"({len(unguarded)} occurrence(s)) — wrap col in _safe_col(col):\n"
        + "\n".join(unguarded)
    )

    # Also flag any f-string with a bare {col} in SQL context (covers the
    # partial-fallback pattern at line ~472).
    # Allow {_safe_col(col)} but flag bare {col} inside f"UPDATE ..."
    lines = text.splitlines()
    bare_col_leaks = []
    for i, line in enumerate(lines, 1):
        # Skip comments/docstrings approximately.
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        # Look at any f-string SQL that contains {col} without _safe_col
        if re.search(r'f["\'](UPDATE|SELECT|INSERT|DELETE)[^"\']*\{col\}', line):
            if "_safe_col" not in line:
                bare_col_leaks.append(f"  line {i}: {line.strip()}")

    assert not bare_col_leaks, (
        "supabase_adapter.py has bare {col} interpolation in SQL:\n"
        + "\n".join(bare_col_leaks)
    )
    print("✅ test_no_unguarded_col_interpolation_in_dynamic_sql")


TESTS = [
    test_safe_col_rejects_malicious_names,
    test_safe_col_accepts_real_column_names,
    test_safe_col_rejects_non_string_types,
    test_every_field_map_value_is_safe,
    test_no_unguarded_col_interpolation_in_dynamic_sql,
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
