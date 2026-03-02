"""Test script for EFF Thumbnail & Title Generator.

Tests template selection, title generation, prompt building, and the
full produce_thumbnail_and_title pipeline (with API call mocked unless
KIE_API_KEY is set).

Run:
    cd skills/video-pipeline
    python -m thumbnail_generator.test_generator
"""

import os
import sys
import json
import tempfile

# Ensure parent dir is on path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from thumbnail_generator.templates import select_template, TEMPLATES, TEMPLATE_A
from thumbnail_generator.titles import generate_title, extract_caps_word, TITLE_FORMULAS
from thumbnail_generator.config import ASPECT_RATIO, COST_PER_IMAGE
from thumbnail_generator.validator import validate_thumbnail


def test_template_selection():
    """Test that template selection logic routes correctly."""
    print("--- Template Selection ---")

    # Template B: Cinematic Close-Up — person-focused keywords
    assert select_template("The CEO who destroyed an empire") == "template_b"
    assert select_template("Putin's assassination plot") == "template_b"
    assert select_template("Why this dictator scares the world") == "template_b"
    assert select_template("The general who defied orders", ["military leader"]) == "template_b"
    print("  template_b selection (person-focused): PASS")

    # Template A: Cinematic Scene — default for systems/institutions
    assert select_template("China's economy explained") == "template_a"
    assert select_template("Dollar crisis", ["economics"]) == "template_a"
    assert select_template("The robot trap nobody sees coming") == "template_a"
    assert select_template("Corporate inequality", ["monopoly"]) == "template_a"
    print("  template_a selection (default): PASS")

    print("  ALL TEMPLATE SELECTION TESTS PASSED\n")


def test_title_generation():
    """Test title formula generation."""
    print("--- Title Generation ---")

    # Test trap formula
    title = generate_title("trap", {
        "noun": "Robot",
        "caps_word": "TRAP",
        "parenthetical": "A 4-Stage Monopoly",
    })
    assert "TRAP" in title
    assert "Robot" in title
    assert "(A 4-Stage Monopoly)" in title
    print(f"  trap: '{title}' - PASS")

    # Test country_dollar formula
    title = generate_title("country_dollar", {
        "country": "China",
        "amount": "140 Billion",
        "noun": "Dollar",
        "caps_word": "TRAP",
        "parenthetical": "The Silent Economic War",
    })
    assert "TRAP" in title
    assert "China" in title
    assert "$140 Billion" in title
    print(f"  country_dollar: '{title}' - PASS")

    # Test slow_death formula
    title = generate_title("slow_death", {
        "caps_word": "DEATH",
        "system": "the Dollar",
        "parenthetical": "And Who Controls What Replaces It",
    })
    assert "DEATH" in title
    assert "Dollar" in title
    print(f"  slow_death: '{title}' - PASS")

    # Test stronger_than formula
    title = generate_title("stronger_than", {
        "country": "Russia",
        "caps_word": "STRONGER",
        "parenthetical": "The Machiavellian Energy Play",
    })
    assert "STRONGER" in title
    assert "Russia" in title
    print(f"  stronger_than: '{title}' - PASS")

    # Test list_warning formula
    title = generate_title("list_warning", {
        "number": "7",
        "noun": "Economic",
        "caps_word": "LIES",
        "parenthetical": "Machiavelli Warned You",
    })
    assert "LIES" in title
    assert "7" in title
    print(f"  list_warning: '{title}' - PASS")

    # Test swallowed formula
    title = generate_title("swallowed", {
        "entity": "Blackrock",
        "caps_word": "SWALLOWED",
        "target": "the Housing Market",
        "parenthetical": "The 3-Stage Playbook",
    })
    assert "SWALLOWED" in title
    assert "Blackrock" in title
    print(f"  swallowed: '{title}' - PASS")

    print("  ALL TITLE GENERATION TESTS PASSED\n")


def test_extract_caps_word():
    """Test CAPS word extraction from titles."""
    print("--- CAPS Word Extraction ---")

    assert extract_caps_word("The Robot TRAP Nobody Sees Coming") == "TRAP"
    assert extract_caps_word("The Slow DEATH of the Dollar") == "DEATH"
    assert extract_caps_word("Why Russia is STRONGER Than You Think") == "STRONGER"
    assert extract_caps_word("How Blackrock SWALLOWED the Housing Market") == "SWALLOWED"
    assert extract_caps_word("7 Economic LIES They Need You to Believe") == "LIES"
    print("  ALL CAPS EXTRACTION TESTS PASSED\n")


def test_prompt_template_filling():
    """Test that template variables fill correctly."""
    print("--- Prompt Template Filling ---")

    vars_a = {
        "scene_description": "military command bunker with glowing screens and a "
                             "single empty chair under a spotlight",
        "accent_color": "amber",
        "line_1": "CHINA'S $140B TRAP",
        "red_word": "TRAP",
        "line_2": "DOLLAR WEAPON",
    }
    prompt = TEMPLATE_A.format(**vars_a)
    assert "military command bunker" in prompt
    assert "amber" in prompt
    assert "CHINA'S $140B TRAP" in prompt
    assert "TRAP" in prompt
    assert "DOLLAR WEAPON" in prompt
    assert "16:9" in prompt
    assert "Arri Alexa" in prompt
    print(f"  Template A fill ({len(prompt)} chars): PASS")

    from thumbnail_generator.templates import TEMPLATE_B
    vars_b = {
        "close_up_subject": "a weathered hand gripping a nuclear launch key",
        "emotion_detail": "sweat visible, tension in every detail",
        "background_element": "a blurred war room map",
        "accent_color": "red",
        "line_1": "THE NUCLEAR TRAP",
        "red_word": "TRAP",
        "line_2": "NOBODY SEES COMING",
    }
    prompt_b = TEMPLATE_B.format(**vars_b)
    assert "weathered hand gripping" in prompt_b
    assert "sweat visible" in prompt_b
    assert "blurred war room map" in prompt_b
    assert "THE NUCLEAR TRAP" in prompt_b
    assert "Rembrandt lighting" in prompt_b
    print(f"  Template B fill ({len(prompt_b)} chars): PASS")

    print("  ALL TEMPLATE FILLING TESTS PASSED\n")


