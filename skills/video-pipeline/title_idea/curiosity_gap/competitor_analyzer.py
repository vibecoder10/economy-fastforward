# skills/video-pipeline/curiosity_gap/competitor_analyzer.py
"""Two-phase competitor video analysis.

Phase 1: Quick title analysis (all >50 VPH videos) - text only, fast
Phase 2: Deep thumbnail analysis (top 20% per channel) - vision API, expensive

Uses VPH normalization per channel with cold start handling.
"""

import bisect
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from title_idea.curiosity_gap.structures import (
    CuriosityStructure,
    get_structure_prompt,
    validate_structure,
)


# VPH normalization constants
MIN_CHANNEL_SAMPLE = 5
COLD_START_VPH_THRESHOLD = 100
TOP_PERCENTILE = 80  # Top 20% = 80th percentile and above


@dataclass
class TitleAnalysis:
    """Result of Phase 1 title analysis."""
    structure: CuriosityStructure
    confidence: int  # 0-100
    gap_mechanism: str
    variables: Dict[str, str] = field(default_factory=dict)


@dataclass
class ThumbnailAnalysis:
    """Result of Phase 2 thumbnail analysis."""
    colors: List[str] = field(default_factory=list)
    composition: str = ""
    text_extracted: str = ""
    yin_yang_relationship: str = ""
    yin_yang_approach: str = ""  # "from_hook" or "from_gap"


def get_recent_channel_videos(channel_name: str, limit: int = 20) -> List[Dict]:
    """Fetch recent videos for a channel from Airtable.

    Args:
        channel_name: Channel name (e.g., "CaspianReport")
        limit: Max videos to fetch

    Returns:
        List of video dicts with 'vph' field
    """
    # Import here to avoid circular dependency
    from clients.airtable_client import AirtableClient

    client = AirtableClient()
    # Synchronous call - Airtable client is not async
    records = client.get_competitor_videos_by_channel(
        channel_name=channel_name,
        limit=limit,
    )
    return [{"vph": r.get("fields", {}).get("VPH", 0)} for r in records]


def should_deep_analyze_sync(video_vph: float, channel_name: str) -> bool:
    """Determine if video qualifies for deep thumbnail analysis (sync version).

    Uses VPH percentile ranking within channel. Falls back to
    absolute threshold for new channels with insufficient data.

    Args:
        video_vph: Views per hour for this video
        channel_name: Channel name (e.g., "CaspianReport")

    Returns:
        True if video is in top 20% of channel's recent videos
    """
    channel_videos = get_recent_channel_videos(channel_name, limit=20)

    if len(channel_videos) < MIN_CHANNEL_SAMPLE:
        # Cold start: use absolute threshold
        return video_vph >= COLD_START_VPH_THRESHOLD

    vphs = sorted([v["vph"] for v in channel_videos])

    # Use bisect for correct percentile with duplicates
    position = bisect.bisect_left(vphs, video_vph)
    percentile = (position / len(vphs)) * 100

    return percentile >= TOP_PERCENTILE


async def should_deep_analyze(video_vph: float, channel_name: str) -> bool:
    """Async wrapper for should_deep_analyze_sync.

    The Airtable call is synchronous, but we wrap it for consistent
    async interface in the analyzer.
    """
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        should_deep_analyze_sync,
        video_vph,
        channel_name,
    )


