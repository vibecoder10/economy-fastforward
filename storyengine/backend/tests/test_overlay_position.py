"""Local-only tests for composition-aware documentary overlay placement."""

import os
import sys

from PIL import Image, ImageDraw
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import overlay_position  # noqa: E402


def _studio_image(path, subject_rect=None):
    image = Image.new("RGB", (960, 540), "#efede7")
    if subject_rect:
        render_rect = subject_rect
        scaled = tuple(round(value / 2) for value in render_rect)
        draw = ImageDraw.Draw(image)
        draw.rectangle(scaled, fill="#171717", outline="#050505", width=6)
        left, top, right, bottom = scaled
        draw.line((left, bottom, right, top), fill="#f5f5f5", width=5)
        draw.line((left, top, right, bottom), fill="#f5f5f5", width=5)
    image.save(path)


def _inset(rect, amount=24):
    left, top, right, bottom = rect
    return left + amount, top + amount, right - amount, bottom - amount


def test_subject_in_lower_left_selects_bottom_right(tmp_path):
    left_rect, _ = overlay_position.card_rectangles()
    path = tmp_path / "subject-left.png"
    _studio_image(path, _inset(left_rect))

    assert overlay_position.choose_overlay_position(path, view_index=1) == "bottom_right"


def test_subject_in_lower_right_selects_bottom_left(tmp_path):
    _, right_rect = overlay_position.card_rectangles()
    path = tmp_path / "subject-right.png"
    _studio_image(path, _inset(right_rect))

    assert overlay_position.choose_overlay_position(path, view_index=2) == "bottom_left"


def test_card_rectangles_match_remotion_card_footprint_and_safe_margins():
    assert overlay_position.RENDER_WIDTH == 1920
    assert overlay_position.RENDER_HEIGHT == 1080
    assert overlay_position.OVERLAY_SIDE_MARGIN == 76
    assert overlay_position.OVERLAY_BOTTOM_MARGIN == 68
    assert overlay_position.OVERLAY_CARD_WIDTH == 940
    assert overlay_position.OVERLAY_CARD_HEIGHT == 230

    left, right = overlay_position.card_rectangles()
    top = 1080 - 68 - 230
    bottom = 1080 - 68
    assert left == (76, top, 76 + 940, bottom)
    assert right == (1920 - 76 - 940, top, 1920 - 76, bottom)


def test_exact_occupancy_tie_alternates_deterministically_by_view_index(tmp_path):
    path = tmp_path / "empty-studio.png"
    _studio_image(path)

    assert overlay_position.choose_overlay_position(path, view_index=1) == "bottom_left"
    assert overlay_position.choose_overlay_position(path, view_index=2) == "bottom_right"
    assert overlay_position.choose_overlay_position(path, view_index=3) == "bottom_left"


def test_corrupt_image_raises_with_path_instead_of_guessing(tmp_path):
    path = tmp_path / "corrupt.png"
    path.write_bytes(b"this is not an image")

    with pytest.raises(RuntimeError, match="corrupt[.]png"):
        overlay_position.choose_overlay_position(path, view_index=1)
