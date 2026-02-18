"""SEO Description and Tags Generator for YouTube uploads.

Generates YouTube-optimized descriptions, tags, and hashtags from a video's
script, beat sheet, and title using the Anthropic API.

Description architecture:
    {hook_line}

    {summary_paragraph}

    Timestamps
    00:00 - {chapter_1_title}
    {estimated_time} - {chapter_2_title}
    ...

    Subscribe for more: https://www.youtube.com/@EconomyFastForward

    #{dynamic_hashtag_1} #{dynamic_hashtag_2} #{dynamic_hashtag_3} #EconomyFastForward #Economy
"""

import json
from typing import Optional


# Static hashtags (always appended)
STATIC_HASHTAGS = ["#EconomyFastForward", "#Economy"]

# Channel subscribe line
SUBSCRIBE_LINE = (
    "Subscribe for more: https://www.youtube.com/@EconomyFastForward"
)

# YouTube category IDs
CATEGORY_NEWS_POLITICS = "25"
CATEGORY_EDUCATION = "27"

# Prompt for Anthropic API to generate SEO metadata
SEO_PROMPT = """\
You are a YouTube SEO specialist for a finance/economics channel called Economy FastForward.

Given the video title, hook, and script excerpt below, generate YouTube metadata.

RULES:
- hook_line: 1 compelling sentence, front-loaded with primary keyword. MUST be under 150 characters. This shows in YouTube search results.
- summary: 2-3 sentences with natural keyword integration. NOT keyword stuffing. Reads like a human wrote it.
- keywords: 5-8 primary keywords extracted from the content.
- hashtags: Exactly 3 dynamic hashtags relevant to THIS video's topic (no # prefix, just the word). These will appear above the title on YouTube.
- tags: 10-15 YouTube tags. Mix of broad niche tags ("economy", "finance", "geopolitics") and specific video tags. These are metadata, not visible to viewers.
- chapter_titles: One title per chapter (group every 3-4 scenes). Short, compelling chapter titles for timestamps.

VIDEO TITLE: {title}

HOOK: {hook}

SCRIPT (first 500 words):
{script_excerpt}

TOTAL SCENES: {scene_count}

Respond with ONLY valid JSON, no markdown fences:
{{
  "hook_line": "...",
  "summary": "...",
  "keywords": ["...", "..."],
  "hashtags": ["...", "...", "..."],
  "tags": ["...", "...", "..."],
  "chapter_titles": ["...", "...", "..."]
}}
"""


class SEOGenerator:
    """Generates YouTube SEO metadata using Anthropic API."""

    def __init__(self, anthropic_client):
        """Initialize with an existing AnthropicClient instance.

        Args:
            anthropic_client: Instance of clients.anthropic_client.AnthropicClient
        """
        self.anthropic = anthropic_client

    def generate(
        self,
        title: str,
        hook: str,
        scripts: list[dict],
        total_duration_seconds: Optional[float] = None,
    ) -> dict:
        """Generate SEO description, tags, and hashtags for a video.

        Args:
            title: Video title
            hook: Hook script text
            scripts: List of script records from Airtable (sorted by scene)
            total_duration_seconds: Total video duration in seconds (for timestamps)

        Returns:
            dict with keys: description, tags, hashtags
        """
        # Build script excerpt (first ~500 words)
        full_script = ""
        for script in scripts:
            text = script.get("Scene text", "")
            full_script += text + " "
            if len(full_script.split()) > 500:
                break
        script_excerpt = " ".join(full_script.split()[:500])

        scene_count = len(scripts)

        # Call Anthropic API
        prompt = SEO_PROMPT.format(
            title=title,
            hook=hook,
            script_excerpt=script_excerpt,
            scene_count=scene_count,
        )

        response = self.anthropic.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )

        # Parse response
        response_text = response.content[0].text.strip()
        # Remove markdown fences if present
        if response_text.startswith("```"):
            response_text = response_text.split("\n", 1)[1]
            if response_text.endswith("```"):
                response_text = response_text[:-3]
        seo_data = json.loads(response_text)

        # Build timestamps from chapter titles
        chapter_titles = seo_data.get("chapter_titles", [])
        timestamps = self._generate_timestamps(
            chapter_titles, scene_count, total_duration_seconds
        )

        # Build hashtags string
        dynamic_hashtags = [
            f"#{h.lstrip('#')}" for h in seo_data.get("hashtags", [])[:3]
        ]
        all_hashtags = dynamic_hashtags + STATIC_HASHTAGS

        # Build full description
        description = self._format_description(
            hook_line=seo_data.get("hook_line", ""),
            summary=seo_data.get("summary", ""),
            timestamps=timestamps,
            hashtags=all_hashtags,
        )

        # Build tags (comma-separated for Airtable storage)
        tags = seo_data.get("tags", [])
        tags_str = ", ".join(tags)

        return {
            "description": description,
            "tags": tags_str,
            "hashtags": " ".join(all_hashtags),
            "tags_list": tags,
            "hook_line": seo_data.get("hook_line", ""),
            "keywords": seo_data.get("keywords", []),
        }

    def _generate_timestamps(
        self,
        chapter_titles: list[str],
        scene_count: int,
        total_duration_seconds: Optional[float],
    ) -> str:
        """Generate timestamp section from chapter titles.

        Distributes timecodes proportionally across total video duration.
        """
        if not chapter_titles:
            return ""

        # Default to 10 minutes if duration unknown
        total_seconds = total_duration_seconds or 600.0

        lines = []
        for i, title in enumerate(chapter_titles):
            # Distribute proportionally
            offset_seconds = (i / len(chapter_titles)) * total_seconds
            minutes = int(offset_seconds // 60)
            seconds = int(offset_seconds % 60)
            timecode = f"{minutes:02d}:{seconds:02d}"
            lines.append(f"{timecode} - {title}")

        return "\n".join(lines)

    def _format_description(
        self,
        hook_line: str,
        summary: str,
        timestamps: str,
        hashtags: list[str],
    ) -> str:
        """Format the full YouTube description."""
        parts = [hook_line, "", summary]

        if timestamps:
            parts.extend(["", "Timestamps", timestamps])

        parts.extend(["", f"Subscribe for more: https://www.youtube.com/@EconomyFastForward"])

        parts.extend(["", " ".join(hashtags)])

        return "\n".join(parts)
