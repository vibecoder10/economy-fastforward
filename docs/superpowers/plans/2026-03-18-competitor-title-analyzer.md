# Competitor Title Analyzer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an analysis system that examines competitor video titles from the Competitor Videos table, identifies successful patterns (styles, themes, structures), and surfaces actionable insights for content creation.

**Architecture:** A new `osiris/title_analyzer.py` module that queries the Competitor Videos table, groups by VPH performance tiers, uses Claude to extract title patterns, and outputs structured pattern reports. Integrates with the existing `LearningsEngine` to inject patterns into generation prompts.

**Tech Stack:** Python, pyairtable, Claude API (Anthropic), existing Osiris infrastructure

---

## File Structure

| File | Responsibility |
|------|----------------|
| `osiris/title_analyzer.py` | Core analysis: fetch videos, group by performance, extract patterns via Claude, return structured insights |
| `osiris/__init__.py` | Add export for `TitleAnalyzer` |
| `pipeline_constants.py` | Add new fields for title pattern storage (if persisting to Airtable) |
| `clients/airtable_client.py` | Add `get_competitor_videos_with_metrics()` method |
| `tests/osiris/test_title_analyzer.py` | Unit tests for pattern extraction |

---

### Task 1: Add Airtable Method to Fetch Competitor Videos with Metrics

**Files:**
- Modify: `skills/video-pipeline/clients/airtable_client.py` (add after `batch_create_competitor_videos()` around line 708)
- Test: Manual REPL test

**Note:** `CompetitorVideoFields` is already imported in airtable_client.py from pipeline_constants.

- [ ] **Step 1: Write the failing test**

Create a simple test that verifies the method returns structured data:

```python
# Manual test - run in Python REPL
from clients.airtable_client import AirtableClient
client = AirtableClient()
videos = client.get_competitor_videos_with_metrics(min_vph=50)
assert isinstance(videos, list)
assert len(videos) > 0
assert "Title" in videos[0]
assert "VPH" in videos[0]
print(f"✓ Got {len(videos)} videos with metrics")
```

- [ ] **Step 2: Add the method to AirtableClient**

Add after `get_all_competitor_video_ids()` (around line 600):

```python
def get_competitor_videos_with_metrics(
    self,
    min_vph: float = 0,
    min_views: int = 0,
    limit: int = 500,
) -> list[dict]:
    """Get competitor videos with performance metrics for analysis.

    Args:
        min_vph: Minimum VPH filter (default 0 = all)
        min_views: Minimum view count filter (default 0 = all)
        limit: Max records to return (default 500)

    Returns:
        List of video dicts with fields: Title, VPH, Views, Hours Old,
        Published Date, Channel, URL
    """
    try:
        # Build formula for filtering
        conditions = []
        if min_vph > 0:
            conditions.append(f"{{VPH}} >= {min_vph}")
        if min_views > 0:
            conditions.append(f"{{Views}} >= {min_views}")

        formula = None
        if conditions:
            formula = "AND(" + ", ".join(conditions) + ")"

        records = self.competitor_videos_table.all(
            formula=formula,
            max_records=limit,
            sort=["-VPH"],  # Highest VPH first
            fields=[
                CompetitorVideoFields.TITLE,
                CompetitorVideoFields.VPH,
                CompetitorVideoFields.VIEWS,
                CompetitorVideoFields.HOURS_OLD,
                CompetitorVideoFields.PUBLISHED_DATE,
                CompetitorVideoFields.CHANNEL,
                CompetitorVideoFields.URL,
            ],
        )
        return [r["fields"] for r in records if r["fields"].get(CompetitorVideoFields.VPH)]
    except Exception as e:
        print(f"    ⚠️ Could not fetch competitor videos: {e}")
        return []
```

- [ ] **Step 3: Run manual test to verify**

```bash
cd skills/video-pipeline && python3 -c "
from clients.airtable_client import AirtableClient
client = AirtableClient()
videos = client.get_competitor_videos_with_metrics(min_vph=50)
print(f'Got {len(videos)} videos with VPH >= 50')
for v in videos[:3]:
    print(f\"  - {v.get('Title', 'N/A')[:50]}... | VPH: {v.get('VPH')}\")
"
```

