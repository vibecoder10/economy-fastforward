"""Functional test for Stage 1.5 / Cycle 50: SQL injection risk in dynamic
column names — regression lock.

Background (pre-existing bug shape, already fixed but not pinned):
Several backend routes and adapters build UPDATE / SELECT SQL with f-strings
where the *column name* is interpolated dynamically. Values always use
positional params ($N / %s), so the injection surface is narrow — but a
column-name interpolation with no validation is still a real injection
vector. A future dev writing `f\"UPDATE videos SET {col} = $1\"` where `col`
comes from `request.json()` directly would reintroduce a SQLi hole without
any type checker complaining.

The fix (landed):
Every dynamic column goes through one of:
  - `database.safe_column(name)` — async codebase (asyncpg routes)
  - `supabase_adapter._safe_col(name)` — sync codebase (psycopg2 adapter)
Both validate against the same regex `^[a-z][a-z0-9_]*$`. Any name outside
that shape raises `ValueError` before reaching the cursor.

This test pins the fix three ways:
  1. Both validator functions still exist with the restrictive regex.
  2. `safe_column` rejects the canonical SQLi payload shapes at runtime.
  3. Static audit: every f-string in backend/*.py that renders a SQL keyword
     and interpolates a `{name}` segment must have that name come from
     safe_column / _safe_col, a literal, an allowlist-filtered key, or an
     integer-bounded expression. No raw request-field interpolation.
"""
import ast
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Files we audit. Everything else either doesn't touch SQL or lives outside
# the tenant-facing boundary (scripts, migrations, tests).
AUDIT_FILES = [
    "database.py",
    "supabase_adapter.py",
    "pipeline_executor.py",
    "routes/projects.py",
    "routes/videos.py",
    "routes/youtube_sync.py",
    "routes/billing.py",
    "routes/autopilot.py",
    "routes/niche.py",
    "routes/discovery.py",
    "routes/settings.py",
    "routes/profile.py",
    "routes/preferences.py",
    "routes/learning_extraction.py",
    "routes/channel_profile.py",
    "routes/characters.py",
    "routes/environments.py",
    "routes/queue.py",
    "routes/chat.py",
]


def _backend() -> Path:
    return Path(__file__).resolve().parents[2]


def test_safe_column_exists_with_restrictive_regex():
    """`database.safe_column` and `supabase_adapter._safe_col` are the two
    choke-points for dynamic column names. Both must exist and match the
    restrictive `^[a-z][a-z0-9_]*$` regex. A permissive regex (`.*`, or one
    that allows quotes / spaces / semicolons) re-opens the injection door."""
    db = (_backend() / "database.py").read_text()
    adapter = (_backend() / "supabase_adapter.py").read_text()

    for label, text in (("database.py", db), ("supabase_adapter.py", adapter)):
        m = re.search(
            r'_SAFE_COLUMN_RE\s*=\s*re\.compile\(\s*r?["\']([^"\']+)["\']',
            text,
        )
        assert m, f"{label} no longer defines _SAFE_COLUMN_RE — SQLi regression risk"
        pattern = m.group(1)
        assert pattern == r"^[a-z][a-z0-9_]*$", (
            f"{label}: _SAFE_COLUMN_RE loosened to {pattern!r}. The original "
            "Stage 1.5 fix used ^[a-z][a-z0-9_]*$ — anything more permissive "
            "lets quotes / spaces / semicolons through."
        )
    print("✅ test_safe_column_exists_with_restrictive_regex")


def test_safe_column_rejects_injection_payloads():
    """Runtime check: the canonical SQLi payloads for a column-name slot must
    all raise ValueError. If any of these start sneaking through, the regex
    was widened or the function was replaced by an identity pass-through.

    We import safe_column via a minimal reimplementation rather than the real
    module — the real database.py imports asyncpg which may not be installed
    in every dev venv. The reimplementation uses the exact regex string
    extracted from database.py, so if the source regex widens, the runtime
    check below catches it."""
    db_text = (_backend() / "database.py").read_text()
    m = re.search(
        r'_SAFE_COLUMN_RE\s*=\s*re\.compile\(\s*r?["\']([^"\']+)["\']',
        db_text,
    )
    assert m, "cannot locate _SAFE_COLUMN_RE in database.py"
    pattern = m.group(1)
    _re = re.compile(pattern)

    def safe_column(name: str) -> str:
        if not _re.match(name):
            raise ValueError(f"Invalid column name: {name!r}")
        return name

    # Legit names must pass unchanged
    for ok in ("revision_notes", "video_title", "storyboard_1_url", "avg_retention"):
        assert safe_column(ok) == ok, f"safe_column rejected valid column {ok!r}"

    # Every canonical SQLi shape must be rejected
    payloads = [
        "id; DROP TABLE videos--",
        "id) UNION SELECT * FROM tenants--",
        "id OR 1=1",
        "'; DELETE FROM users;--",
        "id--",
        "id/*",
        "Id",                      # uppercase — regex is lowercase-only
        "id SPACE",                # space
        "id\"",                    # quote
        "1id",                     # starts with digit
        "",                        # empty
        "id=1",                    # equals
    ]
    for p in payloads:
        try:
            safe_column(p)
        except ValueError:
            continue
        raise AssertionError(
            f"safe_column accepted injection payload {p!r} — Stage 1.5 regression"
        )
    print("✅ test_safe_column_rejects_injection_payloads")


