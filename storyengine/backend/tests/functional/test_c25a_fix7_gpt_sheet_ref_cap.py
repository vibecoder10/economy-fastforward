"""Tests for C25a-fix7 Part B (2026-07-20): storyboard SHEET draws to
gpt-image-2-image-to-image were 400ing ("The current content could not be
processed", 0 credits consumed) on video cd5d2883-427e-4bfb-854d-8849d025d444
the moment the LOCKED LOCATION environment reference became a THIRD
`input_urls` entry alongside 2 cast sheets.

Evidence trail (see scripts/coverage_to_app.py's SHEET_REF_CAP comment for the
full writeup):
  - Today's 3-ref sheet calls (2 cast + 1 env) failed 100% of the time, both
    before and after C25a-fix5's unrelated URL-extension fix landed.
  - A same-day 2-ref call (`redraw_asset_image`, cast sheets only — that path
    never adds an env ref, confirmed by reading its source below) succeeded.
  - June sheets (video f32ed182, before the environments feature existed —
    confirmed via `git log -S "sheet_refs.append(env"`, commit aa51d2d3) drew
    clean at 2 refs, 11-13k chars — LONGER than today's failing ~6.5-6.9k char
    prompts, ruling out prompt length as the cause.
  - Kie's own docs (docs.kie.ai/market/gpt/gpt-image-2-image-to-image) document
    `input_urls` as `maxItems: 16` — there is NO documented 2-image limit, so
    this is an empirical Kie/OpenAI-side quirk, not a documented API cap. The
    fix caps at the last CONFIRMED-WORKING count (2) regardless of the
    documented ceiling.

Call-shape ref counts (quoted from the actual call sites, all in this repo):
  - generate_storyboard_sheet_for_scene (this file, ~L958-985, BEFORE this fix):
    `sheet_refs = list(cast_refs)` then unconditionally
    `sheet_refs.append(env["reference_url"])` when an env matches — 3 refs
    whenever the video has 2 cast members AND a locked environment.
  - redraw_asset_image (~L1060-1062): `reference_urls=cast_refs` — cast sheets
    only, env never added — this is the 2-ref path that kept working.
  - generate_thumbnail_gpt2 (skills/video-pipeline/shared/clients/
    image_client.py ~L905-906): sends `input_urls: refs` = EXACTLY whatever
    list its caller passed, capped only at `[:16]` — no cap of its own, so the
    caller (generate_storyboard_sheet_for_scene) is the only place that can
    enforce a smaller cap.

Fix: `SHEET_REF_CAP = 2`, applied only in the sheet-draw path, cast sheets
first (character identity is product law), env ref appended only if a slot
remains, with a loud print() when either a cast ref or the env ref gets
dropped. The LOCKED LOCATION text block is added to the prompt regardless of
whether its image ref survived the cap, so a dropped env ref degrades
location lock gracefully (text-only), not silently.

No network, no real DB — same module-stub-at-import-time + per-test patch
pattern as test_c16b_coverage_skip_if_done.py. `generate_coverage_directive`
is patched to return a fixed, real-format directive so the REAL
parse_coverage / enforce_shot_budget / _plan_sheet_prompts / _match_scene_env
run unmocked — only network- and DB-touching calls are patched.

Stash-proof: `git stash` scripts/coverage_to_app.py's SHEET_REF_CAP change and
every "_capped" test below fails (3 refs reach generate_scene_image_for_model
instead of 2); the "_under_cap" and "_no_env" tests still pass either way,
which is why the capped tests are the ones that actually pin the fix.

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c25a_fix7_gpt_sheet_ref_cap.py -q
"""
import asyncio
import os
import sys
import types
from unittest.mock import AsyncMock, patch

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
_PIPELINE_PATH = os.path.join(_BACKEND, "..", "..", "..", "skills", "video-pipeline")
sys.path.insert(0, os.path.abspath(_BACKEND))
sys.path.insert(0, os.path.abspath(_PIPELINE_PATH))


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod


async def _boom(*a, **k):
    raise AssertionError("pure tests must not touch runtime services")


