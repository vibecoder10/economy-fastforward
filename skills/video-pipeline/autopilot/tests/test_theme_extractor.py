"""Tests for theme extractor."""

import pytest
import json
import asyncio
from unittest.mock import Mock, patch, AsyncMock
from autopilot.analysis.theme_extractor import (
    ThemeExtractor,
    ThemeAnalysis,
    ANGLE_TYPES,
    EMOTIONAL_HOOKS,
    TOPIC_CATEGORIES,
)


class TestThemeExtractor:
    """Test suite for theme extraction."""

    @pytest.fixture
    def mock_anthropic(self):
        """Mock Anthropic client."""
        mock = Mock()
        mock.messages = Mock()
        mock.messages.create = Mock()
        return mock

    @pytest.fixture
    def extractor(self, mock_anthropic):
        return ThemeExtractor(anthropic_client=mock_anthropic)

    @pytest.fixture
    def sample_extraction_response(self):
        """Sample Claude extraction response."""
        return {
            "primary_theme": "US-Iran conflict",
            "secondary_themes": ["regime change", "covert operations", "Middle East"],
            "angle_type": "hidden_truth",
            "emotional_hooks": ["curiosity_gap", "fear"],
            "topic_category": "geopolitics",
            "title_formula": "How [Major Power] [Deliberate Verb] the [Major Event]",
            "formula_variables": {
                "major_power": "US",
                "deliberate_verb": "Engineered",
                "major_event": "Iran War"
            },
            "confidence": 0.92
        }

    def test_parse_response_valid_json(self, extractor, sample_extraction_response):
        """Should parse valid JSON response."""
        analysis = extractor._parse_response(json.dumps(sample_extraction_response))

        assert analysis is not None
        assert analysis.primary_theme == "US-Iran conflict"
        assert analysis.angle_type == "hidden_truth"
        assert "curiosity_gap" in analysis.emotional_hooks
        assert analysis.topic_category == "geopolitics"
        assert analysis.confidence == 0.92

    def test_parse_response_with_markdown(self, extractor, sample_extraction_response):
        """Should parse JSON wrapped in markdown code blocks."""
        markdown_response = f"```json\n{json.dumps(sample_extraction_response)}\n```"
        analysis = extractor._parse_response(markdown_response)

        assert analysis is not None
        assert analysis.primary_theme == "US-Iran conflict"

    def test_parse_response_invalid_json(self, extractor):
        """Should return None for invalid JSON."""
        analysis = extractor._parse_response("not valid json at all")
        assert analysis is None

    def test_extract_success(self, extractor, mock_anthropic, sample_extraction_response):
        """Should extract theme analysis from title."""
        # Mock successful API response
        mock_response = Mock()
        mock_response.content = [Mock(text=json.dumps(sample_extraction_response))]
        mock_anthropic.messages.create.return_value = mock_response

        async def run_test():
            return await extractor.extract("How the US Engineered the Iran War")

        analysis = asyncio.run(run_test())

        assert analysis is not None
        assert analysis.primary_theme == "US-Iran conflict"
        assert analysis.angle_type == "hidden_truth"
        assert "curiosity_gap" in analysis.emotional_hooks

    def test_extract_validates_angle_type(self, extractor, mock_anthropic):
        """Should fallback to default for invalid angle_type."""
        response_data = {
            "primary_theme": "Test",
            "secondary_themes": [],
            "angle_type": "invalid_angle",  # Invalid
            "emotional_hooks": ["fear"],
            "topic_category": "geopolitics",
            "title_formula": "Test",
            "formula_variables": {},
            "confidence": 0.8
        }
        mock_response = Mock()
        mock_response.content = [Mock(text=json.dumps(response_data))]
        mock_anthropic.messages.create.return_value = mock_response

        async def run_test():
            return await extractor.extract("Test Title")

        analysis = asyncio.run(run_test())

        assert analysis is not None
        assert analysis.angle_type == "hidden_truth"  # Default fallback

    def test_extract_filters_invalid_hooks(self, extractor, mock_anthropic):
        """Should filter out invalid emotional hooks."""
        response_data = {
            "primary_theme": "Test",
            "secondary_themes": [],
            "angle_type": "warning",
            "emotional_hooks": ["fear", "invalid_hook", "outrage"],  # One invalid
            "topic_category": "economy",
            "title_formula": "Test",
            "formula_variables": {},
            "confidence": 0.8
        }
        mock_response = Mock()
        mock_response.content = [Mock(text=json.dumps(response_data))]
        mock_anthropic.messages.create.return_value = mock_response

        async def run_test():
            return await extractor.extract("Test Title")

        analysis = asyncio.run(run_test())

        assert analysis is not None
        assert "fear" in analysis.emotional_hooks
        assert "outrage" in analysis.emotional_hooks
        assert "invalid_hook" not in analysis.emotional_hooks

    def test_extract_empty_title(self, extractor):
        """Should return None for empty title."""
        async def run_test():
            return await extractor.extract("")

        analysis = asyncio.run(run_test())
        assert analysis is None

    def test_quick_extract_topic_category(self):
        """Should categorize topics using quick regex."""
        assert ThemeExtractor.quick_extract_topic_category("Russia's Military Invasion") == "military"
        assert ThemeExtractor.quick_extract_topic_category("China's Economic Crisis") == "geopolitics"
        assert ThemeExtractor.quick_extract_topic_category("Dollar Collapse Coming") == "finance"
        assert ThemeExtractor.quick_extract_topic_category("AI Will Replace Jobs") == "tech"
        assert ThemeExtractor.quick_extract_topic_category("Oil Prices Surge") == "energy"
        assert ThemeExtractor.quick_extract_topic_category("GDP Growth Slows") == "economy"

    def test_quick_extract_angle(self):
        """Should detect angle type using quick regex."""
        assert ThemeExtractor.quick_extract_angle("How the US Engineered the Crisis") == "hidden_truth"
        assert ThemeExtractor.quick_extract_angle("Why China Can't Win") == "impossibility"
        assert ThemeExtractor.quick_extract_angle("10 Days Until Collapse") == "countdown"
        assert ThemeExtractor.quick_extract_angle("This Will Destroy the Dollar") == "warning"
        assert ThemeExtractor.quick_extract_angle("The Secret Nobody Knows") == "revelation"
        assert ThemeExtractor.quick_extract_angle("What If Russia Attacked NATO") == "scenario"
        assert ThemeExtractor.quick_extract_angle("How AI Actually Works") == "explanation"
        assert ThemeExtractor.quick_extract_angle("US vs China: Who Wins?") == "comparison"

    def test_prompt_contains_required_elements(self, extractor):
        """Extraction prompt should ask for all required elements."""
        prompt = extractor.EXTRACTION_PROMPT.lower()
        assert "primary_theme" in prompt or "primary theme" in prompt
        assert "angle_type" in prompt or "angle type" in prompt
        assert "emotional_hooks" in prompt or "emotional hooks" in prompt
        assert "topic_category" in prompt or "topic category" in prompt
        assert "title_formula" in prompt or "formula" in prompt

    def test_angle_types_list(self):
        """Should have expected angle types defined."""
        assert "hidden_truth" in ANGLE_TYPES
        assert "impossibility" in ANGLE_TYPES
        assert "countdown" in ANGLE_TYPES
        assert "warning" in ANGLE_TYPES
        assert "revelation" in ANGLE_TYPES

    def test_emotional_hooks_list(self):
        """Should have expected emotional hooks defined."""
        assert "curiosity_gap" in EMOTIONAL_HOOKS
        assert "fear" in EMOTIONAL_HOOKS
        assert "outrage" in EMOTIONAL_HOOKS
        assert "urgency" in EMOTIONAL_HOOKS
        assert "scale" in EMOTIONAL_HOOKS
