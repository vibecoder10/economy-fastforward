"""Tests for sound prompt bot curation logic.

Tests the pure logic functions (bounds, parsing, enforcement) without
importing the full client dependency chain.
"""

import json
import math
import sys
from unittest.mock import MagicMock

import pytest

# Mock heavy client dependencies before importing sound_prompt_bot
sys.modules.setdefault("clients.anthropic_client", MagicMock())
sys.modules.setdefault("clients.airtable_client", MagicMock())

from bots.sound_prompt_bot import SoundPromptBot, MIN_SOUND_PERCENT, MAX_SOUND_PERCENT


def _make_image(scene: int, index: int, text: str = "narration", prompt: str = "visual") -> dict:
    return {
        "id": f"rec_{scene}_{index}",
        "Scene": scene,
        "Image Index": index,
        "Sentence Text": text,
        "Image Prompt": prompt,
        "Shot Type": "wide",
    }


def _make_scene_images(scene: int, count: int) -> list[dict]:
    return [_make_image(scene, i + 1) for i in range(count)]


def _bot() -> SoundPromptBot:
    """Create a SoundPromptBot without triggering client __init__."""
    bot = SoundPromptBot.__new__(SoundPromptBot)
    bot.min_sound_pct = MIN_SOUND_PERCENT
    bot.max_sound_pct = MAX_SOUND_PERCENT
    return bot


class TestComputeBounds:
    """Test percentage-based min/max sound selection bounds."""

    def test_6_images_scene(self):
        """Standard scene: 6 images -> min 2, max 3."""
        bot = _bot()
        min_s, max_s = bot._compute_bounds(6)
        assert min_s == 2  # ceil(6 * 0.25) = 2
        assert max_s == 3  # floor(6 * 0.60) = 3

    def test_4_images_scene(self):
        """Short scene: 4 images -> min 1, max 2."""
        bot = _bot()
        min_s, max_s = bot._compute_bounds(4)
        assert min_s == 1  # ceil(4 * 0.25) = 1
        assert max_s == 2  # floor(4 * 0.60) = 2

    def test_10_images_scene(self):
        """Long scene: 10 images -> min 3, max 6."""
        bot = _bot()
        min_s, max_s = bot._compute_bounds(10)
        assert min_s == 3  # ceil(10 * 0.25) = 3
        assert max_s == 6  # floor(10 * 0.60) = 6

    def test_1_image_scene(self):
        """Single image: always at least 1."""
        bot = _bot()
        min_s, max_s = bot._compute_bounds(1)
        assert min_s == 1
        assert max_s == 1

    def test_2_images_scene(self):
        """2 images -> min 1, max 1."""
        bot = _bot()
        min_s, max_s = bot._compute_bounds(2)
        assert min_s == 1  # ceil(2 * 0.25) = 1
        assert max_s == 1  # floor(2 * 0.60) = 1

    def test_min_never_exceeds_max(self):
        """Min should never exceed max for any count 1-30."""
        bot = _bot()
        for count in range(1, 30):
            min_s, max_s = bot._compute_bounds(count)
            assert min_s <= max_s, f"min {min_s} > max {max_s} for {count} images"
            assert min_s >= 1, f"min was 0 for {count} images"


