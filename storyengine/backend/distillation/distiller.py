"""LLM-powered content distillation — extracts structured intelligence from raw text.

Uses Claude Haiku for cost efficiency (~$0.001 per transcript).
Each source type has a specialized extraction prompt.
"""

import json
import httpx
from typing import Optional

HAIKU_MODEL = "claude-haiku-4-5-20251001"
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"

# ── Competitor Transcript Prompt ──────────────────────────────────

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
    """Distill a competitor transcript into structured intelligence.

    Returns dict with 'summary' and 'structured_metadata' keys,
    or None if distillation fails.
    """
    # Truncate transcript to ~6000 words to keep Haiku costs minimal
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
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        response.raise_for_status()
        data = response.json()

    # Extract text from response
    text = data["content"][0]["text"].strip()

    # Parse JSON (handle markdown code blocks)
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    metadata = json.loads(text)
    summary = metadata.pop("summary", "")

    return {
        "summary": summary,
        "structured_metadata": metadata,
        "model_used": HAIKU_MODEL,
    }
