"""C25a-fix14 (2026-07-20): style-brand neutralizer.

Root cause (Ryan's catch, live on PocoAPoco 'El Mercado' 65a8021e): a
trademarked studio name in the STYLE prompt reads as an IP/policy reference to
GPT Image 2, which returns "content could not be processed" (failCode 400, 0
credits). A storyboard board that reliably 400'd on this scene drew clean on
the primary header the moment the studio name came out of the style — nothing
else changed. (This dwarfed the earlier caption / panel-count contributions,
which only nudged marginal sheets.)

Fix: scripts/coverage_to_app.py's _neutralize_style_brands() + the explicit
_STYLE_BRAND_PATTERNS list, wired into _resolve_style — the ONE seam every
image path (director, cast sheet, storyboard) draws its style from — so a
studio name can never reach an image prompt no matter how it entered the
stored style (creator entry, producer-LLM elaboration, legacy preset). Only
the human-readable style DESCRIPTION is scrubbed; the classifier IDs
(channel_format 'pixar_3d' etc.) are internal keys that never reach an image
model and are deliberately untouched.

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest \
        tests/functional/test_c25a_fix14_style_brand_neutralizer.py -q
"""
import os
import subprocess
import sys

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
_PIPELINE_PATH = os.path.join(_BACKEND, "..", "..", "..", "skills", "video-pipeline")
sys.path.insert(0, os.path.abspath(_BACKEND))
sys.path.insert(0, os.path.abspath(_PIPELINE_PATH))

from scripts.coverage_to_app import (  # noqa: E402
    _neutralize_style_brands, _STYLE_BRAND_PATTERNS,
)

# The trademarked studio names that must NEVER survive into a style prompt.
_BANNED = ["pixar", "disney", "dreamworks", "illumination", "ghibli", "laika", "aardman"]


# ---------------------------------------------------------------------------
# 1. The exact El Mercado style that tripped the filter is fully scrubbed.
# ---------------------------------------------------------------------------

def test_el_mercado_style_scrubbed():
    original = ("3D animated CGI comedy style, stylized Pixar-like characters with warm "
                "expressive faces, soft rounded forms, clean bright saturated colors, smooth "
                "cartoon shading, playful sitcom staging. Fully animated cartoon, NOT "
                "photorealistic, NOT live-action, NOT a real photograph.")
    out = _neutralize_style_brands(original)
    assert "pixar" not in out.lower(), out
    # The LOOK survives — only the studio name is swapped, to neutral craft words.
    assert "stylized 3D animated characters" in out, out
    assert "warm expressive faces" in out and "smooth cartoon shading" in out


# ---------------------------------------------------------------------------
# 2. Every studio name -> neutral craft language, across phrasings.
# ---------------------------------------------------------------------------

def test_all_studio_names_are_removed():
    samples = [
        "Soft 3D Pixar-style CG, rounded forms",
        "Disney Pixar-style 3D animation",
        "DreamWorks-style CG characters",
        "an Illumination-inspired look",
        "Studio Ghibli watercolor storybook",
        "Laika stop-motion feel",
        "Aardman claymation vibe",
        "Walt Disney animation classic",
    ]
    for s in samples:
        out = _neutralize_style_brands(s).lower()
        for brand in _BANNED:
            assert brand not in out, (brand, s, out)
        assert "animated" in out, (s, out)  # a neutral medium word replaces it


# ---------------------------------------------------------------------------
# 3. No word-doubling and no lost separators (the two bugs caught in dev).
# ---------------------------------------------------------------------------

def test_no_doubled_3d_and_separators_preserved():
    # "3D Pixar-style" would naively become "3D 3D animated" — collapse it.
    assert _neutralize_style_brands("Soft 3D Pixar-style CG") == "Soft 3D animated CG"
    # A bare studio name keeps the space before the next word.
    assert _neutralize_style_brands("Studio Ghibli watercolor look") == \
        "hand-drawn animated watercolor look"
    assert _neutralize_style_brands("Disney movie about a dog") == "3D animated movie about a dog"


# ---------------------------------------------------------------------------
# 4. Non-brand style text passes through byte-identical.
# ---------------------------------------------------------------------------

def test_non_brand_styles_untouched():
    for s in [
        "Clean 2D flat vector animation, bold flat colors, crisp outlines",
        "Photorealistic cinematic photography, natural lighting",
        "Modern anime cel-shaded illustration, expressive faces",
        "Warm hand-painted watercolor storybook art, soft edges",
    ]:
        assert _neutralize_style_brands(s) == s


def test_none_and_empty_pass_through():
    assert _neutralize_style_brands(None) is None
    assert _neutralize_style_brands("") == ""


# ---------------------------------------------------------------------------
# 5. The pattern table is a flat, inspectable, append-only list (add new
#    studios here, nowhere else).
# ---------------------------------------------------------------------------

def test_pattern_table_shape():
    assert isinstance(_STYLE_BRAND_PATTERNS, list)
    assert len(_STYLE_BRAND_PATTERNS) >= 6
    for pattern, replacement in _STYLE_BRAND_PATTERNS:
        assert hasattr(pattern, "sub"), pattern
        assert isinstance(replacement, str) and "animated" in replacement


# ---------------------------------------------------------------------------
# 6. py_compile guard.
# ---------------------------------------------------------------------------

def test_module_compiles():
    target = os.path.abspath(os.path.join(_BACKEND, "scripts", "coverage_to_app.py"))
    result = subprocess.run(
        [sys.executable, "-m", "py_compile", target], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


if __name__ == "__main__":
    test_el_mercado_style_scrubbed()
    test_all_studio_names_are_removed()
    test_no_doubled_3d_and_separators_preserved()
    test_non_brand_styles_untouched()
    test_none_and_empty_pass_through()
    test_pattern_table_shape()
    test_module_compiles()
    print("\nAll C25a-fix14 style-brand-neutralizer tests passed.")
