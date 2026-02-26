"""Tests for 2-stage script generation (generate_script_staged).

Covers:
- Framework lens psychological depth layer
- New thinker lenses
- Outline JSON parsing
- Act assembly and validation
- Fallback behavior on failures
"""

import json
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from brief_translator.script_generator import (
    _build_framework_lens_section,
    _parse_outline_json,
    _format_research_brief_text,
    validate_script,
    extract_acts,
    generate_script_staged,
    generate_script,
)


# ── Sample data ──────────────────────────────────────────────────────────

SAMPLE_BRIEF = {
    "headline": "The AI Bubble: When Silicon Dreams Meet Reality",
    "thesis": "The AI industry is following the same pattern as every tech bubble",
    "executive_hook": "In 2024, $100 billion poured into AI companies. Most will fail.",
    "fact_sheet": "Global AI investment hit $100B in 2024. Top 5 companies control 80%.",
    "historical_parallels": "The Dot-Com Bubble of 1999-2001 mirrors current AI mania.",
    "framework_analysis": "Three laws of power apply directly to the AI arms race.",
    "character_dossier": "Sam Altman: CEO of OpenAI, moved from non-profit to for-profit.",
    "narrative_arc": "Rise, mania, reckoning, aftermath.",
    "counter_arguments": "AI is fundamentally different from dot-com because...",
    "visual_seeds": "Silicon valley office, vintage computer room, trading floor",
    "source_bibliography": "Reuters: AI Investment Report 2024\nBloomberg: Tech Spending",
    "framework_angle": "48 Laws",
    "source_urls": "https://reuters.com/ai-report\nhttps://bloomberg.com/tech",
}

SAMPLE_OUTLINE = {
    "acts": [
        {
            "act_number": i,
            "title": f"Act {i} Title",
            "timestamp": f"{(i-1)*4}:00-{i*4}:00",
            "target_words": 600,
            "beats": [f"Beat 1 for act {i}", f"Beat 2 for act {i}"],
            "framework_references": [f"Law {i}: Reference"],
            "research_elements": [f"Fact from act {i}"],
            "sources_to_cite": ["Reuters"],
            "hook_strategy": f"Hook for act {i}",
            "psychological_layer": f"Psych layer for act {i}",
        }
        for i in range(1, 7)
    ],
    "framework_arc": "Arc across all acts",
    "historical_parallel_placements": "Acts 2, 4, 6",
    "audience_address_moments": ["Act 1 opening", "Act 5 stakes"],
}


# ── Framework Lens Tests ──────────────────────────────────────────────────

ALL_EXPECTED_LENSES = [
    # Original 10
    "48 Laws", "Machiavelli", "Sun Tzu", "Game Theory", "Jung Shadow",
    "Behavioral Econ", "Stoicism", "Propaganda", "Systems Thinking",
    "Evolutionary Psych",
    # New 6
    "Thucydides", "Taleb", "Girard", "Schmitt", "Nietzsche", "Arendt",
]


class TestFrameworkLenses:
    @pytest.mark.parametrize("lens_name", ALL_EXPECTED_LENSES)
    def test_lens_exists(self, lens_name):
        """Every expected lens must produce non-empty output."""
        result = _build_framework_lens_section(lens_name)
        assert len(result) > 100, f"Lens '{lens_name}' produced too-short output"

    @pytest.mark.parametrize("lens_name", ALL_EXPECTED_LENSES)
    def test_lens_has_psychological_depth(self, lens_name):
        """Every lens must include the psychological depth layer."""
        result = _build_framework_lens_section(lens_name)
        assert "PSYCHOLOGICAL DEPTH LAYER" in result, (
            f"Lens '{lens_name}' missing psychological depth layer"
        )

    def test_unknown_lens_gets_fallback(self):
        """Unknown framework angles get a generic power dynamics lens."""
        result = _build_framework_lens_section("Unknown Framework")
        assert "POWER DYNAMICS" in result
        assert "PSYCHOLOGICAL DEPTH LAYER" in result

    def test_empty_lens_gets_fallback(self):
        result = _build_framework_lens_section("")
        assert "POWER DYNAMICS" in result

    def test_new_thinkers_have_unique_content(self):
        """Each new thinker lens has distinct content."""
        lenses = {name: _build_framework_lens_section(name)
                  for name in ["Thucydides", "Taleb", "Girard", "Schmitt", "Nietzsche", "Arendt"]}
        # Check they reference the thinker by name
        assert "Thucydides" in lenses["Thucydides"]
        assert "Taleb" in lenses["Taleb"]
        assert "Girard" in lenses["Girard"]
        assert "Schmitt" in lenses["Schmitt"]
        assert "Nietzsche" in lenses["Nietzsche"]
        assert "Arendt" in lenses["Arendt"]


# ── Outline Parsing Tests ──────────────────────────────────────────────────

class TestOutlineParsing:
    def test_parse_clean_json(self):
        raw = json.dumps(SAMPLE_OUTLINE)
        result = _parse_outline_json(raw)
        assert len(result["acts"]) == 6

    def test_parse_json_with_code_fence(self):
        raw = f"```json\n{json.dumps(SAMPLE_OUTLINE)}\n```"
        result = _parse_outline_json(raw)
        assert len(result["acts"]) == 6

    def test_parse_json_with_plain_code_fence(self):
        raw = f"```\n{json.dumps(SAMPLE_OUTLINE)}\n```"
        result = _parse_outline_json(raw)
        assert len(result["acts"]) == 6

    def test_parse_invalid_json_raises(self):
        with pytest.raises(json.JSONDecodeError):
            _parse_outline_json("not valid json at all")

    def test_parse_json_with_whitespace(self):
        raw = f"  \n  {json.dumps(SAMPLE_OUTLINE)}  \n  "
        result = _parse_outline_json(raw)
        assert len(result["acts"]) == 6


