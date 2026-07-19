"""Tests for thumbnail/engine.py's ThumbnailTitleEngine constructor wiring —
the C34d fix.

Before this fix, `ThumbnailTitleEngine.__init__` took a single
`system_prompt_override` and handed it to BOTH `TitleGenerator` and
`ThumbnailPromptBuilder` — meaning title generation silently borrowed the
THUMBNAIL craft template (`engine_templates.py`'s neutral `title` template
sat unwired, per its own "Phase 3 wires it" comment in
`pipeline_executor.py`). The fix adds an independent
`title_system_prompt_override` param so the title generator gets its own
seam while the thumbnail prompt builder keeps its own override unchanged.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from thumbnail.engine import ThumbnailTitleEngine


def test_title_and_thumbnail_overrides_are_independent():
    """The two overrides must reach two DIFFERENT sub-objects, not collapse
    into one — this is the exact bug the fix closes."""
    engine = ThumbnailTitleEngine(
        anthropic_client=object(),
        image_client=object(),
        system_prompt_override="THUMBNAIL CRAFT PROMPT",
        title_system_prompt_override="TITLE CRAFT PROMPT",
    )

    assert engine.title_gen.system_prompt_override == "TITLE CRAFT PROMPT"
    assert engine.prompt_builder.system_prompt_override == "THUMBNAIL CRAFT PROMPT"
    # The regression this guards against: title no longer equals thumbnail.
    assert engine.title_gen.system_prompt_override != engine.prompt_builder.system_prompt_override


def test_title_override_defaults_to_none_not_thumbnail_override():
    """A caller that only sets the thumbnail override (the pre-fix call
    shape) must NOT leak it into the title generator — title should fall
    through to its own default (None -> TitleGenerator's built-in neutral
    prompt), not silently inherit the thumbnail craft."""
    engine = ThumbnailTitleEngine(
        anthropic_client=object(),
        image_client=object(),
        system_prompt_override="THUMBNAIL CRAFT PROMPT",
    )

    assert engine.title_gen.system_prompt_override is None
    assert engine.prompt_builder.system_prompt_override == "THUMBNAIL CRAFT PROMPT"


def test_both_overrides_none_by_default():
    engine = ThumbnailTitleEngine(anthropic_client=object(), image_client=object())
    assert engine.title_gen.system_prompt_override is None
    assert engine.prompt_builder.system_prompt_override is None
