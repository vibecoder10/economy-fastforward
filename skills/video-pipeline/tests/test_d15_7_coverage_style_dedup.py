"""D15-7 (closes D6-1d's family for good): retire the SECOND, redundant/
leak-prone style resolution inside storyboard.coverage.generate_coverage_frames.

THE BUG: generate_coverage_frames already states this frame's canonical ART
STYLE line via _stated_style_prefix(profile) — fed by coverage_to_app.
_resolve_style's `profile` return, correct and leak-free (a plain function
argument, never an env var). But it ALSO calls storyboard.bot.
build_image_prompt_from_keyframe(kf, profile), which — despite accepting that
SAME `profile` argument — ignored it entirely and did its OWN independent
resolution via shared.profiles.visual.load_profile() (env var VISUAL_PROFILE,
process-global, set by a COMPLETELY different mechanism —
pipeline_executor._resolve_visual_profile_id — for a different, now-
superseded grid pipeline). Two consequences, both real:
  1. A styled video's frame prompt could state its ART STYLE TWICE (once from
     _stated_style_prefix, once from build_image_prompt_from_keyframe's own
     env-based prefix) — the exact BOARD-LAWS L29 "declare one style, once"
     defect, resurfacing INSIDE a single assembler.
  2. Since VISUAL_PROFILE is process-global and generate_coverage_for_video
     never sets it (unlike the legacy grid stages), an UNRELATED tenant's or
     video's earlier stage call could leave a STALE value that leaks into
     THIS video's coverage frames — a style neither this video's creator
     chose nor _resolve_style ever produced.

THE FIX: build_image_prompt_from_keyframe gained `apply_style_wrapping`
(default True, every pre-existing caller unchanged — see test_d11_3_prompt_
compiler.py, which continues to pass unmodified). generate_coverage_frames'
two call sites (master + angle) now pass apply_style_wrapping=False, since
style is already said once, upstream, by _stated_style_prefix.

Run:
    cd skills/video-pipeline && python -m pytest tests/test_d15_7_coverage_style_dedup.py -q
"""
import asyncio
import os
import sys

_PIPELINE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PIPELINE_ROOT)
sys.path.insert(0, os.path.join(_PIPELINE_ROOT, "storyboard"))
sys.path.append(os.path.join(_PIPELINE_ROOT, "image_prompts"))

from storyboard.coverage import generate_coverage_frames, _stated_style_prefix  # noqa: E402
from storyboard.bot import build_image_prompt_from_keyframe  # noqa: E402
from shared.channel_profile import load_profile as load_channel_profile  # noqa: E402
from shared.profiles.visual import clear_cache as clear_visual_profile_cache  # noqa: E402


class _FakeImageClientForFrames:
    SCENE_MODEL = "nano-banana-2"

    def __init__(self):
        self.calls = []

    async def generate_scene_image_zimage(self, prompt, aspect_ratio="16:9", **_kwargs):
        self.calls.append(("generate_scene_image_zimage", prompt, aspect_ratio))
        return {"url": f"https://img/{len(self.calls)}.png"}


MOMENT = {
    "moment_number": 1,
    "master": {"shot_type": "WS", "description": "wide shot of the rider at dawn"},
    "angles": [{"shot_type": "MCU", "description": "close on the rider's determined face"}],
}


def _styled_profile(directive="A watercolor storybook look, soft pastel washes."):
    """The SAME kind of ChannelProfile coverage_to_app._resolve_style
    returns for a real per-video style pick (image_style_override, visual_
    style, or — since D15-7 — style_preset_id)."""
    return load_channel_profile({"Image Style Override": directive})


def _neutral_profile():
    return load_channel_profile({})


def _env_guard():
    """Save/restore VISUAL_PROFILE + clear the visual-profile module cache
    around each test — this file's whole point is proving behavior no
    longer depends on this env var for the coverage path, so it must not
    leak into any OTHER test file."""
    original = os.environ.get("VISUAL_PROFILE")

    class _Guard:
        def __enter__(self):
            clear_visual_profile_cache()
            return self

        def __exit__(self, *exc):
            if original is None:
                os.environ.pop("VISUAL_PROFILE", None)
            else:
                os.environ["VISUAL_PROFILE"] = original
            clear_visual_profile_cache()

    return _Guard()


# =============================================================================
# 1. A styled video's real coverage frame states its ART STYLE exactly ONCE —
#    never doubled by build_image_prompt_from_keyframe's own injection.
# =============================================================================

def test_styled_frame_states_art_style_exactly_once():
    profile = _styled_profile()
    style_prefix = _stated_style_prefix(profile)
    assert style_prefix, "fixture profile must carry a real, non-default style"

    ic = _FakeImageClientForFrames()
    with _env_guard():
        os.environ.pop("VISUAL_PROFILE", None)  # clean: no leak in play yet
        frames = asyncio.run(generate_coverage_frames(
            MOMENT, "https://cast.png", ic, profile, aspect="16:9", resolution="1K",
            model_override="z-image"))
    assert frames is not None and len(frames) == 2
    master_prompt = ic.calls[0][1]
    assert master_prompt.count("ART STYLE") == 1, master_prompt