class CompetitorAnalyzer:
    """Analyze competitor titles and thumbnails."""

    def __init__(self):
        """Initialize analyzer with API clients."""
        # Lazy load to avoid import cycles
        self._anthropic_client = None
        self._gemini_client = None

    @property
    def anthropic_client(self):
        if self._anthropic_client is None:
            from clients.anthropic_client import AnthropicClient
            self._anthropic_client = AnthropicClient()
        return self._anthropic_client

    async def _call_claude_for_title(self, title: str) -> Dict:
        """Call Claude to analyze title structure.

        Args:
            title: Video title to analyze

        Returns:
            Dict with structure, confidence, gap_mechanism, variables
        """
        prompt = f"""Analyze this competitor YouTube title and identify which curiosity gap structure it uses.

TITLE: "{title}"

{get_structure_prompt()}

CALIBRATION EXAMPLES (use these to anchor your scoring):

hidden_flaw (95): "The $100B Mistake Saudi Arabia Is Hiding"
  -> Clear waste/mistake being concealed. Textbook.

hidden_flaw (70): "Why Would the U.S. Capture Iran's Kharg Island?"
  -> Targeting a vulnerability/weakness, but not explicitly about a "mistake"

asymmetric_dg (92): "Why the Navy Is Terrified of $500 Plastic"
  -> Small cheap thing vs massive military. Classic David/Goliath.

asymmetric_dg (55): "Why Can't the U.S. Take Over the Strait of Hormuz?"
  -> Implies inability of a superpower, but no "small beats big" framing. Weak fit.

paradigm_shift (85): "Why Didn't Russia and China Help Iran?"
  -> Challenges assumed alliance. Forces viewer to rethink what they know.

paradigm_shift (50): "How Is the U.S. Actually Reopening the Strait of Hormuz?"
  -> "Actually" adds mild reframing but it's mostly descriptive. Weak fit.

time_bomb (90): "The 40-Year Trap America Walked Into"
  -> Long-term setup with delayed trigger. Textbook.

illusion_control (88): "The Chokepoint That Controls Your Bank Account"
  -> Direct personal financial threat. "YOUR" stakes.

other (25): "Plane Crash with Black Hawk Helicopter Explained"
  -> Purely descriptive, no curiosity gap at all. Low confidence because there's nothing to classify.

SCORING RULES:
- "other" titles should score LOW confidence (20-40) because there's no structure to be confident about
- Descriptive titles ("X Explained", "How X Works", "X vs Y") are almost always "other"
- Don't default to paradigm_shift — it requires genuinely challenging an assumption, not just asking "why"
- A "Why" question is NOT automatically paradigm_shift. "Why can't X" could be asymmetric_dg, hidden_flaw, or other depending on the mechanism.

CONFIDENCE SCORING:
- 95-100: Textbook example. Could teach this structure with this title.
- 80-94: Strong fit. Structure is clearly the primary mechanism.
- 65-79: Moderate fit. Structure present but not dominant.
- 50-64: Weak fit. Another structure might fit better.
- 30-49: Poor fit. Forcing this structure onto the title.
- Below 30: Does not fit. Use "other".

Return JSON with:
- structure: one of the structure IDs above
- confidence: 0-100 how well the title fits the structure
- gap_mechanism: the specific question this title makes viewers ask
- variables: extracted components (amounts, entities, timeframes, etc.)

Return ONLY valid JSON, no markdown fences."""

        response = await self.anthropic_client.generate(
            prompt=prompt,
            max_tokens=500,
        )

        # Parse JSON with fallback
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            # Try to extract JSON from response
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                try:
                    return json.loads(json_match.group())
                except json.JSONDecodeError:
                    pass
            # Return default
            return {
                "structure": "other",
                "confidence": 30,
                "gap_mechanism": "unclear",
                "variables": {},
            }

    async def analyze_title(self, title: str) -> TitleAnalysis:
        """Phase 1: Analyze title structure (text only, cheap).

        Args:
            title: Video title to analyze

        Returns:
            TitleAnalysis with structure and confidence
        """
        result = await self._call_claude_for_title(title)

        structure = validate_structure(result.get("structure", "other"))

        return TitleAnalysis(
            structure=structure,
            confidence=int(result.get("confidence", 30)),
            gap_mechanism=result.get("gap_mechanism", ""),
            variables=result.get("variables", {}),
        )

    async def analyze_thumbnail(
        self,
        video_id: str,
        title: str,
        use_gemini: bool = True,
    ) -> Optional[ThumbnailAnalysis]:
        """Phase 2: Analyze thumbnail (vision API, expensive).

        Args:
            video_id: YouTube video ID
            title: Video title (for yin/yang comparison)
            use_gemini: Use Gemini Vision (default) or Claude Vision

        Returns:
            ThumbnailAnalysis or None if analysis fails
        """
        # Get thumbnail URL
        thumbnail_url = f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"

        if use_gemini:
            return await self._analyze_with_gemini(thumbnail_url, title)
        else:
            return await self._analyze_with_claude(thumbnail_url, title)

    async def _analyze_with_gemini(
        self,
        thumbnail_url: str,
        title: str,
    ) -> Optional[ThumbnailAnalysis]:
        """Analyze thumbnail using Gemini Vision.

        Args:
            thumbnail_url: URL of thumbnail image
            title: Video title for yin/yang comparison

        Returns:
            ThumbnailAnalysis or None
        """
        # Import lazily
        from clients.gemini_client import GeminiClient

        if self._gemini_client is None:
            self._gemini_client = GeminiClient()

        try:
            result = await self._gemini_client.analyze_competitor_thumbnail(
                thumbnail_url=thumbnail_url,
                title=title,
            )
            return ThumbnailAnalysis(
                colors=result.get("colors", []),
                composition=result.get("composition", ""),
                text_extracted=result.get("text_extracted", ""),
                yin_yang_relationship=result.get("yin_yang_relationship", ""),
                yin_yang_approach=result.get("yin_yang_approach", ""),
            )
        except Exception as e:
            print(f"Gemini thumbnail analysis failed: {e}")
            return None

    async def _analyze_with_claude(
        self,
        thumbnail_url: str,
        title: str,
    ) -> Optional[ThumbnailAnalysis]:
        """Analyze thumbnail using Claude Vision (fallback).

        Args:
            thumbnail_url: URL of thumbnail image
            title: Video title for yin/yang comparison

        Returns:
            ThumbnailAnalysis or None
        """
        # TODO: Implement Claude vision fallback in Phase 2
        return None

    async def analyze_video(
        self,
        video_id: str,
        title: str,
        vph: float,
        channel_name: str,
    ) -> Dict:
        """Full analysis: title (always) + thumbnail (if qualifies).

        Args:
            video_id: YouTube video ID
            title: Video title
            vph: Views per hour
            channel_name: Channel name (e.g., "CaspianReport")

        Returns:
            Dict with title_analysis and optional thumbnail_analysis
        """
        # Phase 1: Always analyze title
        title_analysis = await self.analyze_title(title)

        result = {
            "title_analysis": title_analysis,
            "thumbnail_analysis": None,
            "deep_analyzed": False,
        }

        # Phase 2: Thumbnail only if top 20%
        if await should_deep_analyze(vph, channel_name):
            thumbnail_analysis = await self.analyze_thumbnail(video_id, title)
            result["thumbnail_analysis"] = thumbnail_analysis
            result["deep_analyzed"] = True

        return result
