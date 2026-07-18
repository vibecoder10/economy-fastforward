"""Tests for C13b's auto-derivation of videos.render_style from a video's
declared visual style (checklist §C13b).

Pure unit test over channel_format.render_style_for_preset() — the single
classifier both the locked-channel-format path (channel_format.
apply_format_defaults) and the explicit-choice path (routes/videos.py's
create_video) reuse. No DB, no network.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_render_style_derivation.py -q
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from channel_format import render_style_for_preset, style_preset_for_format  # noqa: E402
from routes.videos import _normalize_style_preset  # noqa: E402


def test_realistic_preset_maps_to_realistic():
    assert render_style_for_preset("realistic") == "realistic"


def test_illustrated_presets_map_to_animated():
    for preset in ("pixar_3d", "flat_2d", "anime", "watercolor", "comic"):
        assert render_style_for_preset(preset) == "animated", preset


def test_none_or_unrecognized_preset_stays_unset():
    """The ambiguous case — checklist §C13b: 'if ambiguous, don't derive,
    leave NULL'. Must never guess when the preset itself couldn't be
    resolved."""
    assert render_style_for_preset(None) is None
    assert render_style_for_preset("some_future_preset_id") is None


def test_derivation_chain_from_freeform_visual_style_text():
    """The real end-to-end classifier chain routes/videos.py's create_video
    and channel_format.apply_format_defaults both use: freeform text ->
    _normalize_style_preset -> render_style_for_preset."""
    assert render_style_for_preset(_normalize_style_preset("Pixar 3D")) == "animated"
    assert render_style_for_preset(_normalize_style_preset("cinematic realistic")) == "realistic"
    assert render_style_for_preset(_normalize_style_preset("anime")) == "animated"
    # A freeform style that matches none of the six presets' keywords is
    # genuinely ambiguous — must stay unset, not guess.
    preset = _normalize_style_preset("a weird custom vibe nobody's seen before")
    assert preset is None
    assert render_style_for_preset(preset) is None


def test_channel_format_style_chain_is_the_same_classifier():
    """channel_format.apply_format_defaults's path (locked channel format's
    free-text style -> style_preset_for_format -> render_style_for_preset)
    must agree with the explicit-choice path above for the same input."""
    fmt = {"style": "animated 3D Pixar-style"}
    preset = style_preset_for_format(fmt)
    assert preset == "pixar_3d"
    assert render_style_for_preset(preset) == "animated"

    fmt2 = {"style": "live-action, nobody on camera"}
    preset2 = style_preset_for_format(fmt2)
    assert preset2 == "realistic"
    assert render_style_for_preset(preset2) == "realistic"


if __name__ == "__main__":
    test_realistic_preset_maps_to_realistic()
    test_illustrated_presets_map_to_animated()
    test_none_or_unrecognized_preset_stays_unset()
    test_derivation_chain_from_freeform_visual_style_text()
    test_channel_format_style_chain_is_the_same_classifier()
    print("OK")
