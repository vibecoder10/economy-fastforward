"""Tests for idea creator."""

import pytest
import json
import asyncio
from unittest.mock import Mock, patch, AsyncMock
from autopilot.production.idea_creator import (
    IdeaCreator,
    ModeledIdea,
    CHANNEL_NICHE_VARIABLES,
)
from autopilot.analysis.theme_extractor import ThemeAnalysis
from autopilot.core.confidence_scorer import IdeaCandidate


class TestIdeaCreator:
    """Test suite for idea creation."""

    @pytest.fixture
    def mock_anthropic(self):
        """Mock Anthropic client."""
        mock = AsyncMock()
        return mock

    @pytest.fixture
    def mock_airtable(self):
        """Mock Airtable client."""
        mock = Mock()
        mock.create_idea.return_value = {"id": "rec123", "fields": {"Video Title": "Test"}}
        return mock

    @pytest.fixture
    def creator(self, mock_anthropic, mock_airtable):
        return IdeaCreator(
            airtable_client=mock_airtable,
            anthropic_client=mock_anthropic,
        )

    @pytest.fixture
    def sample_theme_analysis(self):
        return ThemeAnalysis(
            primary_theme="US-Iran conflict",
            secondary_themes=["regime change", "covert operations"],
            angle_type="hidden_truth",
            emotional_hooks=["curiosity_gap", "fear"],
            topic_category="geopolitics",
            title_formula="How [Major Power] [Deliberate Verb] the [Major Event]",
            formula_variables={
                "major_power": "US",
                "deliberate_verb": "Engineered",
                "major_event": "Iran War"
            },
            confidence=0.92
        )

    @pytest.fixture
    def sample_candidate(self):
        return IdeaCandidate(
            record_id="rec456",
            title="How the US Engineered the Iran War",
            source_type="competitor",
            competitor_vph=150.0,
            competitor_title="How the US Engineered the Iran War",
            hours_old=24,
        )

    @pytest.fixture
    def sample_ideas_response(self):
        return [
            {
                "viral_title": "How China Engineered the Taiwan Crisis",
                "hook_script": "In the shadows of diplomacy...",
                "thumbnail_visual": "Map of Taiwan with red arrows",
                "past_context": "Decades of cross-strait tensions",
                "present_parallel": "Recent military exercises",
                "future_prediction": "Potential conflict by 2027",
                "writer_guidance": "Focus on covert operations angle",
                "variables_swapped": ["power: US → China", "event: Iran War → Taiwan Crisis"]
            },
            {
                "viral_title": "How Russia Manufactured the Ukraine Excuse",
                "hook_script": "The Kremlin had a plan...",
                "thumbnail_visual": "Map of Ukraine with NATO arrows",
                "past_context": "Post-Soviet tensions",
                "present_parallel": "Ongoing conflict",
                "future_prediction": "Escalation risks",
                "writer_guidance": "Document the pretext building",
                "variables_swapped": ["power: US → Russia", "event: Iran War → Ukraine War"]
            }
        ]

    def test_parse_ideas_response_valid_json(self, creator, sample_ideas_response):
        """Should parse valid JSON array."""
        ideas = creator._parse_ideas_response(json.dumps(sample_ideas_response))

        assert len(ideas) == 2
        assert ideas[0]["viral_title"] == "How China Engineered the Taiwan Crisis"

    def test_parse_ideas_response_markdown(self, creator, sample_ideas_response):
        """Should parse JSON in markdown code block."""
        markdown = f"```json\n{json.dumps(sample_ideas_response)}\n```"
        ideas = creator._parse_ideas_response(markdown)

        assert len(ideas) == 2

    def test_parse_ideas_response_invalid(self, creator):
        """Should return empty list for invalid JSON."""
        ideas = creator._parse_ideas_response("not json at all")
        assert ideas == []

    def test_build_generation_prompt(self, creator, sample_theme_analysis):
        """Should build prompt with all theme elements."""
        prompt = creator._build_generation_prompt(
            competitor_title="How the US Engineered the Iran War",
            theme_analysis=sample_theme_analysis,
            num_ideas=3,
        )

        assert "How the US Engineered the Iran War" in prompt
        assert "hidden_truth" in prompt
        assert "curiosity_gap" in prompt
        assert "How [Major Power] [Deliberate Verb]" in prompt
        assert "3 ORIGINAL video ideas" in prompt

    def test_generate_modeled_ideas(
        self, creator, mock_anthropic, sample_theme_analysis, sample_ideas_response
    ):
        """Should generate modeled ideas from competitor title."""
        # Mock API response
        mock_response = Mock()
        mock_response.content = [Mock(text=json.dumps(sample_ideas_response))]
        mock_anthropic.messages.create = AsyncMock(return_value=mock_response)

        async def run_test():
            return await creator.generate_modeled_ideas(
                competitor_title="How the US Engineered the Iran War",
                theme_analysis=sample_theme_analysis,
                num_ideas=2,
            )

        ideas = asyncio.run(run_test())

        assert len(ideas) == 2
        assert isinstance(ideas[0], ModeledIdea)
        assert ideas[0].viral_title == "How China Engineered the Taiwan Crisis"
        assert ideas[0].theme_analysis == sample_theme_analysis

    def test_modeled_idea_has_formula_attribution(
        self, creator, mock_anthropic, sample_theme_analysis, sample_ideas_response
    ):
        """Generated ideas should include formula attribution."""
        mock_response = Mock()
        mock_response.content = [Mock(text=json.dumps(sample_ideas_response))]
        mock_anthropic.messages.create = AsyncMock(return_value=mock_response)

        async def run_test():
            return await creator.generate_modeled_ideas(
                competitor_title="How the US Engineered the Iran War",
                theme_analysis=sample_theme_analysis,
                num_ideas=1,
            )

        ideas = asyncio.run(run_test())

        assert len(ideas) >= 1
        idea = ideas[0]
        assert "Modeled from:" in idea.modeled_from
        assert "Formula:" in idea.modeled_from
        assert "hidden_truth" in idea.modeled_from

    def test_create_idea_from_competitor(
        self,
        creator,
        mock_anthropic,
        mock_airtable,
        sample_candidate,
        sample_theme_analysis,
        sample_ideas_response,
    ):
        """Should create idea in Airtable from competitor."""
        mock_response = Mock()
        mock_response.content = [Mock(text=json.dumps(sample_ideas_response))]
        mock_anthropic.messages.create = AsyncMock(return_value=mock_response)

        async def run_test():
            return await creator.create_idea_from_competitor(
                candidate=sample_candidate,
                theme_analysis=sample_theme_analysis,
                idea_index=0,
            )

        record = asyncio.run(run_test())

        assert record is not None
        assert record["id"] == "rec123"
        mock_airtable.create_idea.assert_called_once()

        # Verify idea data passed to create_idea
        call_args = mock_airtable.create_idea.call_args
        idea_data = call_args[0][0]
        assert "viral_title" in idea_data
        assert "narrative_logic" in idea_data
        assert "original_dna" in idea_data

    def test_niche_variables_defined(self):
        """Channel niche variables should be defined."""
        assert "topics" in CHANNEL_NICHE_VARIABLES
        assert "entities" in CHANNEL_NICHE_VARIABLES
        assert len(CHANNEL_NICHE_VARIABLES["topics"]) > 5
        assert "China" in CHANNEL_NICHE_VARIABLES["entities"]

    def test_modeled_idea_dataclass(self, sample_theme_analysis):
        """ModeledIdea should be properly structured."""
        idea = ModeledIdea(
            viral_title="Test Title",
            hook_script="Test hook",
            thumbnail_visual="Test visual",
            narrative_logic={"past_context": "Past", "present_parallel": "Now"},
            writer_guidance="Test guidance",
            modeled_from="Test source",
            formula_used="Test formula",
            variables_swapped=["a → b"],
            theme_analysis=sample_theme_analysis,
            confidence_score=0.8,
        )

        assert idea.viral_title == "Test Title"
        assert idea.theme_analysis.angle_type == "hidden_truth"
        assert "a → b" in idea.variables_swapped