# =============================================================================
# 2. Leak-immunity: a STALE VISUAL_PROFILE from an unrelated video/tenant
#    must NOT reach this video's coverage frame — proves the coverage path no
#    longer depends on the process-global env var at all.
# =============================================================================

def test_stale_visual_profile_env_does_not_leak_into_the_frame():
    profile = _styled_profile("A watercolor storybook look, soft pastel washes.")
    ic = _FakeImageClientForFrames()
    with _env_guard():
        # Simulate an unrelated earlier stage call (or a still-live legacy
        # run_storyboard_prompts invocation) leaving VISUAL_PROFILE set to a
        # completely different preset.
        os.environ["VISUAL_PROFILE"] = "clay_mannequin"
        frames = asyncio.run(generate_coverage_frames(
            MOMENT, "https://cast.png", ic, profile, aspect="16:9", resolution="1K",
            model_override="z-image"))
    assert frames is not None
    master_prompt = ic.calls[0][1]
    assert "watercolor" in master_prompt.lower()
    # clay_mannequin's own style_system prefix text must be ABSENT — it never
    # reaches this call at all now.
    assert "ceramic" not in master_prompt.lower()
    assert "mannequin" not in master_prompt.lower()
    assert master_prompt.count("ART STYLE") == 1, master_prompt


def test_angle_frame_also_states_art_style_exactly_once_and_is_leak_immune():
    profile = _styled_profile("A watercolor storybook look, soft pastel washes.")
    ic = _FakeImageClientForFrames()
    with _env_guard():
        os.environ["VISUAL_PROFILE"] = "holographic_hud"
        frames = asyncio.run(generate_coverage_frames(
            MOMENT, "https://cast.png", ic, profile, aspect="16:9", resolution="1K",
            model_override="z-image"))
    assert frames is not None and len(frames) == 2
    angle_prompt = [c[1] for c in ic.calls][1]
    assert angle_prompt.count("ART STYLE") == 1, angle_prompt
    assert "holographic" not in angle_prompt.lower()
    assert "data terminal" not in angle_prompt.lower()


# =============================================================================
# 3. No-style-set case stays byte-identical to before this chunk — proven
#    against the pre-existing D11-3 legacy-shot test's own methodology
#    (profile=None, clean env — see test_d11_3_prompt_compiler.py).
# =============================================================================

def test_no_style_set_frame_unaffected_by_apply_style_wrapping_change():
    ic = _FakeImageClientForFrames()
    with _env_guard():
        os.environ.pop("VISUAL_PROFILE", None)
        frames = asyncio.run(generate_coverage_frames(
            MOMENT, "https://cast.png", ic, None, aspect="16:9", resolution="1K",
            model_override="z-image"))
    assert frames is not None
    master_prompt = ic.calls[0][1]
    assert "ART STYLE" not in master_prompt
    expected_composition = build_image_prompt_from_keyframe(
        {"composition": MOMENT["master"]["description"]}, None)
    assert expected_composition in master_prompt


# =============================================================================
# 4. build_image_prompt_from_keyframe unit level: apply_style_wrapping=False
#    always falls to the neutral technical wrapper, regardless of env state
#    or the (currently-unused) profile argument's content.
# =============================================================================

def test_apply_style_wrapping_false_ignores_env_var_entirely():
    with _env_guard():
        os.environ["VISUAL_PROFILE"] = "cinematic_illustration"
        out = build_image_prompt_from_keyframe(
            {"composition": "a lone figure on a ridge"}, _styled_profile(),
            apply_style_wrapping=False)
    assert "ink outlines" not in out.lower()
    assert "Full-bleed 16:9 composition, no black bars." in out


def test_apply_style_wrapping_default_true_is_byte_identical_to_before_this_chunk():
    """Regression lock for every OTHER existing caller (storyboard.bot.
    run_storyboard_prompts, and D11-3's own tests) — omitting the new
    parameter must produce the exact same output as passing it explicitly
    True, which must match what this function already did pre-D15-7."""
    with _env_guard():
        os.environ.pop("VISUAL_PROFILE", None)
        default_call = build_image_prompt_from_keyframe(
            {"composition": "a lone figure on a ridge"}, None)
        explicit_true = build_image_prompt_from_keyframe(
            {"composition": "a lone figure on a ridge"}, None, apply_style_wrapping=True)
    assert default_call == explicit_true


if __name__ == "__main__":
    import pytest as _pytest
    sys.exit(_pytest.main([__file__, "-q"]))
