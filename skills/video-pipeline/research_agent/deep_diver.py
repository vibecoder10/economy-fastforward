"""Deep Diver - Comprehensive research using iterative prompt chain.

Architecture: 3-Phase Chain (matching the prompt chain spec)
- Phase 2: Deep Research (Initial → Gap Analysis → Consolidation)
- Phase 3: Strategic Analysis (Framework Analysis → Final Compilation)

Total estimated cost: $2-4/topic
Total estimated time: 10-15 minutes
"""

import os
import json
import asyncio
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, field, asdict

import httpx
from anthropic import Anthropic

from .config import RESEARCH_CONFIG
from .prompts.deep_dive_prompts import (
    PROMPT_2_1_INITIAL_RESEARCH,
    PROMPT_2_2_GAP_ANALYSIS,
    PROMPT_2_3_FACT_CONSOLIDATION,
    PROMPT_3_1_STRATEGIC_ANALYSIS,
    PROMPT_3_2_FINAL_COMPILATION,
)


@dataclass
class ResearchBrief:
    """Complete research brief for a video topic."""
    headline: str
    source_category: str
    framework_angle: str

    # Research artifacts
    executive_hook: str = ""
    thesis: str = ""
    fact_sheet: str = ""
    historical_parallels: str = ""
    framework_analysis: str = ""
    character_dossier: str = ""
    narrative_arc: str = ""
    counter_arguments: str = ""
    visual_seeds: str = ""
    title_options: str = ""
    thumbnail_concepts: str = ""
    source_bibliography: str = ""

    # Metadata
    evergreen_flag: bool = False
    monetization_risk: str = "low"
    research_duration_sec: float = 0
    total_sources_used: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


