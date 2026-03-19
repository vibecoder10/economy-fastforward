# skills/video-pipeline/autopilot/monitoring/performance_comparator.py
"""Compare our performance vs competitor we modeled."""

from dataclasses import dataclass


@dataclass
class PerformanceComparison:
    """Comparison between our video and competitor."""
    our_title: str
    our_ctr: float
    competitor_title: str
    competitor_vph: float
    verdict: str  # "outperformed", "matched", "underperformed"
    delta_description: str


class PerformanceComparator:
    """Compare our CTR against competitor VPH."""

    # VPH to expected CTR mapping (rough heuristic)
    # High VPH suggests topic appeal, but doesn't guarantee our CTR
    VPH_TO_CTR_BASELINE = {
        50: 3.0,    # VPH 50 -> expect ~3% CTR
        100: 3.5,   # VPH 100 -> expect ~3.5% CTR
        150: 4.0,   # VPH 150 -> expect ~4% CTR
        200: 4.5,   # VPH 200 -> expect ~4.5% CTR
        300: 5.0,   # VPH 300+ -> expect ~5% CTR
    }

    def estimate_expected_ctr(self, competitor_vph: float) -> float:
        """Estimate expected CTR based on competitor VPH.

        Higher VPH suggests proven topic appeal, so we'd expect
        to capture some of that with good execution.

        Args:
            competitor_vph: Views per hour of the competitor video

        Returns:
            Expected CTR percentage (e.g., 4.0 for 4%)
        """
        if competitor_vph <= 50:
            return 3.0
        elif competitor_vph >= 300:
            return 5.0
        else:
            # Linear interpolation between breakpoints
            sorted_breakpoints = sorted(self.VPH_TO_CTR_BASELINE.items())
            for i, (vph, ctr) in enumerate(sorted_breakpoints):
                if competitor_vph <= vph:
                    if i == 0:
                        return ctr
                    prev_vph, prev_ctr = sorted_breakpoints[i - 1]
                    ratio = (competitor_vph - prev_vph) / (vph - prev_vph)
                    return prev_ctr + ratio * (ctr - prev_ctr)
            return 5.0

    def compare(
        self,
        our_title: str,
        our_ctr: float,
        competitor_title: str,
        competitor_vph: float,
    ) -> PerformanceComparison:
        """Compare our performance against competitor.

        Args:
            our_title: Our video title
            our_ctr: Our CTR percentage
            competitor_title: Competitor video we modeled
            competitor_vph: Competitor's VPH when we selected them

        Returns:
            PerformanceComparison with verdict
        """
        expected = self.estimate_expected_ctr(competitor_vph)
        delta = our_ctr - expected

        if delta >= 0.5:
            verdict = "outperformed"
            delta_desc = f"+{delta:.1f}% above expected ({expected:.1f}%)"
        elif delta <= -0.5:
            verdict = "underperformed"
            delta_desc = f"{delta:.1f}% below expected ({expected:.1f}%)"
        else:
            verdict = "matched"
            delta_desc = f"~{expected:.1f}% as expected"

        return PerformanceComparison(
            our_title=our_title,
            our_ctr=our_ctr,
            competitor_title=competitor_title,
            competitor_vph=competitor_vph,
            verdict=verdict,
            delta_description=delta_desc,
        )