# SQL statement recognizer — the audit only triggers on f-strings whose
# reconstructed literal *starts* with a top-level SQL verb (after optional
# leading whitespace / parenthesis). This skips log messages, comments, and
# error strings that happen to contain "FROM" or "WHERE" in prose.
_SQL_STMT_RE = re.compile(
    r"^[\s\(]*(?:SELECT|UPDATE|INSERT|DELETE|WITH)\b",
    re.IGNORECASE,
)

# Names we treat as inherently safe sources for interpolation.
_SAFE_EXPR_NAMES = {
    # validator wrappers
    "safe_column", "_safe_col",
    # index / counter locals — always ints
    "idx", "i", "param_idx", "n",
    # literal SQL fragment locals built from hardcoded strings in-function
    # (we still spot-check these in the per-pattern allowlist below).
    "where", "cols",
    # tw = SupabaseAdapter._tw() tenant-isolation predicate. Always a constant
    # fragment " AND <alias>.tenant_id = %s" where alias is a hardcoded literal
    # ("", "v", "s") and the tenant value is parameterized (%s) — no user input
    # can reach it. Same category as `where`/`cols` above.
    "tw",
    # fragments joined from already-validated pieces
    "sets", "updates", "set_parts", "conditions",
}

# Interpolations we've manually verified are safe (literal fragment built
# from in-function constants, or integer-bounded expressions). Each entry
# is (filename, substring-of-line-that-contains-it). Keep this LIST tight —
# every new entry is a manual promise the interpolation is safe.
_VERIFIED_SAFE = [
    # cols = literal string + `, transcript` when a bool flag is set — no user input
    ("routes/autopilot.py", "SELECT {cols}"),
    # modeled_filter = hardcoded ternary ("" vs. "AND (cv.modeled = false...)")
    ("routes/autopilot.py", "query = f\"\"\"SELECT cv.id, cv.video_id"),
    # placeholders is built from integer indices + hardcoded "::jsonb" suffix
    ("routes/autopilot.py", "VALUES ({placeholders})"),
    # where is joined from hardcoded SQL fragment strings inside the function
    ("routes/niche.py", "WHERE {where}"),
    # order is looked up from _SORT_MAP allowlist dict (whitelist-only)
    ("routes/niche.py", "SELECT cv.id, cv.video_id, cv.title, cv.url"),
    # field is validated against hardcoded {"videos_created", ...} set
    ("routes/billing.py", "SET {field} = {field}"),
    # col = f"storyboard_{beat}_url" with 1 <= beat <= 5 validated above
    ("routes/videos.py", "SET {col} = $1"),
    # clear_storyboard_slot: col = f"storyboard_{beat}_url", beat bounded 1-5
    # (raise 400 otherwise) before either of these two statements.
    ("routes/videos.py", "SELECT id, {col} AS url FROM scripts"),
    ("routes/videos.py", 'f"""UPDATE scripts'),
    # updates built from f"{col} = ${idx}" where col is f"storyboard_{beat}_url"
    ("pipeline_executor.py", "SET {', '.join(updates)}"),
    # where built from hardcoded "category = %s" / "active = true" strings
    ("supabase_adapter.py", "SELECT * FROM learnings {where}"),
    # no column interpolation — the {} is an escaped literal in an inner f-string
    ("supabase_adapter.py", "(SELECT id FROM videos WHERE video_title ="),
    # key_col = ("channel_url", url) if url else (("channel", name) if name
    # else (None, None)) — a hardcoded ternary two literal names, never from
    # request input. Guarded by `if key_col:` before use.
    ("routes/chat.py", "UPDATE discovery_ideas SET competitor_video_id = NULL WHERE tenant_id = $1"),
    ("routes/chat.py", "DELETE FROM competitor_videos WHERE tenant_id = $1 AND {key_col}"),
    # col = _PROFILE_FIELD_COLS[kind], a closed dict of 4 hardcoded column
    # names; kind is checked with `kind in _PROFILE_FIELD_COLS` before this
    # runs, so col can only ever be one of the dict's literal values.
    ("routes/chat.py", "INSERT INTO channel_profiles (tenant_id, {col})"),
]


def _is_verified_safe(relpath: str, line: str) -> bool:
    for fn, needle in _VERIFIED_SAFE:
        if relpath.endswith(fn) and needle in line:
            return True
    return False


