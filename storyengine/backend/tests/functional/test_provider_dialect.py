"""Unit tests for backend/provider_dialect.py (D13-1).

Adapter-level tests: exercise ``dialect_for_model``, ``decorate_grok_prompt``,
and ``build_call`` directly, with no DB/network/executor involved. For the
end-to-end proof that ``pipeline_executor.py`` actually produces
byte-identical output THROUGH this adapter, see
``test_d13_1_provider_dialect_golden.py``.

Run: cd storyengine/backend && ./venv/bin/python -m pytest \
    tests/functional/test_provider_dialect.py -q
"""
import os
import sys

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

from provider_dialect import (  # noqa: E402
    ClipDialectRequest,
    build_call,
    decorate_grok_prompt,
    dialect_for_model,
)


# ---------------------------------------------------------------------------
# dialect_for_model
# ---------------------------------------------------------------------------

def test_dialect_classification():
    assert dialect_for_model("veo-3.1-fast") == "veo"
    assert dialect_for_model("veo-3.1-quality") == "veo"
    assert dialect_for_model("seedance-2-fast") == "seedance"
    assert dialect_for_model("grok-imagine") == "grok"


def test_dialect_classification_unknown_id_falls_through_to_grok():
    """_animate_for's own fallthrough: anything that isn't seedance/veo
    resolves to the grok closure — including a name the registry has never
    heard of."""
    assert dialect_for_model("some-future-model") == "grok"
    assert dialect_for_model("") == "grok"
    assert dialect_for_model(None) == "grok"


# ---------------------------------------------------------------------------
# decorate_grok_prompt — the @imageN dialect itself
# ---------------------------------------------------------------------------

def test_decorate_bare_has_no_image2_or_style_clause():
    out = decorate_grok_prompt("core motion", has_reference_sheet=False)
    assert out.startswith("Animate @image1 exactly as shown")
    assert "@image2" not in out
    assert "Art style" not in out
    assert out.endswith("Motion: core motion")


def test_decorate_with_reference_sheet_adds_image2_clause():
    out = decorate_grok_prompt("core motion", has_reference_sheet=True)
    assert "@image2 is the official cast sheet" in out
    assert "(" not in out.split("@image2 is the official cast sheet", 1)[1].split("—")[0]


def test_decorate_with_cast_names_adds_parenthetical():
    out = decorate_grok_prompt("core motion", has_reference_sheet=True, cast_names="Tom, Jerry")
    assert "@image2 is the official cast sheet (Tom, Jerry) —" in out


def test_decorate_with_style_note_has_no_trailing_period_before_motion():
    """Pre-existing quirk (not this chunk's to fix, preserved byte-for-byte):
    the style clause has no trailing period, so it runs straight into
    " Motion: ..." with a single space."""
    out = decorate_grok_prompt("core motion", has_reference_sheet=False, style_note="noir")
    assert "Art style: noir Motion: core motion" in out


def test_decorate_with_camera_mode_appends_camera_grammar_clause():
    out = decorate_grok_prompt(
        "core motion", has_reference_sheet=False,
        camera_mode="dialogue_coverage", camera_seconds=12)
    assert out.endswith(
        "Use the approved dialogue_coverage camera grammar for this exact 12-second section.")


# ---------------------------------------------------------------------------
# build_call — the ONE adapter entry point
# ---------------------------------------------------------------------------

def _req(**over):
    base = dict(core_prompt="push in slowly", image_url="https://x/img.png", duration=6)
    base.update(over)
    return ClipDialectRequest(**base)


def test_build_call_grok_shape():
    call = build_call("grok-imagine", _req(aspect_ratio="9:16", resolution="480p"))
    assert call.method == "generate_video"
    assert call.prompt.startswith("Animate @image1")
    assert call.kwargs == {
        "duration": 6, "extra_image_urls": None,
        "aspect_ratio": "9:16", "resolution": "480p", "task_id_out": None,
    }


def test_build_call_grok_with_reference_sheet_sets_extra_image_urls():
    call = build_call("grok-imagine", _req(reference_image_urls=["https://x/sheet.png"]))
    assert call.kwargs["extra_image_urls"] == ["https://x/sheet.png"]
    assert "@image2" in call.prompt


def test_build_call_seedance_shape_has_no_resolution_key():
    call = build_call("seedance-2-fast", _req())
    assert call.method == "generate_video_seedance"
    assert call.prompt.startswith("Animate @image1"), "seedance shares Grok's decoration"
    assert "resolution" not in call.kwargs
    assert set(call.kwargs) == {"duration", "extra_image_urls", "aspect_ratio", "task_id_out"}


def test_build_call_veo_shape_is_raw_prompt_with_image_url_kwarg():
    task_box = []
    call = build_call("veo-3.1-quality", _req(veo_model="veo-quality-id", task_id_out=task_box))
    assert call.method == "generate_video_veo"
    assert call.prompt == "push in slowly", "veo must NOT get @image1/@image2 decoration"
    assert call.kwargs == {
        "image_url": "https://x/img.png", "model": "veo-quality-id", "task_id_out": task_box,
    }
    assert "duration" not in call.kwargs
    assert "extra_image_urls" not in call.kwargs
    assert "resolution" not in call.kwargs


def test_build_call_unknown_model_falls_back_to_grok_shape():
    call = build_call("some-future-model", _req())
    assert call.method == "generate_video"
    assert call.prompt.startswith("Animate @image1")