# Placeholders at import time; every real test overrides via
# patch("scripts.coverage_to_app.X", ...).
_stub("database", fetch_one=_boom, fetch_all=_boom, execute=_boom)
_stub("storage", upload_bytes=_boom)
_stub("vault", get_secret=_boom)
_stub("kie_unified", get_text_client_for_tenant=_boom)

from scripts.coverage_to_app import (  # noqa: E402
    generate_storyboard_sheet_for_scene, _scene_text_hash, SHEET_REF_CAP,
)

VIDEO_ID = "cd5d2883-427e-4bfb-854d-8849d025d444"
TENANT_ID = "tenant-1"

# Same non-dialogue scene text test_c16b uses — _coverage_shape() deterministically
# returns (3, 2, 3, None) for it, and this directive format is proven to parse
# (test_c16b exercises it through the same parse_coverage/enforce_shot_budget calls).
SCENE_TEXT = "The city lights flicker as rain falls onto empty streets."
DIRECTIVE = (
    "[MOMENT 1 | rain falls on empty streets]\n"
    "- MASTER [WS]: Wide shot of rain-soaked streets, neon reflections shimmering.\n"
    "- ANGLE [MCU]: Close on droplets streaking down a window pane.\n"
)
SCENE_HASH = _scene_text_hash(SCENE_TEXT)

ENV = {
    "name": "Downtown Street",
    "description": "A rain-slicked downtown street at night.",
    "reference_url": "https://fake/env-downtown.png",
}


def _video_row():
    return {
        "id": VIDEO_ID, "tenant_id": TENANT_ID, "video_title": "Test Video",
        "aspect": "16:9", "image_style_override": None, "visual_style": None,
        "image_model_override": None, "render_style": None, "video_model": "grok-imagine",
        "dialogue_audio": "voice_over",
    }


class FakeDB:
    def __init__(self, cast_refs):
        self.cast_refs = cast_refs

    async def fetch_one(self, query, *args):
        if "FROM videos WHERE id=$1" in query:
            return _video_row()
        if "coverage_directive, coverage_directive_hash FROM scripts" in query:
            return {"id": "script-1", "coverage_directive": None, "coverage_directive_hash": None}
        raise AssertionError(f"unexpected fetch_one query: {query}")

    async def fetch_all(self, query, *args):
        if "SELECT scene, scene_text FROM scripts" in query:
            return [{"scene": 1, "scene_text": SCENE_TEXT}]
        if "FROM video_characters" in query:
            return [{"reference_url": u} for u in self.cast_refs]
        raise AssertionError(f"unexpected fetch_all query: {query}")

    async def execute(self, query, *args):
        return "OK"


def _run(cast_refs, envs):
    """Runs generate_storyboard_sheet_for_scene end to end (real parse_coverage /
    enforce_shot_budget / _plan_sheet_prompts / _match_scene_env), capturing every
    call made to generate_scene_image_for_model — the ONE call site that actually
    ships reference_urls to Kie as input_urls."""
    fakedb = FakeDB(cast_refs)
    captured_calls = []

    async def _fake_generate_scene_image_for_model(ic, model_override, prompt,
                                                     reference_urls=None, aspect_ratio="16:9"):
        captured_calls.append({"prompt": prompt, "reference_urls": list(reference_urls or [])})
        return "https://fake-storage.example/board.png", "gpt-image-2"

    patches = [
        patch("scripts.coverage_to_app.fetch_one", fakedb.fetch_one),
        patch("scripts.coverage_to_app.fetch_all", fakedb.fetch_all),
        patch("scripts.coverage_to_app.execute", fakedb.execute),
        patch("scripts.coverage_to_app.get_secret", AsyncMock(return_value="fake-kie-key")),
        patch("scripts.coverage_to_app.get_text_client_for_tenant", AsyncMock(return_value=object())),
        patch("scripts.coverage_to_app.claude_model_for_direct_client", lambda c: "fake-model"),
        patch("scripts.coverage_to_app.scene_aware_bible", AsyncMock(return_value=None)),
        patch("scripts.coverage_to_app._approved_envs", AsyncMock(return_value=envs)),
        patch("scripts.coverage_to_app.generate_coverage_directive", AsyncMock(return_value=DIRECTIVE)),
        patch("scripts.coverage_to_app.generate_scene_image_for_model",
              _fake_generate_scene_image_for_model),
        patch("scripts.coverage_to_app._stable_url", AsyncMock(return_value="https://stable/final.png")),
    ]
    for p in patches:
        p.start()
    try:
        result = asyncio.run(
            generate_storyboard_sheet_for_scene(VIDEO_ID, TENANT_ID, scene=1, plan_only=False))
    finally:
        for p in patches:
            p.stop()
    assert result["status"] == "completed", result
    assert captured_calls, "generate_scene_image_for_model was never called"
    return captured_calls


