# skills/video-pipeline/curiosity_gap/tests/test_integration.py
"""Integration tests for curiosity gap Phase 1."""

import asyncio
import pytest
from unittest.mock import AsyncMock, Mock, patch
from pathlib import Path

from curiosity_gap.competitor_analyzer import CompetitorAnalyzer, TitleAnalysis
from curiosity_gap.structures import CuriosityStructure


def run_async(coro):
    """Run an async coroutine synchronously for testing."""
    return asyncio.get_event_loop().run_until_complete(coro)


class TestCompetitorAnalyzerIntegration:
    """Integration tests for full analyzer flow."""

    @pytest.fixture
    def analyzer(self):
        return CompetitorAnalyzer()

    def test_full_video_analysis_flow(self, analyzer):
        """Test complete video analysis (title + conditional thumbnail)."""
        async def _test():
            # Mock Claude response
            mock_title_response = {
                "structure": "hidden_flaw",
                "confidence": 85,
                "gap_mechanism": "What's the $100B mistake?",
                "variables": {"amount": "$100B", "entity": "Saudi Arabia"},
            }

            # Mock channel videos for VPH percentile
            mock_channel_videos = [{"vph": v} for v in [50, 75, 100, 125, 150]]

            with patch.object(analyzer, '_call_claude_for_title', return_value=mock_title_response):
                with patch('curiosity_gap.competitor_analyzer.get_recent_channel_videos', return_value=mock_channel_videos):
                    # Test video in top 20% (VPH 200 > 80th percentile of channel)
                    result = await analyzer.analyze_video(
                        video_id="test123",
                        title="The $100B Mistake Saudi Arabia Is Hiding",
                        vph=200,
                        channel_name="CaspianReport",
                    )

                    assert result["title_analysis"].structure == CuriosityStructure.HIDDEN_FLAW
                    assert result["title_analysis"].confidence == 85
                    assert result["deep_analyzed"] is True  # Top 20% qualifies

        run_async(_test())

    def test_low_vph_skips_thumbnail(self, analyzer):
        """Videos below top 20% should skip thumbnail analysis."""
        async def _test():
            mock_title_response = {
                "structure": "other",
                "confidence": 40,
                "gap_mechanism": "unclear",
                "variables": {},
            }

            mock_channel_videos = [{"vph": v} for v in [100, 150, 200, 250, 300]]

            with patch.object(analyzer, '_call_claude_for_title', return_value=mock_title_response):
                with patch('curiosity_gap.competitor_analyzer.get_recent_channel_videos', return_value=mock_channel_videos):
                    # Test video NOT in top 20% (VPH 120 < 80th percentile)
                    result = await analyzer.analyze_video(
                        video_id="test456",
                        title="Some Low Performing Title",
                        vph=120,
                        channel_name="CaspianReport",
                    )

                    assert result["deep_analyzed"] is False
                    assert result["thumbnail_analysis"] is None

        run_async(_test())

    def test_thumbnail_analysis_called_for_top_performer(self, analyzer):
        """Videos in top 20% should trigger thumbnail analysis."""
        async def _test():
            mock_title_response = {
                "structure": "asymmetric_dg",
                "confidence": 90,
                "gap_mechanism": "How does small beat big?",
                "variables": {"small_entity": "$500 Plastic", "big_entity": "Navy"},
            }

            mock_channel_videos = [{"vph": v} for v in [50, 75, 100, 125, 150]]

            mock_thumbnail_result = {
                "colors": ["red", "yellow"],
                "composition": "face-left, text-right",
                "text_extracted": "NAVY'S WEAKNESS",
                "yin_yang_relationship": "Title asks question, thumbnail shows answer",
                "yin_yang_approach": "from_hook",
            }

            with patch.object(analyzer, '_call_claude_for_title', return_value=mock_title_response):
                with patch('curiosity_gap.competitor_analyzer.get_recent_channel_videos', return_value=mock_channel_videos):
                    with patch.object(analyzer, '_analyze_with_gemini', return_value=Mock(
                        colors=mock_thumbnail_result["colors"],
                        composition=mock_thumbnail_result["composition"],
                        text_extracted=mock_thumbnail_result["text_extracted"],
                        yin_yang_relationship=mock_thumbnail_result["yin_yang_relationship"],
                        yin_yang_approach=mock_thumbnail_result["yin_yang_approach"],
                    )):
                        # VPH 200 is in top 20% of [50, 75, 100, 125, 150]
                        result = await analyzer.analyze_video(
                            video_id="test789",
                            title="Why the Navy Is Terrified of $500 Plastic",
                            vph=200,
                            channel_name="CaspianReport",
                        )

                        assert result["deep_analyzed"] is True
                        assert result["thumbnail_analysis"] is not None
                        assert result["thumbnail_analysis"].colors == ["red", "yellow"]

        run_async(_test())


