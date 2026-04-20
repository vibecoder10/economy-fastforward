"""Functional test for Stage 3.1 suggest-titles wire-up.

Roadmap Cycle 41 audit: Stage 3.1 ("add title suggestion to create flow")
is already fully shipped. Pinning the wire here prevents a revert from
silently cutting the button out.

Wire-up has 6 links:
  1. Backend POST /api/videos/suggest-titles endpoint (routes/videos.py)
  2. Pydantic request shape SuggestTitlesRequest with `topic` field
  3. Frontend api.ts: `suggestTitles` function + `TitleSuggestion` type
  4. FirstVideoFlow component calls suggestTitles + renders suggestions
  5. CreateVideoStep (onboarding) calls suggestTitles
  6. Pipeline page renders FirstVideoFlow; onboarding page renders
     CreateVideoStep — so both entry points into "create video" carry
     the title-suggestion step

If any of these 6 go missing on a refactor, this test flags it.
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _storyengine_dir() -> Path:
    return Path(__file__).resolve().parents[3]


def _repo_read(rel: str) -> str:
    path = _storyengine_dir() / rel
    assert path.exists(), f"Expected file missing: {rel}"
    return path.read_text()


def test_backend_endpoint_registered():
    src = _repo_read("backend/routes/videos.py")
    assert re.search(
        r'@router\.post\(\s*"/suggest-titles"\s*\)\s*\n\s*async\s+def\s+suggest_titles',
        src,
    ), (
        "backend/routes/videos.py must expose POST /suggest-titles "
        "(async def suggest_titles)."
    )
    print("✅ test_backend_endpoint_registered")


def test_backend_request_shape_has_topic():
    src = _repo_read("backend/routes/videos.py")
    m = re.search(
        r"class\s+SuggestTitlesRequest\b[\s\S]{0,400}?topic\s*:\s*str",
        src,
    )
    assert m, (
        "SuggestTitlesRequest must declare a `topic: str` field — the "
        "frontend serializes `{ topic }` into the POST body."
    )
    print("✅ test_backend_request_shape_has_topic")


def test_frontend_api_has_suggestTitles_function():
    src = _repo_read("frontend/src/lib/api.ts")
    # The function exists and hits the correct path with POST
    m = re.search(
        r"export\s+const\s+suggestTitles\s*=\s*\(\s*topic:\s*string\s*\)\s*=>[\s\S]{0,200}?"
        r'"/api/videos/suggest-titles"[\s\S]{0,80}?method:\s*"POST"',
        src,
    )
    assert m, (
        "frontend/src/lib/api.ts must export `suggestTitles(topic)` that "
        "POSTs to /api/videos/suggest-titles."
    )
    # The TitleSuggestion type must exist and have a `title` field
    assert re.search(
        r"interface\s+TitleSuggestion\b[\s\S]{0,200}?title\s*:\s*string",
        src,
    ), "TitleSuggestion type must have `title: string`."
    print("✅ test_frontend_api_has_suggestTitles_function")


def test_firstvideoflow_uses_suggestTitles():
    src = _repo_read("frontend/src/components/pipeline/FirstVideoFlow.tsx")
    assert "suggestTitles" in src, (
        "FirstVideoFlow.tsx must import/use suggestTitles — it's the primary "
        "create-video entry point from the pipeline page."
    )
    # Should call it inside an async handler and setSuggestions with result
    assert re.search(
        r"await\s+suggestTitles\s*\([\s\S]{0,60}?\)[\s\S]{0,200}?setSuggestions",
        src,
    ), (
        "FirstVideoFlow must await suggestTitles() and store the results "
        "via setSuggestions. Check that the button handler wasn't removed."
    )
    print("✅ test_firstvideoflow_uses_suggestTitles")


def test_createvideostep_onboarding_uses_suggestTitles():
    src = _repo_read("frontend/src/components/onboarding/CreateVideoStep.tsx")
    assert "suggestTitles" in src, (
        "CreateVideoStep.tsx (onboarding) must use suggestTitles — it's the "
        "first-time-user create-video path."
    )
    assert re.search(
        r"await\s+suggestTitles\s*\(",
        src,
    ), "CreateVideoStep must call await suggestTitles(...)."
    print("✅ test_createvideostep_onboarding_uses_suggestTitles")


def test_create_flow_entry_points_render_the_components():
    # Pipeline page mounts FirstVideoFlow
    pipeline_src = _repo_read("frontend/src/app/pipeline/page.tsx")
    assert re.search(
        r'import\s+\{\s*FirstVideoFlow\s*\}\s+from\s+"@/components/pipeline/FirstVideoFlow"',
        pipeline_src,
    ), "pipeline/page.tsx must import FirstVideoFlow."
    assert re.search(
        r"<FirstVideoFlow\b",
        pipeline_src,
    ), "pipeline/page.tsx must render <FirstVideoFlow ...>."

    # Onboarding page mounts CreateVideoStep
    onboarding_src = _repo_read("frontend/src/app/onboarding/page.tsx")
    assert re.search(
        r'import\s+\{\s*CreateVideoStep\s*\}\s+from\s+"@/components/onboarding/CreateVideoStep"',
        onboarding_src,
    ), "onboarding/page.tsx must import CreateVideoStep."
    assert re.search(
        r"<CreateVideoStep\b",
        onboarding_src,
    ), "onboarding/page.tsx must render <CreateVideoStep ...>."
    print("✅ test_create_flow_entry_points_render_the_components")


TESTS = [
    test_backend_endpoint_registered,
    test_backend_request_shape_has_topic,
    test_frontend_api_has_suggestTitles_function,
    test_firstvideoflow_uses_suggestTitles,
    test_createvideostep_onboarding_uses_suggestTitles,
    test_create_flow_entry_points_render_the_components,
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
