"""Tests for animation_prompt_engine.py — animation prompt generation.

Tests cover:
- Template structure integrity
- Rule 1: Verb-first motion design (verb extraction)
- Rule 2: Static camera default, camera only for REVEAL/SCALE/ISOLATION
- Rule 3: Maximum 2 animated elements per prompt
- Batch generation
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from animation_prompt_engine import (
    generate_animation_prompt,
    generate_prompts_for_segments,
    extract_core_verb,
    classify_camera_purpose,
    count_animated_elements,
    validate_max_actions,
    ANIMATION_TEMPLATES,
    UNIVERSAL_RULES,
    CAMERA_PURPOSE_STATIC,
    CAMERA_PURPOSE_REVEAL,
    CAMERA_PURPOSE_SCALE,
    CAMERA_PURPOSE_ISOLATION,
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

    def test_all_templates_start_with_static(self):
        """Rule 2: All templates should default to static camera."""
        for intensity, tmpl in ANIMATION_TEMPLATES.items():
            for content_type, motion in tmpl["motion_by_type"].items():
                assert motion.startswith("Static wide shot"), (
                    f"{intensity}/{content_type} doesn't start with 'Static wide shot': {motion[:50]}"
                )

    def test_low_templates_have_max_one_action(self):
        """Rule 3: Low intensity templates should have at most 1 subject action."""
        for content_type, motion in ANIMATION_TEMPLATES["low"]["motion_by_type"].items():
            # Count sentences after "Static wide shot."
            rest = motion.replace("Static wide shot.", "").strip()
            sentences = [s.strip() for s in rest.split(".") if s.strip()]
            assert len(sentences) <= 2, (
                f"Low/{content_type} has {len(sentences)} action sentences (max 1 expected): {motion}"
            )


class TestVerbExtraction:
    """Rule 1: Verb extraction from sentence text."""

    def test_extracts_going_dark(self):
        verb = extract_core_verb("Launch site after launch site going dark")
        assert verb == "going dark"

    def test_extracts_scattered(self):
        verb = extract_core_verb("Scattered across hardened bunkers")
        assert "scatter" in verb

    def test_extracts_frozen(self):
        verb = extract_core_verb("The count locks frozen at zero")
        assert verb == "locks frozen"

    def test_extracts_dont_matter(self):
        verb = extract_core_verb("Your missiles don't matter")
        assert verb == "don't matter"

    def test_extracts_collapse(self):
        verb = extract_core_verb("The entire network collapses overnight")
        assert "collapse" in verb

    def test_extracts_surge(self):
        verb = extract_core_verb("Oil prices surge past $200 a barrel")
        assert "surge" in verb

    def test_empty_text_returns_empty(self):
        assert extract_core_verb("") == ""

    def test_no_verb_returns_empty_or_fallback(self):
        result = extract_core_verb("The big red thing")
        # May return empty or a fallback — should not crash
        assert isinstance(result, str)

    def test_phrasal_verb_takes_priority(self):
        verb = extract_core_verb("Systems are shutting down rapidly")
        assert verb == "shutting down"

    def test_extracts_spread_across(self):
        verb = extract_core_verb("Forces spread across the continent")
        assert "spread" in verb


class TestCameraPurpose:
    """Rule 2: Camera purpose classification."""

    def test_default_is_static(self):
        assert classify_camera_purpose("The chart shows a decline") == CAMERA_PURPOSE_STATIC

    def test_empty_text_is_static(self):
        assert classify_camera_purpose("") == CAMERA_PURPOSE_STATIC

    def test_reveal_keywords(self):
        assert classify_camera_purpose("Behind the data reveals a hidden network") == CAMERA_PURPOSE_REVEAL

    def test_scale_keywords(self):
        assert classify_camera_purpose("Thousands of missiles spanning the entire continent") == CAMERA_PURPOSE_SCALE

    def test_isolation_keywords(self):
        assert classify_camera_purpose("Only one critical node remains active") == CAMERA_PURPOSE_ISOLATION

    def test_generic_sentence_is_static(self):
        assert classify_camera_purpose("Oil prices dropped last quarter") == CAMERA_PURPOSE_STATIC

    def test_valid_purposes(self):
        from animation_prompt_engine import VALID_CAMERA_PURPOSES
        assert CAMERA_PURPOSE_STATIC in VALID_CAMERA_PURPOSES
        assert CAMERA_PURPOSE_REVEAL in VALID_CAMERA_PURPOSES
        assert CAMERA_PURPOSE_SCALE in VALID_CAMERA_PURPOSES
        assert CAMERA_PURPOSE_ISOLATION in VALID_CAMERA_PURPOSES


class TestAnimatedElementCount:
    """Rule 3: Maximum 2 animated elements per prompt."""

    def test_static_with_one_action(self):
        prompt = "Static wide shot. Chart line draws itself left to right."
        count = count_animated_elements(prompt)
        assert count <= 2

    def test_camera_plus_one_action(self):
        prompt = "Slow push-in toward the central node. Connection lines snap and dissolve."
        count = count_animated_elements(prompt)
        assert count <= 2

    def test_validate_max_actions_passes(self):
        prompt = "Static wide shot. Route lines draw themselves across the map."
        valid, count = validate_max_actions(prompt)
        assert valid is True

    def test_empty_prompt(self):
        assert count_animated_elements("") == 0

    def test_validate_max_actions_returns_count(self):
        prompt = "Static wide shot. Labels hold steady."
        valid, count = validate_max_actions(prompt)
        assert isinstance(count, int)
        assert isinstance(valid, bool)


class TestGenerateAnimationPrompt:
    """Individual prompt generation."""

    def _make_segment(self, intensity: str = "low", text: str = "Test segment text.") -> dict:
        return {
            "index": 0,
            "text": text,
            "word_count": 25,
            "intensity": intensity,
        }

    def test_low_intensity_prompt(self):
        seg = self._make_segment("low")
        prompt = generate_animation_prompt(seg, "B_data_terminal", 10)
        assert "static" in prompt.lower()
        assert "10 seconds" in prompt

    def test_medium_intensity_prompt(self):
        seg = self._make_segment("medium")
        prompt = generate_animation_prompt(seg, "A_geographic_map", 10)
        assert "static" in prompt.lower()

    def test_high_intensity_prompt(self):
        seg = self._make_segment("high")
        prompt = generate_animation_prompt(seg, "E_network_diagram", 6)
        assert "static" in prompt.lower()
        assert "6 seconds" in prompt

    def test_universal_rules_present(self):
        seg = self._make_segment("low")
        prompt = generate_animation_prompt(seg, "B_data_terminal", 10)
        assert "No human figures" in prompt

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

    def test_verb_drives_motion_in_prompt(self):
        """Rule 1: Verb from sentence text should drive the motion description."""
        seg = self._make_segment("medium", text="Oil prices surge past $200")
        prompt = generate_animation_prompt(seg, "B_data_terminal", 10)
        # The verb "surge" maps to spike/rockets motion, NOT the generic template
        assert "spike" in prompt.lower() or "rocket" in prompt.lower()
        # Should NOT contain the generic medium/B_data_terminal template text
        assert "draws itself from left to right" not in prompt.lower()

    def test_static_camera_default(self):
        """Rule 2: Default prompt should have static camera."""
        seg = self._make_segment("medium", text="The chart shows a decline")
        prompt = generate_animation_prompt(seg, "B_data_terminal", 10)
        assert "static" in prompt.lower()

    def test_camera_added_for_reveal(self):
        """Rule 2: Camera motion added when sentence justifies REVEAL."""
        seg = self._make_segment("medium", text="Behind the curtain reveals hidden assets")
        prompt = generate_animation_prompt(seg, "B_data_terminal", 10)
        # Should have camera motion (lateral pan revealing) instead of static
        assert "reveal" in prompt.lower() or "pan" in prompt.lower()

    def test_camera_added_for_scale(self):
        """Rule 2: Camera motion added when sentence justifies SCALE."""
        seg = self._make_segment("medium", text="Thousands of missiles across the entire globe")
        prompt = generate_animation_prompt(seg, "A_geographic_map", 10)
        assert "pull-back" in prompt.lower() or "scale" in prompt.lower()

    def test_verb_motion_overrides_generic_template(self):
        """Rule 1: Verb-driven motion replaces the generic content-type template."""
        seg = self._make_segment("high", text="The network collapses overnight")
        prompt = generate_animation_prompt(seg, "E_network_diagram", 10)
        # Should use verb motion ("buckles inward") not generic HIGH/E template
        assert "buckles" in prompt.lower() or "flatline" in prompt.lower()
        # Should NOT contain the generic high/E_network_diagram text
        assert "explosion of particles" not in prompt.lower()

    def test_going_dark_produces_extinguish_motion(self):
        """Rule 1: 'going dark' = lights extinguishing, not generic satellite template."""
        seg = self._make_segment("high", text="Launch site after launch site going dark")
        prompt = generate_animation_prompt(seg, "G_satellite", 10)
        assert "extinguish" in prompt.lower()

    def test_dont_matter_produces_dissolve_motion(self):
        """Rule 1: 'don't matter' = dissolving to nothing, not generic comparison."""
        seg = self._make_segment("high", text="Your missiles don't matter")
        prompt = generate_animation_prompt(seg, "C_object_comparison", 10)
        assert "dissolve" in prompt.lower() or "fade" in prompt.lower()

    def test_no_verb_uses_content_type_template(self):
        """Rule 1 fallback: when no verb found, generic template is used."""
        seg = self._make_segment("medium", text="The big red chart.")
        prompt = generate_animation_prompt(seg, "B_data_terminal", 10)
        # Should use the generic medium/B_data_terminal template
        assert "chart line draws itself" in prompt.lower() or "draws itself" in prompt.lower()


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
            {"index": 0, "text": "Map explodes.", "word_count": 25, "intensity": "high"},
            {"index": 1, "text": "Chart holds steady.", "word_count": 25, "intensity": "low"},
        ]
        content_types = {0: "A_geographic_map", 1: "B_data_terminal"}
        results = generate_prompts_for_segments(segments, content_types, 10)

        # Both should have static camera (default)
        assert "static" in results[0]["animation_prompt"].lower()
        assert "static" in results[1]["animation_prompt"].lower()

    def test_result_has_required_fields(self):
        segments = [{"index": 0, "text": "Test.", "word_count": 25, "intensity": "medium"}]
        results = generate_prompts_for_segments(segments, clip_duration=10)
        assert "segment_index" in results[0]
        assert "intensity" in results[0]
        assert "clip_duration" in results[0]
        assert "animation_prompt" in results[0]
        assert "camera_purpose" in results[0]
        assert "core_verb" in results[0]

    def test_per_segment_clip_duration_override(self):
        """Segments with their own clip_duration override the global default."""
        segments = [
            {"index": 0, "text": "Short.", "word_count": 10, "intensity": "low", "clip_duration": 6},
            {"index": 1, "text": "Longer segment here.", "word_count": 25, "intensity": "low", "clip_duration": 10},
        ]
        results = generate_prompts_for_segments(segments, clip_duration=10)
        assert "6 seconds" in results[0]["animation_prompt"]
        assert results[0]["clip_duration"] == 6
        assert "10 seconds" in results[1]["animation_prompt"]
        assert results[1]["clip_duration"] == 10

    def test_camera_purpose_in_results(self):
        segments = [
            {"index": 0, "text": "Behind the data reveals hidden truth.", "word_count": 25, "intensity": "medium"},
            {"index": 1, "text": "Oil prices dropped.", "word_count": 25, "intensity": "low"},
        ]
        results = generate_prompts_for_segments(segments, clip_duration=10)
        assert results[0]["camera_purpose"] == CAMERA_PURPOSE_REVEAL
        assert results[1]["camera_purpose"] == CAMERA_PURPOSE_STATIC

    def test_core_verb_in_results(self):
        segments = [
            {"index": 0, "text": "The network collapses overnight.", "word_count": 25, "intensity": "high"},
        ]
        results = generate_prompts_for_segments(segments, clip_duration=10)
        assert "collapse" in results[0]["core_verb"]