# ---------------------------------------------------------------------------
# The cap: 2 cast + 1 env (the exact prod failure shape) must NOT reach Kie
# as 3 refs — env is dropped, cast sheets both survive.
# ---------------------------------------------------------------------------

def test_two_cast_refs_plus_env_caps_at_two_env_dropped():
    calls = _run(cast_refs=["https://fake/cast-a.png", "https://fake/cast-b.png"], envs=[ENV])
    refs = calls[0]["reference_urls"]
    assert len(refs) == SHEET_REF_CAP == 2, refs
    assert refs == ["https://fake/cast-a.png", "https://fake/cast-b.png"], (
        "cast sheets must win the slots over the env ref")
    assert ENV["reference_url"] not in refs, "env ref must be the one dropped, not a cast ref"


def test_env_locked_location_text_survives_even_when_its_ref_is_dropped():
    """Location lock degrades gracefully (prompt text stays) not silently
    (the whole env is not just forgotten) when the cap drops its image ref."""
    calls = _run(cast_refs=["https://fake/cast-a.png", "https://fake/cast-b.png"], envs=[ENV])
    assert "LOCKED LOCATION" in calls[0]["prompt"]
    assert ENV["name"] in calls[0]["prompt"]


# ---------------------------------------------------------------------------
# Under the cap: 1 cast + 1 env fits in 2 slots — both must be sent.
# ---------------------------------------------------------------------------

def test_one_cast_ref_plus_env_both_sent_under_cap():
    calls = _run(cast_refs=["https://fake/cast-a.png"], envs=[ENV])
    refs = calls[0]["reference_urls"]
    assert refs == ["https://fake/cast-a.png", ENV["reference_url"]], refs
    assert len(refs) <= SHEET_REF_CAP


# ---------------------------------------------------------------------------
# No env at all: cast-only behavior is unaffected by the cap logic when it
# already fits (regression guard against the fix breaking the common case).
# ---------------------------------------------------------------------------

def test_no_env_two_cast_refs_unaffected():
    calls = _run(cast_refs=["https://fake/cast-a.png", "https://fake/cast-b.png"], envs=[])
    refs = calls[0]["reference_urls"]
    assert refs == ["https://fake/cast-a.png", "https://fake/cast-b.png"]
    assert "LOCKED LOCATION" not in calls[0]["prompt"]


# ---------------------------------------------------------------------------
# Cast alone can also exceed the cap (3+ characters, no env at all) — the cap
# is a total-refs cap, not just an env-vs-cast tiebreak. Priority order still
# keeps the FIRST cast refs (cast rows are ORDER BY sort, i.e. the creator's
# own ordering) and drops the rest.
# ---------------------------------------------------------------------------

def test_three_cast_refs_no_env_still_caps_at_two():
    calls = _run(
        cast_refs=["https://fake/cast-a.png", "https://fake/cast-b.png", "https://fake/cast-c.png"],
        envs=[])
    refs = calls[0]["reference_urls"]
    assert len(refs) == SHEET_REF_CAP == 2, refs
    assert refs == ["https://fake/cast-a.png", "https://fake/cast-b.png"], (
        "the cap must keep the first N cast refs in their existing sort order")


if __name__ == "__main__":
    test_two_cast_refs_plus_env_caps_at_two_env_dropped()
    test_env_locked_location_text_survives_even_when_its_ref_is_dropped()
    test_one_cast_ref_plus_env_both_sent_under_cap()
    test_no_env_two_cast_refs_unaffected()
    test_three_cast_refs_no_env_still_caps_at_two()
    print("\nAll C25a-fix7 Part B (GPT sheet ref cap) tests passed.")
