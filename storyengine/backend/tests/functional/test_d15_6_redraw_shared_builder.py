"""D15-6 (fold assembler C onto the shared canonical builder) — golden proof.

D15-5 made storyboard.shot_context the ONE canonical material/environment-
locks precedence module, with assembler A (scripts.coverage_to_app's SHEET
path) and assembler B (storyboard.coverage's FRAME path) both delegating to
it. Assembler C — scripts.coverage_to_app.redraw_asset_image, the per-shot
REDRAW path — still carried its own third, hand-inlined copy of the
material-map / environment-locks composition, computed fresh from DB rows
at redraw time (the "fresh beats baked" philosophy — CORRECT, and
unchanged by this chunk):

    material_map = (env.get("material_map") or "").strip()
    if material_map:
        env_note += f" Material map, fixed for this whole set: {material_map}."
    ...
    env_locks = _env_locks_text(env)
    if env_locks:
        env_note += f" Environment locks, fixed for this whole set: {env_locks}."

This chunk replaces ONLY that composition with calls into the shared
storyboard.shot_context builder (via this file's own already-imported
_shared_canonical_material_line / _shared_canonical_environment_locks_line
aliases, mode="frame" — matching assembler B's per-shot-tail usage, since a
redraw is a single-shot draw prompt, not a once-per-scene sheet block).
redraw_asset_image never parses location_sets (it matches ONE environment
per shot via _match_scene_env, not a per-LOCSET clause), so every call here
passes location_sets=None — canonical_material_line/
canonical_environment_locks_line's single-location branch
(`if matched_env: return field_getter(matched_env)`) is exactly the inline
read it replaces, so the composed prompt must be BYTE-IDENTICAL before and
after this chunk.

Cast/identity composition (the CHARACTER block, D9-2 locks + D9-4 NEVER
clauses) is UNTOUCHED — D15-5 confirmed cast composition was never
duplicated between A and B, and this chunk's scope is material/locks only
(see HANDOFF-D15-6 for the "candidate for future extraction, not extracted
here" note on C's cast-identity block).

GOLDEN VALUES below were captured from redraw_asset_image's UNMODIFIED,
pre-refactor body (a scratch script run against the D15-6 worktree before
this file's own production edit landed) across a fixture matrix: populated
material+locks, NULL material+locks, material-only, locks-only, and a
multi-environment `envs` list where the matched environment is NOT the
first one in the list (proving the full `envs` list still flows through
unchanged even though this call site only ever exercises the single-
location branch).

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest \
        tests/functional/test_d15_6_redraw_shared_builder.py -q
"""
import asyncio
import os
import sys
import types
from unittest.mock import AsyncMock, patch

import pytest

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
_PIPELINE_PATH = os.path.join(_BACKEND, "..", "..", "skills", "video-pipeline")
sys.path.insert(0, os.path.abspath(_BACKEND))
sys.path.insert(0, os.path.abspath(_PIPELINE_PATH))


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod


async def _boom(*a, **k):
    raise AssertionError("pure tests must not touch runtime services")


_stub("database", fetch_one=_boom, fetch_all=_boom, execute=_boom)
_stub("storage", upload_bytes=_boom)
_stub("vault", get_secret=_boom)
_stub("kie_unified", get_text_client_for_tenant=_boom)

import scripts.coverage_to_app as coverage_to_app  # noqa: E402
from scripts.coverage_to_app import redraw_asset_image  # noqa: E402

VID, TENANT, ASSET = "vid-1", "tenant-1", "asset-1"
STORED_PROMPT = "(SETUP B) MCU OTS onto Ryan, glancing at the prep board"


