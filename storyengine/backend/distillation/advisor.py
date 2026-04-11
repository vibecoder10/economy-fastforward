"""Intelligence Advisor — data-backed production recommendations from niche intelligence.

Queries content_intelligence aggregates (hook types, thumbnail patterns, title structures,
timing, topics) and returns the best-performing options for each dimension.

Used by:
  - Autopilot scoring: boost candidates matching intelligence-optimal patterns
  - Discovery prompt: inject niche recommendations so Claude generates data-aligned ideas
  - /api/intelligence/recommendations endpoint: frontend dashboard display
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional

from database import fetch_all, fetch_one

logger = logging.getLogger("storyengine")

# Minimum distilled videos for recommendations to be meaningful
MIN_SAMPLE_SIZE = 5
# Full confidence threshold
FULL_CONFIDENCE_SAMPLE = 50


@dataclass
class HookRecommendation:
    """Best-performing hook type in the niche."""
    hook_type: str
    avg_vph: float
    count: int
    avg_like_ratio: float = 0.0


@dataclass
class ThumbnailRecommendation:
    """Best-performing thumbnail patterns."""
    layout: Optional[str] = None
    layout_avg_vph: float = 0
    style: Optional[str] = None
    style_avg_vph: float = 0
    face_emotion: Optional[str] = None
    face_emotion_avg_vph: float = 0
    face_present: Optional[bool] = None
    face_present_avg_vph: float = 0


@dataclass
class TimingRecommendation:
    """Optimal publish timing."""
    best_day: Optional[int] = None  # 0-6 (Mon-Sun)
    best_day_name: Optional[str] = None
    best_day_avg_vph: float = 0
    best_hour: Optional[int] = None  # 0-23
    best_hour_avg_vph: float = 0


@dataclass
class IntelligenceRecommendations:
    """Full set of data-backed recommendations for the niche."""
    hook: Optional[HookRecommendation] = None
    thumbnail: Optional[ThumbnailRecommendation] = None
    title_structure: Optional[str] = None  # e.g. "hidden_knowledge"
    title_structure_avg_vph: float = 0
    timing: Optional[TimingRecommendation] = None
    top_topics: list[str] = field(default_factory=list)
    top_topics_vph: list[float] = field(default_factory=list)
    sample_size: int = 0
    confidence: float = 0.0  # 0-1

    def to_dict(self) -> dict:
        """Serialize for API response."""
        result = {
            "sample_size": self.sample_size,
            "confidence": round(self.confidence, 2),
            "hook": None,
            "thumbnail": None,
            "title_structure": None,
            "timing": None,
            "top_topics": [],
        }
        if self.hook:
            result["hook"] = {
                "type": self.hook.hook_type,
                "avg_vph": self.hook.avg_vph,
                "count": self.hook.count,
                "avg_like_ratio": self.hook.avg_like_ratio,
            }
        if self.thumbnail:
            result["thumbnail"] = {
                "layout": self.thumbnail.layout,
                "layout_avg_vph": self.thumbnail.layout_avg_vph,
                "style": self.thumbnail.style,
                "style_avg_vph": self.thumbnail.style_avg_vph,
                "face_emotion": self.thumbnail.face_emotion,
                "face_emotion_avg_vph": self.thumbnail.face_emotion_avg_vph,
                "face_present": self.thumbnail.face_present,
                "face_present_avg_vph": self.thumbnail.face_present_avg_vph,
            }
        if self.title_structure:
            result["title_structure"] = {
                "structure": self.title_structure,
                "avg_vph": self.title_structure_avg_vph,
            }
        if self.timing:
            day_names = ["Monday", "Tuesday", "Wednesday", "Thursday",
                         "Friday", "Saturday", "Sunday"]
            result["timing"] = {
                "best_day": self.timing.best_day,
                "best_day_name": self.timing.best_day_name or (
                    day_names[self.timing.best_day]
                    if self.timing.best_day is not None else None
                ),
                "best_day_avg_vph": self.timing.best_day_avg_vph,
                "best_hour": self.timing.best_hour,
                "best_hour_avg_vph": self.timing.best_hour_avg_vph,
            }
        if self.top_topics:
            result["top_topics"] = [
                {"topic": t, "avg_vph": v}
                for t, v in zip(self.top_topics, self.top_topics_vph)
            ]
        return result

    def to_prompt_context(self) -> str:
        """Format as text for Claude prompt injection."""
        if self.sample_size < MIN_SAMPLE_SIZE:
            return ""

        lines = [
            "## Niche Intelligence (Data-Backed Recommendations)",
            f"Based on analysis of {self.sample_size} competitor videos in your niche:",
        ]

        if self.hook:
            lines.append(
                f"- Best hook type: {self.hook.hook_type} "
                f"(avg {self.hook.avg_vph:,.0f} VPH, {self.hook.count} videos)"
            )
        if self.title_structure:
            lines.append(
                f"- Best title structure: {self.title_structure} "
                f"(avg {self.title_structure_avg_vph:,.0f} VPH)"
            )
        if self.thumbnail:
            parts = []
            if self.thumbnail.style:
                parts.append(f"{self.thumbnail.style} style")
            if self.thumbnail.layout:
                parts.append(f"{self.thumbnail.layout} layout")
            if self.thumbnail.face_emotion:
                parts.append(f"{self.thumbnail.face_emotion} expression")
            if parts:
                lines.append(
                    f"- Best thumbnail: {', '.join(parts)} "
                    f"(avg {max(self.thumbnail.style_avg_vph, self.thumbnail.layout_avg_vph):,.0f} VPH)"
                )
        if self.timing:
            parts = []
            if self.timing.best_day_name:
                parts.append(
                    f"{self.timing.best_day_name} "
                    f"(avg {self.timing.best_day_avg_vph:,.0f} VPH)"
                )
            if self.timing.best_hour is not None:
                parts.append(
                    f"{self.timing.best_hour}:00 "
                    f"(avg {self.timing.best_hour_avg_vph:,.0f} VPH)"
                )
            if parts:
                lines.append(f"- Best publish timing: {', '.join(parts)}")
        if self.top_topics:
            topic_strs = [
                f"{t} ({v:,.0f} VPH)"
                for t, v in zip(self.top_topics[:5], self.top_topics_vph[:5])
            ]
            lines.append(f"- Top performing topics: {', '.join(topic_strs)}")

        if len(lines) <= 2:
            return ""
        return "\n".join(lines)


class IntelligenceAdvisor:
    """Query content_intelligence for data-backed production decisions.

    Aggregates hook types, thumbnail patterns, title structures, timing,
    and topics — all correlated with VPH performance — to recommend
    optimal parameters for new video production.
    """

    async def get_recommendations(self, tenant_id: str) -> IntelligenceRecommendations:
        """Get full recommendations based on niche intelligence.

        Runs 5 parallel queries against content_intelligence + competitor_videos.
        Returns structured recommendations with confidence score.
        """
        # Check sample size first
        count_row = await fetch_one(
            """SELECT COUNT(*) as count FROM content_intelligence
               WHERE tenant_id = $1 AND source_type = 'competitor_transcript'""",
            tenant_id,
        )
        sample_size = count_row["count"] if count_row else 0

        if sample_size < MIN_SAMPLE_SIZE:
            return IntelligenceRecommendations(
                sample_size=sample_size,
                confidence=0.0,
            )

        # Run all queries in parallel
        hook_task = self._query_best_hook(tenant_id)
        thumb_task = self._query_best_thumbnail(tenant_id)
        title_task = self._query_best_title_structure(tenant_id)
        timing_task = self._query_best_timing(tenant_id)
        topics_task = self._query_top_topics(tenant_id)

        hook, thumb, title, timing, topics = await asyncio.gather(
            hook_task, thumb_task, title_task, timing_task, topics_task,
            return_exceptions=True,
        )

        # Build recommendations, handling any individual query failures
        recs = IntelligenceRecommendations(
            sample_size=sample_size,
            confidence=min(1.0, sample_size / FULL_CONFIDENCE_SAMPLE),
        )

        if isinstance(hook, HookRecommendation):
            recs.hook = hook
        elif isinstance(hook, Exception):
            logger.warning("Hook query failed: %s", hook)

        if isinstance(thumb, ThumbnailRecommendation):
            recs.thumbnail = thumb
        elif isinstance(thumb, Exception):
            logger.warning("Thumbnail query failed: %s", thumb)

        if isinstance(title, tuple) and len(title) == 2:
            recs.title_structure, recs.title_structure_avg_vph = title
        elif isinstance(title, Exception):
            logger.warning("Title structure query failed: %s", title)

        if isinstance(timing, TimingRecommendation):
            recs.timing = timing
        elif isinstance(timing, Exception):
            logger.warning("Timing query failed: %s", timing)

        if isinstance(topics, tuple) and len(topics) == 2:
            recs.top_topics, recs.top_topics_vph = topics
        elif isinstance(topics, Exception):
            logger.warning("Topics query failed: %s", topics)

        return recs

    async def _query_best_hook(self, tenant_id: str) -> Optional[HookRecommendation]:
        """Find the best-performing hook type by avg VPH."""
        rows = await fetch_all(
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
            HAVING COUNT(*) >= 2
            ORDER BY avg_vph DESC NULLS LAST
            LIMIT 1""",
            tenant_id,
        )
        if not rows:
            return None
        r = rows[0]
        return HookRecommendation(
            hook_type=r["hook_type"],
            avg_vph=float(r["avg_vph"] or 0),
            count=int(r["count"]),
            avg_like_ratio=float(r["avg_like_ratio"] or 0),
        )

    async def _query_best_thumbnail(self, tenant_id: str) -> Optional[ThumbnailRecommendation]:
        """Find best-performing thumbnail patterns (layout, style, emotion, face)."""
        thumb = ThumbnailRecommendation()
        has_any = False

        # Best layout
        layouts = await fetch_all(
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
            HAVING COUNT(*) >= 2
            ORDER BY avg_vph DESC NULLS LAST
            LIMIT 1""",
            tenant_id,
        )
        if layouts:
            thumb.layout = layouts[0]["layout"]
            thumb.layout_avg_vph = float(layouts[0]["avg_vph"] or 0)
            has_any = True

        # Best style
        styles = await fetch_all(
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
            HAVING COUNT(*) >= 2
            ORDER BY avg_vph DESC NULLS LAST
            LIMIT 1""",
            tenant_id,
        )
        if styles:
            thumb.style = styles[0]["style"]
            thumb.style_avg_vph = float(styles[0]["avg_vph"] or 0)
            has_any = True

        # Best face emotion
        emotions = await fetch_all(
            """SELECT
                ci.structured_metadata->'thumbnail_dna'->>'face_emotion' as emotion,
                COUNT(*) as count,
                ROUND(AVG(cv.vph)::numeric, 1) as avg_vph
            FROM content_intelligence ci
            JOIN competitor_videos cv ON cv.id = ci.source_id AND cv.tenant_id = ci.tenant_id
            WHERE ci.tenant_id = $1
              AND ci.source_type = 'competitor_transcript'
              AND ci.structured_metadata->'thumbnail_dna'->>'face_emotion' IS NOT NULL
              AND ci.structured_metadata->'thumbnail_dna'->>'face_emotion' != 'none'
            GROUP BY emotion
            HAVING COUNT(*) >= 2
            ORDER BY avg_vph DESC NULLS LAST
            LIMIT 1""",
            tenant_id,
        )
        if emotions:
            thumb.face_emotion = emotions[0]["emotion"]
            thumb.face_emotion_avg_vph = float(emotions[0]["avg_vph"] or 0)
            has_any = True

        # Face present vs not
        face_stats = await fetch_all(
            """SELECT
                (ci.structured_metadata->'thumbnail_dna'->>'face_present')::boolean as face_present,
                COUNT(*) as count,
                ROUND(AVG(cv.vph)::numeric, 1) as avg_vph
            FROM content_intelligence ci
            JOIN competitor_videos cv ON cv.id = ci.source_id AND cv.tenant_id = ci.tenant_id
            WHERE ci.tenant_id = $1
              AND ci.source_type = 'competitor_transcript'
              AND ci.structured_metadata->'thumbnail_dna'->>'face_present' IS NOT NULL
            GROUP BY face_present
            HAVING COUNT(*) >= 2
            ORDER BY avg_vph DESC NULLS LAST
            LIMIT 1""",
            tenant_id,
        )
        if face_stats:
            thumb.face_present = bool(face_stats[0]["face_present"])
            thumb.face_present_avg_vph = float(face_stats[0]["avg_vph"] or 0)
            has_any = True

        return thumb if has_any else None

    async def _query_best_title_structure(self, tenant_id: str) -> tuple[Optional[str], float]:
        """Find best-performing title structure by avg VPH."""
        rows = await fetch_all(
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
            HAVING COUNT(*) >= 2
            ORDER BY avg_vph DESC NULLS LAST
            LIMIT 1""",
            tenant_id,
        )
        if not rows:
            return None, 0.0
        return rows[0]["structure"], float(rows[0]["avg_vph"] or 0)

    async def _query_best_timing(self, tenant_id: str) -> Optional[TimingRecommendation]:
        """Find optimal publish day and hour by avg VPH."""
        timing = TimingRecommendation()
        has_any = False
        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday",
                     "Friday", "Saturday", "Sunday"]

        # Best day
        days = await fetch_all(
            """SELECT
                published_day_of_week as day,
                COUNT(*) as count,
                ROUND(AVG(vph)::numeric, 1) as avg_vph
            FROM competitor_videos
            WHERE tenant_id = $1
              AND published_day_of_week IS NOT NULL
              AND vph > 0
            GROUP BY published_day_of_week
            HAVING COUNT(*) >= 3
            ORDER BY avg_vph DESC NULLS LAST
            LIMIT 1""",
            tenant_id,
        )
        if days:
            timing.best_day = int(days[0]["day"])
            timing.best_day_name = day_names[timing.best_day] if timing.best_day < 7 else "Unknown"
            timing.best_day_avg_vph = float(days[0]["avg_vph"] or 0)
            has_any = True

        # Best hour
        hours = await fetch_all(
            """SELECT
                published_hour as hour,
                COUNT(*) as count,
                ROUND(AVG(vph)::numeric, 1) as avg_vph
            FROM competitor_videos
            WHERE tenant_id = $1
              AND published_hour IS NOT NULL
              AND vph > 0
            GROUP BY published_hour
            HAVING COUNT(*) >= 3
            ORDER BY avg_vph DESC NULLS LAST
            LIMIT 1""",
            tenant_id,
        )
        if hours:
            timing.best_hour = int(hours[0]["hour"])
            timing.best_hour_avg_vph = float(hours[0]["avg_vph"] or 0)
            has_any = True

        return timing if has_any else None

    async def _query_top_topics(self, tenant_id: str, limit: int = 5) -> tuple[list[str], list[float]]:
        """Find top-performing topics by avg VPH."""
        rows = await fetch_all(
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
            HAVING COUNT(*) >= 2
            ORDER BY avg_vph DESC NULLS LAST
            LIMIT $2""",
            tenant_id, limit,
        )
        if not rows:
            return [], []
        return (
            [r["topic"] for r in rows],
            [float(r["avg_vph"] or 0) for r in rows],
        )


# Module-level instance for convenience
_advisor: Optional[IntelligenceAdvisor] = None


def get_advisor() -> IntelligenceAdvisor:
    """Get or create the singleton advisor instance."""
    global _advisor
    if _advisor is None:
        _advisor = IntelligenceAdvisor()
    return _advisor