# ── Research Brief Formatting Tests ──────────────────────────────────────

class TestFormatResearchBrief:
    def test_includes_all_populated_fields(self):
        result = _format_research_brief_text(SAMPLE_BRIEF)
        assert "Headline:" in result
        assert "Thesis:" in result
        assert "Fact Sheet:" in result

    def test_skips_empty_fields(self):
        brief = {"headline": "Test", "thesis": "", "fact_sheet": "Facts"}
        result = _format_research_brief_text(brief)
        assert "Headline:" in result
        assert "Thesis:" not in result  # Empty, should be skipped
        assert "Fact Sheet:" in result


# ── Act Assembly and Validation Tests ──────────────────────────────────────

class TestActAssembly:
    def test_validate_script_with_act_markers(self):
        """Scripts with proper act markers pass validation."""
        script = "\n\n".join([
            f"[ACT {i} — Title {i} | {(i-1)*4}:00-{i*4}:00 | ~600 words]\n"
            + " ".join(["word"] * 600)
            for i in range(1, 7)
        ])
        result = validate_script(script)
        assert result["act_count"] == 6
        assert result["word_count"] >= 3000

    def test_extract_acts_returns_dict(self):
        script = "\n".join([
            f"[ACT {i} — Title | 0:00-1:00 | ~100 words]\nContent for act {i}."
            for i in range(1, 7)
        ])
        acts = extract_acts(script)
        assert len(acts) == 6
        assert 1 in acts
        assert 6 in acts


# ── Staged Generation Tests (with mocks) ──────────────────────────────────

class TestGenerateScriptStaged:
    @pytest.fixture
    def mock_client(self):
        """Create a mock Anthropic client."""
        client = MagicMock()
        client.generate = AsyncMock()
        return client

    def _make_act_text(self, act_num):
        """Generate realistic act text with marker."""
        words = " ".join(["word"] * 550)
        return f"[ACT {act_num} — Title {act_num} | 0:00-4:00 | ~600 words]\n{words}"

    def test_staged_happy_path(self, mock_client):
        """Full staged pipeline succeeds with valid outline + 6 acts."""
        # Stage 1 returns valid JSON outline
        mock_client.generate.side_effect = [
            json.dumps(SAMPLE_OUTLINE),  # outline
        ] + [
            self._make_act_text(i) for i in range(1, 7)  # 6 acts
        ]

        result = asyncio.get_event_loop().run_until_complete(
            generate_script_staged(mock_client, SAMPLE_BRIEF)
        )

        assert result["script"] is not None
        assert result["outline"] is not None
        assert len(result["acts"]) == 6
        assert result["validation"]["act_count"] == 6
        # 7 total calls: 1 outline + 6 acts
        assert mock_client.generate.call_count == 7

    def test_staged_outline_failure_falls_back(self, mock_client):
        """If outline fails twice, falls back to monolithic generation."""
        full_script = "\n\n".join([
            self._make_act_text(i) for i in range(1, 7)
        ])

        mock_client.generate.side_effect = [
            "not json",   # outline attempt 1 fails
            "still not json",  # outline attempt 2 fails
            full_script,  # monolithic fallback
        ]

        result = asyncio.get_event_loop().run_until_complete(
            generate_script_staged(mock_client, SAMPLE_BRIEF)
        )

        assert result["script"] is not None
        assert result["outline"] is None  # outline failed
        # 2 outline attempts + 1 monolithic fallback
        assert mock_client.generate.call_count == 3

    def test_staged_act_failure_retries(self, mock_client):
        """Individual act failures retry up to 2 times."""
        responses = [json.dumps(SAMPLE_OUTLINE)]  # outline succeeds

        # Act 1: fails once, then succeeds
        responses.append("")  # fail (empty)
        responses.append(self._make_act_text(1))  # succeed on retry

        # Acts 2-6: succeed immediately
        for i in range(2, 7):
            responses.append(self._make_act_text(i))

        mock_client.generate.side_effect = responses

        result = asyncio.get_event_loop().run_until_complete(
            generate_script_staged(mock_client, SAMPLE_BRIEF)
        )

        assert len(result["acts"]) == 6
        # 1 outline + 1 fail + 1 retry + 5 acts = 8
        assert mock_client.generate.call_count == 8

    def test_staged_uses_sonnet_by_default(self, mock_client):
        """Default model should be Sonnet, not Opus."""
        mock_client.generate.side_effect = [
            json.dumps(SAMPLE_OUTLINE),
        ] + [
            self._make_act_text(i) for i in range(1, 7)
        ]

        asyncio.get_event_loop().run_until_complete(
            generate_script_staged(mock_client, SAMPLE_BRIEF)
        )

        # Check all calls used Sonnet
        for call in mock_client.generate.call_args_list:
            model = call.kwargs.get("model", call.args[1] if len(call.args) > 1 else None)
            if model:
                assert "sonnet" in model.lower(), f"Expected Sonnet, got {model}"
