from __future__ import annotations

import custom_film_production_runner as production


def test_spoken_prose_preserves_plausible_bold_emphatic_sentence():
    script = (
        "# NARRATION SCRIPT\n\n"
        "[ACT 1 — BLACKOUT | 0:00 - 0:12 | ~30 words]\n"
        "**At 2 AM, Chicago failed.**\n"
        "A camera follows the failed signal across the room."
    )

    prose = production._script_spoken_prose(script)

    assert "NARRATION SCRIPT" not in prose
    assert "At 2 AM, Chicago failed." in prose
    assert "A camera follows the failed signal across the room." in prose


def test_bold_spoken_facts_still_reach_grounding_checks():
    base = (
        "# NARRATION SCRIPT\n\n"
        "[ACT 1 — BLACKOUT | 0:00 - 0:12 | ~30 words]\n"
        "**At 2 AM, Chicago failed.**\n"
        "A camera follows the blackout signal across the room."
    )
    script = base + " " + " ".join(
        ["blackout"] * (30 - production._script_word_count(base))
    )

    issues = production._script_grounding_issues(
        script,
        approved_context="opening\nSet up the blackout without warning",
        config=production._ExactSectionConfig(12),
        generator_validation={"valid": True, "issues": []},
    )

    assert any("2" in issue for issue in issues)
    assert any("AM" in issue and "Chicago" in issue for issue in issues)


def test_fenced_formatted_prose_keeps_factual_words_visible():
    script = (
        "# NARRATION SCRIPT\n\n"
        "```text\n"
        "# At 2 AM, Chicago failed.\n"
        "THE BLACKOUT CONTINUED\n"
        "```\n"
    )

    prose = production._script_spoken_prose(script)

    assert "NARRATION SCRIPT" not in prose
    assert "At 2 AM, Chicago failed." in prose
    assert "THE BLACKOUT CONTINUED" in prose
