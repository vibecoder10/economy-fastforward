from __future__ import annotations

import pytest

import custom_film_production_runner as production


@pytest.mark.parametrize(
    "terminal_chrome",
    [
        "# END",
        "**END**",
        "__SCRIPT END__",
        "~~~",
    ],
)
def test_formatted_terminal_end_or_fence_chrome_is_rejected(terminal_chrome):
    script = (
        "[ACT 1 — EVIDENCE | 0:00 - 0:12 | ~30 words]\n"
        "Spoken narration follows.\n"
        + terminal_chrome
    )

    assert production._script_output_format_issues(
        script,
        config=production._ExactSectionConfig(12),
    )
