"""Tests for animation_prompt_engine.py — animation prompt generation."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from animation_prompt_engine import (
    generate_animation_prompt,
    generate_prompts_for_segments,
    ANIMATION_TEMPLATES,
    UNIVERSAL_RULES,
)


class TestAnimationTemplateStructure:
    """Verify template data structure integrity."""

    def test_all_intensities_exist(self):
        for intensity in ("low", "medium", "high"):
            assert intensity in ANIMATION_TEMPLATES
            assert "motion_by_type" in ANIMATION_TEMPLATES[intensity]
            assert "prefix" in ANIMATION_TEMPLATES[intensity]

    def test_all_content_types_covered(self):
        expected_types = {
            "A_geographic_map", "B_data_terminal", "C_object_comparison",
            "D_document_display", "E_network_diagram", "F_timeline",
            "G_satellite", "H_abstract_concept",
        }
        for intensity in ("low", "medium", "high"):
            types = set(ANIMATION_TEMPLATES[intensity]["motion_by_type"].keys())
            assert types == expected_types, f"Missing types for {intensity}: {expected_types - types}"

    def test_motion_descriptions_non_empty(self):
        for intensity, tmpl in ANIMATION_TEMPLATES.items():
            for content_type, motion in tmpl["motion_by_type"].items():
                assert len(motion) > 20, f"Motion for {intensity}/{content_type} too short"


class TestGenerateAnimationPrompt:
    """Individual prompt generation."""

    def _make_segment(self, intensity: str = "low") -> dict:
        return {
            "index": 0,
            "text": "Test segment text.",
            "word_count": 25,
            "intensity": intensity,
        }

    def test_low_intensity_prompt(self):
        seg = self._make_segment("low")
        prompt = generate_animation_prompt(seg, "B_data_terminal", 10)
        assert "ambient" in prompt.lower() or "subtle" in prompt.lower()
        assert "10 seconds" in prompt

    def test_medium_intensity_prompt(self):
        seg = self._make_segment("medium")
        prompt = generate_animation_prompt(seg, "A_geographic_map", 10)
        assert "reveal" in prompt.lower() or "active" in prompt.lower()

    def test_high_intensity_prompt(self):
        seg = self._make_segment("high")
        prompt = generate_animation_prompt(seg, "E_network_diagram", 6)
        assert "dramatic" in prompt.lower()
        assert "6 seconds" in prompt

    def test_universal_rules_present(self):
        seg = self._make_segment("low")
        prompt = generate_animation_prompt(seg, "B_data_terminal", 10)
        assert "no zoom or reframe" in prompt.lower() or "do not zoom" in prompt.lower()
        assert "no human figures" in prompt.lower() or "No human" in prompt

    def test_unknown_content_type_falls_back(self):
        seg = self._make_segment("medium")
        prompt = generate_animation_prompt(seg, "Z_unknown_type", 10)
        # Should fall back to B_data_terminal, not crash
        assert len(prompt) > 50

    def test_empty_content_type_falls_back(self):
        seg = self._make_segment("low")
        prompt = generate_animation_prompt(seg, "", 10)
        assert len(prompt) > 50

    def test_6s_clip_duration(self):
        seg = self._make_segment("low")
        prompt = generate_animation_prompt(seg, "B_data_terminal", 6)
        assert "6 seconds" in prompt

    def test_10s_clip_duration(self):
        seg = self._make_segment("low")
        prompt = generate_animation_prompt(seg, "B_data_terminal", 10)
        assert "10 seconds" in prompt

    def test_all_content_types_produce_prompts(self):
        seg = self._make_segment("medium")
        content_types = [
            "A_geographic_map", "B_data_terminal", "C_object_comparison",
            "D_document_display", "E_network_diagram", "F_timeline",
            "G_satellite", "H_abstract_concept",
        ]
        for ct in content_types:
            prompt = generate_animation_prompt(seg, ct, 10)
            assert len(prompt) > 50, f"Empty prompt for {ct}"


class TestGeneratePromptsForSegments:
    """Batch prompt generation."""

    def test_generates_for_all_segments(self):
        segments = [
            {"index": i, "text": f"Segment {i}.", "word_count": 25, "intensity": "low"}
            for i in range(5)
        ]
        results = generate_prompts_for_segments(segments, clip_duration=10)
        assert len(results) == 5

    def test_respects_content_type_mapping(self):
        segments = [
            {"index": 0, "text": "Map segment.", "word_count": 25, "intensity": "high"},
            {"index": 1, "text": "Chart segment.", "word_count": 25, "intensity": "low"},
        ]
        content_types = {0: "A_geographic_map", 1: "B_data_terminal"}
        results = generate_prompts_for_segments(segments, content_types, 10)

        # High intensity segment should have dramatic language
        assert "dramatic" in results[0]["animation_prompt"].lower() or "high-energy" in results[0]["animation_prompt"].lower()
        # Low intensity should have subtle language
        assert "subtle" in results[1]["animation_prompt"].lower() or "ambient" in results[1]["animation_prompt"].lower()

    def test_result_has_required_fields(self):
        segments = [{"index": 0, "text": "Test.", "word_count": 25, "intensity": "medium"}]
        results = generate_prompts_for_segments(segments, clip_duration=10)
        assert "segment_index" in results[0]
        assert "intensity" in results[0]
        assert "animation_prompt" in results[0]
