"""Create original ideas from competitor video modeling."""

import json
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

from autopilot.analysis.theme_extractor import ThemeAnalysis
from autopilot.core.confidence_scorer import IdeaCandidate

logger = logging.getLogger(__name__)


@dataclass
class ModeledIdea:
    """A modeled idea ready for Airtable."""
    viral_title: str
    hook_script: str = ""
    thumbnail_visual: str = ""
    thumbnail_style_override: str = ""
    narrative_logic: Dict[str, str] = field(default_factory=dict)
    writer_guidance: str = ""
    modeled_from: str = ""
    formula_used: str = ""
    variables_swapped: List[str] = field(default_factory=list)
    theme_analysis: Optional[ThemeAnalysis] = None
    confidence_score: float = 0.0


# Channel niche variables for Economy FastForward
CHANNEL_NICHE_VARIABLES = {
    "topics": [
        "dollar collapse", "Federal Reserve", "inflation", "China economy",
        "Russia sanctions", "oil crisis", "trade war", "recession",
        "gold standard", "BRICS", "currency war", "national debt",
        "housing crash", "bank failures", "crypto regulation"
    ],
    "entities": [
        "China", "Russia", "Iran", "Saudi Arabia", "BRICS", "NATO",
        "Federal Reserve", "IMF", "World Bank", "OPEC", "Wall Street"
    ],
    "mechanisms": [
        "sanctions", "tariffs", "currency manipulation", "debt trap",
        "monetary policy", "quantitative easing", "interest rates"
    ],
    "consequences": [
        "collapse", "crash", "crisis", "war", "default", "recession",
        "hyperinflation", "devaluation"
    ],
    "timeframes": [
        "2025", "2026", "next year", "coming months", "imminent"
    ]
}


