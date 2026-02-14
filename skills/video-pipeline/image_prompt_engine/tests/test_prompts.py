"""
Tests for prompt construction and formatting.

Verifies that the prompt builder produces correctly structured prompts
with all required style markers, accent colors, and aspect ratios.
"""

import sys
import os

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from image_prompt_engine.prompt_builder import (
    build_prompt,
    generate_prompts,
    resolve_accent_color,
)
from image_prompt_engine.style_config import (
    ACCENT_COLOR_MAP,
    COMPOSITION_DIRECTIVES,
    DEFAULT_CONFIG,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sample_scenes(n: int = 136) -> list[dict]:
    """Generate n minimal scene dicts."""
    descriptions = [
        "A lone figure in a dark tailored suit standing at the end of a rain-slicked corridor",
        "Close-up of hands placing a black king chess piece onto an illuminated world map",
        "Dark aerial view of a sprawling city at night with glowing connection lines",
        "A shadowy figure silhouetted against a massive curved wall of data screens",
        "A Renaissance-era ruler sitting alone at a desk covered in maps and sealed letters",
        "Interior of the East India Company trading hall with merchants around a table",
        "An empty boardroom with one chair illuminated by overhead light",
        "A hand signing a classified document under harsh desk lamp lighting",
        "Globe with luminous connection lines between entities on a dark background",
        "Medieval war room with generals gathered around a sand table",
    ]
    return [{"scene_description": descriptions[i % len(descriptions)]} for i in range(n)]


def _generate_full_video(seed: int = 42) -> list[dict]:
    """Generate prompts for a full video."""
    return generate_prompts(_sample_scenes(), topic_category="geopolitical", seed=seed)


# ---------------------------------------------------------------------------
# Prompt format tests
# ---------------------------------------------------------------------------

class TestPromptFormat:
    def test_all_prompts_end_with_16_9(self):
        """Every prompt ends with '16:9'."""
        results = _generate_full_video()
        for r in results:
            assert r["prompt"].rstrip().endswith("16:9"), (
                f"Prompt at index {r['index']} does not end with '16:9': "
                f"...{r['prompt'][-30:]}"
            )

    def test_dossier_prompts_contain_arri_alexa(self):
        """All Dossier prompts include 'shot on Arri Alexa'."""
        results = _generate_full_video()
        for r in results:
            if r["style"] == "dossier":
                assert "shot on Arri Alexa" in r["prompt"], (
                    f"Dossier prompt at index {r['index']} missing 'shot on Arri Alexa'"
                )

    def test_echo_prompts_contain_candlelight(self):
        """All Echo prompts include candlelight/chiaroscuro reference."""
        results = _generate_full_video()
        for r in results:
            if r["style"] == "echo":
                prompt_lower = r["prompt"].lower()
                assert "candlelight" in prompt_lower or "chiaroscuro" in prompt_lower, (
                    f"Echo prompt at index {r['index']} missing candlelight/chiaroscuro"
                )

    def test_schema_prompts_contain_bloomberg(self):
        """All Schema prompts include Bloomberg/surveillance reference."""
        results = _generate_full_video()
        for r in results:
            if r["style"] == "schema":
                prompt_lower = r["prompt"].lower()
                assert "bloomberg" in prompt_lower or "surveillance" in prompt_lower, (
                    f"Schema prompt at index {r['index']} missing Bloomberg/surveillance"
                )

    def test_accent_color_substituted(self):
        """No prompt contains the literal placeholder '[ACCENT_COLOR]'."""
        results = _generate_full_video()
        for r in results:
            assert "[ACCENT_COLOR]" not in r["prompt"], (
                f"Unsubstituted [ACCENT_COLOR] in prompt at index {r['index']}"
            )


# ---------------------------------------------------------------------------
# Accent color tests
# ---------------------------------------------------------------------------

class TestAccentColor:
    def test_accent_color_consistency(self):
        """All prompts in a video use the same accent color."""
        results = _generate_full_video()
        colors = {r["accent_color"] for r in results}
        assert len(colors) == 1, f"Multiple accent colors found: {colors}"

    def test_geopolitical_gets_cold_teal(self):
        color = resolve_accent_color(topic_category="geopolitical")
        assert color == "cold teal"

    def test_financial_gets_warm_amber(self):
        color = resolve_accent_color(topic_category="financial")
        assert color == "warm amber"

    def test_conflict_gets_muted_crimson(self):
        color = resolve_accent_color(topic_category="conflict")
        assert color == "muted crimson"

    def test_unknown_category_gets_default(self):
        color = resolve_accent_color(topic_category="unknown_category")
        assert color == DEFAULT_CONFIG["default_accent_color"]

    def test_explicit_color_overrides_category(self):
        color = resolve_accent_color(accent_color="hot pink", topic_category="geopolitical")
        assert color == "hot pink"

    def test_no_inputs_returns_default(self):
        color = resolve_accent_color()
        assert color == DEFAULT_CONFIG["default_accent_color"]

    def test_accent_color_appears_in_dossier_prompt(self):
        """Dossier prompts contain the chosen accent color string."""
        results = generate_prompts(
            _sample_scenes(10),
            accent_color="warm amber",
            seed=42,
        )
        dossier = [r for r in results if r["style"] == "dossier"]
        assert len(dossier) > 0
        for r in dossier:
            assert "warm amber" in r["prompt"]

    def test_accent_color_appears_in_schema_prompt(self):
        """Schema prompts contain the chosen accent color string."""
        results = generate_prompts(
            _sample_scenes(136),
            accent_color="muted crimson",
            seed=42,
        )
        schema = [r for r in results if r["style"] == "schema"]
        assert len(schema) > 0
        for r in schema:
            assert "muted crimson" in r["prompt"]


# ---------------------------------------------------------------------------
# Prompt structure tests
# ---------------------------------------------------------------------------

class TestPromptStructure:
    def test_prompt_contains_scene_description(self):
        """Each prompt starts with the scene description."""
        scenes = [{"scene_description": "A unique test scene with a golden eagle"}]
        results = generate_prompts(scenes, accent_color="cold teal", seed=42)
        assert "A unique test scene with a golden eagle" in results[0]["prompt"]

    def test_prompt_contains_composition_directive(self):
        """Each prompt includes the composition directive text."""
        results = _generate_full_video()
        for r in results:
            comp_text = COMPOSITION_DIRECTIVES[r["composition"]]
            assert comp_text in r["prompt"], (
                f"Composition '{r['composition']}' text not found in prompt at index {r['index']}"
            )

    def test_output_has_required_keys(self):
        """Each result dict has all required output keys."""
        required = {"prompt", "style", "composition", "accent_color", "act", "index", "ken_burns"}
        results = _generate_full_video()
        for r in results:
            missing = required - set(r.keys())
            assert not missing, f"Missing keys {missing} at index {r.get('index', '?')}"

    def test_style_values_are_valid(self):
        """Style field is always one of the three valid styles."""
        valid = {"dossier", "schema", "echo"}
        results = _generate_full_video()
        for r in results:
            assert r["style"] in valid, f"Invalid style '{r['style']}' at index {r['index']}"

    def test_composition_values_are_valid(self):
        """Composition field is always a recognized composition key."""
        valid = set(COMPOSITION_DIRECTIVES.keys())
        results = _generate_full_video()
        for r in results:
            assert r["composition"] in valid, (
                f"Invalid composition '{r['composition']}' at index {r['index']}"
            )


# ---------------------------------------------------------------------------
# build_prompt unit tests
# ---------------------------------------------------------------------------

class TestBuildPrompt:
    def test_dossier_basic(self):
        prompt = build_prompt(
            "A figure in shadows",
            "dossier",
            "wide",
            "cold teal",
        )
        assert prompt.startswith("A figure in shadows")
        assert "wide establishing shot" in prompt
        assert "cold teal" in prompt
        assert "shot on Arri Alexa" in prompt
        assert prompt.endswith("16:9")

    def test_schema_basic(self):
        prompt = build_prompt(
            "City at night with data overlay",
            "schema",
            "overhead",
            "warm amber",
        )
        assert "City at night with data overlay" in prompt
        assert "overhead" in prompt.lower() or "surveillance perspective" in prompt
        assert "warm amber" in prompt
        assert "Bloomberg" in prompt
        assert prompt.endswith("16:9")

    def test_echo_basic(self):
        prompt = build_prompt(
            "Renaissance ruler at a desk",
            "echo",
            "medium",
            "cold teal",
        )
        assert "Renaissance ruler at a desk" in prompt
        assert "figure from waist up" in prompt
        assert "candlelight" in prompt
        assert "oil painting texture" in prompt
        assert prompt.endswith("16:9")

    def test_strips_trailing_comma_from_description(self):
        """Scene descriptions with trailing commas don't create double commas."""
        prompt = build_prompt("A test scene, ,", "dossier", "wide", "cold teal")
        assert ", , ," not in prompt

    def test_echo_always_has_warm_amber_tones(self):
        """Echo suffix includes 'warm amber tones' regardless of chosen accent."""
        prompt = build_prompt("Historical scene", "echo", "wide", "cold teal")
        assert "warm amber tones" in prompt


# ---------------------------------------------------------------------------
# Full pipeline integration
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_full_video_generation_count(self):
        """generate_prompts returns one result per scene."""
        scenes = _sample_scenes(140)
        results = generate_prompts(scenes, topic_category="surveillance", seed=7)
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
            topic_category="financial",
            act_timestamps=custom,
            seed=42,
        )
        assert len(results) == 100
        assert results[0]["style"] == "dossier"
        assert results[-1]["style"] == "dossier"

    @pytest.mark.parametrize("category,expected_color", [
        ("geopolitical", "cold teal"),
        ("financial", "warm amber"),
        ("conflict", "muted crimson"),
    ])
    def test_topic_category_sets_accent_color(self, category, expected_color):
        scenes = _sample_scenes(20)
        results = generate_prompts(scenes, topic_category=category, seed=42)
        assert all(r["accent_color"] == expected_color for r in results)
