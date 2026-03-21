# skills/video-pipeline/autopilot/tests/test_memory_writer_structure.py
"""Tests for curiosity gap memory writing."""

import pytest
from pathlib import Path
from autopilot.learning.memory_writer import MemoryWriter, ExtractedLearning, ExperimentResult
from autopilot.monitoring.early_warning import CTRVerdict


class TestCuriosityGapMemoryWriter:
    """Test suite for curiosity gap memory writing."""

    @pytest.fixture
    def temp_memory_dir(self, tmp_path):
        """Create temporary memory directory with title_patterns.md."""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()

        # Create initial title_patterns.md
        title_patterns = memory_dir / "title_patterns.md"
        title_patterns.write_text("""# Title Patterns

Last updated: 2026-03-18
Sample size: 0 videos

---

## Proven Formulas (USE)

*No proven formulas yet.*

---

## Curiosity Gap Structures

| Structure | Avg CTR | Sample | Verdict |
|-----------|---------|--------|---------|
| *No data yet* | | | |

---

## Notes

Pattern types: question, statement, number
""")
        return memory_dir

    @pytest.fixture
    def writer(self, temp_memory_dir):
        return MemoryWriter(memory_dir=temp_memory_dir)

    def test_update_curiosity_gap_patterns_keep(self, writer, temp_memory_dir):
        """Should add KEEP structure to Curiosity Gap Structures section."""
        learnings = [
            ExtractedLearning(
                category="structure",
                pattern="hidden_flaw",
                verdict=CTRVerdict.KEEP,
                confidence=75.0,
                evidence="Structure 'hidden_flaw'. CTR: 5.2%",
                video_title="The $100B Mistake",
                ctr=5.2,
            )
        ]

        writer.update_curiosity_gap_patterns(learnings)

        content = (temp_memory_dir / "title_patterns.md").read_text()
        assert "hidden_flaw" in content
        assert "5.2%" in content
        assert "keep" in content.lower()

    def test_update_curiosity_gap_patterns_discard(self, writer, temp_memory_dir):
        """Should add DISCARD structure to Curiosity Gap Structures section."""
        learnings = [
            ExtractedLearning(
                category="structure",
                pattern="time_bomb",
                verdict=CTRVerdict.DISCARD,
                confidence=40.0,
                evidence="Structure 'time_bomb'. CTR: 2.1%",
                video_title="The 40-Year Trap",
                ctr=2.1,
            )
        ]

        writer.update_curiosity_gap_patterns(learnings)

        content = (temp_memory_dir / "title_patterns.md").read_text()
        assert "time_bomb" in content
        assert "2.1%" in content

    def test_update_curiosity_gap_patterns_skips_non_structure(self, writer, temp_memory_dir):
        """Should skip non-structure category learnings."""
        learnings = [
            ExtractedLearning(
                category="title",  # Not "structure"
                pattern="question_format",
                verdict=CTRVerdict.KEEP,
                confidence=60.0,
                evidence="Question format",
                video_title="Why X?",
                ctr=4.5,
            )
        ]

        original_content = (temp_memory_dir / "title_patterns.md").read_text()
        writer.update_curiosity_gap_patterns(learnings)
        new_content = (temp_memory_dir / "title_patterns.md").read_text()

        # Should be unchanged
        assert original_content == new_content

    def test_process_result_includes_structure(self, writer, temp_memory_dir):
        """process_result should call update_curiosity_gap_patterns."""
        # Create experiments_log.md for append_experiment
        (temp_memory_dir / "experiments_log.md").write_text("# Experiment Log\n")

        result = ExperimentResult(
            video_title="The $100B Mistake",
            date="2026-03-20",
            modeled_from=None,
            predicted_ctr=None,
            actual_ctr=5.2,
            verdict=CTRVerdict.KEEP,
            thumbnail_override=None,
            title_formula=None,
            learnings=[
                ExtractedLearning(
                    category="structure",
                    pattern="hidden_flaw",
                    verdict=CTRVerdict.KEEP,
                    confidence=75.0,
                    evidence="hidden_flaw structure",
                    video_title="The $100B Mistake",
                    ctr=5.2,
                )
            ],
        )

        writer.process_result(result)

        content = (temp_memory_dir / "title_patterns.md").read_text()
        assert "hidden_flaw" in content