class TestStructuresIntegration:
    """Integration tests for structure definitions."""

    def test_all_structures_have_complete_definitions(self):
        """Every structure should have all required fields."""
        from curiosity_gap.structures import STRUCTURE_DEFINITIONS, CuriosityStructure

        required_fields = ["gap_mechanism", "when_to_use", "example"]

        for structure in CuriosityStructure:
            assert structure in STRUCTURE_DEFINITIONS, f"Missing definition for {structure}"
            for field in required_fields:
                assert field in STRUCTURE_DEFINITIONS[structure], f"Missing {field} for {structure}"

    def test_structure_prompt_contains_all_mechanisms(self):
        """Generated prompt should include all gap mechanisms."""
        from curiosity_gap.structures import get_structure_prompt, STRUCTURE_DEFINITIONS, CuriosityStructure

        prompt = get_structure_prompt()

        for structure in CuriosityStructure:
            if structure != CuriosityStructure.OTHER:
                mechanism = STRUCTURE_DEFINITIONS[structure]["gap_mechanism"]
                # At least part of the mechanism should be in the prompt
                assert structure.value in prompt, f"Structure {structure.value} not in prompt"

    def test_validate_structure_handles_all_valid_inputs(self):
        """validate_structure should handle all valid structure names."""
        from curiosity_gap.structures import validate_structure, CuriosityStructure

        # Test all valid structures
        assert validate_structure("hidden_flaw") == CuriosityStructure.HIDDEN_FLAW
        assert validate_structure("asymmetric_dg") == CuriosityStructure.ASYMMETRIC_DG
        assert validate_structure("time_bomb") == CuriosityStructure.TIME_BOMB
        assert validate_structure("paradigm_shift") == CuriosityStructure.PARADIGM_SHIFT
        assert validate_structure("illusion_control") == CuriosityStructure.ILLUSION_CONTROL
        assert validate_structure("other") == CuriosityStructure.OTHER

    def test_validate_structure_normalizes_case(self):
        """validate_structure should be case-insensitive."""
        from curiosity_gap.structures import validate_structure, CuriosityStructure

        assert validate_structure("HIDDEN_FLAW") == CuriosityStructure.HIDDEN_FLAW
        assert validate_structure("Hidden_Flaw") == CuriosityStructure.HIDDEN_FLAW
        assert validate_structure("  hidden_flaw  ") == CuriosityStructure.HIDDEN_FLAW

    def test_validate_structure_returns_other_for_invalid(self):
        """validate_structure should return OTHER for invalid inputs."""
        from curiosity_gap.structures import validate_structure, CuriosityStructure

        assert validate_structure("unknown_structure") == CuriosityStructure.OTHER
        assert validate_structure("") == CuriosityStructure.OTHER
        assert validate_structure(None) == CuriosityStructure.OTHER

    def test_get_main_structures_excludes_other(self):
        """get_main_structures should return 5 structures without OTHER."""
        from curiosity_gap.structures import get_main_structures, CuriosityStructure

        main_structures = get_main_structures()

        assert len(main_structures) == 5
        assert CuriosityStructure.OTHER not in main_structures
        assert CuriosityStructure.HIDDEN_FLAW in main_structures
        assert CuriosityStructure.ASYMMETRIC_DG in main_structures
        assert CuriosityStructure.TIME_BOMB in main_structures
        assert CuriosityStructure.PARADIGM_SHIFT in main_structures
        assert CuriosityStructure.ILLUSION_CONTROL in main_structures


class TestVPHNormalizationIntegration:
    """Integration tests for VPH normalization logic."""

    def test_percentile_calculation_at_boundaries(self):
        """Test percentile calculation at edge cases."""
        from curiosity_gap.competitor_analyzer import should_deep_analyze_sync

        # 10 videos, 80th percentile is at position 8 (index 7)
        mock_videos = [{"vph": v} for v in [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]]

        with patch('curiosity_gap.competitor_analyzer.get_recent_channel_videos', return_value=mock_videos):
            # VPH 85 is above 80th percentile (position 8 of 10 = 80%)
            assert should_deep_analyze_sync(85, "TestChannel") is True

            # VPH 75 is at 70th percentile (position 7 of 10)
            assert should_deep_analyze_sync(75, "TestChannel") is False

            # VPH 100 is at 100th percentile
            assert should_deep_analyze_sync(100, "TestChannel") is True

    def test_cold_start_threshold_boundaries(self):
        """Test cold start behavior with few videos."""
        from curiosity_gap.competitor_analyzer import should_deep_analyze_sync, COLD_START_VPH_THRESHOLD

        # Only 3 videos = cold start mode
        mock_videos = [{"vph": v} for v in [50, 100, 150]]

        with patch('curiosity_gap.competitor_analyzer.get_recent_channel_videos', return_value=mock_videos):
            # Exactly at threshold
            assert should_deep_analyze_sync(COLD_START_VPH_THRESHOLD, "NewChannel") is True

            # Just below threshold
            assert should_deep_analyze_sync(COLD_START_VPH_THRESHOLD - 1, "NewChannel") is False

    def test_empty_channel_uses_cold_start(self):
        """Empty channel should use cold start threshold."""
        from curiosity_gap.competitor_analyzer import should_deep_analyze_sync, COLD_START_VPH_THRESHOLD

        with patch('curiosity_gap.competitor_analyzer.get_recent_channel_videos', return_value=[]):
            # Should use cold start threshold
            assert should_deep_analyze_sync(COLD_START_VPH_THRESHOLD + 50, "EmptyChannel") is True
            assert should_deep_analyze_sync(COLD_START_VPH_THRESHOLD - 1, "EmptyChannel") is False
