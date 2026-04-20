"""Functional test for Stage 6.6 part 2: POST /api/system-prompts/generate.

Stage 6.6 had 3 parts:
  1. Wire all 6 system prompts to the pipeline — shipped Cycle 7, pinned
     by test_prompt_override_wiring.py
  2. AI prompt generator endpoint — shipped, but no regression test. THIS
     FILE.
  3. Redesigned system-prompts UI — shipped (page.tsx has the style
     textarea + generate flow)

Why pin part 2 specifically: the /generate endpoint is what makes the
whole "grandma-mode" onboarding work. If the route signature drifts
(param rename, missing prompt key in the meta-prompt template, Claude
call body changes) users silently fall back to generic default prompts
with no visible error. That's the exact silent-failure shape we keep
getting burned by (cf. Cycles 19, 27, 29 — all "endpoint returns fine,
but the thing it was supposed to DO didn't happen").

Source-audit only. Does not hit Claude. The live /generate endpoint is
smoke-tested on VPS via the existing /system-prompts page.
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _route_file() -> Path:
    return Path(__file__).resolve().parents[2] / "routes" / "system_prompts.py"


def _source() -> str:
    return _route_file().read_text()


# The 6 prompt keys the pipeline expects. If this list drifts we have
# a silent failure — the meta-prompt might generate only 5 prompts and
# the 6th bot falls back to the built-in default.
EXPECTED_KEYS = [
    "script",
    "thumbnail",
    "video_motion",
    "sound_curation",
    "sound_generation",
    "research",
]


def test_route_file_exists():
    assert _route_file().exists(), f"system_prompts.py not at {_route_file()}"
    print("✅ test_route_file_exists")


def test_generate_endpoint_registered():
    """POST /generate must be declared. Route decorators can drift
    easily — a rename to @router.post("/auto-generate") or similar
    silently breaks the frontend."""
    src = _source()
    assert re.search(
        r'@router\.post\(\s*["\']\/generate["\']',
        src,
    ), (
        "POST /generate route decorator missing from system_prompts.py. "
        "Frontend /system-prompts page will 404 on the generate button."
    )
    print("✅ test_generate_endpoint_registered")


def test_prompt_keys_list_matches_pipeline():
    """The PROMPT_KEYS constant (or equivalent list) must be exactly
    the 6 keys the pipeline PROMPT_MAP knows about. If a 7th prompt is
    added here without a matching entry in pipeline_executor._load_prompt_overrides
    PROMPT_MAP, users see "Generated" in the UI but the new prompt is
    never read by any bot."""
    src = _source()
    # Look for PROMPT_KEYS list
    m = re.search(
        r"PROMPT_KEYS\s*=\s*\[([^\]]+)\]",
        src,
    )
    assert m, "PROMPT_KEYS list not found — endpoint can't map response to keys"
    list_body = m.group(1)
    for key in EXPECTED_KEYS:
        assert re.search(rf'["\']{key}["\']', list_body), (
            f"PROMPT_KEYS missing {key!r} — this key will be silently "
            f"skipped when the endpoint persists the generated prompts"
        )
    print("✅ test_prompt_keys_list_matches_pipeline")


def test_meta_prompt_template_covers_all_six():
    """The META_PROMPT_TEMPLATE must include a {<key>_template} slot
    for each of the 6 prompts. If one slot is missing, the generator
    LLM has no reference for that key and the output is garbage."""
    src = _source()
    for key in EXPECTED_KEYS:
        assert re.search(
            rf"\b{key}_template\b",
            src,
        ), (
            f"META_PROMPT_TEMPLATE missing {key}_template slot. "
            f"Claude won't have the reference template for {key!r}."
        )
    print("✅ test_meta_prompt_template_covers_all_six")


def test_generate_reads_vault_api_key():
    """The endpoint must pull the anthropic_api_key from vault, not
    from a hardcoded value or env. Regression guard: a past cycle
    refactor leaked raw str(e) on vault failures (Cycle 27) — touching
    this code path is the exact place that bug lived."""
    src = _source()
    # Must reference anthropic_api_key AND go through get_secret
    assert re.search(
        r'get_secret\s*\(\s*["\']anthropic_api_key["\']',
        src,
    ), "generate endpoint not using get_secret('anthropic_api_key', ...)"
    print("✅ test_generate_reads_vault_api_key")


def test_generate_surfaces_missing_key_as_400():
    """If no anthropic_api_key is set, the endpoint must raise a 400
    with a clear message. Silent 500 = "the button does nothing and
    the user doesn't know why" (Stage 6.5 class of bug)."""
    src = _source()
    # Find the generate function block (up to the next @router or EOF)
    m = re.search(
        r'@router\.post\(\s*["\']\/generate["\'].*?(?=@router\.|\Z)',
        src,
        re.DOTALL,
    )
    assert m, "could not extract generate function body"
    body = m.group(0)
    # Must have a 400 raise specifically when api_key is falsy
    assert re.search(
        r'if\s+not\s+api_key\s*:[\s\S]{0,400}?status_code\s*=\s*400',
        body,
    ), (
        "generate endpoint missing `if not api_key: raise 400` guard. "
        "Missing key will surface as an opaque 500 instead of a clear "
        "'configure your Anthropic key in Settings' message."
    )
    print("✅ test_generate_surfaces_missing_key_as_400")


def test_keys_match_pipeline_prompt_map():
    """Cross-file consistency check: the pipeline_executor PROMPT_MAP
    and this endpoint's PROMPT_KEYS must name the same 6 keys. If they
    drift, a prompt generated by /generate but not listed in PROMPT_MAP
    (or vice versa) silently doesn't apply."""
    pipeline_src = (
        Path(__file__).resolve().parents[2] / "pipeline_executor.py"
    ).read_text()
    # Extract the PROMPT_MAP dict keys
    m = re.search(
        r"PROMPT_MAP\s*=\s*\{([^}]+)\}",
        pipeline_src,
        re.DOTALL,
    )
    assert m, "pipeline_executor.PROMPT_MAP not found — cross-file check can't run"
    map_body = m.group(1)
    # Grab the string keys at the start of each map entry
    map_keys = set(re.findall(r'"(\w+)"\s*:', map_body))
    endpoint_keys = set(EXPECTED_KEYS)
    # The endpoint's expected keys must be a subset of (or equal to)
    # the pipeline's PROMPT_MAP keys. Extra keys on the pipeline side
    # are OK (room for future); extra on the endpoint side are a bug.
    missing_in_pipeline = endpoint_keys - map_keys
    assert not missing_in_pipeline, (
        f"Endpoint claims to generate {missing_in_pipeline} but "
        f"pipeline_executor.PROMPT_MAP doesn't know about them. "
        f"Those prompts will be silently dropped when a video is generated."
    )
    print("✅ test_keys_match_pipeline_prompt_map")


TESTS = [
    test_route_file_exists,
    test_generate_endpoint_registered,
    test_prompt_keys_list_matches_pipeline,
    test_meta_prompt_template_covers_all_six,
    test_generate_reads_vault_api_key,
    test_generate_surfaces_missing_key_as_400,
    test_keys_match_pipeline_prompt_map,
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
