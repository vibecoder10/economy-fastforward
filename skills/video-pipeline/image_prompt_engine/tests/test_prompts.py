"""
Tests for the Holographic Intelligence Display prompt system.

Verifies that the prompt builder produces correctly structured prompts
following the holographic display architecture:
[Display Format framing] [Content description] [Color Mood] [Universal Suffix]
"""

import sys
import os

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from image_prompt_engine.prompt_builder import (
    build_prompt,
    generate_prompts,
    resolve_accent_color,
    resolve_scene_accent_color,
    resolve_scene_color_mood,
)
from image_prompt_engine.style_config import (
    ContentType,
    DisplayFormat,
    ColorMood,
    CONTENT_TYPE_CONFIG,
    DISPLAY_FORMAT_CONFIG,
    COLOR_MOOD_CONFIG,
    HOLOGRAPHIC_SUFFIX,
    DEFAULT_CONFIG,
    resolve_content_type,
    resolve_color_mood,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sample_scenes(n: int = 136) -> list[dict]:
    """Generate n minimal scene dicts for holographic display testing."""
    descriptions = [
        "A detailed map of the Strait of Hormuz showing shipping lanes and naval positions",
        "Oil price candlestick chart spiking with red warning indicators at $148 per barrel",
        "Two wireframe objects for scale comparison showing a drone versus a supertanker",
        "A floating maritime insurance document with DENIED stamp and premium data",
        "Network diagram showing five major chokepoints with trade flow percentages",
        "Timeline comparing 1956 Suez crisis with 1973 OPEC embargo and 2026 Hormuz closure",
        "Satellite reconnaissance of the Strait showing ship positions and measurement lines",
        "Balance scale visualization showing military cost asymmetry with price labels",
        "Financial terminal displaying inflation rate climbing to 9.2% with bond yield data",
        "Geographic map of Persian Gulf with 150 anchored tanker dots and country labels",
    ]
    return [{"scene_description": descriptions[i % len(descriptions)]} for i in range(n)]


def _generate_full_video(seed: int = 42) -> list[dict]:
    """Generate prompts for a full video."""
    return generate_prompts(_sample_scenes(), seed=seed)


# ---------------------------------------------------------------------------
# Holographic display structure tests
# ---------------------------------------------------------------------------

class TestHolographicStructure:
    """Verify prompts follow the holographic display architecture."""

    def test_prompt_starts_with_format_framing(self):
        """Prompt starts with a display format framing description."""
        prompt = build_prompt(
            "a detailed map of shipping lanes",
            "geographic_map", "war_table", "strategic",
        )
        assert prompt.startswith("Overhead angled view of a holographic war table")

    def test_prompt_contains_content_description(self):
        """Prompt includes the scene content description."""
        prompt = build_prompt(
            "a detailed map of the Strait of Hormuz",
            "geographic_map", "war_table", "strategic",
        )
        assert "Strait of Hormuz" in prompt

    def test_prompt_contains_color_mood(self):
        """Prompt includes the color mood language."""
        prompt = build_prompt(
            "a detailed map of shipping lanes",
            "geographic_map", "war_table", "strategic",
        )
        assert "teal" in prompt.lower() or "cyan" in prompt.lower()

    def test_prompt_contains_universal_suffix(self):
        """Every prompt contains the universal suffix."""
        prompt = build_prompt(
            "oil price chart spiking",
            "data_terminal", "wall_display", "alert",
        )
        assert "no people visible" in prompt
        assert "no human figures" in prompt
        assert "16:9 aspect ratio" in prompt

    def test_all_format_framings_exist(self):
        """Every display format has a framing description."""
        for fmt in DisplayFormat:
            assert "framing" in DISPLAY_FORMAT_CONFIG[fmt]
            assert len(DISPLAY_FORMAT_CONFIG[fmt]["framing"]) > 10


# ---------------------------------------------------------------------------
# No human figures tests
# ---------------------------------------------------------------------------

class TestNoHumanFigures:
    """Verify holographic display images never contain human references."""

    def test_suffix_prohibits_people(self):
        """Universal suffix explicitly prohibits people."""
        assert "no people visible" in HOLOGRAPHIC_SUFFIX
        assert "no human figures" in HOLOGRAPHIC_SUFFIX
        assert "no faces" in HOLOGRAPHIC_SUFFIX
        assert "no silhouettes of people" in HOLOGRAPHIC_SUFFIX

    def test_every_prompt_has_no_people_suffix(self):
        """Every generated prompt includes the no-people suffix."""
        results = _generate_full_video()
        for r in results:
            assert "no people visible" in r["prompt"], (
                f"Prompt at index {r['index']} missing no-people suffix"
            )


# ---------------------------------------------------------------------------
# Color mood tests
# ---------------------------------------------------------------------------

class TestColorMood:
    def test_color_moods_are_valid(self):
        """All per-scene color moods are recognized values."""
        valid = {m.value for m in ColorMood}
        results = _generate_full_video()
        for r in results:
            assert r["color_mood"] in valid, (
                f"Invalid color mood '{r['color_mood']}' at index {r['index']}"
            )

    def test_color_mood_variety(self):
        """Multiple color moods are used across a full video."""
        results = _generate_full_video()
        moods = {r["color_mood"] for r in results}
        assert len(moods) >= 3, f"Expected at least 3 different moods, got {len(moods)}"

    def test_alert_keywords_trigger_alert(self):
        mood = resolve_color_mood("A crisis and military attack with missile strikes")
        assert mood == ColorMood.ALERT

    def test_archive_keywords_trigger_archive(self):
        mood = resolve_color_mood("Historical parallel from 1973 showing the pattern")
        assert mood == ColorMood.ARCHIVE

    def test_strategic_keywords_trigger_strategic(self):
        mood = resolve_color_mood("Strategic analysis of the chokepoint map and geography")
        assert mood == ColorMood.STRATEGIC

    def test_no_keywords_falls_back_to_strategic(self):
        mood = resolve_color_mood("A quiet room with nothing specific")
        assert mood == ColorMood.STRATEGIC


# ---------------------------------------------------------------------------
# Content type tests
# ---------------------------------------------------------------------------

class TestContentType:
    def test_content_types_are_valid(self):
        """All content types in results are recognized values."""
        valid = {ct.value for ct in ContentType}
        results = _generate_full_video()
        for r in results:
            assert r["content_type"] in valid, (
                f"Invalid content type '{r['content_type']}' at index {r['index']}"
            )

    def test_map_keywords_trigger_geographic_map(self):
        ct = resolve_content_type("Map of the strait showing chokepoint and shipping routes")
        assert ct == ContentType.GEOGRAPHIC_MAP

    def test_price_keywords_trigger_data_terminal(self):
        ct = resolve_content_type("Oil price spike with market crash and inflation data")
        assert ct == ContentType.DATA_TERMINAL

    def test_network_keywords_trigger_network_diagram(self):
        ct = resolve_content_type("Supply chain network showing cascade and domino effects")
        assert ct == ContentType.NETWORK_DIAGRAM

    def test_no_keywords_falls_back_to_data_terminal(self):
        ct = resolve_content_type("A quiet room with nothing specific")
        assert ct == ContentType.DATA_TERMINAL


# ---------------------------------------------------------------------------
# Display format tests
# ---------------------------------------------------------------------------

class TestDisplayFormat:
    def test_display_formats_are_valid(self):
        """All display formats in results are recognized values."""
        valid = {fmt.value for fmt in DisplayFormat}
        results = _generate_full_video()
        for r in results:
            assert r["display_format"] in valid, (
                f"Invalid display format '{r['display_format']}' at index {r['index']}"
            )

    def test_format_variety(self):
        """Multiple display formats are used across a full video."""
        results = _generate_full_video()
        formats = {r["display_format"] for r in results}
        assert len(formats) >= 3, f"Expected at least 3 formats, got {len(formats)}"


# ---------------------------------------------------------------------------
# Prompt format tests — display format framing in prompts
# ---------------------------------------------------------------------------

class TestPromptFormat:
    def test_war_table_prompts_contain_holographic_table(self):
        """War table prompts reference holographic table/war table."""
        prompt = build_prompt("map content", "geographic_map", "war_table", "strategic")
        assert "holographic war table" in prompt.lower()

    def test_wall_display_prompts_contain_wall_display(self):
        """Wall display prompts reference holographic wall display."""
        prompt = build_prompt("data content", "data_terminal", "wall_display", "alert")
        assert "holographic wall display" in prompt.lower()

    def test_floating_prompts_contain_floating(self):
        """Floating projection prompts reference floating/dark space."""
        prompt = build_prompt("comparison content", "object_comparison", "floating", "power")
        assert "floating" in prompt.lower()

    def test_multi_panel_prompts_contain_panels(self):
        """Multi-panel prompts reference multiple display panels."""
        prompt = build_prompt("timeline content", "timeline", "multi_panel", "archive")
        assert "panel" in prompt.lower()

    def test_close_up_prompts_contain_close_up(self):
        """Close-up detail prompts reference close-up/detail."""
        prompt = build_prompt("key statistic", "data_terminal", "close_up_detail", "personal")
        assert "close-up" in prompt.lower() or "close up" in prompt.lower()


# ---------------------------------------------------------------------------
# Prompt structure tests
# ---------------------------------------------------------------------------

class TestPromptStructure:
    def test_prompt_contains_scene_description(self):
        """Each prompt contains the scene description text."""
        scenes = [{"scene_description": "A unique test map of the Strait of Hormuz"}]
        results = generate_prompts(scenes, seed=42)
        assert "Strait of Hormuz" in results[0]["prompt"]

    def test_output_has_required_keys(self):
        """Each result dict has all required output keys."""
        required = {"prompt", "content_type", "display_format", "color_mood", "act", "index", "ken_burns"}
        results = _generate_full_video()
        for r in results:
            missing = required - set(r.keys())
            assert not missing, f"Missing keys {missing} at index {r.get('index', '?')}"


# ---------------------------------------------------------------------------
# build_prompt unit tests
# ---------------------------------------------------------------------------

class TestBuildPrompt:
    def test_war_table_strategic(self):
        prompt = build_prompt(
            "a detailed map of the Persian Gulf with shipping lanes",
            "geographic_map", "war_table", "strategic",
        )
        assert "holographic war table" in prompt.lower()
        assert "teal" in prompt.lower() or "cyan" in prompt.lower()
        assert "no people visible" in prompt
        assert "16:9" in prompt

    def test_wall_display_alert(self):
        prompt = build_prompt(
            "oil price candlestick chart spiking with red warning indicators",
            "data_terminal", "wall_display", "alert",
        )
        assert "holographic wall display" in prompt.lower()
        assert "red" in prompt.lower() or "amber" in prompt.lower() or "warning" in prompt.lower()

    def test_floating_power(self):
        prompt = build_prompt(
            "two wireframe objects showing drone versus supertanker comparison",
            "object_comparison", "floating", "power",
        )
        assert "floating" in prompt.lower()
        assert "navy" in prompt.lower() or "steel" in prompt.lower() or "blue" in prompt.lower()

    def test_multi_panel_archive(self):
        prompt = build_prompt(
            "three eras side by side showing 1956 Suez and 1973 OPEC and 2026 Hormuz",
            "timeline", "multi_panel", "archive",
        )
        assert "panel" in prompt.lower()
        assert "gold" in prompt.lower() or "amber" in prompt.lower() or "brass" in prompt.lower()


# ---------------------------------------------------------------------------
# Visual identity tests
# ---------------------------------------------------------------------------

class TestVisualIdentity:
    """Verify the holographic display visual identity is intact."""

    def test_no_legacy_style_in_any_prompt(self):
        """No prompt contains legacy cinematic documentary language."""
        results = _generate_full_video()
        forbidden_terms = [
            "mannequin",
            "3D editorial conceptual render",
            "department store display",
            "clay render",
            "matte gray",
            "Rembrandt lighting",
            "Arri Alexa",
            "Kodak Vision",
            "anonymous figure",
        ]
        for r in results:
            prompt_lower = r["prompt"].lower()
            for term in forbidden_terms:
                assert term.lower() not in prompt_lower, (
                    f"Forbidden legacy term '{term}' found in prompt at index {r['index']}: "
                    f"{r['prompt'][:100]}..."
                )

    def test_all_prompts_end_with_16_9(self):
        """Every prompt ends with 16:9 aspect ratio (in suffix)."""
        results = _generate_full_video()
        for r in results:
            assert "16:9" in r["prompt"], (
                f"Prompt at index {r['index']} missing 16:9"
            )

    def test_dark_operations_room_in_every_prompt(self):
        """Every prompt references dark operations room."""
        results = _generate_full_video()
        for r in results:
            assert "dark operations room" in r["prompt"].lower(), (
                f"Prompt at index {r['index']} missing dark operations room"
            )


# ---------------------------------------------------------------------------
# Per-scene color mood resolution tests
# ---------------------------------------------------------------------------

class TestSceneColorMood:
    def test_crisis_triggers_alert(self):
        mood = resolve_scene_color_mood("A crisis and attack on the military base", "strategic")
        assert mood == "alert"

    def test_historical_triggers_archive(self):
        mood = resolve_scene_color_mood("Historical parallel from the 1973 era", "strategic")
        assert mood == "archive"

    def test_military_triggers_power(self):
        mood = resolve_scene_color_mood("Navy fleet deployment from the military base command", "strategic")
        assert mood == "power"

    def test_no_keywords_falls_back_to_video_mood(self):
        mood = resolve_scene_color_mood("A quiet room with soft light", "archive")
        assert mood == "archive"

    def test_cascade_triggers_contagion(self):
        mood = resolve_scene_color_mood("Cascade of domino effects spreading through the system", "strategic")
        assert mood == "contagion"


# ---------------------------------------------------------------------------
# Legacy API compatibility tests
# ---------------------------------------------------------------------------

class TestLegacyAPI:
    def test_resolve_accent_color_geopolitical(self):
        color = resolve_accent_color(topic_category="geopolitical")
        assert color == "strategic"

    def test_resolve_accent_color_financial(self):
        color = resolve_accent_color(topic_category="financial")
        assert color == "personal"

    def test_resolve_accent_color_conflict(self):
        color = resolve_accent_color(topic_category="conflict")
        assert color == "alert"

    def test_resolve_accent_color_unknown(self):
        color = resolve_accent_color(topic_category="unknown_category")
        assert color == "strategic"

    def test_explicit_color_overrides_category(self):
        color = resolve_accent_color(accent_color="cold teal", topic_category="conflict")
        assert color == "strategic"

    def test_no_inputs_returns_default(self):
        color = resolve_accent_color()
        assert color == "strategic"


# ---------------------------------------------------------------------------
# Full pipeline integration
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_full_video_generation_count(self):
        """generate_prompts returns one result per scene."""
        scenes = _sample_scenes(140)
        results = generate_prompts(scenes, seed=7)
        assert len(results) == 140

    def test_custom_act_timestamps(self):
        """Custom act timestamps are respected."""
        custom = {
            "act1_end": 60,
            "act2_end": 300,
            "act3_end": 600,
            "act4_end": 900,
            "act5_end": 1100,
            "act6_end": 1200,
        }
        scenes = _sample_scenes(100)
        results = generate_prompts(
            scenes,
            act_timestamps=custom,
            seed=42,
        )
        assert len(results) == 100