class IdeaCreator:
    """Create original ideas by modeling competitor videos."""

    def __init__(
        self,
        airtable_client=None,
        anthropic_client=None,
        thumbnail_analyzer=None,
        thumbnail_adapter=None,
    ):
        """Initialize idea creator.

        Args:
            airtable_client: AirtableClient instance
            anthropic_client: Anthropic client for API calls
            thumbnail_analyzer: ThumbnailAnalyzer instance
            thumbnail_adapter: ThumbnailAdapter instance
        """
        self.airtable = airtable_client
        self.anthropic = anthropic_client
        self.thumbnail_analyzer = thumbnail_analyzer
        self.thumbnail_adapter = thumbnail_adapter

    def _get_airtable(self):
        """Get or create Airtable client."""
        if self.airtable is None:
            from clients.airtable_client import AirtableClient
            self.airtable = AirtableClient()
        return self.airtable

    def _get_anthropic(self):
        """Get or create Anthropic client."""
        if self.anthropic is None:
            import anthropic
            self.anthropic = anthropic.AsyncAnthropic()
        return self.anthropic

    def _get_thumbnail_analyzer(self):
        """Get or create ThumbnailAnalyzer."""
        if self.thumbnail_analyzer is None:
            from autopilot.analysis.thumbnail_analyzer import ThumbnailAnalyzer
            self.thumbnail_analyzer = ThumbnailAnalyzer()
        return self.thumbnail_analyzer

    def _get_thumbnail_adapter(self):
        """Get or create ThumbnailAdapter."""
        if self.thumbnail_adapter is None:
            from autopilot.analysis.thumbnail_adapter import ThumbnailAdapter
            from autopilot.learning.pattern_library import PatternLibrary
            self.thumbnail_adapter = ThumbnailAdapter(PatternLibrary())
        return self.thumbnail_adapter

    async def generate_modeled_ideas(
        self,
        competitor_title: str,
        theme_analysis: ThemeAnalysis,
        num_ideas: int = 3,
    ) -> List[ModeledIdea]:
        """Generate original ideas by modeling a competitor's title formula.

        Args:
            competitor_title: The competitor video title to model
            theme_analysis: Extracted theme analysis from the title
            num_ideas: Number of ideas to generate

        Returns:
            List of ModeledIdea objects
        """
        anthropic = self._get_anthropic()

        # Build the generation prompt using theme analysis
        prompt = self._build_generation_prompt(
            competitor_title=competitor_title,
            theme_analysis=theme_analysis,
            num_ideas=num_ideas,
        )

        try:
            response = await anthropic.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}]
            )

            content = response.content[0].text.strip()
            ideas_data = self._parse_ideas_response(content)

            modeled_ideas = []
            for idea_data in ideas_data:
                idea = ModeledIdea(
                    viral_title=idea_data.get("viral_title", ""),
                    hook_script=idea_data.get("hook_script", ""),
                    thumbnail_visual=idea_data.get("thumbnail_visual", ""),
                    narrative_logic={
                        "past_context": idea_data.get("past_context", ""),
                        "present_parallel": idea_data.get("present_parallel", ""),
                        "future_prediction": idea_data.get("future_prediction", ""),
                    },
                    writer_guidance=idea_data.get("writer_guidance", ""),
                    modeled_from=f"Modeled from: {competitor_title}\nFormula: {theme_analysis.title_formula}\nAngle: {theme_analysis.angle_type}",
                    formula_used=theme_analysis.title_formula,
                    variables_swapped=idea_data.get("variables_swapped", []),
                    theme_analysis=theme_analysis,
                )
                modeled_ideas.append(idea)

            return modeled_ideas

        except Exception as e:
            logger.error(f"Failed to generate modeled ideas: {e}")
            return []

    def _build_generation_prompt(
        self,
        competitor_title: str,
        theme_analysis: ThemeAnalysis,
        num_ideas: int,
    ) -> str:
        """Build the prompt for generating modeled ideas."""

        return f"""You are a YouTube strategist for "Economy FastForward" — a finance/economics channel.

A competitor video is performing well:
TITLE: "{competitor_title}"

We've analyzed this title:
- FORMULA: {theme_analysis.title_formula}
- VARIABLES: {json.dumps(theme_analysis.formula_variables)}
- ANGLE TYPE: {theme_analysis.angle_type}
- EMOTIONAL HOOKS: {theme_analysis.emotional_hooks}
- TOPIC CATEGORY: {theme_analysis.topic_category}

Generate {num_ideas} ORIGINAL video ideas that MODEL this title's appeal WITHOUT COPYING it.

KEY RULES:
1. Use the SAME FORMULA structure but with DIFFERENT topics
2. Maintain the SAME ANGLE TYPE ({theme_analysis.angle_type})
3. Use the SAME EMOTIONAL HOOKS ({theme_analysis.emotional_hooks})
4. Topics must be relevant to our channel: economics, finance, geopolitics affecting economy
5. NO synonym swaps — the topic must be genuinely different

Example of MODELING (not copying):
- Original: "How the US Engineered the Iran War"
- GOOD: "How China Engineered the Taiwan Crisis" (same formula, different topic)
- BAD: "How America Planned the Iran Conflict" (synonym swap = copying)

For each idea, provide:
1. viral_title: Your generated title using the formula
2. hook_script: First 15 seconds of narration (compelling hook)
3. thumbnail_visual: Visual concept for thumbnail
4. past_context: Historical context for the story
5. present_parallel: What's happening RIGHT NOW
6. future_prediction: What this means for the future
7. writer_guidance: Tone and approach for the scriptwriter
8. variables_swapped: Which variables you changed from the original

Respond in JSON array format only. Example:
[
  {{
    "viral_title": "...",
    "hook_script": "...",
    "thumbnail_visual": "...",
    "past_context": "...",
    "present_parallel": "...",
    "future_prediction": "...",
    "writer_guidance": "...",
    "variables_swapped": ["power: US → China", "event: Iran War → Taiwan Crisis"]
  }}
]"""

    def _parse_ideas_response(self, content: str) -> List[dict]:
        """Parse Claude response into list of idea dicts."""
        import re

        # Try direct JSON parse
        try:
            data = json.loads(content)
            if isinstance(data, list):
                return data
            return []
        except json.JSONDecodeError:
            pass

        # Try extracting from markdown
        json_match = re.search(r'```(?:json)?\s*(\[.*?\])\s*```', content, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except:
                pass

        # Try finding array in raw text
        array_match = re.search(r'\[\s*\{.*?\}\s*\]', content, re.DOTALL)
        if array_match:
            try:
                return json.loads(array_match.group(0))
            except:
                pass

        logger.error(f"Failed to parse ideas response")
        return []

    async def analyze_competitor_thumbnail(
        self,
        video_id: str,
    ) -> Optional[str]:
        """Analyze competitor thumbnail and generate style override.

        Args:
            video_id: YouTube video ID

        Returns:
            Thumbnail style override string or None
        """
        try:
            analyzer = self._get_thumbnail_analyzer()
            adapter = self._get_thumbnail_adapter()

            # Analyze thumbnail
            analysis = await analyzer.analyze_from_video_id(video_id)
            if analysis is None:
                logger.warning(f"Thumbnail analysis failed for {video_id}")
                return None

            # Generate override
            override = adapter.generate_override(analysis, use_replace=True)
            return override

        except Exception as e:
            logger.error(f"Thumbnail analysis error: {e}")
            return None

    async def create_idea_from_competitor(
        self,
        candidate: IdeaCandidate,
        theme_analysis: ThemeAnalysis,
        idea_index: int = 0,
    ) -> Optional[dict]:
        """Create an idea in Airtable from a selected competitor video.

        Args:
            candidate: The selected IdeaCandidate
            theme_analysis: Extracted theme analysis
            idea_index: Which of the generated ideas to use (0-2)

        Returns:
            Created Airtable record dict or None
        """
        # Generate modeled ideas
        modeled_ideas = await self.generate_modeled_ideas(
            competitor_title=candidate.competitor_title or candidate.title,
            theme_analysis=theme_analysis,
            num_ideas=3,
        )

        if not modeled_ideas:
            logger.error("No modeled ideas generated")
            return None

        # Select the idea to use
        idea = modeled_ideas[min(idea_index, len(modeled_ideas) - 1)]

        # Analyze competitor thumbnail (non-blocking)
        thumbnail_override = None
        if candidate.record_id:
            # Try to get video_id from record
            video_id = self._extract_video_id(candidate)
            if video_id:
                thumbnail_override = await self.analyze_competitor_thumbnail(video_id)
                idea.thumbnail_style_override = thumbnail_override or ""

        # Build Airtable record data
        idea_data = {
            "viral_title": idea.viral_title,
            "hook_script": idea.hook_script,
            "thumbnail_visual": idea.thumbnail_visual,
            "narrative_logic": idea.narrative_logic,
            "writer_guidance": idea.writer_guidance,
            "modeled_from": idea.modeled_from,
            "reference_url": candidate.competitor_title,  # Competitor reference
            "original_dna": json.dumps({
                "source_type": "autopilot_modeling",
                "competitor_title": candidate.competitor_title,
                "competitor_vph": candidate.competitor_vph,
                "theme_analysis": {
                    "primary_theme": theme_analysis.primary_theme,
                    "angle_type": theme_analysis.angle_type,
                    "emotional_hooks": theme_analysis.emotional_hooks,
                    "topic_category": theme_analysis.topic_category,
                    "title_formula": theme_analysis.title_formula,
                },
                "formula_used": idea.formula_used,
                "variables_swapped": idea.variables_swapped,
            }),
        }

        # Add thumbnail style override if we have one
        if thumbnail_override:
            idea_data["Thumbnail Style Override"] = thumbnail_override

        # Create in Airtable
        try:
            airtable = self._get_airtable()
            record = airtable.create_idea(idea_data, source="autopilot_modeling")
            logger.info(f"Created idea: {idea.viral_title}")
            return record
        except Exception as e:
            logger.error(f"Failed to create idea in Airtable: {e}")
            return None

    def _extract_video_id(self, candidate: IdeaCandidate) -> Optional[str]:
        """Extract YouTube video ID from candidate if available."""
        # The candidate might have the video_id stored, or we extract from URL
        # For now, return None - the Competitor Videos table should have video_id
        # This will be populated when we wire up the full flow
        return None

    async def create_all_ideas_from_competitor(
        self,
        candidate: IdeaCandidate,
        theme_analysis: ThemeAnalysis,
    ) -> List[dict]:
        """Create all 3 modeled ideas in Airtable.

        Args:
            candidate: The selected IdeaCandidate
            theme_analysis: Extracted theme analysis

        Returns:
            List of created Airtable records
        """
        records = []
        for i in range(3):
            record = await self.create_idea_from_competitor(
                candidate=candidate,
                theme_analysis=theme_analysis,
                idea_index=i,
            )
            if record:
                records.append(record)

        return records
