"""Functional test for Stage 5.3 / Cycle 55: dev-token production-safety
regression lock.

The bug shape being prevented: a developer adds a convenience bypass
like `if token == "dev-token": return fake_user` to let them curl the
API during local dev, and forgets to gate it behind an env flag. Ship
that to prod and every attacker who guesses "dev-token" is logged in
as whatever fake identity the bypass returns — with full tenant access.

The current guard (both copies — `backend/auth.py` and
`backend/routes/videos.py`'s SSE audio stream) is:

    dev_token = os.getenv("DEV_TOKEN")
    if dev_token and token == dev_token and os.getenv("DEV_MODE") == "true":
        # accept as dev user

This is prod-safe because:
  1. `dev_token and ...` — if `DEV_TOKEN` is unset or empty in prod, the
     branch is unreachable regardless of what the client sends.
  2. `token == dev_token` compares the incoming token to whatever secret
     value the env var has — there is no literal `"dev-token"` fallback.
  3. `os.getenv("DEV_MODE") == "true"` — belt-and-suspenders; even if
     someone accidentally leaked the DEV_TOKEN value, DEV_MODE has to be
     flipped on too.

This test pins all three conditions so a refactor can't drop one of
them and silently regress to a permanent backdoor:
  - No literal `"dev-token"`/`"devtoken"` accept branch anywhere in
    `backend/` (the bypass token must come from an env var, not code).
  - `DEV_MODE == "true"` check is present in every file that references
    `DEV_TOKEN`.
  - `DEV_TOKEN` truthy-check is present in every file that references
    `DEV_TOKEN` (so an unset env var is unreachable, not a match-against-
    None).
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _find_dev_token_files() -> list[Path]:
    """Every .py file under backend/ that references DEV_TOKEN."""
    hits: list[Path] = []
    for p in _backend_root().rglob("*.py"):
        # Skip test files — they're allowed to reference DEV_TOKEN freely
        if "/tests/" in str(p):
            continue
        text = p.read_text()
        if "DEV_TOKEN" in text:
            hits.append(p)
    return sorted(hits)


def test_no_literal_dev_token_accept_branch():
    """The guard MUST compare the incoming token to an env var, not to
    a hardcoded string. If `token == "dev-token"` (or similar literal)
    appears as an accept condition, any client can guess it in prod."""
    forbidden_literals = [
        re.compile(r'==\s*["\']dev-token["\']'),
        re.compile(r'==\s*["\']devtoken["\']'),
        re.compile(r'==\s*["\']dev_token["\']'),
        re.compile(r'["\']dev-token["\']\s*==\s*token'),
    ]
    offenders: list[str] = []
    for p in _backend_root().rglob("*.py"):
        if "/tests/" in str(p):
            continue
        text = p.read_text()
        for pat in forbidden_literals:
            for m in pat.finditer(text):
                # Exclude anything inside a string literal that is clearly
                # a comment/docstring (heuristic: if the whole match is
                # inside """..."""). Instead of parsing, just require the
                # match NOT be on a line that starts with `#` or is inside
                # a docstring-like context.
                line_start = text.rfind("\n", 0, m.start()) + 1
                line_end = text.find("\n", m.start())
                line = text[line_start:line_end if line_end != -1 else len(text)]
                if line.lstrip().startswith("#"):
                    continue
                line_num = text[: m.start()].count("\n") + 1
                offenders.append(
                    f"  - {p.relative_to(_backend_root())}:{line_num} — {line.strip()[:140]}"
                )
    assert not offenders, (
        "Stage 5.3 regression — literal `\"dev-token\"` accept branch "
        "found in backend code. Any attacker who sends that exact string "
        "would authenticate in prod:\n" + "\n".join(offenders) + "\n\n"
        "The dev bypass MUST compare against `os.getenv(\"DEV_TOKEN\")`, "
        "not a hardcoded string — and must ALSO gate on "
        "`os.getenv(\"DEV_MODE\") == \"true\"`."
    )
    print("✅ test_no_literal_dev_token_accept_branch")


def test_dev_token_sites_gate_on_dev_mode():
    """Every file that reads DEV_TOKEN must ALSO check DEV_MODE == "true"
    in the same neighborhood. Dropping the DEV_MODE gate leaves a live
    backdoor whenever DEV_TOKEN happens to be set in the environment."""
    offenders: list[str] = []
    for p in _find_dev_token_files():
        text = p.read_text()
        # For each DEV_TOKEN occurrence, look +/- 15 lines for the DEV_MODE check
        for m in re.finditer(r"DEV_TOKEN", text):
            line_num = text[: m.start()].count("\n") + 1
            lines = text.splitlines()
            start = max(0, line_num - 16)
            end = min(len(lines), line_num + 15)
            window = "\n".join(lines[start:end])
            if re.search(r'DEV_MODE.*==\s*["\']true["\']', window):
                continue
            # Also allow the window to contain a *function call* that
            # in turn checks DEV_MODE — skip occurrences inside comments
            # or docstrings heuristically
            line = lines[line_num - 1] if line_num <= len(lines) else ""
            if line.lstrip().startswith("#"):
                continue
            offenders.append(
                f"  - {p.relative_to(_backend_root())}:{line_num} — {line.strip()[:140]}"
            )
    assert not offenders, (
        "Stage 5.3 regression — file references DEV_TOKEN without a "
        "nearby `DEV_MODE == \"true\"` check. If DEV_TOKEN leaks into "
        "the prod env (shared .env, accidentally set), the bypass is "
        "live with no second gate:\n" + "\n".join(offenders)
    )
    print("✅ test_dev_token_sites_gate_on_dev_mode")


def test_dev_token_sites_check_token_truthy():
    """`if dev_token and token == dev_token ...` — the `dev_token and`
    prefix makes the branch unreachable when the env var is unset (rather
    than comparing the incoming token against None). Drop that prefix and
    a client sending empty/None could match."""
    offenders: list[str] = []
    for p in _find_dev_token_files():
        text = p.read_text()
        # We expect to see a pattern like:
        #     dev_token = os.getenv("DEV_TOKEN")
        #     if dev_token and token == dev_token ...
        # OR
        #     if os.getenv("DEV_TOKEN") and ...
        # The invariant: any `token == dev_token`-style comparison must be
        # preceded (in the same boolean expression) by a truthy-check on
        # the env value.
        for m in re.finditer(
            r"(if\s+[^\n:]+token\s*==\s*(?:dev_token|os\.getenv\(\s*['\"]DEV_TOKEN['\"]\s*\))[^\n:]*)",
            text,
        ):
            expr = m.group(1)
            # Must contain either `dev_token and` or `DEV_TOKEN") and` or
            # `DEV_TOKEN') and` earlier in the same boolean expression.
            if re.search(r"\bdev_token\s+and\b", expr):
                continue
            if re.search(r"DEV_TOKEN['\"]\s*\)\s+and\b", expr):
                continue
            line_num = text[: m.start()].count("\n") + 1
            offenders.append(
                f"  - {p.relative_to(_backend_root())}:{line_num} — {expr.strip()[:160]}"
            )
    assert not offenders, (
        "Stage 5.3 regression — DEV_TOKEN comparison is not guarded by a "
        "truthy-check on the env var. If DEV_TOKEN is unset, "
        "`token == None` could match a None/empty client token:\n"
        + "\n".join(offenders)
    )
    print("✅ test_dev_token_sites_check_token_truthy")


def test_auth_py_still_has_guard():
    """Positive check: the main auth verifier `backend/auth.py` must still
    have the dev-token guard in the exact 3-condition shape. If the
    function was refactored to drop it entirely, that's great — but if
    only PART of it was dropped, that's the regression we're watching for."""
    text = (_backend_root() / "auth.py").read_text()
    if "DEV_TOKEN" not in text:
        # Fully removed — that's actually the safest state. Tests above
        # would cover nothing in auth.py, which is fine.
        print("✅ test_auth_py_still_has_guard (DEV_TOKEN removed from auth.py — safest)")
        return
    # Still present — must have all three conditions
    assert re.search(
        r"dev_token\s*=\s*os\.getenv\(\s*['\"]DEV_TOKEN['\"]\s*\)",
        text,
    ), "auth.py no longer reads DEV_TOKEN via os.getenv — regression shape unclear"
    assert re.search(
        r"if\s+dev_token\s+and\s+token\s*==\s*dev_token\s+and\s+os\.getenv\(\s*['\"]DEV_MODE['\"]\s*\)\s*==\s*['\"]true['\"]",
        text,
    ), (
        "Stage 5.3 regression — `backend/auth.py` dev-token guard no "
        "longer matches the exact safe shape "
        "`if dev_token and token == dev_token and os.getenv(\"DEV_MODE\") == \"true\"`. "
        "If you meant to simplify this, make sure all three conditions "
        "survive — dropping any one of them reintroduces a prod backdoor."
    )
    print("✅ test_auth_py_still_has_guard")


TESTS = [
    test_no_literal_dev_token_accept_branch,
    test_dev_token_sites_gate_on_dev_mode,
    test_dev_token_sites_check_token_truthy,
    test_auth_py_still_has_guard,
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
