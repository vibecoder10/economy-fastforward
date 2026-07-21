"""_enforce_stylized_media: an animated/stylized style must reach the image
models with an explicit photorealism ban; everything else passes untouched.

Live evidence (2026-07-21): video cd5d2883 'Spanish Class' carried the weak
'Soft 3D Pixar-style CG, subsurface skin, shallow depth of field' look and its
nano-banana-2 storyboard sheets drifted fully live-action (the photoreal
environment reference dominated). El Mercado 65a8021e, identical pipeline but
a style carrying 'NOT photorealistic, NOT live-action', held the 3D-cartoon
look on every panel. The guard turns the first case into the second.
"""

import os
import sys
import types

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


_stub("database", fetch_one=_boom, fetch_all=_boom, execute=_boom)
_stub("storage", upload_bytes=_boom)
_stub("vault", get_secret=_boom)
_stub("kie_unified", get_text_client_for_tenant=_boom)

from scripts.coverage_to_app import (  # noqa: E402
    _enforce_stylized_media, _resolve_style,
)

BAN = "NOT photorealistic, NOT live-action, NOT a real photograph."


def test_weak_animated_style_gains_the_ban():
    weak = "Soft 3D animated CG, rounded forms, warm cinematic light, subsurface skin, shallow depth of field"
    out = _enforce_stylized_media(weak)
    assert out.startswith(weak)
    assert out.endswith(BAN)
    assert "characters, sets, props and food alike" in out


def test_style_already_banning_photoreal_is_untouched():
    strong = ("3D animated CGI comedy style. Fully animated 3D cartoon, "
              "NOT photorealistic, NOT live-action, NOT a real photograph.")
    assert _enforce_stylized_media(strong) == strong


def test_realistic_style_is_untouched():
    realistic = "Photorealistic cinematic photography, natural lighting, real textures"
    assert _enforce_stylized_media(realistic) == realistic


def test_no_style_passes_through():
    assert _enforce_stylized_media(None) is None
    assert _enforce_stylized_media("") == ""
    assert _enforce_stylized_media("   ") == "   "


def test_other_stylized_media_gain_the_ban_too():
    for look in (
        "Modern anime cel-shaded illustration, expressive faces",
        "Warm hand-painted watercolor storybook art, soft edges",
        "Bold graphic-novel illustration, inked outlines",
    ):
        assert _enforce_stylized_media(look).endswith(BAN)


def test_resolve_style_applies_scrub_then_ban():
    # The exact pre-fix Spanish Class override: brand-scrub must remove the
    # studio name AND the guard must append the ban, in that order.
    profile, directive = _resolve_style(
        "Soft 3D Pixar-style CG, rounded forms, warm cinematic light, "
        "subsurface skin, shallow depth of field", None)
    assert "pixar" not in directive.lower()
    assert directive.endswith(BAN)


def test_resolve_style_no_pick_stays_none():
    profile, directive = _resolve_style(None, None)
    assert directive is None
