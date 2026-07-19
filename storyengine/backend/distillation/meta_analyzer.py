"""Second-order distillation — niche-level meta-analysis across all distilled content.

Takes individual video DNA (hook types, title structures, thumbnail patterns, timing)
and generates actionable niche-level insights using Claude meta-analysis:
  - "mystery_question hooks outperform all others by 40% in your niche"
  - "Videos published Tuesday 6AM get 2.5x average VPH"
  - "editorial thumbnails with face_with_text layout = highest performing combination"

Entry point:
  generate_niche_meta_insights(tenant_id) → stored in niche_meta_insights table
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from database import fetch_all, fetch_one, execute
from distillation.advisor import IntelligenceAdvisor
# Single Claude tier source (checklist §3.4 / C35) — see shared.channel_profile.
from actions import CLAUDE_MODELS

logger = logging.getLogger("storyengine")

# Minimum distilled videos for meta-analysis to be meaningful
MIN_VIDEOS_FOR_META = 20

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday",
             "Friday", "Saturday", "Sunday"]


async def _get_aggregated_patterns(tenant_id: str) -> dict:
    """Gather all aggregated pattern data for meta-analysis prompt."""

    # Hook types with VPH
    hooks = await fetch_all(
        """SELECT
            COALESCE(
                ci.structured_metadata->'hook_dna'->>'type',
                ci.structured_metadata->'hook'->>'type'
            ) as hook_type,
            COUNT(*) as count,
            ROUND(AVG(cv.vph)::numeric, 1) as avg_vph,
            ROUND(AVG(cv.like_ratio)::numeric, 5) as avg_like_ratio
        FROM content_intelligence ci
        JOIN competitor_videos cv ON cv.id = ci.source_id AND cv.tenant_id = ci.tenant_id
        WHERE ci.tenant_id = $1
          AND ci.source_type = 'competitor_transcript'
          AND COALESCE(
                ci.structured_metadata->'hook_dna'->>'type',
                ci.structured_metadata->'hook'->>'type'
              ) IS NOT NULL
        GROUP BY hook_type
        ORDER BY avg_vph DESC NULLS LAST""",
        tenant_id,
    )

    # Title structures with VPH
    title_structures = await fetch_all(
        """SELECT
            COALESCE(
                ci.structured_metadata->'title_dna'->>'structure',
                ci.structured_metadata->'title'->>'structure'
            ) as structure,
            COUNT(*) as count,
            ROUND(AVG(cv.vph)::numeric, 1) as avg_vph
        FROM content_intelligence ci
        JOIN competitor_videos cv ON cv.id = ci.source_id AND cv.tenant_id = ci.tenant_id
        WHERE ci.tenant_id = $1
          AND ci.source_type = 'competitor_transcript'
          AND COALESCE(
                ci.structured_metadata->'title_dna'->>'structure',
                ci.structured_metadata->'title'->>'structure'
              ) IS NOT NULL
        GROUP BY structure
        ORDER BY avg_vph DESC NULLS LAST""",
        tenant_id,
    )

    # Thumbnail patterns
    thumb_layouts = await fetch_all(
        """SELECT
            ci.structured_metadata->'thumbnail_dna'->'composition'->>'layout' as layout,
            COUNT(*) as count,
            ROUND(AVG(cv.vph)::numeric, 1) as avg_vph
        FROM content_intelligence ci
        JOIN competitor_videos cv ON cv.id = ci.source_id AND cv.tenant_id = ci.tenant_id
        WHERE ci.tenant_id = $1
          AND ci.source_type = 'competitor_transcript'
          AND ci.structured_metadata->'thumbnail_dna'->'composition'->>'layout' IS NOT NULL
        GROUP BY layout
        ORDER BY avg_vph DESC NULLS LAST""",
        tenant_id,
    )

    thumb_styles = await fetch_all(
        """SELECT
            ci.structured_metadata->'thumbnail_dna'->>'overall_style' as style,
            COUNT(*) as count,
            ROUND(AVG(cv.vph)::numeric, 1) as avg_vph
        FROM content_intelligence ci
        JOIN competitor_videos cv ON cv.id = ci.source_id AND cv.tenant_id = ci.tenant_id
        WHERE ci.tenant_id = $1
          AND ci.source_type = 'competitor_transcript'
          AND ci.structured_metadata->'thumbnail_dna'->>'overall_style' IS NOT NULL
        GROUP BY style
        ORDER BY avg_vph DESC NULLS LAST""",
        tenant_id,
    )

    # Topics
    topics = await fetch_all(
        """SELECT
            tag as topic,
            COUNT(*) as count,
            ROUND(AVG(cv.vph)::numeric, 1) as avg_vph
        FROM content_intelligence ci
        JOIN competitor_videos cv ON cv.id = ci.source_id AND cv.tenant_id = ci.tenant_id,
             jsonb_array_elements_text(
                 COALESCE(ci.structured_metadata->'content_dna'->'topic_tags',
                          ci.structured_metadata->'content'->'topic_tags')
             ) as tag
        WHERE ci.tenant_id = $1
          AND ci.source_type = 'competitor_transcript'
        GROUP BY tag
        ORDER BY avg_vph DESC NULLS LAST
        LIMIT 15""",
        tenant_id,
    )

    # Timing
    days = await fetch_all(
        """SELECT
            published_day_of_week as day,
            COUNT(*) as count,
            ROUND(AVG(vph)::numeric, 1) as avg_vph
        FROM competitor_videos
        WHERE tenant_id = $1
          AND published_day_of_week IS NOT NULL AND vph > 0
        GROUP BY published_day_of_week
        ORDER BY published_day_of_week""",
        tenant_id,
    )

    hours = await fetch_all(
        """SELECT
            published_hour as hour,
            COUNT(*) as count,
            ROUND(AVG(vph)::numeric, 1) as avg_vph
        FROM competitor_videos
        WHERE tenant_id = $1
          AND published_hour IS NOT NULL AND vph > 0
        GROUP BY published_hour
        ORDER BY avg_vph DESC NULLS LAST
        LIMIT 10""",
        tenant_id,
    )

    # Controversy level correlation
    controversy = await fetch_all(
        """SELECT
            COALESCE(
                ci.structured_metadata->'content_dna'->>'controversy_level',
                ci.structured_metadata->'content'->>'controversy_level'
            ) as level,
            COUNT(*) as count,
            ROUND(AVG(cv.vph)::numeric, 1) as avg_vph
        FROM content_intelligence ci
        JOIN competitor_videos cv ON cv.id = ci.source_id AND cv.tenant_id = ci.tenant_id
        WHERE ci.tenant_id = $1
          AND ci.source_type = 'competitor_transcript'
          AND COALESCE(
                ci.structured_metadata->'content_dna'->>'controversy_level',
                ci.structured_metadata->'content'->>'controversy_level'
              ) IS NOT NULL
        GROUP BY level
        ORDER BY avg_vph DESC NULLS LAST""",
        tenant_id,
    )

    # Tone correlation
    tones = await fetch_all(
        """SELECT
            COALESCE(
                ci.structured_metadata->'content_dna'->>'tone',
                ci.structured_metadata->'content'->>'tone'
            ) as tone,
            COUNT(*) as count,
            ROUND(AVG(cv.vph)::numeric, 1) as avg_vph
        FROM content_intelligence ci
        JOIN competitor_videos cv ON cv.id = ci.source_id AND cv.tenant_id = ci.tenant_id
        WHERE ci.tenant_id = $1
          AND ci.source_type = 'competitor_transcript'
          AND COALESCE(
                ci.structured_metadata->'content_dna'->>'tone',
                ci.structured_metadata->'content'->>'tone'
              ) IS NOT NULL
        GROUP BY tone
        ORDER BY avg_vph DESC NULLS LAST""",
        tenant_id,
    )

    # Top 5 viral videos for context
    viral = await fetch_all(
        """SELECT cv.title, cv.vph, cv.views, cv.channel,
                  ci.summary,
                  ci.structured_metadata->'hook_dna'->>'type' as hook_type,
                  ci.structured_metadata->'title_dna'->>'structure' as title_structure,
                  ci.structured_metadata->'content_dna'->>'tone' as tone
           FROM competitor_videos cv
           LEFT JOIN content_intelligence ci
               ON ci.source_id = cv.id AND ci.tenant_id = cv.tenant_id
               AND ci.source_type = 'competitor_transcript'
           WHERE cv.tenant_id = $1 AND cv.vph > 0
           ORDER BY cv.vph DESC
           LIMIT 5""",
        tenant_id,
    )

    # Overall stats
    overall = await fetch_one(
        """SELECT
            COUNT(*) as total,
            ROUND(AVG(vph)::numeric, 1) as avg_vph,
            ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY vph)::numeric, 1) as median_vph
        FROM competitor_videos
        WHERE tenant_id = $1 AND vph > 0""",
        tenant_id,
    )

    return {
        "hooks": [dict(r) for r in (hooks or [])],
        "title_structures": [dict(r) for r in (title_structures or [])],
        "thumb_layouts": [dict(r) for r in (thumb_layouts or [])],
        "thumb_styles": [dict(r) for r in (thumb_styles or [])],
        "topics": [dict(r) for r in (topics or [])],
        "timing_days": [
            {**dict(r), "day_name": DAY_NAMES[r["day"]] if r.get("day") is not None and r["day"] < 7 else "?"}
            for r in (days or [])
        ],
        "timing_hours": [dict(r) for r in (hours or [])],
        "controversy": [dict(r) for r in (controversy or [])],
        "tones": [dict(r) for r in (tones or [])],
        "viral_videos": [dict(r) for r in (viral or [])],
        "overall": dict(overall) if overall else {},
    }


def _build_meta_prompt(patterns: dict) -> str:
    """Build Claude prompt for niche meta-analysis."""
    overall = patterns.get("overall", {})
    total = overall.get("total", 0)
    avg_vph = overall.get("avg_vph", 0)
    median_vph = overall.get("median_vph", 0)

    sections = [f"You are analyzing {total} competitor videos in a YouTube niche."]
    sections.append(f"Average VPH: {avg_vph}, Median VPH: {median_vph}\n")

    # Hooks
    if patterns.get("hooks"):
        lines = ["HOOK TYPES (how videos open):"]
        for h in patterns["hooks"]:
            pct = f"({h['count']}/{total})" if total else ""
            above = ((float(h["avg_vph"]) / float(avg_vph)) - 1) * 100 if avg_vph else 0
            lines.append(f"  {h['hook_type']}: avg {h['avg_vph']} VPH, {h['count']} videos {pct}, {above:+.0f}% vs avg")
        sections.append("\n".join(lines))

    # Title structures
    if patterns.get("title_structures"):
        lines = ["TITLE STRUCTURES:"]
        for t in patterns["title_structures"]:
            above = ((float(t["avg_vph"]) / float(avg_vph)) - 1) * 100 if avg_vph else 0
            lines.append(f"  {t['structure']}: avg {t['avg_vph']} VPH, {t['count']} videos, {above:+.0f}% vs avg")
        sections.append("\n".join(lines))

    # Thumbnail patterns
    if patterns.get("thumb_layouts") or patterns.get("thumb_styles"):
        lines = ["THUMBNAIL PATTERNS:"]
        for tl in patterns.get("thumb_layouts", []):
            lines.append(f"  Layout: {tl['layout']}: avg {tl['avg_vph']} VPH ({tl['count']})")
        for ts in patterns.get("thumb_styles", []):
            lines.append(f"  Style: {ts['style']}: avg {ts['avg_vph']} VPH ({ts['count']})")
        sections.append("\n".join(lines))

    # Topics
    if patterns.get("topics"):
        lines = ["TOP TOPICS:"]
        for t in patterns["topics"][:10]:
            lines.append(f"  {t['topic']}: avg {t['avg_vph']} VPH ({t['count']} videos)")
        sections.append("\n".join(lines))

    # Timing
    if patterns.get("timing_days"):
        lines = ["PUBLISH TIMING BY DAY:"]
        for d in patterns["timing_days"]:
            lines.append(f"  {d['day_name']}: avg {d['avg_vph']} VPH ({d['count']} videos)")
        sections.append("\n".join(lines))
    if patterns.get("timing_hours"):
        lines = ["TOP PUBLISH HOURS:"]
        for h in patterns["timing_hours"][:5]:
            lines.append(f"  {h['hour']}:00: avg {h['avg_vph']} VPH ({h['count']} videos)")
        sections.append("\n".join(lines))

    # Controversy & tone
    if patterns.get("controversy"):
        lines = ["CONTROVERSY LEVEL:"]
        for c in patterns["controversy"]:
            lines.append(f"  {c['level']}: avg {c['avg_vph']} VPH ({c['count']})")
        sections.append("\n".join(lines))
    if patterns.get("tones"):
        lines = ["TONE:"]
        for t in patterns["tones"]:
            lines.append(f"  {t['tone']}: avg {t['avg_vph']} VPH ({t['count']})")
        sections.append("\n".join(lines))

    # Top viral
    if patterns.get("viral_videos"):
        lines = ["TOP 5 VIDEOS (by VPH):"]
        for v in patterns["viral_videos"]:
            lines.append(f"  \"{v['title']}\" ({v['channel']}) — {v['vph']} VPH, {v.get('views', '?')} views")
            if v.get("hook_type"):
                lines.append(f"    Hook: {v['hook_type']}, Structure: {v.get('title_structure', '?')}, Tone: {v.get('tone', '?')}")
        sections.append("\n".join(lines))

    data_block = "\n\n".join(sections)

    return f"""Analyze this YouTube niche data and produce a structured meta-analysis.

