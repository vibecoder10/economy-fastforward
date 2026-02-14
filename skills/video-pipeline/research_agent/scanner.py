"""Research Scanner - Broad environmental scan using Tavily search.

Executes web searches across multiple source categories to surface
8-12 candidate video topics for the dark psychology / strategic power niche.
"""

import os
import json
import asyncio
from datetime import datetime, timedelta
from typing import Optional
from dataclasses import dataclass, field, asdict

import httpx
from anthropic import Anthropic

from .config import (
    RESEARCH_CONFIG,
    SourceCategory,
    SCAN_SYNTHESIZER_PROMPT,
    TOPIC_SCORER_PROMPT,
)


@dataclass
class SearchResult:
    """A single search result from Tavily."""
    title: str
    url: str
    content: str
    score: float
    published_date: Optional[str] = None


@dataclass
class TopicCandidate:
    """A potential video topic candidate."""
    headline: str
    source_category: str
    source_urls: list[str]
    timeliness_score: int
    audience_fit_score: int
    content_gap_score: int
    composite_score: float
    framework_hint: str
    competitor_coverage: str = ""
    reasoning: str = ""
    kill_flags: list[str] = field(default_factory=list)
    selection_recommendation: str = "backlog"

    def to_dict(self) -> dict:
        return asdict(self)


class ResearchScanner:
    """Executes broad environmental scans for video topic discovery."""

    def __init__(
        self,
        tavily_api_key: Optional[str] = None,
        anthropic_api_key: Optional[str] = None,
    ):
        """Initialize the scanner with API clients.

        Args:
            tavily_api_key: Tavily API key (or from TAVILY_API_KEY env var)
            anthropic_api_key: Anthropic API key (or from ANTHROPIC_API_KEY env var)
        """
        self.tavily_api_key = tavily_api_key or os.getenv("TAVILY_API_KEY")
        if not self.tavily_api_key:
            raise ValueError("TAVILY_API_KEY not found in environment")

        self.anthropic_api_key = anthropic_api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY not found in environment")

        self.anthropic = Anthropic(api_key=self.anthropic_api_key)
        self.config = RESEARCH_CONFIG

    async def _tavily_search(
        self,
        query: str,
        search_depth: str = "advanced",
        max_results: int = 5,
    ) -> list[SearchResult]:
        """Execute a single Tavily search.

        Args:
            query: Search query string
            search_depth: "basic" or "advanced"
            max_results: Maximum number of results to return

        Returns:
            List of SearchResult objects
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": self.tavily_api_key,
                    "query": query,
                    "search_depth": search_depth,
                    "max_results": max_results,
                    "include_domains": self.config["api_config"]["tavily_include_domains"] or None,
                    "exclude_domains": self.config["api_config"]["tavily_exclude_domains"],
                },
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()

        results = []
        for item in data.get("results", []):
            results.append(SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                content=item.get("content", ""),
                score=item.get("score", 0.0),
                published_date=item.get("published_date"),
            ))

        return results

    async def _run_category_searches(
        self,
        category: SourceCategory,
    ) -> list[SearchResult]:
        """Run all searches for a single category.

        Args:
            category: The source category to search

        Returns:
            Combined list of search results
        """
        queries = self.config["search_queries"].get(category, [])
        searches_per_category = self.config["scan_config"]["searches_per_category"]
        results_per_search = self.config["scan_config"]["results_per_search"]

        # Limit to configured number of searches
        queries = queries[:searches_per_category]

        all_results = []
        for query in queries:
            try:
                results = await self._tavily_search(
                    query=query,
                    search_depth=self.config["api_config"]["tavily_search_depth"],
                    max_results=results_per_search,
                )
                all_results.extend(results)
                print(f"    {category.value}: '{query}' -> {len(results)} results")
            except Exception as e:
                print(f"    {category.value}: '{query}' -> ERROR: {e}")

        return all_results

    async def run_broad_scan(self) -> dict:
        """Execute the full broad environmental scan.

        Returns:
            Dict containing:
                - raw_results: All search results by category
                - candidates: Synthesized topic candidates
                - scan_metadata: Timing and stats
        """
        print("\n[RESEARCH SCANNER] Starting broad environmental scan...")
        start_time = datetime.utcnow()

        # Run searches across all categories in parallel
        categories = [
            SourceCategory.BREAKING_NEWS,
            SourceCategory.GEOPOLITICAL,
            SourceCategory.PSYCHOLOGY_TREND,
            SourceCategory.ECONOMIC,
            SourceCategory.AI_TECH,
        ]

        print("  Running web searches...")
        tasks = [self._run_category_searches(cat) for cat in categories]
        category_results = await asyncio.gather(*tasks)

        # Organize results by category
        raw_results = {}
        total_results = 0
        for cat, results in zip(categories, category_results):
            raw_results[cat.value] = [
                {"title": r.title, "url": r.url, "content": r.content[:500]}
                for r in results
            ]
            total_results += len(results)

        print(f"  Total search results: {total_results}")

        # Synthesize candidates using Claude
        print("  Synthesizing topic candidates with Claude...")
        candidates = await self._synthesize_candidates(raw_results)
        print(f"  Generated {len(candidates)} topic candidates")

        # Calculate scan duration
        end_time = datetime.utcnow()
        duration_sec = (end_time - start_time).total_seconds()

        return {
            "raw_results": raw_results,
            "candidates": [c.to_dict() for c in candidates],
            "scan_metadata": {
                "scan_date": start_time.isoformat(),
                "duration_sec": round(duration_sec, 1),
                "total_search_results": total_results,
                "candidates_generated": len(candidates),
                "categories_scanned": [c.value for c in categories],
            },
        }

    async def _synthesize_candidates(
        self,
        raw_results: dict,
    ) -> list[TopicCandidate]:
        """Use Claude to synthesize search results into topic candidates.

        Args:
            raw_results: Dict of search results by category

        Returns:
            List of TopicCandidate objects
        """
        # Format results for the prompt
        results_text = json.dumps(raw_results, indent=2)

        # Call Claude to synthesize
        response = self.anthropic.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=4000,
            system=SCAN_SYNTHESIZER_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": f"""Analyze these search results and extract 8-12 video topic candidates:

SEARCH RESULTS BY CATEGORY:
{results_text}

Remember:
- Focus on topics that fit the dark psychology / strategic power niche
- Look for power dynamics, manipulation, strategic genius angles
- Identify underserved topics (content gaps)
- Score timeliness, audience fit, and content gap

Return JSON with candidates array.""",
                }
            ],
        )

        # Parse response
        response_text = response.content[0].text
        clean_response = response_text.replace("```json", "").replace("```", "").strip()

        try:
            data = json.loads(clean_response)
        except json.JSONDecodeError as e:
            print(f"    Warning: Failed to parse Claude response: {e}")
            return []

        # Convert to TopicCandidate objects
        candidates = []
        weights = self.config["scoring_weights"]

        for item in data.get("candidates", []):
            timeliness = item.get("timeliness_score", 5)
            audience_fit = item.get("audience_fit_score", 5)
            content_gap = item.get("content_gap_score", 5)

            # Calculate composite score
            composite = (
                timeliness * weights.timeliness
                + audience_fit * weights.audience_fit
                + content_gap * weights.content_gap
            )

            candidates.append(TopicCandidate(
                headline=item.get("headline", ""),
                source_category=item.get("source_category", "breaking_news"),
                source_urls=item.get("source_urls", []),
                timeliness_score=timeliness,
                audience_fit_score=audience_fit,
                content_gap_score=content_gap,
                composite_score=round(composite, 2),
                framework_hint=item.get("framework_hint", ""),
                reasoning=item.get("reasoning", ""),
            ))

        # Sort by composite score descending
        candidates.sort(key=lambda x: x.composite_score, reverse=True)

        return candidates

    async def score_and_rank(
        self,
        candidates: list[TopicCandidate],
    ) -> list[TopicCandidate]:
        """Re-score candidates and apply kill filters.

        This is Phase 1.5 from the PRD - takes raw candidates and
        applies editorial judgment + kill filters.

        Args:
            candidates: List of candidates from broad scan

        Returns:
            Ranked candidates with kill flags and recommendations
        """
        print("  Scoring and ranking candidates...")

        # Format candidates for scoring prompt
        candidates_text = json.dumps([c.to_dict() for c in candidates], indent=2)

        response = self.anthropic.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=3000,
            system=TOPIC_SCORER_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": f"""Score these topic candidates and apply kill filters:

