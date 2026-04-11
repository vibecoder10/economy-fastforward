"""LLM-powered content distillation — extracts structured intelligence from raw text.

Uses Claude Haiku for cost efficiency (~$0.001 per transcript).
Each source type has a specialized extraction prompt.
"""

import json
import httpx
from typing import Optional

HAIKU_MODEL = "claude-haiku-4-5-20251001"
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"


async def _call_haiku(prompt: str, api_key: str, max_tokens: int = 2048) -> Optional[str]:
    """Call Claude Haiku and return the raw text response."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            ANTHROPIC_API_URL,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": HAIKU_MODEL,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        response.raise_for_status()
        data = response.json()

    text = data["content"][0]["text"].strip()

    # Strip markdown code blocks
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    return text


# ── Full Video DNA Prompt ─────────────────────────────────────────
# Extracts everything needed to understand WHY a video worked.

FULL_VIDEO_DNA_PROMPT = """Analyze this YouTube video and extract the complete DNA of why it works (or doesn't). Return ONLY valid JSON.

Video Title: {title}
Channel: {channel}
Views: {views:,}
VPH (views per hour): {vph}
Duration: {duration_seconds}s
Likes: {likes:,}
Comments: {comment_count:,}
Subscriber Count: {channel_subs:,}
Like Ratio: {like_ratio}
Views/Sub Ratio: {views_per_sub_ratio}
Published: {published_day} at {published_hour}:00 UTC
Has Chapters: {has_chapters}
Description (first 500 chars): {description}
Tags: {tags}

Transcript (first ~5000 words):
{transcript}

Extract this JSON:
{{
  "summary": "2-3 sentence summary of the video's core argument and why it resonated",

  "title_dna": {{
    "structure": "hidden_knowledge | impossible_stat | personal_challenge | how_to | listicle | news_reaction | story | controversy | comparison | prediction",
    "curiosity_gap": "open_question | impossible_claim | hidden_knowledge | stakes_reveal | timeline_promise | contradiction | none",
    "power_words": ["up to 3 emotionally charged words from the title"],
    "has_number": true or false,
    "title_length_words": 0,
    "clickability_assessment": "why this title makes someone click, in one sentence"
  }},

  "hook_dna": {{
    "type": "mystery_question | impossible_stat | controversy | story_open | direct_challenge | news_hook | personal_story | list_tease | cold_open",
    "opening_line": "the first compelling sentence verbatim",
    "pattern": "brief description of the hook technique",
    "time_to_hook_seconds": 0,
    "first_open_loop": "the first unanswered question or tease that keeps viewers watching"
  }},

  "content_dna": {{
    "topic_tags": ["3-5 topic keywords"],
    "entities": ["key people, companies, or organizations"],
    "key_stats": ["up to 3 memorable numbers or data points"],
    "controversy_level": "low | medium | high",
    "timeliness": "breaking | trending | evergreen | evergreen_with_news_hook",
    "tone": "investigative | authoritative | conversational | outraged | educational | storytelling | comedic | urgent",
    "niche_category": "the broad content category (finance, politics, tech, health, etc.)"
  }},

  "structure_dna": {{
    "type": "escalation | investigation | chronological | problem_solution | comparison | mystery_reveal | listicle | debate | narrative",
    "arc": ["4-6 narrative beat labels"],
    "pacing": "slow_build | fast_punchy | steady | climactic",
    "words_per_minute": 0
  }},

  "retention_dna": {{
    "first_5min_summary": "what specifically happens in the first 5 minutes that keeps people watching",
    "open_loop_count": 0,
    "pattern_interrupts": ["up to 3 re-engagement phrases verbatim"],
    "cliffhanger_density": "low | medium | high",
    "payoff_quality": "does the video deliver on the title/hook promise? strong | adequate | weak | misleading"
  }},

  "villain_dna": {{
    "has_villain": true or false,
    "villain_type": "person | institution | system | ideology | none",
    "villain_name": "specific name if applicable, or null",
    "villain_reveal_position": "early | mid | late | throughout | none",
    "stakes_personal": true or false
  }},

  "engagement_signals": {{
    "comment_bait": "what in this video would drive people to comment",
    "share_trigger": "what would make someone share this",
    "controversy_type": "political | moral | factual | none",
    "polarizing": true or false
  }},

  "context_dna": {{
    "news_riding": true or false,
    "is_outlier_for_channel": "likely based on views_per_sub_ratio: true if > 1.5",
    "audience_type": "general | niche_expert | niche_curious | mainstream_curious",
    "content_depth": "surface | moderate | deep_dive"
  }}
}}"""


async def distill_full_video_dna(
    title: str,
    channel: str,
    views: int,
    vph: float,
    duration_seconds: int,
    transcript: str,
    api_key: str,
    likes: int = 0,
    comment_count: int = 0,
    channel_subs: int = 0,
    like_ratio: float = 0,
    views_per_sub_ratio: float = 0,
    published_day: str = "Unknown",
    published_hour: int = 0,
    has_chapters: bool = False,
    description: str = "",
    tags: str = "",
) -> Optional[dict]:
    """Distill a competitor video into full structured DNA.

    Returns dict with 'summary' and 'structured_metadata' keys,
    or None if distillation fails.
    """
    # Truncate transcript to ~5000 words
    words = transcript.split()
    if len(words) > 5000:
        transcript = " ".join(words[:5000])

    prompt = FULL_VIDEO_DNA_PROMPT.format(
        title=title or "Unknown",
        channel=channel or "Unknown",
        views=views or 0,
        vph=vph or 0,
        duration_seconds=duration_seconds or 0,
        likes=likes or 0,
        comment_count=comment_count or 0,
        channel_subs=channel_subs or 0,
        like_ratio=f"{like_ratio:.4f}" if like_ratio else "N/A",
        views_per_sub_ratio=f"{views_per_sub_ratio:.2f}" if views_per_sub_ratio else "N/A",
        published_day=published_day or "Unknown",
        published_hour=published_hour if published_hour is not None else "Unknown",
        has_chapters=has_chapters,
        description=(description or "")[:500],
        tags=tags or "None",
        transcript=transcript,
    )

    text = await _call_haiku(prompt, api_key, max_tokens=2048)
    if not text:
        return None

    metadata = json.loads(text)
    summary = metadata.pop("summary", "")

    return {
        "summary": summary,
        "structured_metadata": metadata,
        "model_used": HAIKU_MODEL,
    }


# ── Legacy simple transcript prompt (kept for backwards compatibility) ──

COMPETITOR_TRANSCRIPT_PROMPT = """Analyze this YouTube video and extract structured intelligence. Return ONLY valid JSON.

Video Title: {title}
Channel: {channel}
Views: {views:,}
VPH (views per hour): {vph}
Duration: {duration_seconds}s

Transcript:
{transcript}

Extract this JSON structure:
{{
  "summary": "2-3 sentence summary of the video's core argument and approach",
  "hook": {{
    "type": "mystery_question | impossible_stat | controversy | story_open | direct_challenge | news_hook | personal_story | list_tease",
    "opening_line": "the first compelling sentence or question verbatim",
    "pattern": "brief description of the hook technique used"
  }},
  "structure": {{
    "type": "escalation | investigation | chronological | problem_solution | comparison | mystery_reveal | listicle | debate",
    "arc": ["4-6 narrative beat labels describing the video's progression"],
    "pacing": "slow_build | fast_punchy | steady | climactic"
  }},
  "content": {{
    "topic_tags": ["3-5 topic keywords"],
    "entities": ["key people, companies, or organizations mentioned"],
    "key_stats": ["up to 3 memorable numbers or data points"],
    "controversy_level": "low | medium | high",
    "timeliness": "breaking | trending | evergreen | evergreen_with_news_hook"
  }},
  "retention_signals": {{
    "open_loops": 0,
    "pattern_interrupts": ["up to 3 key re-engagement phrases"],
    "cliffhanger_density": "low | medium | high"
  }},
  "production": {{
    "estimated_length_minutes": 0,
    "words_per_minute": 0
  }}
}}"""


async def distill_transcript(
    title: str,
    channel: str,
    views: int,
    vph: float,
    duration_seconds: int,
    transcript: str,
    api_key: str,
) -> Optional[dict]:
    """Legacy simple transcript distillation. Use distill_full_video_dna for new code."""
    words = transcript.split()
    if len(words) > 6000:
        transcript = " ".join(words[:6000])

    prompt = COMPETITOR_TRANSCRIPT_PROMPT.format(
        title=title or "Unknown",
        channel=channel or "Unknown",
        views=views or 0,
        vph=vph or 0,
        duration_seconds=duration_seconds or 0,
        transcript=transcript,
    )

    text = await _call_haiku(prompt, api_key)
    if not text:
        return None

    metadata = json.loads(text)
    summary = metadata.pop("summary", "")

    return {
        "summary": summary,
        "structured_metadata": metadata,
        "model_used": HAIKU_MODEL,
    }
