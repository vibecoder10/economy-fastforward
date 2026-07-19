"""Functional test: the `title` engine template is wired (checklist C34d).

Before this fix, `engine_templates.py` already had a neutral, niche-agnostic
`title` template (with a "Phase 3 wires it" comment marking it unused), but
`_load_prompt_overrides`'s PROMPT_MAP omitted "title" entirely — so
`self._pipeline` never got a `title_system_prompt` attribute at all. The only
place title generation got a system prompt override was via
`thumbnail/run.py` borrowing `pipeline.thumbnail_system_prompt` wholesale for
BOTH the thumbnail prompt builder AND the title generator (see
`ThumbnailTitleEngine`'s pre-fix single `system_prompt_override` param).

This test proves:
1. `_load_prompt_overrides` now sets `title_system_prompt` on the pipeline.
2. It resolves to the neutral `title` engine template — NOT the thumbnail
   template, and not None.
3. A tenant override for prompt_key="title" (if one exists in
   tenant_prompt_defaults) beats the neutral template, same precedence as
   every other prompt key.
4. The skill-side consumer (`skills/video-pipeline/thumbnail/run.py`) reads
   `title_system_prompt` as its OWN attribute, separate from
   `thumbnail_system_prompt`.
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO_ROOT = Path(__file__).resolve().parents[4]


class FakePipeline:
    """Stand-in for LightPipeline — just a bag of attributes."""
    pass


async def test_load_prompt_overrides_sets_title_to_neutral_template_not_thumbnail():
    from pipeline_executor import PipelineExecutor
    import pipeline_executor as pe_mod

    executor = PipelineExecutor.__new__(PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor._pipeline = FakePipeline()

    async def fake_fetch_all(query, *args):
        assert "tenant_prompt_defaults" in query
        return []  # no tenant overrides at all

    original = pe_mod.fetch_all
    pe_mod.fetch_all = fake_fetch_all
    try:
        video = {}  # no per-video override columns for title (none exist)
        await executor._load_prompt_overrides(video)
    finally:
        pe_mod.fetch_all = original

    title_prompt = getattr(executor._pipeline, "title_system_prompt", None)
    thumbnail_prompt = getattr(executor._pipeline, "thumbnail_system_prompt", None)

    assert title_prompt, "title_system_prompt was never set — PROMPT_MAP gap not closed"
    assert title_prompt != thumbnail_prompt, (
        "title_system_prompt must be its OWN resolved prompt, not a copy of "
        "the thumbnail override"
    )
    # It should be the neutral `title` engine template, identity-filled — the
    # title craft's signature language, not the thumbnail visual-director craft.
    assert "curiosity gap" in title_prompt.lower()
    assert "visual director" not in title_prompt.lower()
    print("✅ test_load_prompt_overrides_sets_title_to_neutral_template_not_thumbnail")


async def test_tenant_title_override_beats_neutral_template():
    from pipeline_executor import PipelineExecutor
    import pipeline_executor as pe_mod

    executor = PipelineExecutor.__new__(PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor._pipeline = FakePipeline()

    async def fake_fetch_all(query, *args):
        return [{"prompt_key": "title", "prompt_text": "TENANT custom title voice."}]

    original = pe_mod.fetch_all
    pe_mod.fetch_all = fake_fetch_all
    try:
        await executor._load_prompt_overrides({})
    finally:
        pe_mod.fetch_all = original

    assert executor._pipeline.title_system_prompt == "TENANT custom title voice."
    print("✅ test_tenant_title_override_beats_neutral_template")


def test_run_py_reads_title_system_prompt_as_its_own_attribute():
    """Static check: thumbnail/run.py must read `title_system_prompt`
    separately from `thumbnail_system_prompt` when constructing
    ThumbnailTitleEngine — proves the skill-side consumer half of the wire,
    mirroring test_prompt_override_wiring.py's consumer-audit pattern."""
    src = (REPO_ROOT / "skills/video-pipeline/thumbnail/run.py").read_text()

    assert re.search(r'getattr\(pipeline,\s*["\']title_system_prompt["\']', src), (
        "thumbnail/run.py does not read title_system_prompt off the pipeline"
    )
    assert re.search(r'getattr\(pipeline,\s*["\']thumbnail_system_prompt["\']', src), (
        "thumbnail/run.py should still read thumbnail_system_prompt for the thumbnail craft"
    )
    assert "title_system_prompt_override=" in src, (
        "thumbnail/run.py must pass title_system_prompt_override to ThumbnailTitleEngine "
        "as its own kwarg, not folded into system_prompt_override"
    )
    print("✅ test_run_py_reads_title_system_prompt_as_its_own_attribute")


async def main():
    await test_load_prompt_overrides_sets_title_to_neutral_template_not_thumbnail()
    await test_tenant_title_override_beats_neutral_template()
    test_run_py_reads_title_system_prompt_as_its_own_attribute()
    print("\nAll tests passed.")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