CANDIDATES:
{candidates_text}

Apply these kill filters:
1. SATURATION: Flag if 3+ competitor channels likely covered this exact topic recently
2. MONETIZATION RISK: Flag topics involving violence, hate speech, etc.
3. WEAK NARRATIVE: Flag if topic can't sustain a 25-minute deep dive

Return JSON with scored_candidates array including kill_flags and selection_recommendation.""",
                }
            ],
        )

        # Parse response
        response_text = response.content[0].text
        clean_response = response_text.replace("```json", "").replace("```", "").strip()

        try:
            data = json.loads(clean_response)
        except json.JSONDecodeError as e:
            print(f"    Warning: Failed to parse scorer response: {e}")
            return candidates

        # Update candidates with scores and flags
        scored_map = {
            item["headline"]: item
            for item in data.get("scored_candidates", [])
        }

        weights = self.config["scoring_weights"]
        for candidate in candidates:
            if candidate.headline in scored_map:
                scored = scored_map[candidate.headline]
                candidate.timeliness_score = scored.get("timeliness_score", candidate.timeliness_score)
                candidate.audience_fit_score = scored.get("audience_fit_score", candidate.audience_fit_score)
                candidate.content_gap_score = scored.get("content_gap_score", candidate.content_gap_score)
                candidate.kill_flags = scored.get("kill_flags", [])
                candidate.selection_recommendation = scored.get("selection_recommendation", "backlog")

                # Recalculate composite
                candidate.composite_score = round(
                    candidate.timeliness_score * weights.timeliness
                    + candidate.audience_fit_score * weights.audience_fit
                    + candidate.content_gap_score * weights.content_gap,
                    2,
                )

        # Re-sort by composite score
        candidates.sort(key=lambda x: x.composite_score, reverse=True)

        # Mark top picks
        primary_found = False
        secondary_found = False
        for candidate in candidates:
            if candidate.kill_flags:
                candidate.selection_recommendation = "reject"
            elif not primary_found and candidate.selection_recommendation != "reject":
                candidate.selection_recommendation = "primary"
                primary_found = True
            elif not secondary_found and candidate.selection_recommendation != "reject":
                candidate.selection_recommendation = "secondary"
                secondary_found = True
            elif candidate.selection_recommendation not in ["reject"]:
                candidate.selection_recommendation = "backlog"

        return candidates

    async def run_full_phase1(self) -> dict:
        """Execute Phase 1: Broad Scan + Scoring/Ranking.

        Returns:
            Complete Phase 1 output including:
                - all_candidates: Full list with scores and recommendations
                - primary_pick: Top candidate for deep dive
                - secondary_pick: Runner-up candidate
                - scan_metadata: Timing and stats
        """
        # Run broad scan
        scan_result = await self.run_broad_scan()
        candidates = [TopicCandidate(**c) for c in scan_result["candidates"]]

        # Score and rank
        ranked_candidates = await self.score_and_rank(candidates)

        # Extract picks
        primary_pick = None
        secondary_pick = None
        for candidate in ranked_candidates:
            if candidate.selection_recommendation == "primary" and not primary_pick:
                primary_pick = candidate
            elif candidate.selection_recommendation == "secondary" and not secondary_pick:
                secondary_pick = candidate

        print("\n[RESEARCH SCANNER] Phase 1 Complete:")
        print(f"  Total candidates: {len(ranked_candidates)}")
        if primary_pick:
            print(f"  Primary pick: {primary_pick.headline} (score: {primary_pick.composite_score})")
        if secondary_pick:
            print(f"  Secondary pick: {secondary_pick.headline} (score: {secondary_pick.composite_score})")

        return {
            "all_candidates": [c.to_dict() for c in ranked_candidates],
            "primary_pick": primary_pick.to_dict() if primary_pick else None,
            "secondary_pick": secondary_pick.to_dict() if secondary_pick else None,
            "scan_metadata": scan_result["scan_metadata"],
        }