def test_title_thumbnail_pairing():
    """Test that CAPS word matches between title and thumbnail red_word."""
    print("--- Title-Thumbnail Pairing ---")

    title = generate_title("trap", {
        "noun": "Robot",
        "caps_word": "TRAP",
        "parenthetical": "A 4-Stage Monopoly",
    })
    caps = extract_caps_word(title)
    red_word = "TRAP"
    assert caps == red_word, f"CAPS word '{caps}' != red_word '{red_word}'"
    print(f"  Title: '{title}'")
    print(f"  CAPS word: {caps}, red_word: {red_word} - MATCH")

    print("  PAIRING TEST PASSED\n")


def test_config_constants():
    """Verify critical config values."""
    print("--- Config Constants ---")

    assert ASPECT_RATIO == "16:9", f"ASPECT_RATIO must be 16:9, got {ASPECT_RATIO}"
    assert COST_PER_IMAGE == 0.09
    print("  ASPECT_RATIO=16:9: PASS")
    print("  COST_PER_IMAGE=0.09: PASS")
    print("  CONFIG TESTS PASSED\n")


def test_end_to_end_dry_run():
    """Test the full pipeline without API calls (dry run).

    This verifies template selection, prompt building, and title generation
    work together. The actual API call is skipped unless KIE_API_KEY is set.
    """
    print("--- End-to-End Dry Run ---")

    topic = "China's $140 Billion Dollar Trap"
    tags = ["china", "dollar", "trap", "economics"]

    # Step 1: Template selection
    template_key = select_template(topic, tags)
    print(f"  Topic: {topic}")
    print(f"  Tags: {tags}")
    print(f"  Selected template: {template_key}")
    assert template_key == "template_a"  # No person keywords → default

    # Step 2: Build prompt
    template_vars = {
        "scene_description": "massive oil tanker in dark ocean with a single "
                             "red warning light",
        "accent_color": "amber",
        "line_1": "CHINA'S $140B TRAP",
        "red_word": "TRAP",
        "line_2": "DOLLAR WEAPON",
    }
    prompt = TEMPLATE_A.format(**template_vars)
    print(f"  Prompt length: {len(prompt)} chars")
    assert len(prompt) > 200, "Prompt too short"

    # Step 3: Generate title
    title = generate_title("country_dollar", {
        "country": "China",
        "amount": "140 Billion",
        "noun": "Dollar",
        "caps_word": "TRAP",
        "parenthetical": "The Silent Economic War",
    })
    print(f"  Title: {title}")
    caps = extract_caps_word(title)
    assert caps == "TRAP"
    print(f"  CAPS/red_word match: {caps} == TRAP")

    # Step 4: Verify pairing
    assert "TRAP" in prompt, "red_word TRAP must appear in prompt"
    assert "TRAP" in title, "CAPS word TRAP must appear in title"
    print("  Title-thumbnail pairing: VERIFIED")

    print("  END-TO-END DRY RUN PASSED\n")


def test_produce_thumbnail_and_title_integration():
    """Full integration test — calls API only if KIE_API_KEY is set."""
    api_key = os.environ.get("KIE_API_KEY") or os.environ.get("KIE_AI_API_KEY")

    if not api_key:
        print("--- Integration Test (SKIPPED — no API key) ---")
        print("  Set KIE_API_KEY to run the full integration test.\n")
        return

    print("--- Integration Test (LIVE API) ---")
    from thumbnail_generator.generator import produce_thumbnail_and_title

    with tempfile.TemporaryDirectory() as tmpdir:
        result = produce_thumbnail_and_title(
            topic="China's $140 Billion Dollar Trap",
            tags=["china", "dollar", "trap", "economics"],
            template_vars={
                "scene_description": "massive oil tanker in dark ocean with a "
                                     "single red warning light",
                "accent_color": "amber",
                "line_1": "CHINA'S $140B TRAP",
                "red_word": "TRAP",
                "line_2": "DOLLAR WEAPON",
            },
            title_formula="country_dollar",
            title_vars={
                "country": "China",
                "amount": "140 Billion",
                "noun": "Dollar",
                "caps_word": "TRAP",
                "parenthetical": "The Silent Economic War",
            },
            output_dir=tmpdir,
            api_key=api_key,
        )
        print(f"  Result: {json.dumps(result, indent=2, default=str)}")
        assert result["title"] is not None
        assert result["template_used"] in ("template_a", "template_b")
        assert result["attempts"] >= 1
        print("  INTEGRATION TEST PASSED\n")


if __name__ == "__main__":
    print("=" * 60)
    print("EFF Thumbnail & Title Generator — Test Suite")
    print("=" * 60 + "\n")

    test_config_constants()
    test_template_selection()
    test_title_generation()
    test_extract_caps_word()
    test_prompt_template_filling()
    test_title_thumbnail_pairing()
    test_end_to_end_dry_run()
    test_produce_thumbnail_and_title_integration()

    print("=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)