def _run(envs, match_index=0, capture_shared_calls=None):
    calls = []

    async def fake_fetch_one(query, *args):
        if "FROM assets a JOIN videos v" in query:
            return {"id": ASSET, "scene": 1, "image_index": 122, "image_prompt": STORED_PROMPT,
                    "hero_shot": True, "generation_method": "coverage",
                    "aspect": "16:9", "image_model_override": None,
                    "image_style_override": None, "visual_style": None}
        if "coverage_directive, scene_text FROM scripts" in query:
            return {"coverage_directive": "vintage kitchen plan", "scene_text": "kitchen scene"}
        raise AssertionError(f"unexpected fetch_one: {query}")

    async def fake_fetch_all(query, *args):
        if "FROM video_characters" in query:
            return [{"reference_url": "https://fake/cast-a.png"}]
        raise AssertionError(f"unexpected fetch_all: {query}")

    async def fake_gen(ic, model_override, prompt, reference_urls=None, **kw):
        calls.append({"prompt": prompt, "refs": list(reference_urls or [])})
        return "https://fake/redrawn.png", "gpt-image-2"

    patches = [
        patch("scripts.coverage_to_app.fetch_one", fake_fetch_one),
        patch("scripts.coverage_to_app.fetch_all", fake_fetch_all),
        patch("scripts.coverage_to_app.execute", AsyncMock()),
        patch("scripts.coverage_to_app.get_secret", AsyncMock(return_value="fake-key")),
        patch("scripts.coverage_to_app.ImageClient", lambda **kw: object()),
        patch("scripts.coverage_to_app._approved_envs", AsyncMock(return_value=envs or [])),
        patch("scripts.coverage_to_app._match_scene_env", lambda text, e: (e[match_index] if e else None)),
        patch("scripts.coverage_to_app.generate_scene_image_for_model", fake_gen),
        patch("scripts.coverage_to_app._stable_url", AsyncMock(return_value="https://stable/x.png")),
        patch("scripts.coverage_to_app.record_ledger_entry", AsyncMock()),
    ]
    if capture_shared_calls is not None:
        real_material = coverage_to_app._shared_canonical_material_line
        real_locks = coverage_to_app._shared_canonical_environment_locks_line

        def spy_material(*a, **kw):
            capture_shared_calls.append(("material", a, kw))
            return real_material(*a, **kw)

        def spy_locks(*a, **kw):
            capture_shared_calls.append(("locks", a, kw))
            return real_locks(*a, **kw)

        patches.append(patch("scripts.coverage_to_app._shared_canonical_material_line", spy_material))
        patches.append(patch("scripts.coverage_to_app._shared_canonical_environment_locks_line", spy_locks))

    for p in patches:
        p.start()
    try:
        result = asyncio.run(redraw_asset_image(VID, TENANT, ASSET))
    finally:
        for p in patches:
            p.stop()
    assert result["status"] == "completed", result
    assert len(calls) == 1
    return calls[0]["prompt"]


# =============================================================================
# Fixture matrix (envs list -> (matched_index, golden composed prompt))
# =============================================================================

_STYLE_LOCK_HEAD = "STYLE LOCK: render in the EXACT same art style"