class DeepDiver:
    """Executes the 3-phase deep research chain."""

    def __init__(
        self,
        tavily_api_key: Optional[str] = None,
        anthropic_api_key: Optional[str] = None,
    ):
        """Initialize with API clients."""
        self.tavily_api_key = tavily_api_key or os.getenv("TAVILY_API_KEY")
        if not self.tavily_api_key:
            raise ValueError("TAVILY_API_KEY not found")

        self.anthropic_api_key = anthropic_api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY not found")

        self.anthropic = Anthropic(api_key=self.anthropic_api_key)
        self.config = RESEARCH_CONFIG

    async def _tavily_search(
        self,
        query: str,
        search_depth: str = "advanced",
        max_results: int = 10,
        include_raw: bool = True,
    ) -> list[dict]:
        """Execute a Tavily search."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": self.tavily_api_key,
                    "query": query,
                    "search_depth": search_depth,
                    "max_results": max_results,
                    "include_raw_content": include_raw,
                },
                timeout=45.0,
            )
            response.raise_for_status()
            data = response.json()

        return [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": r.get("content", "")[:3000],
                "raw_content": (r.get("raw_content") or "")[:8000],
                "published_date": r.get("published_date", ""),
            }
            for r in data.get("results", [])
        ]

    def _call_claude(
        self,
        prompt: str,
        system_prompt: str = "",
        model: str = "claude-sonnet-4-5-20250929",
        max_tokens: int = 8000,
    ) -> str:
        """Make a Claude API call."""
        messages = [{"role": "user", "content": prompt}]
        kwargs = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system_prompt:
            kwargs["system"] = system_prompt

        response = self.anthropic.messages.create(**kwargs)
        return response.content[0].text

    async def run_deep_dive(self, topic: dict) -> ResearchBrief:
        """Execute the full 3-phase research chain.

        Phase 2: Deep Research
          2.1 Initial Source Gathering
          2.2 Gap Analysis & Second Pass
          2.3 Fact Verification & Consolidation

        Phase 3: Strategic Analysis
          3.1 Framework Analysis & Narrative Architecture
          3.2 Final Brief Compilation
        """
        print(f"\n[DEEP DIVER] Starting 3-phase research chain...")
        start_time = datetime.utcnow()

        # Extract topic info
        headline = topic.get("headline") or topic.get("Headline", "")
        source_category = topic.get("source_category") or topic.get("Source Category", "")
        framework = topic.get("framework_hint") or topic.get("Framework Angle", "48 Laws")
        source_urls = topic.get("source_urls") or topic.get("Source URLs", "")

        print(f"  Topic: {headline[:60]}...")
        print(f"  Framework: {framework}")

        # ============================================================
        # PHASE 2: DEEP RESEARCH
        # ============================================================
        print("\n  === PHASE 2: DEEP RESEARCH ===")

        # 2.1 Initial Source Gathering
        print("  [2.1] Initial source gathering...")
        initial_research = await self._phase_2_1_initial_research(
            headline, framework, source_urls
        )

        # 2.2 Gap Analysis & Second Research Pass
        print("  [2.2] Gap analysis & second pass...")
        gap_research = await self._phase_2_2_gap_analysis(
            headline, framework, initial_research
        )

        # 2.3 Fact Verification & Consolidation
        print("  [2.3] Fact consolidation...")
        consolidated = self._phase_2_3_consolidation(
            headline, initial_research, gap_research
        )

        # ============================================================
        # PHASE 3: STRATEGIC ANALYSIS
        # ============================================================
        print("\n  === PHASE 3: STRATEGIC ANALYSIS ===")

        # 3.1 Framework Analysis & Narrative Architecture
        print("  [3.1] Framework analysis & narrative...")
        strategic_analysis = self._phase_3_1_strategic_analysis(
            headline, framework, consolidated
        )

        # 3.2 Final Brief Compilation
        print("  [3.2] Compiling final brief...")
        brief = self._phase_3_2_compilation(
            headline, source_category, framework,
            consolidated, strategic_analysis
        )

        # Calculate duration
        end_time = datetime.utcnow()
        brief.research_duration_sec = (end_time - start_time).total_seconds()

        print(f"\n[DEEP DIVER] Complete in {brief.research_duration_sec:.1f}s")

        return brief

    # ============================================================
    # PHASE 2.1: Initial Source Gathering
    # ============================================================
    async def _phase_2_1_initial_research(
        self,
        headline: str,
        framework: str,
        source_urls: str,
    ) -> str:
        """Deep factual research from multiple angles."""

        # Run multiple targeted searches
        search_queries = [
            headline,
            f"{headline} facts statistics data figures",
            f"{headline} timeline chronology history",
            f"{headline} key players involved who",
            f"{headline} analysis expert opinion",
            f"{headline} critics criticism opposing view",
        ]

        all_sources = []
        for query in search_queries:
            try:
                results = await self._tavily_search(query, max_results=6)
                all_sources.extend(results)
                print(f"      '{query[:40]}...' -> {len(results)} results")
            except Exception as e:
                print(f"      Search error: {e}")

        # Dedupe by URL
        seen = set()
        unique_sources = []
        for s in all_sources:
            if s["url"] not in seen:
                seen.add(s["url"])
                unique_sources.append(s)

        # Format sources for prompt
        sources_text = "\n\n---\n\n".join([
            f"SOURCE: {s['title']}\nURL: {s['url']}\nDATE: {s.get('published_date', 'Unknown')}\n\nCONTENT:\n{s['content']}"
            for s in unique_sources[:12]
        ])

        prompt = PROMPT_2_1_INITIAL_RESEARCH.format(
            topic=headline,
            framework=framework,
            initial_sources=source_urls,
            search_results=sources_text,
        )

        return self._call_claude(prompt, model="claude-sonnet-4-5-20250929", max_tokens=6000)

    # ============================================================
    # PHASE 2.2: Gap Analysis & Second Research Pass
    # ============================================================
    async def _phase_2_2_gap_analysis(
        self,
        headline: str,
        framework: str,
        initial_research: str,
    ) -> str:
        """Fill gaps identified in first research pass."""

        # Targeted searches for gaps and historical parallels
        gap_queries = [
            f"{headline} historical precedent parallel similar",
            f"{headline} underreported hidden angle",
            f"history of {headline.split(':')[0]} origins",
            f"{headline} power dynamics who benefits",
            f"{headline} quotes statements key players said",
        ]

        all_sources = []
        for query in gap_queries:
            try:
                results = await self._tavily_search(query, max_results=5)
                all_sources.extend(results)
                print(f"      '{query[:40]}...' -> {len(results)} results")
            except Exception as e:
                print(f"      Search error: {e}")

        # Dedupe
        seen = set()
        unique_sources = []
        for s in all_sources:
            if s["url"] not in seen:
                seen.add(s["url"])
                unique_sources.append(s)

        sources_text = "\n\n---\n\n".join([
            f"SOURCE: {s['title']}\nURL: {s['url']}\n\nCONTENT:\n{s['content']}"
            for s in unique_sources[:10]
        ])

        prompt = PROMPT_2_2_GAP_ANALYSIS.format(
            topic=headline,
            framework=framework,
            initial_research=initial_research[:8000],
            gap_search_results=sources_text,
        )

        return self._call_claude(prompt, model="claude-sonnet-4-5-20250929", max_tokens=5000)

    # ============================================================
    # PHASE 2.3: Fact Verification & Consolidation
    # ============================================================
    def _phase_2_3_consolidation(
        self,
        headline: str,
        initial_research: str,
        gap_research: str,
    ) -> str:
        """Merge, deduplicate, verify, and organize all research."""

        prompt = PROMPT_2_3_FACT_CONSOLIDATION.format(
            topic=headline,
            research_pass_1=initial_research,
            research_pass_2=gap_research,
        )

        return self._call_claude(prompt, model="claude-sonnet-4-5-20250929", max_tokens=8000)

    # ============================================================
    # PHASE 3.1: Strategic Analysis & Narrative Architecture
    # ============================================================
    def _phase_3_1_strategic_analysis(
        self,
        headline: str,
        framework: str,
        consolidated_research: str,
    ) -> str:
        """Map framework, build story arc, generate creative outputs."""

        # Get framework details from config
        framework_lib = self.config.get("framework_library", {})

        prompt = PROMPT_3_1_STRATEGIC_ANALYSIS.format(
            topic=headline,
            framework=framework,
            framework_library=json.dumps(framework_lib, indent=2),
            verified_research=consolidated_research,
        )

        # Use Opus for highest quality strategic analysis
        return self._call_claude(
            prompt,
            model="claude-opus-4-5-20251101",
            max_tokens=8000,
        )

    # ============================================================
    # Helper: Extract fields manually from text
    # ============================================================
    def _extract_fields_manually(
        self,
        response: str,
        strategic_analysis: str,
        consolidated_research: str,
    ) -> Optional[dict]:
        """Try to extract structured data from non-JSON response."""
        import re

        data = {}

        # Try to find section patterns like "Executive Hook:" or "## Executive Hook"
        patterns = {
            "Executive Hook": r"(?:Executive Hook|HOOK)[:\s]*([^\n]+(?:\n(?![A-Z#])[^\n]+)*)",
            "Thesis": r"(?:Thesis|THESIS)[:\s]*([^\n]+)",
            "Title Options": r"(?:Title Options|TITLES?)[:\s]*([^\n]+(?:\n(?![A-Z#])[^\n]+)*)",
            "Thumbnail Concepts": r"(?:Thumbnail|THUMBNAIL)[:\s]*([^\n]+(?:\n(?![A-Z#])[^\n]+)*)",
        }

        for field, pattern in patterns.items():
            match = re.search(pattern, response, re.IGNORECASE)
            if match:
                data[field] = match.group(1).strip()

        # Use strategic analysis for narrative fields
        if strategic_analysis:
            if "NARRATIVE ARC" in strategic_analysis.upper():
                data["Narrative Arc"] = strategic_analysis[:4000]
            if "CHARACTER" in strategic_analysis.upper():
                data["Character Dossier"] = strategic_analysis[:3000]
            if "FRAMEWORK" in strategic_analysis.upper():
                data["Framework Analysis"] = strategic_analysis[:4000]

        # Use consolidated research for fact sheet
        if consolidated_research:
            data["Fact Sheet"] = consolidated_research[:6000]

        return data if data else None

    # ============================================================
    # PHASE 3.2: Final Brief Compilation
    # ============================================================
    def _phase_3_2_compilation(
        self,
        headline: str,
        source_category: str,
        framework: str,
        consolidated_research: str,
        strategic_analysis: str,
    ) -> ResearchBrief:
        """Compile everything into Airtable-ready format."""

        prompt = PROMPT_3_2_FINAL_COMPILATION.format(
            topic=headline,
            source_category=source_category,
            framework=framework,
            consolidated_research=consolidated_research,
            strategic_analysis=strategic_analysis,
        )

        response = self._call_claude(prompt, model="claude-sonnet-4-5-20250929", max_tokens=12000)

        # Parse JSON response
        try:
            clean = response.replace("```json", "").replace("```", "").strip()
            # Find the JSON object
            start = clean.find("{")
            end = clean.rfind("}") + 1
            if start >= 0 and end > start:
                json_str = clean[start:end]
                # Fix common JSON issues
                json_str = json_str.replace('\n', '\\n').replace('\t', '\\t')
                # Try parsing
                data = json.loads(json_str)
            else:
                raise ValueError("No JSON found in response")
        except (json.JSONDecodeError, ValueError) as e:
            print(f"      Warning: JSON parse failed: {e}")
            # Try to extract fields manually from the response
            data = self._extract_fields_manually(response, strategic_analysis, consolidated_research)
            if not data:
                print(f"      Fallback: using raw research data")
                return ResearchBrief(
                    headline=headline,
                    source_category=source_category,
                    framework_angle=framework,
                    framework_analysis=strategic_analysis[:8000],
                    fact_sheet=consolidated_research[:8000],
                )

        # Build ResearchBrief from parsed data
        return ResearchBrief(
            headline=data.get("Headline", headline),
            source_category=data.get("Source Category", source_category),
            framework_angle=data.get("Framework Angle", framework),
            executive_hook=data.get("Executive Hook", ""),
            thesis=data.get("Thesis", ""),
            fact_sheet=data.get("Fact Sheet", ""),
            historical_parallels=data.get("Historical Parallels", ""),
            framework_analysis=data.get("Framework Analysis", ""),
            character_dossier=data.get("Character Dossier", ""),
            narrative_arc=data.get("Narrative Arc", ""),
            counter_arguments=data.get("Counter Arguments", ""),
            visual_seeds=data.get("Visual Seeds", ""),
            title_options=data.get("Title Options", ""),
            thumbnail_concepts=data.get("Thumbnail Concepts", ""),
            source_bibliography=data.get("Source Bibliography", ""),
            evergreen_flag=data.get("Evergreen Flag", False),
            monetization_risk=data.get("Monetization Risk", "low"),
        )