- [ ] **Step 4: Commit**

```bash
git add skills/video-pipeline/clients/airtable_client.py
git commit -m "feat(osiris): add get_competitor_videos_with_metrics for title analysis

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

### Task 2: Create TitleAnalyzer Core Class

**Files:**
- Create: `skills/video-pipeline/osiris/title_analyzer.py`
- Modify: `skills/video-pipeline/osiris/__init__.py`

- [ ] **Step 1: Create the title_analyzer.py file with basic structure**

```python
"""
Osiris Title Analyzer - Extracts winning patterns from competitor titles.

Analyzes the Competitor Videos table to identify:
- Title structures that correlate with high VPH
- Common themes in top performers
- Stylistic patterns (caps, numbers, questions, etc.)
- Channel-specific patterns

Usage:
    python -m osiris.title_analyzer
    python -m osiris.title_analyzer --dry-run --min-vph 100

Integrates with LearningsEngine to inject patterns into generation prompts.
"""

import asyncio
import json
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


@dataclass
class TitlePattern:
    """A detected title pattern with performance metrics."""
    pattern_name: str
    description: str
    example_titles: list[str]
    avg_vph: float
    count: int
    confidence: float  # 0-100 based on sample size and consistency


@dataclass
class TitleAnalysisResult:
    """Complete analysis result."""
    top_patterns: list[TitlePattern]
    theme_clusters: dict[str, list[str]]  # theme -> example titles
    structural_insights: list[str]
    channel_breakdowns: dict[str, dict]  # channel -> {avg_vph, top_patterns}
    total_videos_analyzed: int
    vph_threshold_used: float