FIXTURES = {
    "populated_material_and_locks": (
        [{
            "name": "Home kitchen", "reference_url": "https://fake/env.png",
            "material_map": "glass front, solid rear",
            "architecture_lock": "curved amphitheater, 12 rows",
            "lighting_time_weather_lock": "dim, screen-glow only",
            "palette_lock": "black and gold",
            "props": None,
        }],
        0,
        "(SETUP B) MCU OTS onto Ryan, glancing at the prep board STYLE LOCK: render in the "
        "EXACT same art style and rendering quality as the attached reference image(s). If the "
        "reference is a photoreal / live-action / 3D-CG render, this frame MUST be equally "
        "photoreal and realistic — never switch to 2D illustration, painting, cartoon or "
        "anime, and never change the art style or rendering between frames. NEVER draw speech "
        "bubbles, dialogue balloons, captions or subtitles; on-screen text or lettering only if "
        "this shot's description explicitly asks for it. This is ONE SINGLE FRAME — one "
        "continuous scene from one camera at one instant. NEVER a split screen, diptych, "
        "side-by-side comparison, before/after, grid, collage, comic panels or any composition "
        "divided into sections. If the description mentions an emotional change, draw only the "
        "LAST beat of it. The LAST attached reference image is the LOCKED LOCATION — Home "
        "kitchen: this frame's background is this EXACT location; keep its layout, colors and "
        "props IDENTICAL to that reference. Material map, fixed for this whole set: glass "
        "front, solid rear. Environment locks, fixed for this whole set: curved amphitheater, "
        "12 rows; dim, screen-glow only; black and gold.",
    ),
    "null_material_and_locks": (
        [{
            "name": "Pod", "reference_url": "https://fake/env2.png",
            "material_map": None,
            "architecture_lock": None, "lighting_time_weather_lock": None, "palette_lock": None,
            "props": None,
        }],
        0,
        "(SETUP B) MCU OTS onto Ryan, glancing at the prep board STYLE LOCK: render in the "
        "EXACT same art style and rendering quality as the attached reference image(s). If the "
        "reference is a photoreal / live-action / 3D-CG render, this frame MUST be equally "
        "photoreal and realistic — never switch to 2D illustration, painting, cartoon or "
        "anime, and never change the art style or rendering between frames. NEVER draw speech "
        "bubbles, dialogue balloons, captions or subtitles; on-screen text or lettering only if "
        "this shot's description explicitly asks for it. This is ONE SINGLE FRAME — one "
        "continuous scene from one camera at one instant. NEVER a split screen, diptych, "
        "side-by-side comparison, before/after, grid, collage, comic panels or any composition "
        "divided into sections. If the description mentions an emotional change, draw only the "
        "LAST beat of it. The LAST attached reference image is the LOCKED LOCATION — Pod: "
        "this frame's background is this EXACT location; keep its layout, colors and props "
        "IDENTICAL to that reference.",
    ),
    "material_only_no_locks": (
        [{
            "name": "Corridor", "reference_url": "https://fake/env3.png",
            "material_map": "brushed steel panels",
            "architecture_lock": None, "lighting_time_weather_lock": None, "palette_lock": None,
            "props": None,
        }],
        0,
        "(SETUP B) MCU OTS onto Ryan, glancing at the prep board STYLE LOCK: render in the "
        "EXACT same art style and rendering quality as the attached reference image(s). If the "
        "reference is a photoreal / live-action / 3D-CG render, this frame MUST be equally "
        "photoreal and realistic — never switch to 2D illustration, painting, cartoon or "
        "anime, and never change the art style or rendering between frames. NEVER draw speech "
        "bubbles, dialogue balloons, captions or subtitles; on-screen text or lettering only if "
        "this shot's description explicitly asks for it. This is ONE SINGLE FRAME — one "
        "continuous scene from one camera at one instant. NEVER a split screen, diptych, "
        "side-by-side comparison, before/after, grid, collage, comic panels or any composition "
        "divided into sections. If the description mentions an emotional change, draw only the "
        "LAST beat of it. The LAST attached reference image is the LOCKED LOCATION — "
        "Corridor: this frame's background is this EXACT location; keep its layout, colors and "
        "props IDENTICAL to that reference. Material map, fixed for this whole set: brushed "
        "steel panels.",
    ),
    "locks_only_no_material": (
        [{
            "name": "Hall", "reference_url": "https://fake/env4.png",
            "material_map": "",
            "architecture_lock": "hexagonal cell", "lighting_time_weather_lock": None,
            "palette_lock": "cold blue",
            "props": None,
        }],
        0,
        "(SETUP B) MCU OTS onto Ryan, glancing at the prep board STYLE LOCK: render in the "
        "EXACT same art style and rendering quality as the attached reference image(s). If the "
        "reference is a photoreal / live-action / 3D-CG render, this frame MUST be equally "
        "photoreal and realistic — never switch to 2D illustration, painting, cartoon or "
        "anime, and never change the art style or rendering between frames. NEVER draw speech "
        "bubbles, dialogue balloons, captions or subtitles; on-screen text or lettering only if "
        "this shot's description explicitly asks for it. This is ONE SINGLE FRAME — one "
        "continuous scene from one camera at one instant. NEVER a split screen, diptych, "
        "side-by-side comparison, before/after, grid, collage, comic panels or any composition "
        "divided into sections. If the description mentions an emotional change, draw only the "
        "LAST beat of it. The LAST attached reference image is the LOCKED LOCATION — Hall: "
        "this frame's background is this EXACT location; keep its layout, colors and props "
        "IDENTICAL to that reference. Environment locks, fixed for this whole set: hexagonal "
        "cell; cold blue.",
    ),
    "multi_env_matched_second": (
        [
            {"name": "Wrong Room", "reference_url": "https://fake/wrong.png",
             "material_map": "SHOULD NOT APPEAR", "architecture_lock": "SHOULD NOT APPEAR",
             "lighting_time_weather_lock": None, "palette_lock": None, "props": None},
            {"name": "Right Room", "reference_url": "https://fake/right.png",
             "material_map": "matched room material", "architecture_lock": "matched room arch",
             "lighting_time_weather_lock": "matched room light", "palette_lock": None,
             "props": None},
        ],
        1,
        "(SETUP B) MCU OTS onto Ryan, glancing at the prep board STYLE LOCK: render in the "
        "EXACT same art style and rendering quality as the attached reference image(s). If the "
        "reference is a photoreal / live-action / 3D-CG render, this frame MUST be equally "
        "photoreal and realistic — never switch to 2D illustration, painting, cartoon or "
        "anime, and never change the art style or rendering between frames. NEVER draw speech "
        "bubbles, dialogue balloons, captions or subtitles; on-screen text or lettering only if "
        "this shot's description explicitly asks for it. This is ONE SINGLE FRAME — one "
        "continuous scene from one camera at one instant. NEVER a split screen, diptych, "
        "side-by-side comparison, before/after, grid, collage, comic panels or any composition "
        "divided into sections. If the description mentions an emotional change, draw only the "
        "LAST beat of it. The LAST attached reference image is the LOCKED LOCATION — Right "
        "Room: this frame's background is this EXACT location; keep its layout, colors and "
        "props IDENTICAL to that reference. Material map, fixed for this whole set: matched "
        "room material. Environment locks, fixed for this whole set: matched room arch; "
        "matched room light.",
    ),
}


