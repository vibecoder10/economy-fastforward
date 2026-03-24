"""Tests for WeaponsCheck — the quality enforcer for every block of text."""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock

from agents.weapons_check import WeaponsCheck, WeaponsReport, ScoredBlock
from agents.config import WeaponsConfig


def _run(coro):
    """Run an async function synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)


SAMPLE_SCRIPT = """ACT 2 — THE SETUP

Zhang Wei stared at the terminal. The number: $3.2 trillion. America's
debt sat in Chinese vaults. Nobody in Washington understood what that meant.

ACT 3 — THE ESCALATION

But the real weapon wasn't the bonds themselves. It was the threat of
selling them. One phone call could crash the dollar by 15% in a day.

ACT 4 — THE TURN

In March 2026, a Bloomberg terminal flashed an anomaly that nobody at the
Federal Reserve had anticipated. China wasn't selling. They were buying.

ACT 5 — THE IMPLICATIONS

The world Zhang Wei had known for twenty years was ending. The new one
would be denominated in a currency that didn't yet exist. And America
had exactly eighteen months to figure out its response."""


def _make_score_response(novelty: int, intensity: int) -> str:
    return json.dumps({
        "novelty": {"score": novelty, "reasoning": "test reasoning"},
        "intensity": {"score": intensity, "reasoning": "test reasoning"},
    })


class TestWeaponsNoneGranularity:

    def test_none_granularity_skips(self):
        config = WeaponsConfig(granularity="none")
        checker = WeaponsCheck(config=config)

        report = _run(checker.check(SAMPLE_SCRIPT))

        assert isinstance(report, WeaponsReport)
        assert len(report.blocks) == 0
        assert len(report.filler_blocks) == 0
        assert len(report.rewrite_blocks) == 0
        assert report.pass_rate == 1.0


class TestWeaponsActLevel:

    def test_act_level_scores_acts(self):
        mock_claude = AsyncMock()
        # Return passing scores for each act
        mock_claude.generate.return_value = _make_score_response(8, 8)

        config = WeaponsConfig(granularity="act", min_novelty=7, min_intensity=7)
        checker = WeaponsCheck(config=config, claude_client=mock_claude)

        report = _run(checker.check(SAMPLE_SCRIPT))

        # Should have 4 acts (Acts 2-5)
        assert len(report.blocks) == 4
        assert all(b.novelty == 8 for b in report.blocks)
        assert all(b.intensity == 8 for b in report.blocks)
        assert report.pass_rate == 1.0

    def test_act_labels_correct(self):
        mock_claude = AsyncMock()
        mock_claude.generate.return_value = _make_score_response(8, 8)

        config = WeaponsConfig(granularity="act")
        checker = WeaponsCheck(config=config, claude_client=mock_claude)

        report = _run(checker.check(SAMPLE_SCRIPT))

        labels = [b.label for b in report.blocks]
        assert "Act 2" in labels
        assert "Act 3" in labels
        assert "Act 4" in labels
        assert "Act 5" in labels


class TestWeaponsLineLevel:

    def test_line_level_scores_blocks(self):
        mock_claude = AsyncMock()
        mock_claude.generate.return_value = _make_score_response(8, 8)

        config = WeaponsConfig(granularity="line", min_novelty=7, min_intensity=7)
        checker = WeaponsCheck(config=config, claude_client=mock_claude)

        report = _run(checker.check(SAMPLE_SCRIPT))

        # Should have more blocks than acts (2-3 sentence groups)
        assert len(report.blocks) >= 4
        # All blocks should have labels like "Act N, Block M"
        assert any("Block" in b.label for b in report.blocks)


class TestWeaponsClassification:

    def test_filler_blocks_identified(self):
        mock_claude = AsyncMock()
        # First block: filler (both below 5)
        # Second block: good
        mock_claude.generate.side_effect = [
            _make_score_response(3, 4),  # Both < 5 = filler
            _make_score_response(8, 8),  # Good
            _make_score_response(3, 3),  # Both < 5 = filler
            _make_score_response(9, 9),  # Great
        ]

        config = WeaponsConfig(granularity="act", min_novelty=7, min_intensity=7, filler_threshold=5)
        checker = WeaponsCheck(config=config, claude_client=mock_claude)

        report = _run(checker.check(SAMPLE_SCRIPT))

        assert len(report.filler_blocks) == 2
        assert all(b.is_filler for b in report.filler_blocks)
        assert all(b.novelty < 5 and b.intensity < 5 for b in report.filler_blocks)

    def test_rewrite_blocks_identified(self):
        mock_claude = AsyncMock()
        # Block with novelty < 7 but intensity >= 7 -> needs rewrite
        # Block with both >= 7 -> passes
        mock_claude.generate.side_effect = [
            _make_score_response(5, 8),  # Novelty < 7 -> rewrite
            _make_score_response(8, 5),  # Intensity < 7 -> rewrite
            _make_score_response(8, 8),  # Both >= 7 -> passes
            _make_score_response(9, 9),  # Both >= 7 -> passes
        ]

        config = WeaponsConfig(granularity="act", min_novelty=7, min_intensity=7, filler_threshold=5)
        checker = WeaponsCheck(config=config, claude_client=mock_claude)

        report = _run(checker.check(SAMPLE_SCRIPT))

        assert len(report.rewrite_blocks) == 2
        assert all(b.needs_rewrite for b in report.rewrite_blocks)
        assert report.pass_rate == 0.5  # 2 out of 4 passed

    def test_parse_error_returns_neutral(self):
        mock_claude = AsyncMock()
        mock_claude.generate.return_value = "invalid json garbage"

        config = WeaponsConfig(granularity="act", min_novelty=7, min_intensity=7)
        checker = WeaponsCheck(config=config, claude_client=mock_claude)

        report = _run(checker.check(SAMPLE_SCRIPT))

        # Should not crash — neutral scores (5) mean needs_rewrite (5 < 7)
        assert len(report.blocks) == 4
        assert all(b.novelty == 5 for b in report.blocks)
        assert all(b.intensity == 5 for b in report.blocks)


class TestWeaponsReport:

    def test_report_to_dict(self):
        report = WeaponsReport(
            blocks=[
                ScoredBlock(text="test", label="Act 2", novelty=8, intensity=9),
                ScoredBlock(text="weak", label="Act 3", novelty=3, intensity=3,
                            is_filler=True, needs_rewrite=True),
            ],
            filler_blocks=[
                ScoredBlock(text="weak", label="Act 3", novelty=3, intensity=3,
                            is_filler=True, needs_rewrite=True),
            ],
            rewrite_blocks=[],
            pass_rate=0.5,
        )

        d = report.to_dict()
        assert d["total_blocks"] == 2
        assert d["filler_count"] == 1
        assert d["rewrite_count"] == 0
        assert d["pass_rate"] == 0.5
