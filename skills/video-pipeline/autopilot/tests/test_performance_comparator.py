# skills/video-pipeline/autopilot/tests/test_performance_comparator.py
"""Tests for performance comparator (us vs competitor)."""

import pytest
from autopilot.monitoring.performance_comparator import (
    PerformanceComparison,
    PerformanceComparator,
)


class TestPerformanceComparator:
    """Test suite for performance comparator."""

    @pytest.fixture
    def comparator(self):
        return PerformanceComparator()

    def test_estimate_expected_ctr_low_vph(self, comparator):
        """VPH 50 should return 3.0% expected CTR."""
        assert comparator.estimate_expected_ctr(50) == 3.0
        # Even lower VPH should also return 3.0%
        assert comparator.estimate_expected_ctr(25) == 3.0

    def test_estimate_expected_ctr_high_vph(self, comparator):
        """VPH 300+ should return 5.0% expected CTR."""
        assert comparator.estimate_expected_ctr(300) == 5.0
        # Even higher VPH should cap at 5.0%
        assert comparator.estimate_expected_ctr(500) == 5.0

    def test_estimate_expected_ctr_interpolation(self, comparator):
        """VPH 125 should interpolate correctly between 100 (3.5%) and 150 (4.0%)."""
        # VPH 125 is halfway between 100 and 150
        # Expected CTR should be halfway between 3.5% and 4.0% = 3.75%
        expected = comparator.estimate_expected_ctr(125)
        assert expected == pytest.approx(3.75, abs=0.01)

    def test_compare_outperformed(self, comparator):
        """CTR 5.0% vs expected 4.0% (VPH 150) should be outperformed."""
        result = comparator.compare(
            our_title="Our China Video",
            our_ctr=5.0,
            competitor_title="Competitor China Video",
            competitor_vph=150.0,
        )

        assert isinstance(result, PerformanceComparison)
        assert result.verdict == "outperformed"
        assert result.our_title == "Our China Video"
        assert result.our_ctr == 5.0
        assert result.competitor_title == "Competitor China Video"
        assert result.competitor_vph == 150.0
        assert "+" in result.delta_description

    def test_compare_underperformed(self, comparator):
        """CTR 3.0% vs expected 4.0% (VPH 150) should be underperformed."""
        result = comparator.compare(
            our_title="Our Economy Video",
            our_ctr=3.0,
            competitor_title="Competitor Economy Video",
            competitor_vph=150.0,
        )

        assert result.verdict == "underperformed"
        assert "-" in result.delta_description

    def test_compare_matched(self, comparator):
        """CTR 4.2% vs expected 4.0% (VPH 150) should be matched (within 0.5%)."""
        result = comparator.compare(
            our_title="Our NATO Video",
            our_ctr=4.2,
            competitor_title="Competitor NATO Video",
            competitor_vph=150.0,
        )

        assert result.verdict == "matched"
        assert "expected" in result.delta_description.lower()
