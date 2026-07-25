from __future__ import annotations

import pytest

import custom_film_production_runner as production


@pytest.mark.parametrize(
    "script",
    [
        (
            "Spoken lead "
            "[ACT 1 — EVIDENCE | 0:00 - 0:12 | ~30 words] "
            "spoken body"
        ),
        "[ACT 1 - EVIDENCE | 0:00 - 0:12 | ~30 words]",
        "[ACT 1 — EVIDENCE | 0:00 - 0:12 | 30 words]",
        "[ACT 1 — <SHORT SECTION TITLE> | 0:00 - 0:12 | ~30 words]",
        "**[ACT 1 — EVIDENCE | 0:00 - 0:12 | ~30 words]**",
    ],
)
def test_output_format_rejects_nonexact_or_wrapped_marker_grammar(script):
    assert production._script_output_format_issues(
        script,
        config=production._ExactSectionConfig(12),
    )


def test_output_format_accepts_only_canonical_standalone_marker():
    script = (
        "[ACT 1 — EVIDENCE REVIEW | 0:00 - 0:12 | ~30 words]\n"
        "Spoken body follows on the next line."
    )

    assert production._script_output_format_issues(
        script,
        config=production._ExactSectionConfig(12),
    ) == []