class TitleAnalyzer:
    """Analyzes competitor titles to extract winning patterns.

    Groups videos by VPH performance tier, then uses Claude to identify
    what patterns distinguish top performers from average performers.

    Usage:
        analyzer = TitleAnalyzer(airtable_client, anthropic_client)
        result = await analyzer.analyze()
        print(result.top_patterns)
    """

    # VPH tiers for comparison
    VPH_TIER_TOP = 200     # Top performers
    VPH_TIER_GOOD = 100    # Good performers
    VPH_TIER_AVERAGE = 50  # Average performers

    def __init__(
        self,
        airtable_client,
        anthropic_client,
        slack_client=None,
    ):
        """Initialize the title analyzer.

        Args:
            airtable_client: AirtableClient instance
            anthropic_client: AnthropicClient for pattern extraction
            slack_client: Optional SlackClient for notifications
        """
        self.airtable = airtable_client
        self.anthropic = anthropic_client
        self.slack = slack_client

    async def analyze(
        self,
        min_vph: float = 0,
        limit: int = 500,
        dry_run: bool = False,
    ) -> TitleAnalysisResult:
        """Run full title pattern analysis.

        Args:
            min_vph: Minimum VPH to include (0 = all with valid VPH)
            limit: Max videos to analyze
            dry_run: If True, skip persistence and just return results

        Returns:
            TitleAnalysisResult with patterns, themes, and insights
        """
        logger.info("Fetching competitor videos for analysis...")

        # Step 1: Fetch videos with metrics
        videos = self.airtable.get_competitor_videos_with_metrics(
            min_vph=min_vph,
            limit=limit,
        )

        if not videos:
            logger.warning("No videos found for analysis")
            return TitleAnalysisResult(
                top_patterns=[],
                theme_clusters={},
                structural_insights=[],
                channel_breakdowns={},
                total_videos_analyzed=0,
                vph_threshold_used=min_vph,
            )

        logger.info(f"Analyzing {len(videos)} competitor videos...")

        # Step 2: Group by performance tier
        tiers = self._group_by_vph_tier(videos)
        logger.info(f"  Top tier (VPH>{self.VPH_TIER_TOP}): {len(tiers['top'])} videos")
        logger.info(f"  Good tier (VPH>{self.VPH_TIER_GOOD}): {len(tiers['good'])} videos")
        logger.info(f"  Average tier (VPH>{self.VPH_TIER_AVERAGE}): {len(tiers['average'])} videos")

        # Step 3: Extract structural patterns (fast, no API call)
        structural_patterns = self._extract_structural_patterns(videos)

        # Step 4: Extract semantic patterns via Claude
        semantic_patterns = await self._extract_semantic_patterns(tiers)

        # Step 5: Build channel breakdowns
        channel_breakdowns = self._build_channel_breakdowns(videos)

        # Step 6: Combine into result
        result = TitleAnalysisResult(
            top_patterns=semantic_patterns,
            theme_clusters=self._extract_theme_clusters(tiers["top"]),
            structural_insights=structural_patterns,
            channel_breakdowns=channel_breakdowns,
            total_videos_analyzed=len(videos),
            vph_threshold_used=min_vph,
        )

        # Step 7: Print summary
        self._print_summary(result)

        return result

    def _group_by_vph_tier(self, videos: list[dict]) -> dict[str, list[dict]]:
        """Group videos into performance tiers."""
        tiers = {
            "top": [],      # VPH > 200
            "good": [],     # 100 < VPH <= 200
            "average": [],  # 50 < VPH <= 100
            "below": [],    # VPH <= 50
        }

        for video in videos:
            vph = video.get("VPH", 0)
            if vph > self.VPH_TIER_TOP:
                tiers["top"].append(video)
            elif vph > self.VPH_TIER_GOOD:
                tiers["good"].append(video)
            elif vph > self.VPH_TIER_AVERAGE:
                tiers["average"].append(video)
            else:
                tiers["below"].append(video)

        return tiers

    def _extract_structural_patterns(self, videos: list[dict]) -> list[str]:
        """Extract structural title patterns (no API call needed).

        Detects:
        - Question marks
        - ALL CAPS words
        - Numbers/statistics
        - Year mentions
        - Colon structure
        - Length distributions
        """
        patterns = defaultdict(lambda: {"count": 0, "vph_sum": 0})

        for video in videos:
            title = video.get("Title", "")
            vph = video.get("VPH", 0)

            # Question format
            if "?" in title:
                patterns["question"]["count"] += 1
                patterns["question"]["vph_sum"] += vph

            # ALL CAPS words (4+ chars)
            if re.search(r'\b[A-Z]{4,}\b', title):
                patterns["caps_emphasis"]["count"] += 1
                patterns["caps_emphasis"]["vph_sum"] += vph

            # Numbers/statistics
            if re.search(r'\$[\d,]+|\d+%|\d{1,3}(?:,\d{3})+', title):
                patterns["numbers_stats"]["count"] += 1
                patterns["numbers_stats"]["vph_sum"] += vph

            # Year mentions (2024-2030)
            if re.search(r'\b20[2-3]\d\b', title):
                patterns["year_mention"]["count"] += 1
                patterns["year_mention"]["vph_sum"] += vph

            # Colon structure
            if ":" in title:
                patterns["colon_structure"]["count"] += 1
                patterns["colon_structure"]["vph_sum"] += vph

            # How/Why/What questions
            if re.match(r'^(How|Why|What|When|Where|Who)\b', title, re.IGNORECASE):
                patterns["how_why_what"]["count"] += 1
                patterns["how_why_what"]["vph_sum"] += vph

        # Format insights
        insights = []
        total = len(videos)

        for pattern_name, data in sorted(
            patterns.items(),
            key=lambda x: x[1]["vph_sum"] / max(x[1]["count"], 1),
            reverse=True
        ):
            count = data["count"]
            if count >= 5:  # Minimum sample size
                avg_vph = data["vph_sum"] / count
                pct = (count / total) * 100
                insights.append(
                    f"{pattern_name.replace('_', ' ').title()}: "
                    f"{count} videos ({pct:.0f}%), avg VPH {avg_vph:.0f}"
                )

        return insights

    async def _extract_semantic_patterns(
        self,
        tiers: dict[str, list[dict]]
    ) -> list[TitlePattern]:
        """Use Claude to extract semantic patterns from top performers."""

        top_titles = [v.get("Title", "") for v in tiers["top"][:30]]
        good_titles = [v.get("Title", "") for v in tiers["good"][:30]]
        average_titles = [v.get("Title", "") for v in tiers["average"][:20]]

        if len(top_titles) < 5:
            logger.warning("Not enough top performers for pattern extraction")
            return []

        system_prompt = """You are a YouTube title analyst specializing in news/documentary content.

Analyze the provided title lists grouped by performance tier. Identify patterns that distinguish TOP performers from AVERAGE performers.

Focus on:
1. **Structural patterns**: Title length, punctuation, capitalization
2. **Emotional hooks**: Urgency, fear, curiosity, revelation
3. **Topic framing**: How subjects are positioned (victim vs aggressor, hidden vs exposed)
4. **Specificity**: Use of names, dates, numbers, locations
5. **Promise type**: What the viewer expects to learn

Return JSON with this exact structure:
{
  "patterns": [
    {
      "pattern_name": "short descriptive name",
      "description": "What makes this pattern effective",
      "distinguishing_factor": "Why top performers use this more than average",
      "example_titles": ["title 1", "title 2"],
      "confidence": 85
    }
  ],
  "anti_patterns": [
    {
      "pattern_name": "pattern to avoid",
      "description": "Why this correlates with lower performance"
    }
  ]
}

Return ONLY valid JSON."""

        user_prompt = f"""Analyze these competitor video titles by performance tier:

## TOP PERFORMERS (VPH > 200)
{chr(10).join(f'- {t}' for t in top_titles)}

## GOOD PERFORMERS (VPH 100-200)
{chr(10).join(f'- {t}' for t in good_titles)}

## AVERAGE PERFORMERS (VPH 50-100)
{chr(10).join(f'- {t}' for t in average_titles)}

Identify 3-5 patterns that distinguish top performers. What do they do differently?"""

        try:
            from pipeline_constants import Models
            response = await self.anthropic.generate(
                prompt=user_prompt,
                system_prompt=system_prompt,
                model=Models.CLAUDE_SONNET,
            )

            # Parse JSON response
            clean = response.replace("```json", "").replace("```", "").strip()
            data = json.loads(clean)

            patterns = []
            for p in data.get("patterns", []):
                # Calculate avg_vph from example titles
                example_vphs = []
                for example in p.get("example_titles", []):
                    for v in tiers["top"] + tiers["good"]:
                        if v.get("Title") == example:
                            example_vphs.append(v.get("VPH", 0))
                            break

                patterns.append(TitlePattern(
                    pattern_name=p.get("pattern_name", "Unknown"),
                    description=p.get("description", ""),
                    example_titles=p.get("example_titles", [])[:3],
                    avg_vph=sum(example_vphs) / len(example_vphs) if example_vphs else 0,
                    count=len(p.get("example_titles", [])),
                    confidence=p.get("confidence", 50),
                ))

            return patterns

        except Exception as e:
            logger.error(f"Failed to extract semantic patterns: {e}")
            return []

    def _extract_theme_clusters(self, top_videos: list[dict]) -> dict[str, list[str]]:
        """Group top titles by apparent theme/topic."""
        themes = defaultdict(list)

        keywords = {
            "geopolitics": ["war", "military", "nato", "russia", "china", "iran", "israel", "invasion", "attack"],
            "economy": ["economy", "dollar", "debt", "inflation", "recession", "gdp", "trade", "tariff"],
            "tech": ["ai", "tech", "robot", "automation", "digital", "cyber"],
            "power": ["power", "empire", "collapse", "rise", "fall", "control", "secret"],
        }

        for video in top_videos:
            title = video.get("Title", "").lower()
            for theme, words in keywords.items():
                if any(word in title for word in words):
                    themes[theme].append(video.get("Title", ""))
                    break
            else:
                themes["other"].append(video.get("Title", ""))

        return dict(themes)

    def _build_channel_breakdowns(self, videos: list[dict]) -> dict[str, dict]:
        """Build per-channel performance breakdowns."""
        channels = defaultdict(lambda: {"videos": [], "vph_sum": 0})

        for video in videos:
            channel = video.get("Channel", "Unknown")
            vph = video.get("VPH", 0)
            channels[channel]["videos"].append(video.get("Title", ""))
            channels[channel]["vph_sum"] += vph

        result = {}
        for channel, data in channels.items():
            count = len(data["videos"])
            if count >= 3:  # Min sample
                result[channel] = {
                    "count": count,
                    "avg_vph": data["vph_sum"] / count,
                    "top_title": data["videos"][0] if data["videos"] else "",
                }

        return dict(sorted(
            result.items(),
            key=lambda x: x[1]["avg_vph"],
            reverse=True
        ))

    def _print_summary(self, result: TitleAnalysisResult) -> None:
        """Print formatted summary to console."""
        print("\n" + "=" * 60)
        print("COMPETITOR TITLE ANALYSIS")
        print("=" * 60)
        print(f"Videos analyzed: {result.total_videos_analyzed}")
        print(f"VPH threshold: {result.vph_threshold_used}")

        if result.structural_insights:
            print("\n## Structural Patterns")
            for insight in result.structural_insights[:8]:
                print(f"  • {insight}")

        if result.top_patterns:
            print("\n## Semantic Patterns (from top performers)")
            for p in result.top_patterns:
                print(f"\n  {p.pattern_name} (confidence: {p.confidence}%)")
                print(f"    {p.description}")
                if p.example_titles:
                    print(f"    Example: \"{p.example_titles[0][:60]}...\"")

        if result.theme_clusters:
            print("\n## Theme Distribution")
            for theme, titles in result.theme_clusters.items():
                print(f"  • {theme.title()}: {len(titles)} videos")

        if result.channel_breakdowns:
            print("\n## Top Channels by Avg VPH")
            for channel, data in list(result.channel_breakdowns.items())[:5]:
                print(f"  • {channel}: {data['avg_vph']:.0f} avg VPH ({data['count']} videos)")

        print("\n" + "=" * 60)


