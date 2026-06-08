"""
IdeaBot - Generates viral video concepts from URLs or topics.

Accepts:
1. YouTube URL - Extracts thumbnail, analyzes with Gemini, generates ideas
2. Topic/Concept - Uses the topic directly to generate ideas

Outputs 3 distinct video concepts with:
- Viral title (clickbait-worthy)
- Thumbnail visual concept
- Hook script (first 15 seconds)
- Narrative logic (past/present/future)
- Writer guidance
"""

import re
from typing import Optional

from title_idea.curiosity_gap.gap_title_engine import GapTitleEngine
from autopilot.learning.pattern_library import PatternLibrary
from orchestrator.pipeline_constants import CURIOSITY_GAP_ENABLED


class IdeaBot:
    """Generates video ideas from URLs or concepts."""

    def __init__(
        self,
        anthropic_client,
        airtable_client,
        gemini_client=None,
        slack_client=None,
        gap_title_engine=None,
        pattern_library=None,
    ):
        """Initialize with required clients.

        Args:
            anthropic_client: For generating ideas with Claude
            airtable_client: For saving ideas to Airtable
            gemini_client: Optional, for analyzing YouTube thumbnails
            slack_client: Optional, for notifications
            gap_title_engine: Optional, for curiosity gap title generation
            pattern_library: Optional, for pattern memory lookup
        """
        self.anthropic = anthropic_client
        self.airtable = airtable_client
        self.gemini = gemini_client
        self.slack = slack_client
        self.gap_title_engine = gap_title_engine
        self.pattern_library = pattern_library

    def _extract_youtube_video_id(self, url: str) -> Optional[str]:
        """Extract video ID from various YouTube URL formats.

        Supports:
        - youtube.com/watch?v=VIDEO_ID
        - youtu.be/VIDEO_ID
        - youtube.com/embed/VIDEO_ID
        - youtube.com/v/VIDEO_ID
        - youtube.com/shorts/VIDEO_ID
        """
        patterns = [
            r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([a-zA-Z0-9_-]{11})',
            r'youtube\.com/v/([a-zA-Z0-9_-]{11})',
            r'youtube\.com/shorts/([a-zA-Z0-9_-]{11})',
        ]

        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    def _get_youtube_thumbnail(self, video_id: str) -> str:
        """Get the highest quality thumbnail URL for a YouTube video."""
        return f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"

    def _is_youtube_url(self, input_text: str) -> bool:
        """Check if input is a YouTube URL."""
        return bool(
            'youtube.com' in input_text.lower() or
            'youtu.be' in input_text.lower()
        )

    async def _analyze_youtube_video(self, url: str) -> dict:
        """Analyze a YouTube video by its thumbnail.

        Returns video DNA dict for idea generation.
        """
        video_id = self._extract_youtube_video_id(url)
        if not video_id:
            raise ValueError(f"Could not extract video ID from URL: {url}")

        thumbnail_url = self._get_youtube_thumbnail(video_id)
        print(f"  Thumbnail URL: {thumbnail_url}")

        # Analyze thumbnail with Gemini if available
        thumbnail_analysis = {}
        if self.gemini:
            print("  Analyzing thumbnail with Gemini...")
            thumbnail_analysis = await self.gemini.generate_thumbnail_spec(
                reference_image_url=thumbnail_url,
                video_title="Reference Video",
                video_summary="",
            )

        return {
            "source_type": "youtube_url",
            "video_id": video_id,
            "url": url,
            "thumbnail_url": thumbnail_url,
            "thumbnail_analysis": thumbnail_analysis,
        }

    async def _build_concept_dna(self, concept: str) -> dict:
        """Build DNA from a concept/topic description.

        Returns video DNA dict for idea generation.
        """
        return {
            "source_type": "concept",
            "concept": concept,
            "topic": concept,
        }

    async def _enhance_title_with_curiosity_gap(
        self,
        idea: dict,
    ) -> dict:
        """Enhance idea with curiosity gap optimized title.

        Args:
            idea: Idea dict from generate_video_ideas

        Returns:
            Enhanced idea dict with structure metadata
        """
        if not CURIOSITY_GAP_ENABLED:
            return idea

        # Lazy initialize engine if needed
        if self.gap_title_engine is None:
            self.gap_title_engine = GapTitleEngine(self.anthropic)

        if self.pattern_library is None:
            self.pattern_library = PatternLibrary()

        # Build story context from idea
        story_context = {
            "hook": idea.get("hook_script", ""),
            "thesis": idea.get("narrative_logic", {}).get("present_parallel", ""),
            "facts": [],  # Could extract from research if available
        }

        try:
            titles = await self.gap_title_engine.generate_titles(
                story_context,
                pattern_library=self.pattern_library,
                target_count=1,  # Just need best title
            )

            if titles:
                best = titles[0]
                idea["viral_title"] = best.text
                idea["curiosity_structure"] = best.structure.value
                idea["structure_confidence"] = best.structure_confidence
                idea["thumbnail_text"] = best.thumbnail_text
                idea["thumbnail_approach"] = best.thumbnail_approach
                print(f"    Enhanced title: {best.text}")
                print(f"    Structure: {best.structure.value} ({best.structure_confidence}%)")

        except Exception as e:
            print(f"    Curiosity gap enhancement failed: {e}")
            # Non-blocking - keep original title

        return idea

    async def generate_ideas(
        self,
        input_text: str,
        save_to_airtable: bool = True,
        notify_slack: bool = True,
    ) -> list[dict]:
        """Generate 3 video ideas from input (URL or concept).

        Args:
            input_text: YouTube URL or concept/topic description
            save_to_airtable: Whether to save ideas to Airtable
            notify_slack: Whether to send Slack notification

        Returns:
            List of 3 video concept dicts
        """
        print(f"\n💡 IDEA BOT: Generating ideas...")
        print(f"  Input: {input_text[:100]}...")

        # Determine input type and build DNA
        if self._is_youtube_url(input_text):
            print("  Type: YouTube URL")
            video_dna = await self._analyze_youtube_video(input_text)
        else:
            print("  Type: Concept/Topic")
            video_dna = await self._build_concept_dna(input_text)

        # Generate ideas with Claude
        print("  Generating ideas with Claude...")
        ideas = await self.anthropic.generate_video_ideas(video_dna)

        print(f"  Generated {len(ideas)} ideas:")
        for i, idea in enumerate(ideas, 1):
            title = idea.get("viral_title", "Untitled")
            print(f"    {i}. {title}")

        # Enhance with curiosity gap titles
        if CURIOSITY_GAP_ENABLED:
            print("  Enhancing with curiosity gap structures...")
            enhanced_ideas = []
            for idea in ideas:
                enhanced = await self._enhance_title_with_curiosity_gap(idea)
                enhanced_ideas.append(enhanced)
            ideas = enhanced_ideas

        # Add original DNA and reference URL to each idea
        for idea in ideas:
            idea["original_dna"] = str(video_dna)
            # If input was a YouTube URL, save it as reference for thumbnail creation
            if video_dna.get("source_type") == "youtube_url" and video_dna.get("url"):
                idea["reference_url"] = video_dna.get("url")

        # Save to Airtable (Idea Concepts table)
        if save_to_airtable:
            print("  Saving to Airtable (Idea Concepts)...")
            for i, idea in enumerate(ideas, 1):
                try:
                    record = self.airtable.create_idea(idea, source="url_analysis")
                    print(f"    ✅ Saved idea {i}: {record.get('id')}")

                    # Save curiosity structure metadata if present
                    if idea.get("curiosity_structure"):
                        try:
                            self.airtable.update_idea_curiosity_structure(
                                record_id=record.get("id"),
                                structure=idea.get("curiosity_structure"),
                                confidence=idea.get("structure_confidence", 0),
                                thumbnail_text=idea.get("thumbnail_text", ""),
                                thumbnail_approach=idea.get("thumbnail_approach", "from_gap"),
                            )
                        except Exception as e:
                            print(f"    Warning: Could not save structure metadata: {e}")
                except Exception as e:
                    print(f"    ❌ Failed to save idea {i}: {e}")

        # Notify Slack
        if notify_slack and self.slack:
            try:
                self.slack.notify_idea_generated(ideas)
                print("  ✅ Slack notification sent")
            except Exception as e:
                print(f"  ⚠️ Slack notification failed: {e}")

        return ideas

    async def generate_from_url(self, url: str, **kwargs) -> list[dict]:
        """Convenience method for URL-based generation."""
        return await self.generate_ideas(url, **kwargs)

    async def generate_from_concept(self, concept: str, **kwargs) -> list[dict]:
        """Convenience method for concept-based generation."""
        return await self.generate_ideas(concept, **kwargs)