class TestParseCurationResponse:
    """Test parsing Claude's curation JSON response."""

    def setup_method(self):
        self.bot = _bot()
        self.images = _make_scene_images(1, 6)

    def test_clean_json(self):
        response = json.dumps([
            {"image_index": 1, "sound": True},
            {"image_index": 2, "sound": False},
            {"image_index": 3, "sound": True},
            {"image_index": 4, "sound": False},
            {"image_index": 5, "sound": True},
            {"image_index": 6, "sound": False},
        ])
        result = self.bot._parse_curation_response(response, self.images)
        assert len(result) == 6
        assert result[0] == {"image_index": 1, "sound": True}
        assert result[1] == {"image_index": 2, "sound": False}

    def test_markdown_fenced_json(self):
        response = '```json\n[{"image_index": 1, "sound": true}, {"image_index": 2, "sound": false}]\n```'
        result = self.bot._parse_curation_response(response, self.images)
        selected = [r for r in result if r["sound"]]
        assert len(selected) == 1

    def test_json_with_surrounding_text(self):
        response = 'Here is my selection:\n[{"image_index": 1, "sound": true}]\nDone!'
        result = self.bot._parse_curation_response(response, self.images)
        selected = [r for r in result if r["sound"]]
        assert len(selected) == 1

    def test_missing_indices_filled_as_false(self):
        """Images not mentioned by Claude default to sound=False."""
        response = json.dumps([
            {"image_index": 1, "sound": True},
            {"image_index": 3, "sound": True},
        ])
        result = self.bot._parse_curation_response(response, self.images)
        assert len(result) == 6
        for r in result:
            if r["image_index"] in (2, 4, 5, 6):
                assert r["sound"] is False

    def test_invalid_json_returns_empty(self):
        result = self.bot._parse_curation_response("not json at all", self.images)
        assert result == []

    def test_invalid_indices_ignored(self):
        response = json.dumps([
            {"image_index": 1, "sound": True},
            {"image_index": 99, "sound": True},
        ])
        result = self.bot._parse_curation_response(response, self.images)
        assert len(result) == 6
        assert sum(1 for r in result if r["sound"]) == 1


class TestEnforceBounds:
    """Test min/max enforcement on curation selections."""

    def setup_method(self):
        self.bot = _bot()

    def test_too_few_promotes_earlier_images(self):
        selections = [
            {"image_index": i, "sound": False} for i in range(1, 7)
        ]
        result = self.bot._enforce_bounds(selections, min_sounds=2, max_sounds=4)
        selected = [r for r in result if r["sound"]]
        assert len(selected) == 2
        assert selected[0]["image_index"] == 1
        assert selected[1]["image_index"] == 2

    def test_too_many_demotes_later_images(self):
        selections = [
            {"image_index": i, "sound": True} for i in range(1, 7)
        ]
        result = self.bot._enforce_bounds(selections, min_sounds=2, max_sounds=3)
        selected = [r for r in result if r["sound"]]
        assert len(selected) == 3

    def test_within_bounds_unchanged(self):
        selections = [
            {"image_index": 1, "sound": True},
            {"image_index": 2, "sound": False},
            {"image_index": 3, "sound": True},
            {"image_index": 4, "sound": False},
            {"image_index": 5, "sound": True},
            {"image_index": 6, "sound": False},
        ]
        result = self.bot._enforce_bounds(selections, min_sounds=2, max_sounds=4)
        selected = [r for r in result if r["sound"]]
        assert len(selected) == 3

    def test_result_sorted_by_index(self):
        selections = [
            {"image_index": 3, "sound": True},
            {"image_index": 1, "sound": False},
            {"image_index": 2, "sound": True},
        ]
        result = self.bot._enforce_bounds(selections, min_sounds=1, max_sounds=3)
        indices = [r["image_index"] for r in result]
        assert indices == [1, 2, 3]


class TestFallbackSelection:
    """Test fallback when Claude fails to return valid curation."""

    def setup_method(self):
        self.bot = _bot()

    def test_evenly_spaced_selection(self):
        images = _make_scene_images(1, 6)
        result = self.bot._fallback_selection(images, min_sounds=2)
        selected = [r for r in result if r["sound"]]
        assert len(selected) == 2

    def test_single_image(self):
        images = _make_scene_images(1, 1)
        result = self.bot._fallback_selection(images, min_sounds=1)
        assert len(result) == 1
        assert result[0]["sound"] is True

    def test_empty_scene(self):
        result = self.bot._fallback_selection([], min_sounds=1)
        assert result == []

    def test_all_images_selected_when_min_equals_count(self):
        images = _make_scene_images(1, 3)
        result = self.bot._fallback_selection(images, min_sounds=3)
        selected = [r for r in result if r["sound"]]
        assert len(selected) == 3