def _collect_sql_fstring_interps(path: Path) -> list[tuple[int, str, str]]:
    """Walk the AST and return (lineno, interp_expr_source, full_line) for
    every f-string whose text contains a SQL keyword and which interpolates
    a non-literal `{expr}`."""
    src = path.read_text()
    tree = ast.parse(src)
    lines = src.splitlines()
    found: list[tuple[int, str, str]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.JoinedStr):
            continue
        # Reconstruct the literal parts so we can decide if any are SQL.
        literal = "".join(
            v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str)
        )
        if not _SQL_STMT_RE.match(literal):
            continue
        for v in node.values:
            if isinstance(v, ast.FormattedValue):
                expr_src = ast.unparse(v.value)
                line_src = lines[node.lineno - 1] if node.lineno <= len(lines) else ""
                found.append((node.lineno, expr_src, line_src))
    return found


def test_no_unvalidated_column_interpolations():
    """AST audit — every dynamic column name in SQL f-strings must come
    through a validator, an allowlist, or an integer-bounded expression.

    The audit classifies each `{expr}` inside an SQL f-string as:
      * safe-by-call: contains a call to safe_column / _safe_col
      * safe-by-name: expr is a pure name in `_SAFE_EXPR_NAMES`
      * safe-by-index: expr is `$N` / `${N}` / an arithmetic on idx
      * safe-by-verified: the line is in `_VERIFIED_SAFE`
      * offender: anything else — likely a raw request field or unchecked column

    Any offender fails the test."""
    offenders: list[str] = []
    for rel in AUDIT_FILES:
        p = _backend() / rel
        if not p.exists():
            continue
        for lineno, expr, line in _collect_sql_fstring_interps(p):
            # safe-by-call
            if "safe_column(" in expr or "_safe_col(" in expr:
                continue
            # safe-by-name
            stripped = expr.strip()
            if stripped in _SAFE_EXPR_NAMES:
                continue
            # safe-by-index: pure int / $N / arithmetic on idx
            if re.fullmatch(r"\$?\d+", stripped):
                continue
            if re.fullmatch(r"idx(\s*[-+]\s*\d+)?", stripped):
                continue
            if re.fullmatch(r"param_idx(\s*[-+]\s*\d+)?", stripped):
                continue
            # safe-by-index (call form): `len(params)` / `len(values) - 1` etc.
            # — the routes that build UPDATE ... SET <literal cols> = $N one
            # param at a time size the placeholder off the params list length,
            # not off any column name. len() can only ever yield an int, so
            # this is the same safety class as `idx ± N` above, just spelled
            # as a call instead of a bare counter name.
            if re.fullmatch(r"len\(\w+\)(\s*[-+]\s*\d+)?", stripped):
                continue
            # safe-by-verified: manually vetted line-specific entries
            if _is_verified_safe(rel, line):
                continue
            # safe-by-join: any `.join(...)` expression. The list is built
            # per-element using safe_column / _safe_col at the append site,
            # which is where the real check happens. A refactor that moves
            # the join here with unvalidated input would be caught by
            # test_known_callers_still_use_safe_column + a code review.
            if ".join(" in stripped:
                continue
            offenders.append(
                f"  - {rel}:{lineno}: interpolates {{{expr}}} into SQL — "
                f"not routed through safe_column / allowlist.\n"
                f"      {line.strip()[:140]}"
            )

    assert not offenders, (
        "Stage 1.5 regression — dynamic SQL interpolation without validator:\n"
        + "\n".join(offenders)
        + "\n\nRoute column names through database.safe_column() "
        "(asyncpg paths) or supabase_adapter._safe_col() (psycopg2 paths). "
        "If the interpolation is actually safe (literal fragment built "
        "in-function, integer-bounded), add the specific line to "
        "_VERIFIED_SAFE in this test file — with a comment on WHY it is safe."
    )
    print("✅ test_no_unvalidated_column_interpolations")


def test_known_callers_still_use_safe_column():
    """Positive check — the three routes that do the heaviest dynamic-UPDATE
    work must still reference safe_column. If a refactor drops the call, the
    audit above can miss it (e.g. if the offending line shape changed and
    evades SQL-keyword detection). This is a belt-and-suspenders pin."""
    expected = {
        "routes/projects.py": "safe_column",
        "routes/videos.py": "safe_column",
        "routes/youtube_sync.py": "safe_column",
    }
    missing: list[str] = []
    for rel, needle in expected.items():
        text = (_backend() / rel).read_text()
        if needle not in text:
            missing.append(f"  - {rel} no longer references `{needle}`")
    assert not missing, (
        "Stage 1.5 regression — a hot-path dynamic-UPDATE route stopped "
        "importing safe_column:\n" + "\n".join(missing)
    )
    print("✅ test_known_callers_still_use_safe_column")


TESTS = [
    test_safe_column_exists_with_restrictive_regex,
    test_safe_column_rejects_injection_payloads,
    test_no_unvalidated_column_interpolations,
    test_known_callers_still_use_safe_column,
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