async def run_title_analysis(
    airtable_client=None,
    anthropic_client=None,
    slack_client=None,
    min_vph: float = 0,
    limit: int = 500,
    dry_run: bool = False,
) -> TitleAnalysisResult:
    """Convenience function to run title analysis.

    Args:
        airtable_client: Optional AirtableClient (created if None)
        anthropic_client: Optional AnthropicClient (created if None)
        slack_client: Optional SlackClient (created if None)
        min_vph: Minimum VPH filter
        limit: Max videos to analyze
        dry_run: If True, skip persistence

    Returns:
        TitleAnalysisResult with patterns and insights
    """
    if airtable_client is None:
        from clients.airtable_client import AirtableClient
        airtable_client = AirtableClient()

    if anthropic_client is None:
        from clients.anthropic_client import AnthropicClient
        anthropic_client = AnthropicClient()

    if slack_client is None and not dry_run:
        try:
            from clients.slack_client import SlackClient
            slack_client = SlackClient()
        except Exception:
            slack_client = None

    analyzer = TitleAnalyzer(
        airtable_client=airtable_client,
        anthropic_client=anthropic_client,
        slack_client=slack_client,
    )

    return await analyzer.analyze(
        min_vph=min_vph,
        limit=limit,
        dry_run=dry_run,
    )


