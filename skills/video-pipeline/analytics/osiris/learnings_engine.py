"""
Osiris Learnings Engine - Aggregates and injects channel learnings.

This module sits between the Osiris Learnings table and the generation
prompts (idea_bot, script_generator, thumbnail_bot). It:

1. Queries the learnings table
2. Aggregates by category
3. Formats as prompt injection text
4. Caches for 1 hour to avoid excessive Airtable reads

Usage:
    from analytics.osiris.learnings_engine import LearningsEngine
    from shared.clients.airtable_client import AirtableClient

    engine = LearningsEngine(AirtableClient())
    title_learnings = engine.get_title_learnings()
    # Returns formatted text for injection into title generation prompts

Design Principles:
    - GRACEFUL DEGRADATION: Returns empty string if no learnings
    - CACHING: 1 hour TTL to minimize Airtable API calls
    - READ ONLY: Never writes to Airtable
    - SAFE: Never blocks video generation if learnings unavailable
"""

import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class CachedLearnings:
    """Cached learning data with TTL."""
    data: list[dict]
    fetched_at: float  # Unix timestamp

    def is_expired(self, ttl_seconds: int = 3600) -> bool:
        """Check if cache has expired."""
        return time.time() - self.fetched_at > ttl_seconds


class LearningsEngine:
    """Aggregates channel learnings and injects into generation prompts.

    Usage:
        engine = LearningsEngine(airtable_client)

        # For title generation
        title_prompt = base_prompt + engine.get_title_learnings()

        # For thumbnail generation
        thumbnail_prompt = base_prompt + engine.get_thumbnail_learnings()

        # For script/hook generation
        hook_prompt = base_prompt + engine.get_hook_learnings()
    """

    # Categories matching Airtable Single Select options
    CATEGORY_TITLE = "title"
    CATEGORY_HOOK = "hook"
    CATEGORY_THUMBNAIL = "thumbnail"
    CATEGORY_RETENTION = "retention"
    CATEGORY_FRAMEWORK = "framework"

    # Minimum confidence threshold for including in prompts
    MIN_CONFIDENCE = 40

    # Minimum sample size for statistical significance
    MIN_SAMPLE_SIZE = 2

    def __init__(
        self,
        airtable_client,
        cache_ttl: int = 3600,  # 1 hour default
    ):
        """Initialize the learnings engine.

        Args:
            airtable_client: AirtableClient instance
            cache_ttl: Cache time-to-live in seconds (default 1 hour)
        """
        self._airtable = airtable_client
        self._cache_ttl = cache_ttl
        self._cache: Optional[CachedLearnings] = None

    def get_title_learnings(self) -> str:
        """Get title pattern learnings for idea/title generation prompts.

        Returns formatted text like:
            ## Channel-Specific Title Performance
            Based on your channel's historical data:
            - Question format titles: avg 5.2% CTR (3 videos)
            - Numbers in title: avg 4.1% CTR (5 videos)
        """
        learnings = self._get_learnings_by_category(self.CATEGORY_TITLE)
        if not learnings:
            return ""

        # Aggregate by pattern type
        aggregated = self._aggregate_learnings(learnings, "avg_ctr")

        if not aggregated:
            return ""

        lines = [
            "\n## Channel-Specific Title Performance",
            "Based on your channel's historical data:",
        ]

        # Sort by CTR descending
        sorted_patterns = sorted(
            aggregated.items(),
            key=lambda x: x[1]["avg_metric"],
            reverse=True,
        )

        for pattern, data in sorted_patterns[:5]:  # Top 5 patterns
            if data["sample_size"] >= self.MIN_SAMPLE_SIZE:
                lines.append(
                    f"- {pattern}: avg {data['avg_metric']:.1f}% CTR "
                    f"({data['sample_size']} videos)"
                )

        return "\n".join(lines) + "\n"

    def get_hook_learnings(self) -> str:
        """Get hook/opening learnings for script generation prompts.

        Returns formatted text for Act 1 hook guidance.
        """
        learnings = self._get_learnings_by_category(self.CATEGORY_HOOK)
        if not learnings:
            return ""

        aggregated = self._aggregate_learnings(learnings, "avg_retention")

        if not aggregated:
            return ""

        lines = [
            "\n## Hook Performance on Your Channel",
            "Opening styles that worked well:",
        ]

        sorted_patterns = sorted(
            aggregated.items(),
            key=lambda x: x[1]["avg_metric"],
            reverse=True,
        )

        for pattern, data in sorted_patterns[:4]:
            if data["sample_size"] >= self.MIN_SAMPLE_SIZE:
                lines.append(
                    f"- {pattern}: avg {data['avg_metric']:.1f}% retention "
                    f"({data['sample_size']} videos)"
                )

        return "\n".join(lines) + "\n"

    def get_thumbnail_learnings(self) -> str:
        """Get thumbnail verdict learnings for thumbnail generation.

        Returns formatted text about which verdict words perform best.
        """
        learnings = self._get_learnings_by_category(self.CATEGORY_THUMBNAIL)
        if not learnings:
            return ""

        aggregated = self._aggregate_learnings(learnings, "avg_ctr")

        if not aggregated:
            return ""

        lines = [
            "\n## Thumbnail Performance Data",
            "Verdict styles with best CTR on your channel:",
        ]

        sorted_patterns = sorted(
            aggregated.items(),
            key=lambda x: x[1]["avg_metric"],
            reverse=True,
        )

        for pattern, data in sorted_patterns[:3]:
            if data["sample_size"] >= self.MIN_SAMPLE_SIZE:
                lines.append(
                    f"- {pattern}: avg {data['avg_metric']:.1f}% CTR"
                )

        return "\n".join(lines) + "\n"

    def get_framework_performance(self) -> dict:
        """Get per-framework performance stats.

        Returns:
            {
                "Thucydides Trap": {"avg_ctr": 5.1, "avg_retention": 62.3, "count": 4},
                "Machiavelli": {"avg_ctr": 4.2, "avg_retention": 58.7, "count": 3},
                ...
            }
        """
        learnings = self._get_learnings_by_category(self.CATEGORY_FRAMEWORK)
        if not learnings:
            return {}

        framework_stats = defaultdict(lambda: {
            "ctr_sum": 0,
            "ctr_count": 0,
            "retention_sum": 0,
            "retention_count": 0,
        })

        for learning in learnings:
            # Parse framework from pattern (e.g., "Framework 'Thucydides Trap' | CTR 5.1%")
            pattern = learning.get("Pattern", "")
            if "Framework '" in pattern:
                start = pattern.index("Framework '") + 11
                end = pattern.index("'", start)
                framework = pattern[start:end]

                ctr = learning.get("Avg CTR")
                retention = learning.get("Avg Retention")

                if ctr is not None:
                    framework_stats[framework]["ctr_sum"] += ctr
                    framework_stats[framework]["ctr_count"] += 1

                if retention is not None:
                    framework_stats[framework]["retention_sum"] += retention
                    framework_stats[framework]["retention_count"] += 1

        # Calculate averages
        result = {}
        for framework, stats in framework_stats.items():
            count = max(stats["ctr_count"], stats["retention_count"])
            if count >= 2:  # Minimum threshold
                result[framework] = {
                    "avg_ctr": round(stats["ctr_sum"] / stats["ctr_count"], 1) if stats["ctr_count"] else None,
                    "avg_retention": round(stats["retention_sum"] / stats["retention_count"], 1) if stats["retention_count"] else None,
                    "count": count,
                }

        return result

    def get_framework_learnings(self) -> str:
        """Get framework learnings formatted for prompt injection."""
        framework_stats = self.get_framework_performance()
        if not framework_stats:
            return ""

        lines = [
            "\n## Framework Performance on Your Channel",
        ]

        # Sort by retention (primary driver of watch time)
        sorted_frameworks = sorted(
            framework_stats.items(),
            key=lambda x: x[1].get("avg_retention") or 0,
            reverse=True,
        )

        for framework, stats in sorted_frameworks:
            parts = [f"- {framework}:"]
            if stats.get("avg_retention"):
                parts.append(f"{stats['avg_retention']:.0f}% retention")
            if stats.get("avg_ctr"):
                parts.append(f"{stats['avg_ctr']:.1f}% CTR")
            parts.append(f"({stats['count']} videos)")
            lines.append(" ".join(parts))

        return "\n".join(lines) + "\n"

    def get_all_learnings_for_ideation(self) -> str:
        """Get combined learnings for idea generation.

        Includes title patterns and framework performance.
        """
        parts = []

        title = self.get_title_learnings()
        if title:
            parts.append(title)

        framework = self.get_framework_learnings()
        if framework:
            parts.append(framework)

        if not parts:
            return ""

        return (
            "\n" + "=" * 40 +
            "\nCHANNEL PERFORMANCE DATA (Use to inform your suggestions)" +
            "\n" + "=" * 40 +
            "".join(parts)
        )

    def _get_learnings_by_category(self, category: str) -> list[dict]:
        """Get learnings filtered by category from cache or Airtable."""
        all_learnings = self._get_all_learnings()

        return [
            l for l in all_learnings
            if l.get("Category") == category
            and l.get("Confidence", 0) >= self.MIN_CONFIDENCE
            and l.get("Active", True)
        ]

    def _get_all_learnings(self) -> list[dict]:
        """Get all learnings with caching."""
        # Return from cache if valid
        if self._cache and not self._cache.is_expired(self._cache_ttl):
            return self._cache.data

        # Fetch from Airtable
        try:
            learnings = self._airtable.get_all_learnings(active_only=True)
            self._cache = CachedLearnings(
                data=learnings,
                fetched_at=time.time(),
            )
            return learnings
        except Exception as e:
            logger.warning(f"Failed to fetch learnings: {e}")
            # Return stale cache if available
            if self._cache:
                logger.info("Using stale cache as fallback")
                return self._cache.data
            return []

    def _aggregate_learnings(
        self,
        learnings: list[dict],
        metric_field: str,
    ) -> dict:
        """Aggregate learnings by pattern, calculating weighted average.

        Args:
            learnings: List of learning records
            metric_field: Field to average (avg_ctr, avg_retention)

        Returns:
            {
                "Pattern name": {"avg_metric": 5.1, "sample_size": 3},
                ...
            }
        """
        aggregated = defaultdict(lambda: {
            "total_metric": 0,
            "total_samples": 0,
        })

        for learning in learnings:
            # Extract pattern type (first part before ":")
            full_pattern = learning.get("Pattern", "")
            if ":" in full_pattern:
                pattern_type = full_pattern.split(":")[0].strip()
            else:
                pattern_type = full_pattern[:50]

            metric_value = learning.get(
                metric_field.replace("avg_", "Avg ").replace("ctr", "CTR").replace("retention", "Retention")
            )
            sample_size = learning.get("Sample Size", 1)

            if metric_value is not None:
                aggregated[pattern_type]["total_metric"] += metric_value * sample_size
                aggregated[pattern_type]["total_samples"] += sample_size

        # Calculate weighted averages
        result = {}
        for pattern, data in aggregated.items():
            if data["total_samples"] > 0:
                result[pattern] = {
                    "avg_metric": data["total_metric"] / data["total_samples"],
                    "sample_size": data["total_samples"],
                }

        return result

    def invalidate_cache(self) -> None:
        """Force cache invalidation (e.g., after new learnings are added)."""
        self._cache = None

    def get_cache_status(self) -> dict:
        """Get cache status for debugging."""
        if not self._cache:
            return {"cached": False}

        age = time.time() - self._cache.fetched_at
        return {
            "cached": True,
            "age_seconds": int(age),
            "expired": self._cache.is_expired(self._cache_ttl),
            "entries": len(self._cache.data),
        }

