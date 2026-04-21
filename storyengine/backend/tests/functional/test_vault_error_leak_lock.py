"""Functional test for Stage 1.4 / Cycle 48: SEC-KEYS-001 exception details
leaking to client — regression lock.

The bug (pre-fix): `backend/vault.py`'s `test_key` endpoint caught broad
Exceptions and echoed `str(e)` straight back into the response body. That
leaked httpx internals, DNS hostnames, TLS certificate paths, proxy URLs,
and occasionally raw socket errors — all visible in the Settings > Keys
page when a user clicked Test on a misconfigured key.

The fix was to route every catch-all `except` through `humanize_error(e,
context=...)`, which logs the raw error at WARNING with a `[humanize_error]`
prefix for server-side diagnosis and returns a short, safe, user-readable
message. That fix is landed. This cycle pins it so a future hotfix can't
reintroduce `str(e)` into a response body.

Scope note: server-side `print(f"... {e}")` logging is fine — the client
only ever sees the `return False` / `return {..., humanize_error(e) ...}`
shape. This audit only flags `str(e)` or `{e}` appearing in returned
payloads or HTTPException detail fields.
"""
import ast
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _vault_py() -> Path:
    return Path(__file__).resolve().parents[2] / "vault.py"


def test_humanize_error_imported_and_used():
    """`humanize_error` is the boundary function that converts raw errors
    into safe user-facing strings. If it disappears from vault.py, the
    test_key catch-all has nothing to fall back to."""
    text = _vault_py().read_text()
    assert "humanize_error" in text, (
        "vault.py no longer references humanize_error. SEC-KEYS-001 fix was "
        "removed — catch-all exceptions may leak raw detail to the client."
    )
    # It must be imported (from error_utils or similar)
    assert re.search(r"from\s+\S+\s+import[^#\n]*humanize_error", text) or re.search(
        r"import\s+humanize_error", text
    ), (
        "humanize_error is referenced but not imported — SyntaxError at import time."
    )
    print("✅ test_humanize_error_imported_and_used")


def test_no_raw_exception_str_in_returned_payloads():
    """Scan every `return ...` and every `raise HTTPException(...)` — none
    may embed `str(e)` or `{e}` in text that reaches the client. AST walk
    is the only reliable way to tell 'return-that-reaches-client' from
    'print-to-server-log'."""
    text = _vault_py().read_text()
    tree = ast.parse(text)

    offenders: list[str] = []

    def names_in(node: ast.AST) -> set[str]:
        """Collect bare Name ids inside a node (for detecting `{e}` in f-strings
        or `e` standing alone as str-concat input)."""
        found: set[str] = set()
        for n in ast.walk(node):
            if isinstance(n, ast.Name):
                found.add(n.id)
        return found

    def has_str_of_exception(node: ast.AST, exc_names: set[str]) -> bool:
        """True if `node` contains `str(e)` where e is a captured exception
        OR an f-string interpolating such a name."""
        for n in ast.walk(node):
            # str(e)
            if (
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name)
                and n.func.id == "str"
                and len(n.args) == 1
                and isinstance(n.args[0], ast.Name)
                and n.args[0].id in exc_names
            ):
                return True
            # f-string: JoinedStr containing FormattedValue(Name(e))
            if isinstance(n, ast.JoinedStr):
                for part in n.values:
                    if isinstance(part, ast.FormattedValue) and isinstance(
                        part.value, ast.Name
                    ) and part.value.id in exc_names:
                        return True
        return False

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.exc_stack: list[str] = []

        def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
            had_binding = bool(node.name)
            if had_binding:
                self.exc_stack.append(node.name)
            try:
                self.generic_visit(node)
            finally:
                if had_binding:
                    self.exc_stack.pop()

        def _check(self, value_node: ast.AST, kind: str, lineno: int) -> None:
            if not self.exc_stack:
                return
            exc_names = set(self.exc_stack)
            if has_str_of_exception(value_node, exc_names):
                offenders.append(
                    f"  - line {lineno}: {kind} interpolates raw exception "
                    f"(str(e) or {{e}}) from `except ... as {exc_names}`"
                )

        def visit_Return(self, node: ast.Return) -> None:
            if node.value is not None:
                self._check(node.value, "return", node.lineno)
            self.generic_visit(node)

        def visit_Raise(self, node: ast.Raise) -> None:
            if node.exc is not None:
                self._check(node.exc, "raise", node.lineno)
            self.generic_visit(node)

    Visitor().visit(tree)
    assert not offenders, (
        "SEC-KEYS-001 regression — vault.py returns/raises text that "
        "interpolates a raw captured exception:\n"
        + "\n".join(offenders)
        + "\n\nRoute through humanize_error(e, context='...') instead. "
        "Server-side `print(f'... {e}')` is fine (logs only)."
    )
    print("✅ test_no_raw_exception_str_in_returned_payloads")


def test_test_key_catchall_uses_humanize_error():
    """Positive check: the last-resort `except Exception as e:` in `test_key`
    must call humanize_error on e. Without this, the fallback path silently
    regresses to generic `{"success": False}` or worse, `str(e)`."""
    text = _vault_py().read_text()
    # Find every `except Exception as e:` and scan the following ~300 chars
    # for a humanize_error(e...) call.
    matches = list(re.finditer(r"except\s+Exception\s+as\s+(\w+)\s*:", text))
    # The test_key function is the one with the comment "Never echo raw str(e)".
    # We require at least one such handler to call humanize_error on its binding.
    humanized = False
    for m in matches:
        name = m.group(1)
        window = text[m.end() : m.end() + 400]
        if re.search(rf"humanize_error\(\s*{name}\b", window):
            humanized = True
            break
    assert humanized, (
        "No `except Exception as <n>:` handler in vault.py calls "
        "humanize_error(<n>, ...). The test_key catch-all used to leak "
        "str(e) — that fallback must still be humanized."
    )
    print("✅ test_test_key_catchall_uses_humanize_error")


TESTS = [
    test_humanize_error_imported_and_used,
    test_no_raw_exception_str_in_returned_payloads,
    test_test_key_catchall_uses_humanize_error,
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
