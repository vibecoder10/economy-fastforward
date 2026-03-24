"""Tests for yin/yang thumbnail text generator."""

import pytest
from title_idea.curiosity_gap.structures import CuriosityStructure


class TestThumbnailText:
    """Test suite for ThumbnailText dataclass."""

    def test_thumbnail_text_creation(self):
        """Should create ThumbnailText with required fields."""
        from title_idea.curiosity_gap.thumbnail_generator import ThumbnailText

        thumb = ThumbnailText(
            text="WORTHLESS PIPELINES",
            approach="from_gap",
            reasoning="Title asks about mistake, thumbnail reveals consequence",
        )

        assert thumb.text == "WORTHLESS PIPELINES"
        assert thumb.approach == "from_gap"
        assert "consequence" in thumb.reasoning

    def test_approach_must_be_valid(self):
        """Approach must be from_hook or from_gap."""
        from title_idea.curiosity_gap.thumbnail_generator import ThumbnailText, VALID_APPROACHES

        assert "from_hook" in VALID_APPROACHES
        assert "from_gap" in VALID_APPROACHES
        assert len(VALID_APPROACHES) == 2


class TestYinYangRules:
    """Test suite for yin/yang generation rules."""

    def test_thumbnail_text_is_caps(self):
        """Generated thumbnail text should be ALL CAPS."""
        from title_idea.curiosity_gap.thumbnail_generator import format_thumbnail_text

        result = format_thumbnail_text("worthless pipelines")
        assert result == "WORTHLESS PIPELINES"

    def test_thumbnail_text_max_words(self):
        """Thumbnail text should be 2-4 words max."""
        from title_idea.curiosity_gap.thumbnail_generator import format_thumbnail_text

        # Too long should be truncated
        result = format_thumbnail_text("this is way too many words here")
        word_count = len(result.split())
        assert word_count <= 4

    def test_removes_common_filler(self):
        """Should remove common filler words."""
        from title_idea.curiosity_gap.thumbnail_generator import format_thumbnail_text

        result = format_thumbnail_text("the worthless pipelines")
        assert "THE" not in result.split()


class TestApproachSelection:
    """Test suite for selecting from_hook vs from_gap approach."""

    def test_hidden_flaw_prefers_from_gap(self):
        """Hidden flaw structure prefers from_gap (reveals consequence)."""
        from title_idea.curiosity_gap.thumbnail_generator import select_approach

        approach = select_approach(
            structure=CuriosityStructure.HIDDEN_FLAW,
            title="The $100B Mistake Saudi Arabia Is Hiding",
            hook="Saudi Arabia spent $100B on pipelines now sitting empty.",
        )

        assert approach == "from_gap"

    def test_asymmetric_prefers_from_hook(self):
        """Asymmetric structure prefers from_hook (surprising detail)."""
        from title_idea.curiosity_gap.thumbnail_generator import select_approach

        approach = select_approach(
            structure=CuriosityStructure.ASYMMETRIC_DG,
            title="Why the Navy Is Terrified of $500 Plastic",
            hook="Cheap plastic drones are destroying billion-dollar ships.",
        )

        assert approach == "from_hook"