{data_block}

Return a JSON object with these fields:

{{
  "niche_summary": "2-3 sentence summary of what defines this niche and what drives performance",
  "top_patterns": [
    {{
      "pattern": "Short description (e.g., 'mystery_question hooks')",
      "performance": "+X% above average VPH",
      "recommendation": "Actionable advice",
      "confidence": "high/medium/low"
    }}
  ],
  "combination_insights": [
    "Cross-pattern insight (e.g., 'controversy + mystery_question hook = highest VPH')"
  ],
  "timing_strategy": {{
    "best_days": ["day names"],
    "best_hours": [hour numbers],
    "reasoning": "Why these windows work"
  }},
  "contrarian_findings": [
    "Counter-intuitive pattern (e.g., 'faces in thumbnails actually hurt VPH here')"
  ],
  "niche_signature": {{
    "audience_type": "Who watches",
    "content_preference": "What resonates",
    "visual_language": "What visual style works",
    "emotional_drivers": ["Key emotions"]
  }}
}}

Be specific with numbers. Reference actual patterns from the data. Maximum 5 top_patterns, 3 combination_insights, 3 contrarian_findings. Only include patterns with sufficient sample size (3+).

Return ONLY the JSON object, no markdown fences."""


async def generate_niche_meta_insights(tenant_id: str) -> Optional[dict]:
    """Generate second-order distillation: cross-video meta-analysis.

    1. Query all aggregated patterns (hooks, thumbnails, topics, timing, etc.)
    2. Send to Claude Haiku for meta-analysis
    3. Store structured result in niche_meta_insights table

    Returns the stored insight record or None if insufficient data.
    """
    # Check if we have enough data
    count_row = await fetch_one(
        """SELECT COUNT(*) as count FROM content_intelligence
           WHERE tenant_id = $1 AND source_type = 'competitor_transcript'""",
        tenant_id,
    )
    sample_size = count_row["count"] if count_row else 0

    if sample_size < MIN_VIDEOS_FOR_META:
        logger.info("[MetaAnalyzer] Tenant %s: only %d distilled (need %d), skipping",
                     tenant_id[:8], sample_size, MIN_VIDEOS_FOR_META)
        return None

    # Gather all aggregated patterns
    patterns = await _get_aggregated_patterns(tenant_id)

    # Build and send prompt to Claude
    prompt = _build_meta_prompt(patterns)

    try:
        from vault import get_secret
        api_key = await get_secret("anthropic_api_key", tenant_id)
        if not api_key:
            logger.warning("[MetaAnalyzer] No Anthropic API key for tenant %s", tenant_id[:8])
            return None

        import anthropic
        client = anthropic.AsyncAnthropic(api_key=api_key)
        response = await client.messages.create(
            model=CLAUDE_MODELS["anthropic"]["fast"],
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        content = response.content[0].text.strip()

        # Parse JSON response
        try:
            meta_insights = json.loads(content)
        except json.JSONDecodeError:
            # Try extracting from markdown fences
            import re
            match = re.search(r'\{.*\}', content, re.DOTALL)
            if match:
                meta_insights = json.loads(match.group(0))
            else:
                logger.error("[MetaAnalyzer] Failed to parse Claude response")
                return None

    except Exception as e:
        logger.error("[MetaAnalyzer] Claude API error: %s", e)
        return None

    # Get advisor recommendations for structured fields
    advisor = IntelligenceAdvisor()
    recs = await advisor.get_recommendations(tenant_id)

    # Store in niche_meta_insights table
    try:
        result = await fetch_one(
            """INSERT INTO niche_meta_insights (
                tenant_id, sample_size, meta_report, structured_insights,
                top_hook_types, top_thumbnail_patterns, top_title_structures,
                optimal_timing, niche_signature
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (tenant_id) DO UPDATE SET
                generated_at = now(),
                sample_size = EXCLUDED.sample_size,
                meta_report = EXCLUDED.meta_report,
                structured_insights = EXCLUDED.structured_insights,
                top_hook_types = EXCLUDED.top_hook_types,
                top_thumbnail_patterns = EXCLUDED.top_thumbnail_patterns,
                top_title_structures = EXCLUDED.top_title_structures,
                optimal_timing = EXCLUDED.optimal_timing,
                niche_signature = EXCLUDED.niche_signature
            RETURNING id, generated_at""",
            tenant_id,
            sample_size,
            meta_insights.get("niche_summary", ""),
            json.dumps(meta_insights),
            json.dumps(patterns.get("hooks", [])),
            json.dumps(patterns.get("thumb_layouts", []) + patterns.get("thumb_styles", [])),
            json.dumps(patterns.get("title_structures", [])),
            json.dumps({
                "best_days": meta_insights.get("timing_strategy", {}).get("best_days", []),
                "best_hours": meta_insights.get("timing_strategy", {}).get("best_hours", []),
                "reasoning": meta_insights.get("timing_strategy", {}).get("reasoning", ""),
                "raw_days": patterns.get("timing_days", []),
                "raw_hours": patterns.get("timing_hours", []),
            }),
            json.dumps(meta_insights.get("niche_signature", {})),
        )

        logger.info("[MetaAnalyzer] Tenant %s: meta-insights generated (%d videos analyzed)",
                     tenant_id[:8], sample_size)

        return {
            "id": str(result["id"]),
            "generated_at": result["generated_at"].isoformat(),
            "sample_size": sample_size,
            "insights": meta_insights,
            "recommendations": recs.to_dict(),
        }

    except Exception as e:
        logger.error("[MetaAnalyzer] DB storage error: %s", e)
        return None
