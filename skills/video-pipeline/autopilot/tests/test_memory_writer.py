# skills/video-pipeline/autopilot/tests/test_memory_writer.py
"""Tests for memory writer."""

import pytest
from pathlib import Path
from autopilot.learning.memory_writer import (
    MemoryWriter,
    ExtractedLearning,
    ExperimentResult,
)
from autopilot.monitoring.early_warning import CTRVerdict


class TestMemoryWriter:
    """Test suite for memory writer."""

    @pytest.fixture
    def memory_dir(self, tmp_path):
        """Create a temporary memory directory with empty files."""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()

        # Create empty memory files
        (memory_dir / "experiments_log.md").write_text("# Experiment Log\n")
        (memory_dir / "thumbnail_patterns.md").write_text(
            "# Thumbnail Patterns\n\n## Notes\n"
        )
        (memory_dir / "title_patterns.md").write_text(
            "# Title Patterns\n\n## Notes\n"
        )
        (memory_dir / "LEARNINGS.md").write_text(
            "# Autopilot Learnings\n\nLast updated: 2026-03-01\nVideos produced: 0\n\n## Top 5 Proven Patterns\n"
        )

        return memory_dir

    @pytest.fixture
    def writer(self, memory_dir):
        """Create a memory writer with temp directory."""
        return MemoryWriter(memory_dir=memory_dir)

    @pytest.fixture
    def sample_result(self):
        """Create a sample experiment result."""
        learnings = [
            ExtractedLearning(
                category="thumbnail",
                pattern="Red/yellow color scheme",
                verdict=CTRVerdict.KEEP,
                confidence=0.8,
                evidence="Strong CTR at 5.2%",
                video_title="China's Dollar Trap",
                ctr=5.2,
            ),
            ExtractedLearning(
                category="title",
                pattern="Question format",
                verdict=CTRVerdict.KEEP,
                confidence=0.7,
                evidence="Above average CTR",
                video_title="China's Dollar Trap",
                ctr=5.2,
            ),
        ]
        return ExperimentResult(
            video_title="China's Dollar Trap",
            date="2026-03-18",
            modeled_from="China's Economic Crisis",
            predicted_ctr=4.5,
            actual_ctr=5.2,
            verdict=CTRVerdict.KEEP,
            thumbnail_override="REPLACE: Red gradient background",
            title_formula="Question format",
            learnings=learnings,
        )

    def test_append_experiment(self, writer, memory_dir, sample_result):
        """Should create entry in experiments_log.md."""
        writer.append_experiment(sample_result)

        log_path = memory_dir / "experiments_log.md"
        content = log_path.read_text()

        assert "## Video #1:" in content
        assert "China's Dollar Trap" in content
        assert "Modeled: China's Economic Crisis" in content
        assert "Predicted CTR: 4.5%" in content
        assert "Actual: 5.2%" in content
        assert "Status: KEEP" in content
        assert "Thumbnail override: REPLACE: Red gradient background" in content

    def test_append_increments_number(self, writer, memory_dir, sample_result):
        """Second experiment should be Video #2."""
        writer.append_experiment(sample_result)

        # Create second result with different title
        result2 = ExperimentResult(
            video_title="NATO's Collapse",
            date="2026-03-19",
            modeled_from=None,
            predicted_ctr=None,
            actual_ctr=3.5,
            verdict=CTRVerdict.NEUTRAL,
            thumbnail_override=None,
            title_formula=None,
            learnings=[],
        )
        writer.append_experiment(result2)

        log_path = memory_dir / "experiments_log.md"
        content = log_path.read_text()

        assert "## Video #1:" in content
        assert "## Video #2:" in content
        assert "NATO's Collapse" in content

    def test_update_thumbnail_patterns(self, writer, memory_dir):
        """Should add note to thumbnail_patterns.md."""
        learnings = [
            ExtractedLearning(
                category="thumbnail",
                pattern="Face left composition",
                verdict=CTRVerdict.KEEP,
                confidence=0.75,
                evidence="Consistent high CTR",
                video_title="Test Video",
                ctr=4.8,
            ),
        ]

        writer.update_thumbnail_patterns(learnings)

        pattern_path = memory_dir / "thumbnail_patterns.md"
        content = pattern_path.read_text()

        assert "Face left composition" in content
        assert "CTR 4.8%" in content
        assert "(keep)" in content
        assert "Test Video" in content

    def test_update_title_patterns(self, writer, memory_dir):
        """Should add note to title_patterns.md."""
        learnings = [
            ExtractedLearning(
                category="title",
                pattern="Number + urgency hook",
                verdict=CTRVerdict.DISCARD,
                confidence=0.6,
                evidence="Below average CTR",
                video_title="Failed Test",
                ctr=2.1,
            ),
        ]

        writer.update_title_patterns(learnings)

        pattern_path = memory_dir / "title_patterns.md"
        content = pattern_path.read_text()

        assert "Number + urgency hook" in content
        assert "CTR 2.1%" in content
        assert "(discard)" in content
        assert "Failed Test" in content

    def test_update_learnings_summary(self, writer, memory_dir):
        """Should update header stats in LEARNINGS.md."""
        writer.update_learnings_summary(
            videos_produced=5,
            avg_ctr=4.2,
            best_ctr=5.8,
            best_title="Best Video Ever",
        )

        path = memory_dir / "LEARNINGS.md"
        content = path.read_text()

        assert "Videos produced: 5" in content
        assert "Avg CTR: 4.2%" in content
        assert "Best CTR: 5.8%" in content
        assert "Best Video Ever" in content
        # Should preserve sections below header
        assert "## Top 5 Proven Patterns" in content

    def test_process_result_updates_all(self, writer, memory_dir, sample_result):
        """Full flow should update experiments_log and pattern files."""
        writer.process_result(sample_result)

        # Check experiments log
        log_content = (memory_dir / "experiments_log.md").read_text()
        assert "China's Dollar Trap" in log_content
        assert "## Video #1:" in log_content

        # Check thumbnail patterns
        thumb_content = (memory_dir / "thumbnail_patterns.md").read_text()
        assert "Red/yellow color scheme" in thumb_content
        assert "CTR 5.2%" in thumb_content

        # Check title patterns
        title_content = (memory_dir / "title_patterns.md").read_text()
        assert "Question format" in title_content
        assert "CTR 5.2%" in title_content
