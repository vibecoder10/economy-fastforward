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
    resolve_scene_accent_color,
)
from image_prompt_engine.style_config import (
    ACCENT_COLOR_MAP,
    COMPOSITION_DIRECTIVES,
    DEFAULT_CONFIG,
    SCENE_COLOR_MAP,
    VALID_ACCENT_COLORS,
    YOUTUBE_STYLE_PREFIX,
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
    def test_all_prompts_contain_rembrandt(self):
        """Every prompt contains 'Rembrandt' (from the prefix)."""
        results = _generate_full_video()
        for r in results:
            assert "Rembrandt" in r["prompt"], (
                f"Prompt at index {r['index']} does not contain 'Rembrandt': "
                f"...{r['prompt'][-60:]}"
            )

    def test_dossier_prompts_contain_halation(self):
        """All Dossier prompts include halation reference."""
        results = _generate_full_video()
        for r in results:
            if r["style"] == "dossier":
                assert "halation" in r["prompt"], (
                    f"Dossier prompt at index {r['index']} missing 'halation'"
                )

    def test_echo_prompts_contain_candlelight(self):
        """All Echo prompts include candlelight/chiaroscuro reference."""
        results = _generate_full_video()
        for r in results:
            if r["style"] == "echo":
                prompt_lower = r["prompt"].lower()
                assert "candlelit" in prompt_lower or "chiaroscuro" in prompt_lower, (
                    f"Echo prompt at index {r['index']} missing candlelit/chiaroscuro"
                )

    def test_schema_prompts_contain_data_nodes(self):
        """All Schema prompts include data nodes/connection lines reference."""
        results = _generate_full_video()
        for r in results:
            if r["style"] == "schema":
                prompt_lower = r["prompt"].lower()
                assert "data nodes" in prompt_lower or "connection lines" in prompt_lower, (
                    f"Schema prompt at index {r['index']} missing data nodes/connection lines"
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
    def test_accent_colors_are_valid(self):
        """All per-scene accent colors are recognized valid colors."""
        valid = VALID_ACCENT_COLORS | set(SCENE_COLOR_MAP.keys())
        results = _generate_full_video()
        for r in results:
            assert r["accent_color"] in valid, (
                f"Invalid accent color '{r['accent_color']}' at index {r['index']}"
            )

    def test_per_scene_color_rotation_produces_variety(self):
        """Per-scene rotation generates more than one accent color across a full video."""
        results = _generate_full_video()
        colors = {r["accent_color"] for r in results}
        assert len(colors) > 1, "Expected per-scene color variety across 136 images"

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
        """Dossier prompts contain their per-scene resolved accent color."""
        results = generate_prompts(
            _sample_scenes(10),
            accent_color="warm amber",
            seed=42,
        )
        dossier = [r for r in results if r["style"] == "dossier"]
        assert len(dossier) > 0
        for r in dossier:
            assert r["accent_color"] in r["prompt"], (
                f"Accent color '{r['accent_color']}' not in prompt at index {r['index']}"
            )

    def test_accent_color_appears_in_schema_prompt(self):
        """Schema prompts contain their per-scene resolved accent color."""
        results = generate_prompts(
            _sample_scenes(136),
            accent_color="muted crimson",
            seed=42,
        )
        schema = [r for r in results if r["style"] == "schema"]
        assert len(schema) > 0
        for r in schema:
            assert r["accent_color"] in r["prompt"], (
                f"Accent color '{r['accent_color']}' not in prompt at index {r['index']}"
            )


# ---------------------------------------------------------------------------
# Per-scene accent color resolution tests
# ---------------------------------------------------------------------------

class TestSceneAccentColor:
    def test_crimson_keyword_match(self):
        color = resolve_scene_accent_color("A drone strike on the military base", "cold teal")
        assert color == "muted crimson"

    def test_amber_keyword_match(self):
        color = resolve_scene_accent_color("The king sits on his golden throne in the palace", "cold teal")
        assert color == "warm amber"

    def test_teal_keyword_match(self):
        color = resolve_scene_accent_color("A satellite surveillance command center with radar screens", "warm amber")
        assert color == "cold teal"

    def test_green_keyword_match(self):
        color = resolve_scene_accent_color("Wall Street traders watch the stock market crash on Bloomberg", "cold teal")
        assert color == "muted green"

    def test_no_keywords_falls_back_to_video_color(self):
        color = resolve_scene_accent_color("A quiet room with soft light", "warm amber")
        assert color == "warm amber"

    def test_most_hits_wins(self):
        """Color with the most keyword matches wins."""
        # 3 crimson keywords vs 1 teal keyword
        color = resolve_scene_accent_color(
            "A military assault with weapons destroying the surveillance post", "cold teal"
        )
        assert color == "muted crimson"

    def test_tie_broken_by_priority(self):
        """Ties broken by crimson > amber > teal > green."""
        # 1 crimson ("war") vs 1 amber ("power") → crimson wins
        color = resolve_scene_accent_color("A war for power", "cold teal")
        assert color == "muted crimson"

    def test_case_insensitive(self):
        color = resolve_scene_accent_color("MILITARY DRONE STRIKE", "cold teal")
        assert color == "muted crimson"

    def test_multi_word_keyword(self):
        """Multi-word keywords like 'command center' and 'wall street' match."""
        color = resolve_scene_accent_color("Inside the command center", "warm amber")
        assert color == "cold teal"

        color = resolve_scene_accent_color("The traders on Wall Street panic", "cold teal")
        assert color == "muted green"


# ---------------------------------------------------------------------------
# Prompt structure tests
# ---------------------------------------------------------------------------

class TestPromptStructure:
    def test_prompt_contains_scene_description(self):
        """Each prompt contains the scene description (after the cinematic prefix)."""
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
        assert prompt.startswith("Cinematic photorealistic editorial photograph")
        assert "A figure in shadows" in prompt
        assert "wide establishing shot" in prompt
        assert "cold teal" in prompt
        assert "Rembrandt" in prompt
        assert "dramatic light source" in prompt
        assert "halation" in prompt

    def test_schema_basic(self):
        prompt = build_prompt(
            "City at night with data overlay",
            "schema",
            "overhead",
            "warm amber",
        )
        assert prompt.startswith("Cinematic photorealistic editorial photograph")
        assert "City at night with data overlay" in prompt
        assert "overhead" in prompt.lower() or "surveillance perspective" in prompt
        # "data" keyword triggers per-scene rotation to cold teal
        assert "cold teal" in prompt
        assert "data nodes" in prompt or "connection lines" in prompt

    def test_echo_basic(self):
        prompt = build_prompt(
            "Renaissance ruler at a desk",
            "echo",
            "medium",
            "cold teal",
        )
        assert prompt.startswith("Cinematic photorealistic editorial photograph")
        assert "Renaissance ruler at a desk" in prompt
        assert "figure from waist up" in prompt
        assert "candlelit" in prompt.lower() or "chiaroscuro" in prompt.lower()
        assert "oil painting texture" in prompt

    def test_strips_trailing_comma_from_description(self):
        """Scene descriptions with trailing commas don't create double commas."""
        prompt = build_prompt("A test scene, ,", "dossier", "wide", "cold teal")
        assert ", , ," not in prompt

    def test_echo_always_has_warm_candlelit(self):
        """Echo suffix includes warm candlelit reference regardless of chosen accent."""
        prompt = build_prompt("Historical scene", "echo", "wide", "cold teal")
        assert "warm candlelit" in prompt

    def test_dossier_no_duplicate_rembrandt(self):
        """Dossier prompts should not duplicate 'Rembrandt' (prefix provides it once)."""
        prompt = build_prompt("A test scene", "dossier", "wide", "cold teal")
        count = prompt.lower().count("rembrandt")
        assert count == 1, f"'Rembrandt' appears {count} times (expected 1)"

    def test_dossier_suffix_has_halation(self):
        """Dossier suffix includes halation."""
        from image_prompt_engine.style_config import STYLE_SUFFIXES
        assert "halation" in STYLE_SUFFIXES["dossier"]


# ---------------------------------------------------------------------------
# Cinematic Dossier Style tests (YouTube pipeline)
# ---------------------------------------------------------------------------

class TestCinematicDossierStyle:
    """Verify YouTube pipeline uses cinematic dossier style."""

    def test_all_prompts_start_with_cinematic_prefix(self):
        """Every prompt starts with the cinematic photorealistic prefix."""
        results = _generate_full_video()
        for r in results:
            assert r["prompt"].startswith("Cinematic photorealistic editorial photograph"), (
                f"Prompt at index {r['index']} does not start with cinematic prefix: "
                f"{r['prompt'][:80]}..."
            )

    def test_no_legacy_style_in_any_prompt(self):
        """No prompt contains legacy mannequin/clay/department store language."""
        results = _generate_full_video()
        forbidden_terms = [
            "mannequin",
            "3D editorial conceptual render",
            "department store display",
            "clay render",
            "matte gray",
        ]
        for r in results:
            prompt_lower = r["prompt"].lower()
            for term in forbidden_terms:
                assert term.lower() not in prompt_lower, (
                    f"Forbidden legacy term '{term}' found in prompt at index {r['index']}: "
                    f"{r['prompt'][:100]}..."
                )

    def test_cinematic_prefix_contains_key_elements(self):
        """The cinematic prefix has all required style elements."""
        assert "Cinematic photorealistic editorial photograph" in YOUTUBE_STYLE_PREFIX
        assert "dark moody atmosphere" in YOUTUBE_STYLE_PREFIX
        assert "Rembrandt" in YOUTUBE_STYLE_PREFIX
        assert "shallow depth of field" in YOUTUBE_STYLE_PREFIX
        assert "[ACCENT_COLOR]" in YOUTUBE_STYLE_PREFIX

    def test_accent_color_substituted_in_prefix(self):
        """The [ACCENT_COLOR] placeholder in the prefix is replaced."""
        prompt = build_prompt("Test scene", "dossier", "wide", "cold teal")
        assert "cold teal accent lighting" in prompt
        assert "[ACCENT_COLOR]" not in prompt

    def test_prefix_before_scene_description(self):
        """The cinematic prefix comes before the scene description in the prompt."""
        prompt = build_prompt("A specific unique scene", "dossier", "wide", "cold teal")
        prefix_pos = prompt.index("Cinematic photorealistic")
        scene_pos = prompt.index("A specific unique scene")
        assert prefix_pos < scene_pos, "Cinematic prefix must come before scene description"


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
    def test_topic_category_sets_fallback_color(self, category, expected_color):
        """Scenes without keyword matches fall back to the topic category color."""
        scenes = [{"scene_description": "A neutral empty room with no keywords"}] * 20
        results = generate_prompts(scenes, topic_category=category, seed=42)
        assert all(r["accent_color"] == expected_color for r in results)
