"""Functional test: prove system-prompt overrides actually reach the LLM.

Context: the onboarding "Generate My Style" flow writes 6 rows to
`tenant_prompt_defaults` (script, thumbnail, video_motion, sound_curation,
sound_generation, research). The pipeline's `_load_prompt_overrides` then
reads those rows and attaches them to `self._pipeline` as attributes like
`script_system_prompt`, `thumbnail_system_prompt`, etc.

The ship-log for 2026-04-19 cycle 1 claimed these overrides are wired in
"7 places" — meaning every bot that does an LLM call should be reading
`getattr(pipeline, '<key>_system_prompt', None)` and passing it down.

This test audits the claim. It does two things:

1. **Runtime check on `_load_prompt_overrides`** — asserts that given a
   seeded tenant_overrides dict, the function correctly attaches all 6
   attributes onto the pipeline object with per-video > tenant > None
   priority. This proves the LOAD path works.

2. **Static check on bot consumers** — greps each bot's source for the
   `getattr(pipeline, '<attr>', ...)` pattern and records PASS/FAIL per
   bot. A PASS means the bot reads its assigned override attribute and
   can therefore propagate the user's grandma-mode prompt into an LLM
   call. A FAIL means the attribute is set on the pipeline but nobody
   ever reads it — "wired but not plugged in."

The test itself is always green (it reports its findings), but it
SHOULD be treated as a tracker: once all 6 consumers are wired, the
`overall_status` flips to `FULLY_WIRED` and we can actually trust the
grandma-mode A/B to change output in production.

To run:
    cd storyengine/backend && .venv/bin/python3 tests/functional/test_prompt_override_wiring.py

Last verified: 2026-04-19 — 2/6 bots wired (video_motion, script).
Remaining unwired: thumbnail, sound_curation, sound_generation, research.
"""
import asyncio
import os
import sys
import re
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# ---- Consumer spec: for each tenant_prompt_defaults.prompt_key we expect ----
# (prompt_key, pipeline_attr, bot_source_files)
CONSUMER_SPEC = [
    (
        "script",
        "script_system_prompt",
        [
            "skills/video-pipeline/script/run.py",
            "skills/video-pipeline/script/brief_translator/script_generator.py",
        ],
    ),
    (
        "thumbnail",
        "thumbnail_system_prompt",
        [
            "skills/video-pipeline/thumbnail/run.py",
        ],
    ),
    (
        "video_motion",
        "video_motion_system_prompt",
        [
            "skills/video-pipeline/video_motion/run_scripts.py",
        ],
    ),
    (
        "sound_curation",
        "sound_curation_system_prompt",
        [
            "skills/video-pipeline/sound/run_design.py",
            "skills/video-pipeline/sound/run_effects.py",
        ],
    ),
    (
        "sound_generation",
        "sound_generation_system_prompt",
        [
            "skills/video-pipeline/sound/run_design.py",
            "skills/video-pipeline/sound/run_effects.py",
        ],
    ),
    (
        "research",
        "research_system_prompt",
        [
            "skills/video-pipeline/research/run.py",
        ],
    ),
]


REPO_ROOT = Path(__file__).resolve().parents[4]


class FakePipeline:
    """Stand-in for LightPipeline — just a bag of attributes."""
    pass


