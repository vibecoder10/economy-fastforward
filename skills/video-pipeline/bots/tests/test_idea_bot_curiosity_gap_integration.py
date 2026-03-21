"""Integration tests for IdeaBot with curiosity gap title generation."""

import asyncio
import pytest
from unittest.mock import Mock, AsyncMock, patch


def run_async(coro):
    """Helper to run async coroutines in sync tests."""
    return asyncio.get_event_loop().run_until_complete(coro)


class TestIdeaBotCuriosityGapIntegration:
    """Integration tests for idea bot with curiosity gap."""

    @pytest.fixture
    def mock_anthropic(self):
        """Mock anthropic client that returns basic ideas."""
        mock = Mock()
        mock.generate_video_ideas = AsyncMock(return_value=[
            {
                "viral_title": "China's Dollar Crisis",
                "hook_script": "China's dollar reserves are declining at record pace.",
                "narrative_logic": {
                    "past_context": "China accumulated $4T in reserves",
                    "present_parallel": "Now losing $100B per month",
                    "future_prediction": "Could trigger currency crisis",
                },
                "thumbnail_visual": "Red alert symbol with currency graphs",
                "writer_guidance": "Tone: Urgent, analytical",
            }
        ])
        return mock

    @pytest.fixture
    def mock_airtable(self):
        """Mock airtable client."""
        mock = Mock()
        mock.create_idea = Mock(return_value={"id": "rec123"})
        mock.update_idea_curiosity_structure = Mock()
        return mock

    @pytest.fixture
    def mock_slack(self):
        """Mock slack client."""
        mock = Mock()
        mock.notify_idea_generated = Mock()
        return mock

    @pytest.fixture
    def mock_gap_engine(self):
        """Mock GapTitleEngine that returns predictable titles."""
        from curiosity_gap.structures import CuriosityStructure
        from curiosity_gap.gap_title_engine import GeneratedTitle

        mock = Mock()
        mock.generate_titles = AsyncMock(return_value=[
            GeneratedTitle(
                text="The $3T Trap China Cannot Escape",
                structure=CuriosityStructure.TIME_BOMB,
                structure_confidence=85,
                thumbnail_text="CHECKMATE",
                thumbnail_approach="from_gap",
                reasoning="Long-term trap framing with financial stake",
            )
        ])
        return mock

    def test_generate_ideas_with_curiosity_gap_disabled(self, mock_anthropic, mock_airtable, mock_slack):
        """Should skip enhancement when CURIOSITY_GAP_ENABLED is False."""
        from bots.idea_bot import IdeaBot

        bot = IdeaBot(
            anthropic_client=mock_anthropic,
            airtable_client=mock_airtable,
            slack_client=mock_slack,
        )

        async def run_test():
            with patch('bots.idea_bot.CURIOSITY_GAP_ENABLED', False):
                ideas = await bot.generate_ideas(
                    "China dollar reserves",
                    save_to_airtable=False,
                    notify_slack=False,
                )
            return ideas

        ideas = run_async(run_test())

        assert len(ideas) == 1
        # Should keep original title since enhancement is disabled
        assert ideas[0]["viral_title"] == "China's Dollar Crisis"
        # Should NOT have curiosity structure since enhancement skipped
        assert "curiosity_structure" not in ideas[0]

    def test_generate_ideas_with_curiosity_gap_enabled(
        self, mock_anthropic, mock_airtable, mock_slack, mock_gap_engine
    ):
        """Should enhance ideas with curiosity gap titles when enabled."""
        from bots.idea_bot import IdeaBot

        bot = IdeaBot(
            anthropic_client=mock_anthropic,
            airtable_client=mock_airtable,
            slack_client=mock_slack,
            gap_title_engine=mock_gap_engine,
        )

        async def run_test():
            with patch('bots.idea_bot.CURIOSITY_GAP_ENABLED', True):
                ideas = await bot.generate_ideas(
                    "China dollar reserves",
                    save_to_airtable=False,
                    notify_slack=False,
                )
            return ideas

        ideas = run_async(run_test())

        assert len(ideas) == 1
        # Should have enhanced title
        assert ideas[0]["viral_title"] == "The $3T Trap China Cannot Escape"
        # Should have structure metadata
        assert ideas[0]["curiosity_structure"] == "time_bomb"
        assert ideas[0]["structure_confidence"] == 85
        assert ideas[0]["thumbnail_text"] == "CHECKMATE"
        assert ideas[0]["thumbnail_approach"] == "from_gap"

    def test_curiosity_gap_failure_is_non_blocking(
        self, mock_anthropic, mock_airtable, mock_slack
    ):
        """Should keep original title if curiosity gap enhancement fails."""
        from bots.idea_bot import IdeaBot

        # Mock engine that fails
        failing_engine = Mock()
        failing_engine.generate_titles = AsyncMock(side_effect=Exception("API error"))

        bot = IdeaBot(
            anthropic_client=mock_anthropic,
            airtable_client=mock_airtable,
            slack_client=mock_slack,
            gap_title_engine=failing_engine,
        )

        async def run_test():
            with patch('bots.idea_bot.CURIOSITY_GAP_ENABLED', True):
                ideas = await bot.generate_ideas(
                    "China dollar reserves",
                    save_to_airtable=False,
                    notify_slack=False,
                )
            return ideas

        ideas = run_async(run_test())

        # Should still return ideas with original title
        assert len(ideas) == 1
        assert ideas[0]["viral_title"] == "China's Dollar Crisis"
        # Should not have structure since enhancement failed
        assert "curiosity_structure" not in ideas[0]

    def test_saves_structure_metadata_to_airtable(
        self, mock_anthropic, mock_airtable, mock_slack, mock_gap_engine
    ):
        """Should call update_idea_curiosity_structure when saving to Airtable."""
        from bots.idea_bot import IdeaBot

        bot = IdeaBot(
            anthropic_client=mock_anthropic,
            airtable_client=mock_airtable,
            slack_client=mock_slack,
            gap_title_engine=mock_gap_engine,
        )

        async def run_test():
            with patch('bots.idea_bot.CURIOSITY_GAP_ENABLED', True):
                await bot.generate_ideas(
                    "China dollar reserves",
                    save_to_airtable=True,
                    notify_slack=False,
                )

        run_async(run_test())

        # Should have created the idea
        mock_airtable.create_idea.assert_called_once()

        # Should have saved structure metadata
        mock_airtable.update_idea_curiosity_structure.assert_called_once_with(
            record_id="rec123",
            structure="time_bomb",
            confidence=85,
            thumbnail_text="CHECKMATE",
            thumbnail_approach="from_gap",
        )

    def test_curiosity_gap_metadata_not_saved_if_enhancement_fails(
        self, mock_anthropic, mock_airtable, mock_slack
    ):
        """Should not save structure metadata if enhancement fails."""
        from bots.idea_bot import IdeaBot

        failing_engine = Mock()
        failing_engine.generate_titles = AsyncMock(side_effect=Exception("API error"))

        bot = IdeaBot(
            anthropic_client=mock_anthropic,
            airtable_client=mock_airtable,
            slack_client=mock_slack,
            gap_title_engine=failing_engine,
        )

        async def run_test():
            with patch('bots.idea_bot.CURIOSITY_GAP_ENABLED', True):
                await bot.generate_ideas(
                    "China dollar reserves",
                    save_to_airtable=True,
                    notify_slack=False,
                )

        run_async(run_test())

        # Should have created the idea
        mock_airtable.create_idea.assert_called_once()

        # Should NOT have saved structure metadata since enhancement failed
        mock_airtable.update_idea_curiosity_structure.assert_not_called()

    def test_multiple_ideas_all_enhanced(
        self, mock_anthropic, mock_airtable, mock_slack, mock_gap_engine
    ):
        """Should enhance all ideas in the batch."""
        from bots.idea_bot import IdeaBot

        # Mock returning 3 ideas
        mock_anthropic.generate_video_ideas = AsyncMock(return_value=[
            {
                "viral_title": "Idea 1",
                "hook_script": "Hook 1",
                "narrative_logic": {"past_context": "p", "present_parallel": "pres", "future_prediction": "f"},
                "thumbnail_visual": "Visual 1",
                "writer_guidance": "Guide 1",
            },
            {
                "viral_title": "Idea 2",
                "hook_script": "Hook 2",
                "narrative_logic": {"past_context": "p", "present_parallel": "pres", "future_prediction": "f"},
                "thumbnail_visual": "Visual 2",
                "writer_guidance": "Guide 2",
            },
            {
                "viral_title": "Idea 3",
                "hook_script": "Hook 3",
                "narrative_logic": {"past_context": "p", "present_parallel": "pres", "future_prediction": "f"},
                "thumbnail_visual": "Visual 3",
                "writer_guidance": "Guide 3",
            },
        ])

        # Mock gap engine to return a title for each
        mock_gap_engine.generate_titles = AsyncMock(return_value=[
            Mock(text="Enhanced 1", structure_confidence=85, structure=Mock(value="time_bomb"),
                 thumbnail_text="TEXT1", thumbnail_approach="from_gap", reasoning="reason1"),
        ])

        bot = IdeaBot(
            anthropic_client=mock_anthropic,
            airtable_client=mock_airtable,
            slack_client=mock_slack,
            gap_title_engine=mock_gap_engine,
        )

        async def run_test():
            with patch('bots.idea_bot.CURIOSITY_GAP_ENABLED', True):
                ideas = await bot.generate_ideas(
                    "China",
                    save_to_airtable=False,
                    notify_slack=False,
                )
            return ideas

        ideas = run_async(run_test())

        # Should have enhanced all 3 ideas
        assert len(ideas) == 3
        # Each should have curiosity structure (gap engine was called 3 times)
        for idea in ideas:
            assert "curiosity_structure" in idea

    def test_preserves_original_dna_with_enhancement(
        self, mock_anthropic, mock_airtable, mock_slack, mock_gap_engine
    ):
        """Should preserve original_dna even when enhanced."""
        from bots.idea_bot import IdeaBot

        bot = IdeaBot(
            anthropic_client=mock_anthropic,
            airtable_client=mock_airtable,
            slack_client=mock_slack,
            gap_title_engine=mock_gap_engine,
        )

        async def run_test():
            with patch('bots.idea_bot.CURIOSITY_GAP_ENABLED', True):
                ideas = await bot.generate_ideas(
                    "Test concept",
                    save_to_airtable=False,
                    notify_slack=False,
                )
            return ideas

        ideas = run_async(run_test())

        assert len(ideas) == 1
        # Should have original_dna
        assert "original_dna" in ideas[0]
        assert "concept" in ideas[0]["original_dna"].lower()

    def test_youtube_url_analysis_with_curiosity_gap(
        self, mock_anthropic, mock_airtable, mock_slack, mock_gap_engine
    ):
        """Should handle YouTube URL analysis with curiosity gap enhancement."""
        from bots.idea_bot import IdeaBot

        bot = IdeaBot(
            anthropic_client=mock_anthropic,
            airtable_client=mock_airtable,
            slack_client=mock_slack,
            gap_title_engine=mock_gap_engine,
            gemini_client=None,  # No gemini for this test
        )

        async def run_test():
            with patch('bots.idea_bot.CURIOSITY_GAP_ENABLED', True):
                ideas = await bot.generate_ideas(
                    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                    save_to_airtable=False,
                    notify_slack=False,
                )
            return ideas

        ideas = run_async(run_test())

        assert len(ideas) == 1
        # Should have reference_url from YouTube URL
        assert ideas[0].get("reference_url") == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        # Should have enhancement
        assert ideas[0]["curiosity_structure"] == "time_bomb"

    def test_slack_notification_includes_curiosity_structure(
        self, mock_anthropic, mock_airtable, mock_slack, mock_gap_engine
    ):
        """Slack notification should include curiosity structure info."""
        from bots.idea_bot import IdeaBot

        bot = IdeaBot(
            anthropic_client=mock_anthropic,
            airtable_client=mock_airtable,
            slack_client=mock_slack,
            gap_title_engine=mock_gap_engine,
        )

        async def run_test():
            with patch('bots.idea_bot.CURIOSITY_GAP_ENABLED', True):
                await bot.generate_ideas(
                    "China",
                    save_to_airtable=False,
                    notify_slack=True,
                )

        run_async(run_test())

        # Slack should have been notified
        mock_slack.notify_idea_generated.assert_called_once()

        # Get the ideas passed to slack
        call_args = mock_slack.notify_idea_generated.call_args
        ideas_notified = call_args[0][0]

        # Ideas should have curiosity structure
        assert ideas_notified[0].get("curiosity_structure") == "time_bomb"