@pytest.mark.parametrize("name,case", FIXTURES.items(), ids=list(FIXTURES.keys()))
def test_redraw_composed_prompt_matches_golden(name, case):
    envs, match_index, golden = case
    assert _run(envs, match_index=match_index) == golden


def test_null_locks_and_material_omit_both_clauses():
    envs, match_index, _ = FIXTURES["null_material_and_locks"]
    prompt = _run(envs, match_index=match_index)
    assert "Material map, fixed for this whole set:" not in prompt
    assert "Environment locks, fixed for this whole set:" not in prompt


def test_material_only_omits_locks_clause():
    envs, match_index, _ = FIXTURES["material_only_no_locks"]
    prompt = _run(envs, match_index=match_index)
    assert "Material map, fixed for this whole set: brushed steel panels." in prompt
    assert "Environment locks, fixed for this whole set:" not in prompt


def test_locks_only_omits_material_clause():
    envs, match_index, _ = FIXTURES["locks_only_no_material"]
    prompt = _run(envs, match_index=match_index)
    assert "Environment locks, fixed for this whole set: hexagonal cell; cold blue." in prompt
    assert "Material map, fixed for this whole set:" not in prompt


def test_multi_env_uses_the_matched_environment_not_the_first():
    envs, match_index, _ = FIXTURES["multi_env_matched_second"]
    prompt = _run(envs, match_index=match_index)
    assert "SHOULD NOT APPEAR" not in prompt
    assert "matched room material" in prompt
    assert "matched room arch; matched room light" in prompt


# =============================================================================
# Wiring proof: the composition is ACTUALLY delegated to the shared
# shot_context builder (not just coincidentally producing the same string) —
# spies on scripts.coverage_to_app's own module-level aliases for the shared
# functions and asserts they were called with this call site's real
# fresh-from-DB rows: envs=the full approved-environments list,
# location_sets=None (redraw never parses LOCSETs), matched_env=env,
# mode="frame".
# =============================================================================

def test_material_and_locks_composition_actually_calls_the_shared_builder():
    envs, match_index, _ = FIXTURES["populated_material_and_locks"]
    spy_calls = []
    _run(envs, match_index=match_index, capture_shared_calls=spy_calls)

    material_calls = [c for c in spy_calls if c[0] == "material"]
    locks_calls = [c for c in spy_calls if c[0] == "locks"]
    assert len(material_calls) == 1, "material-line composition must call the shared builder exactly once"
    assert len(locks_calls) == 1, "environment-locks composition must call the shared builder exactly once"

    _, m_args, m_kwargs = material_calls[0]
    assert m_args[0] == envs, "the full approved-envs list must flow through, not just the matched env"
    assert m_args[1] is None, "redraw never parses location_sets — must pass None, not an invented {}"
    assert m_args[2] == envs[0], "matched_env must be the env _match_scene_env picked"
    assert m_kwargs.get("mode") == "frame", "per-shot draw prompt — mode must self-document as frame, not sheet"

    _, l_args, l_kwargs = locks_calls[0]
    assert l_args[0] == envs
    assert l_args[1] is None
    assert l_args[2] == envs[0]
    assert l_kwargs.get("mode") == "frame"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