async def test_load_prompt_overrides_attaches_all_six(monkeypatch=None):
    """Prove the LOAD path: `_load_prompt_overrides` correctly sets 6
    attributes on the pipeline with the right priority."""
    from pipeline_executor import PipelineExecutor

    # Build a PipelineExecutor stub — we only need _load_prompt_overrides,
    # and the method uses self.tenant_id + self._pipeline + fetch_all.
    executor = PipelineExecutor.__new__(PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor._pipeline = FakePipeline()

    # Monkeypatch fetch_all to return seeded tenant overrides
    seeded = {
        "script": "YOU ARE GRANDMA: tuck the audience in with warm storytelling about economics.",
        "thumbnail": "Thumbnails must evoke wholesome kitchen-table wisdom.",
        "video_motion": "Gentle slow pans only; no aggressive cuts.",
        "sound_curation": "Acoustic, homey background. No EDM.",
        "sound_generation": "Synth textures that evoke a crackling fireplace.",
        "research": "Source citations skew toward cookbook analogies.",
    }

    import pipeline_executor as pe_mod

    async def fake_fetch_all(query, *args):
        assert "tenant_prompt_defaults" in query
        return [{"prompt_key": k, "prompt_text": v} for k, v in seeded.items()]

    original = pe_mod.fetch_all
    pe_mod.fetch_all = fake_fetch_all
    try:
        # Fake video row with no per-video overrides
        video = {
            "script_system_prompt": None,
            "thumbnail_system_prompt": None,
            "video_motion_system_prompt": None,
            "sound_system_prompt": None,
        }
        await executor._load_prompt_overrides(video)
    finally:
        pe_mod.fetch_all = original

    assert executor._pipeline.script_system_prompt == seeded["script"]
    assert executor._pipeline.thumbnail_system_prompt == seeded["thumbnail"]
    assert executor._pipeline.video_motion_system_prompt == seeded["video_motion"]
    assert executor._pipeline.sound_curation_system_prompt == seeded["sound_curation"]
    assert executor._pipeline.sound_generation_system_prompt == seeded["sound_generation"]
    assert executor._pipeline.research_system_prompt == seeded["research"]
    print("✅ test_load_prompt_overrides_attaches_all_six")


async def test_per_video_override_beats_tenant():
    """Per-video override wins over tenant default."""
    from pipeline_executor import PipelineExecutor
    import pipeline_executor as pe_mod

    executor = PipelineExecutor.__new__(PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor._pipeline = FakePipeline()

    async def fake_fetch_all(query, *args):
        return [{"prompt_key": "script", "prompt_text": "TENANT default script prompt"}]

    original = pe_mod.fetch_all
    pe_mod.fetch_all = fake_fetch_all
    try:
        video = {"script_system_prompt": "PER-VIDEO wins"}
        await executor._load_prompt_overrides(video)
    finally:
        pe_mod.fetch_all = original

    assert executor._pipeline.script_system_prompt == "PER-VIDEO wins"
    print("✅ test_per_video_override_beats_tenant")


def _consumer_reads_attr(source_path: Path, pipeline_attr: str) -> bool:
    """Search a bot's source for getattr(pipeline, "<attr>", ...) OR
    pipeline.<attr>. Either pattern counts as "the bot reads the override."
    """
    if not source_path.exists():
        return False
    text = source_path.read_text()
    # Pattern 1: getattr(pipeline, "script_system_prompt", ...)
    pat1 = re.compile(
        r'getattr\s*\(\s*pipeline\s*,\s*["\']' + re.escape(pipeline_attr) + r'["\']'
    )
    # Pattern 2: pipeline.script_system_prompt (direct access)
    pat2 = re.compile(r'pipeline\.' + re.escape(pipeline_attr) + r'\b')
    return bool(pat1.search(text) or pat2.search(text))


async def test_audit_bot_consumer_wiring():
    """Static audit: which bots actually READ their override attribute?

    This is the "grandma-mode A/B" test in documentation form. If a bot's
    `pipeline_attr` isn't referenced in its source, the tenant's
    grandma-mode prompt silently dies at the pipeline boundary.
    """
    print("\n=== Bot consumer wiring audit ===")
    results = {}
    for prompt_key, pipeline_attr, sources in CONSUMER_SPEC:
        any_consumer = False
        consuming_files = []
        for rel_path in sources:
            abs_path = REPO_ROOT / rel_path
            if _consumer_reads_attr(abs_path, pipeline_attr):
                any_consumer = True
                consuming_files.append(rel_path)
        results[prompt_key] = {
            "attr": pipeline_attr,
            "wired": any_consumer,
            "consuming_files": consuming_files,
        }
        status = "WIRED  " if any_consumer else "UNWIRED"
        src_hint = consuming_files[0] if consuming_files else "(no consumer reads this attr)"
        print(f"  [{status}] {prompt_key:<20} -> {pipeline_attr:<34} {src_hint}")

    wired = sum(1 for r in results.values() if r["wired"])
    total = len(results)
    print(f"\nOverall: {wired}/{total} bots read their override.")
    if wired < total:
        print(
            "⚠️  Gap: "
            + ", ".join(
                k for k, v in results.items() if not v["wired"]
            )
            + " silently drop their tenant grandma-mode prompt."
        )
    else:
        print("✅ All bots honor their overrides.")

    # Baseline regression guards: wired bots must stay wired.
    # (Wired count can grow without breaking this — UNWIRED bots aren't
    # asserted yet; add them to this block as each one gets wired.)
    assert results["video_motion"]["wired"], (
        "REGRESSION: video_motion bot stopped reading video_motion_system_prompt. "
        "Check skills/video-pipeline/video_motion/run_scripts.py."
    )
    assert results["script"]["wired"], (
        "REGRESSION: script bot stopped reading script_system_prompt. "
        "Check skills/video-pipeline/script/run.py → translate_brief → "
        "BriefTranslator → generate_script → anthropic_client.generate(system_prompt=...)."
    )
    print("✅ test_audit_bot_consumer_wiring (regression guards hold for video_motion + script)")

    return results


async def main():
    await test_load_prompt_overrides_attaches_all_six()
    await test_per_video_override_beats_tenant()
    await test_audit_bot_consumer_wiring()
    print("\nAll tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