async def _cli_main():
    """CLI entry point for `python -m osiris.title_analyzer`."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Osiris Title Analyzer - Extract winning patterns from competitor titles"
    )
    parser.add_argument(
        "--min-vph",
        type=float,
        default=0,
        help="Minimum VPH to include (default: 0 = all)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=500,
        help="Max videos to analyze (default: 500)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run analysis without persisting results",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    print("=" * 60)
    print("OSIRIS TITLE ANALYZER")
    print("=" * 60)
    print(f"  Date: {date.today().isoformat()}")
    print(f"  Min VPH: {args.min_vph}")
    print(f"  Limit: {args.limit}")
    print(f"  Dry run: {args.dry_run}")
    print("=" * 60)

    result = await run_title_analysis(
        min_vph=args.min_vph,
        limit=args.limit,
        dry_run=args.dry_run,
    )

    print(f"\nAnalysis complete. Found {len(result.top_patterns)} semantic patterns.")


if __name__ == "__main__":
    asyncio.run(_cli_main())
```

- [ ] **Step 2: Run to verify basic structure**

```bash
cd skills/video-pipeline && python3 -c "from osiris.title_analyzer import TitleAnalyzer; print('✓ Import successful')"
```

- [ ] **Step 3: Update osiris/__init__.py**

Add exports at the end of the file (after `__version__`):

```python
from .title_analyzer import TitleAnalyzer, run_title_analysis

__all__ = ["TitleAnalyzer", "run_title_analysis"]
```

- [ ] **Step 4: Commit**

```bash
git add skills/video-pipeline/osiris/title_analyzer.py skills/video-pipeline/osiris/__init__.py
git commit -m "feat(osiris): add TitleAnalyzer for competitor title pattern extraction

Analyzes competitor videos by VPH tier, extracts structural patterns
(questions, caps, numbers) and semantic patterns via Claude.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

### Task 3: Add Unit Tests for Pattern Extraction

**Files:**
- Create: `skills/video-pipeline/tests/osiris/__init__.py`
- Create: `skills/video-pipeline/tests/osiris/test_title_analyzer.py`

- [ ] **Step 0: Create test directory**

```bash
mkdir -p skills/video-pipeline/tests/osiris
touch skills/video-pipeline/tests/osiris/__init__.py
```

- [ ] **Step 1: Create test file**

```python
"""Tests for osiris.title_analyzer module."""

import pytest
from unittest.mock import MagicMock, AsyncMock

from osiris.title_analyzer import TitleAnalyzer, TitlePattern


class TestGroupByVphTier:
    """Tests for _group_by_vph_tier method."""

    def test_groups_videos_correctly(self):
        """Videos should be grouped into correct VPH tiers."""
        mock_airtable = MagicMock()
        mock_anthropic = MagicMock()
        analyzer = TitleAnalyzer(mock_airtable, mock_anthropic)

        videos = [
            {"Title": "Top video", "VPH": 250},
            {"Title": "Good video", "VPH": 150},
            {"Title": "Average video", "VPH": 75},
            {"Title": "Below video", "VPH": 30},
        ]

        tiers = analyzer._group_by_vph_tier(videos)

        assert len(tiers["top"]) == 1
        assert len(tiers["good"]) == 1
        assert len(tiers["average"]) == 1
        assert len(tiers["below"]) == 1
        assert tiers["top"][0]["Title"] == "Top video"

    def test_handles_empty_list(self):
        """Should handle empty video list."""
        mock_airtable = MagicMock()
        mock_anthropic = MagicMock()
        analyzer = TitleAnalyzer(mock_airtable, mock_anthropic)

        tiers = analyzer._group_by_vph_tier([])

        assert tiers["top"] == []
        assert tiers["good"] == []


class TestExtractStructuralPatterns:
    """Tests for _extract_structural_patterns method."""

    def test_detects_question_format(self):
        """Should detect question mark titles."""
        mock_airtable = MagicMock()
        mock_anthropic = MagicMock()
        analyzer = TitleAnalyzer(mock_airtable, mock_anthropic)

        videos = [
            {"Title": "Why Did Russia Invade?", "VPH": 100},
            {"Title": "What Happens Next?", "VPH": 150},
            {"Title": "No question here", "VPH": 80},
        ] * 3  # Need 5+ for pattern detection

        insights = analyzer._extract_structural_patterns(videos)

        question_insights = [i for i in insights if "Question" in i]
        assert len(question_insights) >= 1

    def test_detects_caps_emphasis(self):
        """Should detect ALL CAPS words."""
        mock_airtable = MagicMock()
        mock_anthropic = MagicMock()
        analyzer = TitleAnalyzer(mock_airtable, mock_anthropic)

        videos = [
            {"Title": "Russia EXPOSED: The Truth", "VPH": 200},
            {"Title": "China's COLLAPSE Begins", "VPH": 180},
        ] * 3

        insights = analyzer._extract_structural_patterns(videos)

        caps_insights = [i for i in insights if "Caps" in i]
        assert len(caps_insights) >= 1

    def test_detects_numbers(self):
        """Should detect numbers/statistics."""
        mock_airtable = MagicMock()
        mock_anthropic = MagicMock()
        analyzer = TitleAnalyzer(mock_airtable, mock_anthropic)

        videos = [
            {"Title": "The $50 Billion Problem", "VPH": 200},
            {"Title": "Why 80% of Banks Will Fail", "VPH": 180},
            {"Title": "2025: The Year Everything Changes", "VPH": 150},
        ] * 2

        insights = analyzer._extract_structural_patterns(videos)

        number_insights = [i for i in insights if "Numbers" in i or "Year" in i]
        assert len(number_insights) >= 1


class TestExtractThemeClusters:
    """Tests for _extract_theme_clusters method."""

    def test_clusters_by_keyword(self):
        """Should cluster videos by theme keywords."""
        mock_airtable = MagicMock()
        mock_anthropic = MagicMock()
        analyzer = TitleAnalyzer(mock_airtable, mock_anthropic)

        videos = [
            {"Title": "Russia War Escalates", "VPH": 200},
            {"Title": "NATO Military Response", "VPH": 180},
            {"Title": "Dollar Collapse Coming", "VPH": 150},
        ]

        clusters = analyzer._extract_theme_clusters(videos)

        assert "geopolitics" in clusters
        assert "economy" in clusters
        assert len(clusters["geopolitics"]) == 2
        assert len(clusters["economy"]) == 1


class TestBuildChannelBreakdowns:
    """Tests for _build_channel_breakdowns method."""

    def test_calculates_channel_averages(self):
        """Should calculate per-channel VPH averages."""
        mock_airtable = MagicMock()
        mock_anthropic = MagicMock()
        analyzer = TitleAnalyzer(mock_airtable, mock_anthropic)

        videos = [
            {"Title": "Video 1", "Channel": "CaspianReport", "VPH": 200},
            {"Title": "Video 2", "Channel": "CaspianReport", "VPH": 300},
            {"Title": "Video 3", "Channel": "CaspianReport", "VPH": 250},
            {"Title": "Video 4", "Channel": "AiTelly", "VPH": 150},
            {"Title": "Video 5", "Channel": "AiTelly", "VPH": 150},
            {"Title": "Video 6", "Channel": "AiTelly", "VPH": 150},
        ]

        breakdowns = analyzer._build_channel_breakdowns(videos)

        assert "CaspianReport" in breakdowns
        assert breakdowns["CaspianReport"]["avg_vph"] == 250
        assert breakdowns["CaspianReport"]["count"] == 3
```

- [ ] **Step 2: Run tests**

```bash
cd skills/video-pipeline && python -m pytest tests/osiris/test_title_analyzer.py -v
```

- [ ] **Step 3: Fix any failures, then commit**

```bash
git add skills/video-pipeline/tests/osiris/
git commit -m "test(osiris): add unit tests for TitleAnalyzer

Tests cover VPH tier grouping, structural pattern detection,
theme clustering, and channel breakdowns.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

### Task 4: Integration Test - Run Full Analysis

**Files:**
- No new files (manual integration test)

- [ ] **Step 1: Run the analyzer with dry-run**

```bash
cd skills/video-pipeline && python -m osiris.title_analyzer --dry-run --verbose
```

- [ ] **Step 2: Verify output shows patterns**

Expected output should include:
- Number of videos analyzed
- Structural patterns with counts
- Semantic patterns from Claude
- Theme distribution
- Top channels by VPH

- [ ] **Step 3: Run without dry-run if everything looks good**

```bash
cd skills/video-pipeline && python -m osiris.title_analyzer --min-vph 50
```

- [ ] **Step 4: Document in lessons.md if any issues found**

---

### Task 5: Add Slack Command for Title Analysis

**Files:**
- Modify: `skills/video-pipeline/pipeline_control.py`

**Note:** This codebase uses the `@app.message()` decorator pattern from slack-bolt, NOT a class-based dispatch dict. Find a similar handler (like `handle_analyze`) and add nearby.

- [ ] **Step 1: Find the command handler section**

Search for `@app.message` patterns in `pipeline_control.py`. Add the new handler after similar analysis commands.

- [ ] **Step 2: Add the title analysis command handler**

Add near other analysis handlers (search for "analyze" in the file):

```python
@app.message(re.compile(r"analyze[\-\s]?titles?(?:\s+\d+)?", re.IGNORECASE))
async def handle_analyze_titles(message, say):
    """Analyze competitor title patterns from Osiris data."""
    global current_process, current_task_name
    if current_process or current_task_name:
        await say(f":x: Already running `{current_task_name}`. Use `stop` to cancel it first.")
        return

    # Parse optional min_vph from message text
    text = message.get("text", "").strip()
    min_vph = 50  # default
    match = re.search(r"(\d+)", text.replace("analyze", "").replace("titles", "").replace("-", ""))
    if match:
        min_vph = float(match.group(1))

    await say(f":bar_chart: Running title pattern analysis (min VPH: {min_vph})...")

    try:
        from osiris.title_analyzer import run_title_analysis
        result = await run_title_analysis(min_vph=min_vph, limit=300)

        # Format response
        msg = "*Title Analysis Complete*\n"
        msg += f"Videos analyzed: {result.total_videos_analyzed}\n\n"

        if result.structural_insights:
            msg += "*Structural Patterns:*\n"
            for insight in result.structural_insights[:5]:
                msg += f"• {insight}\n"

        if result.top_patterns:
            msg += "\n*Semantic Patterns:*\n"
            for p in result.top_patterns[:3]:
                msg += f"• *{p.pattern_name}*: {p.description[:100]}...\n"

        await say(msg)

    except Exception as e:
        log.exception("Title analysis failed")
        await say(f":x: Title analysis failed: {e}")
```

- [ ] **Step 3: Test via Slack**

Send `analyze titles` or `analyze-titles 100` in Slack and verify response.

- [ ] **Step 4: Commit**

```bash
git add skills/video-pipeline/pipeline_control.py
git commit -m "feat(slack): add analyze-titles command for competitor analysis

Runs Osiris title pattern extraction and returns top insights.
Uses @app.message decorator pattern consistent with existing handlers.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

### Task 6: Wire Patterns into LearningsEngine

**Files:**
- Modify: `skills/video-pipeline/osiris/learnings_engine.py`

- [ ] **Step 1: Add method to get competitor title patterns**

Add to `LearningsEngine` class:

```python
def get_competitor_title_patterns(self) -> str:
    """Get formatted competitor title patterns for ideation prompts.

    Unlike channel-specific learnings (from your videos), these are
    patterns observed in high-performing competitor videos.

    Returns formatted text for prompt injection.
    """
    # This would be populated by periodic title analysis runs
    # For now, return cached results if available

    # Future: Query a new "Competitor Patterns" table
    # that gets populated by scheduled title_analyzer runs

    return ""  # Placeholder for Task 7 implementation
```

- [ ] **Step 2: Commit placeholder**

```bash
git add skills/video-pipeline/osiris/learnings_engine.py
git commit -m "feat(osiris): add placeholder for competitor pattern injection

Prepares LearningsEngine for competitor title pattern integration.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Summary

After completing all tasks, you will have:

1. **Airtable method** to query competitor videos with metrics
2. **TitleAnalyzer class** that:
   - Groups videos by VPH performance tier
   - Extracts structural patterns (questions, caps, numbers, etc.)
   - Uses Claude to identify semantic patterns distinguishing top performers
   - Clusters by theme and channel
3. **Unit tests** for core functionality
4. **CLI interface**: `python -m osiris.title_analyzer --min-vph 50`
5. **Slack command**: `!analyze-titles` for on-demand analysis
6. **LearningsEngine hook** for future prompt injection

## Future Enhancements (Out of Scope)

- Persist patterns to a new Airtable table for historical tracking
- Schedule daily/weekly analysis via cron
- Inject competitor patterns into idea generation prompts
- A/B test title suggestions based on detected patterns

