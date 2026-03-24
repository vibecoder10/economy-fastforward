# skills/video-pipeline/curiosity_gap/tests/test_learning_integration.py
"""Integration tests for curiosity gap learning flow."""

import pytest
from pathlib import Path
from datetime import datetime

from autopilot.learning.learning_extractor import LearningExtractor
from autopilot.learning.memory_writer import MemoryWriter
from autopilot.monitoring.early_warning import CTRVerdict


class TestCuriosityGapLearningIntegration:
    """End-to-end tests for structure learning flow."""

    @pytest.fixture
    def temp_memory_dir(self, tmp_path):
        """Create temporary memory directory."""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()

        # Create initial title_patterns.md with Curiosity Gap Structures section
        (memory_dir / "title_patterns.md").write_text("""# Title Patterns

## Curiosity Gap Structures

| Structure | Avg CTR | Sample | Status |
|-----------|---------|--------|--------|
| *No data yet* | | | |

## Notes
""")
        (memory_dir / "experiments_log.md").write_text("# Experiment Log\n")
        return memory_dir

    def test_full_learning_flow_keep(self, temp_memory_dir):
        """Test: Extract structure learning -> Write to memory (KEEP verdict)."""
        extractor = LearningExtractor()
        writer = MemoryWriter(memory_dir=temp_memory_dir)

        # 1. Extract learnings from a high-CTR video
        result = extractor.extract_all(
            video_title="The $100B Mistake Saudi Arabia Is Hiding",
            ctr=5.2,
            thumbnail_override=None,
            modeled_from="competitor_video_123",
            theme_data=None,
            structure="hidden_flaw",
            structure_confidence=78,
        )

        # Verify structure learning extracted
        structure_learnings = [l for l in result.learnings if l.category == "structure"]
        assert len(structure_learnings) == 1
        assert structure_learnings[0].pattern == "hidden_flaw"
        assert structure_learnings[0].verdict == CTRVerdict.KEEP

        # 2. Write to memory
        writer.process_result(result)

        # 3. Verify memory files updated
        title_patterns = (temp_memory_dir / "title_patterns.md").read_text()
        assert "hidden_flaw" in title_patterns
        assert "5.2%" in title_patterns
        assert "The $100B Mistake" in title_patterns

        experiments_log = (temp_memory_dir / "experiments_log.md").read_text()
        assert "The $100B Mistake" in experiments_log
        assert "KEEP" in experiments_log

    def test_full_learning_flow_discard(self, temp_memory_dir):
        """Test: Low CTR produces DISCARD verdict and learning."""
        extractor = LearningExtractor()
        writer = MemoryWriter(memory_dir=temp_memory_dir)

        result = extractor.extract_all(
            video_title="The 40-Year Trap Nobody Saw",
            ctr=2.0,  # Below 2.5% threshold
            thumbnail_override=None,
            modeled_from=None,
            theme_data=None,
            structure="time_bomb",
            structure_confidence=65,
        )

        assert result.verdict == CTRVerdict.DISCARD

        structure_learnings = [l for l in result.learnings if l.category == "structure"]
        assert len(structure_learnings) == 1
        assert structure_learnings[0].verdict == CTRVerdict.DISCARD

        writer.process_result(result)

        title_patterns = (temp_memory_dir / "title_patterns.md").read_text()
        assert "time_bomb" in title_patterns
        assert "discard" in title_patterns.lower()

    def test_no_structure_produces_no_learning(self, temp_memory_dir):
        """Test: Video without structure produces no structure learning."""
        extractor = LearningExtractor()

        result = extractor.extract_all(
            video_title="Random Video Title",
            ctr=4.0,
            thumbnail_override=None,
            modeled_from=None,
            theme_data=None,
            structure=None,
            structure_confidence=None,
        )

        structure_learnings = [l for l in result.learnings if l.category == "structure"]
        assert len(structure_learnings) == 0

    def test_neutral_verdict_on_borderline_ctr(self, temp_memory_dir):
        """Test: Borderline CTR (2.5-4.0) produces NEUTRAL verdict."""
        extractor = LearningExtractor()
        writer = MemoryWriter(memory_dir=temp_memory_dir)

        result = extractor.extract_all(
            video_title="The Secret Deal That Changed Everything",
            ctr=3.2,  # Between 2.5 and 4.0
            thumbnail_override=None,
            modeled_from=None,
            theme_data=None,
            structure="hidden_truth",
            structure_confidence=70,
        )

        assert result.verdict == CTRVerdict.NEUTRAL

        structure_learnings = [l for l in result.learnings if l.category == "structure"]
        assert len(structure_learnings) == 1
        assert structure_learnings[0].verdict == CTRVerdict.NEUTRAL

        writer.process_result(result)

        title_patterns = (temp_memory_dir / "title_patterns.md").read_text()
        assert "hidden_truth" in title_patterns
        assert "neutral" in title_patterns.lower()

    def test_multiple_experiments_accumulate(self, temp_memory_dir):
        """Test: Multiple experiments accumulate in memory files."""
        extractor = LearningExtractor()
        writer = MemoryWriter(memory_dir=temp_memory_dir)

        # First experiment
        result1 = extractor.extract_all(
            video_title="First Video",
            ctr=5.0,
            structure="hidden_flaw",
            structure_confidence=80,
        )
        writer.process_result(result1)

        # Second experiment
        result2 = extractor.extract_all(
            video_title="Second Video",
            ctr=4.5,
            structure="time_bomb",
            structure_confidence=75,
        )
        writer.process_result(result2)

        # Both should be in experiments log
        experiments_log = (temp_memory_dir / "experiments_log.md").read_text()
        assert "First Video" in experiments_log
        assert "Second Video" in experiments_log
        assert "Video #1" in experiments_log
        assert "Video #2" in experiments_log

        # Both structures should be in title_patterns
        title_patterns = (temp_memory_dir / "title_patterns.md").read_text()
        assert "hidden_flaw" in title_patterns
        assert "time_bomb" in title_patterns
