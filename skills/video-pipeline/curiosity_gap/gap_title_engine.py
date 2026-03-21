"""Curiosity gap title generation engine.

Generates titles using 5 curiosity gap structures, scoring each against
story content. Falls back to MF formulas when <3 structures score above
the confidence floor (60).

NOTE: This file is named gap_title_engine.py (NOT title_generator.py)
to avoid confusion with thumbnail_title/title_generator.py which handles
thumbnail text formatting.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Dict, List
from curiosity_gap.structures import CuriosityStructure, get_main_structures, STRUCTURE_DEFINITIONS
from pipeline_constants import CURIOSITY_GAP_ENABLED, Models


# Confidence floor - structures must score at least this to generate titles
CONFIDENCE_FLOOR = 60


@dataclass
class ScoredStructure:
    """A curiosity gap structure with its fit score for a story."""
    structure: CuriosityStructure
    confidence: int  # 0-100
    reasoning: str


@dataclass
class GeneratedTitle:
    """A generated title with its curiosity gap metadata."""
    text: str                        # "The $100B Mistake Saudi Arabia Is Hiding"
    structure: CuriosityStructure    # HIDDEN_FLAW
    structure_confidence: int        # 78
    thumbnail_text: str              # "WORTHLESS PIPELINES"
    thumbnail_approach: str          # "from_gap" or "from_hook"
    reasoning: str                   # "Story has clear financial waste angle..."

    # Traceability
    source_patterns: List[str] = field(default_factory=list)       # ["competitor:rec123"]
    competitor_video_ids: List[str] = field(default_factory=list)  # Airtable record IDs


def _score_hidden_flaw(hook: str, thesis: str, facts: List[str]) -> int:
    """Score for hidden_flaw: financial waste, mistakes, cover-ups."""
    content = f"{hook} {thesis} {' '.join(facts)}".lower()

    score = 0
    # Financial waste indicators
    if re.search(r'\$\d+[mb]?\b', content):  # Dollar amounts
        score += 25
    if any(word in content for word in ['waste', 'wasted', 'mistake', 'failed', 'failure']):
        score += 25
    if any(word in content for word in ['hiding', 'hidden', 'secret', 'cover']):
        score += 20
    if any(word in content for word in ['billion', 'trillion', 'million']):
        score += 15
    if any(word in content for word in ['abandoned', 'empty', 'unused', 'worthless']):
        score += 15

    return min(100, score)


def _score_asymmetric_dg(hook: str, thesis: str, facts: List[str]) -> int:
    """Score for asymmetric_dg: small vs big, David vs Goliath."""
    content = f"{hook} {thesis} {' '.join(facts)}".lower()

    score = 0
    if any(word in content for word in ['small', 'tiny', 'cheap', '$500', '$100']):
        score += 25
    if any(word in content for word in ['terrified', 'afraid', 'fear', 'scared']):
        score += 20
    if any(word in content for word in ['navy', 'military', 'army', 'superpower']):
        score += 20
    if any(word in content for word in ['beat', 'defeat', 'destroy', 'stop']):
        score += 15
    if any(word in content for word in ['drone', 'boat', 'missile', 'plastic']):
        score += 10

    return min(100, score)


def _score_time_bomb(hook: str, thesis: str, facts: List[str]) -> int:
    """Score for time_bomb: long-term traps, delayed consequences."""
    content = f"{hook} {thesis} {' '.join(facts)}".lower()

    score = 0
    if re.search(r'\d+[- ]year', content):  # X-year patterns
        score += 30
    if any(word in content for word in ['trap', 'trapped', 'walked into']):
        score += 25
    if any(word in content for word in ['decade', 'decades', 'long-term', 'slow']):
        score += 20
    if any(word in content for word in ['set up', 'planted', 'waiting']):
        score += 15
    if any(word in content for word in ['trigger', 'explode', 'collapse']):
        score += 10

    return min(100, score)


def _score_paradigm_shift(hook: str, thesis: str, facts: List[str]) -> int:
    """Score for paradigm_shift: reframing, hidden truths."""
    content = f"{hook} {thesis} {' '.join(facts)}".lower()

    score = 0
    if any(word in content for word in ['proves', 'proof', 'evidence', 'map']):
        score += 25
    if any(word in content for word in ['already', 'begun', 'started', 'happening']):
        score += 20
    if any(word in content for word in ['think', 'believe', 'assume', 'reality']):
        score += 20
    if any(word in content for word in ['wwiii', 'war', 'conflict', 'crisis']):
        score += 15
    if any(word in content for word in ['missing', 'overlooked', 'ignored']):
        score += 15

    return min(100, score)


def _score_illusion_control(hook: str, thesis: str, facts: List[str]) -> int:
    """Score for illusion_control: personal stakes, affects YOU."""
    content = f"{hook} {thesis} {' '.join(facts)}".lower()

    score = 0
    if any(word in content for word in ['your', 'you', 'everyone', 'every american']):
        score += 30
    if any(word in content for word in ['bank', 'money', 'savings', 'wallet']):
        score += 25
    if any(word in content for word in ['control', 'controls', 'chokepoint']):
        score += 20
    if any(word in content for word in ['affect', 'impact', 'change']):
        score += 15
    if any(word in content for word in ['price', 'cost', 'pay', 'inflation']):
        score += 10

    return min(100, score)


STRUCTURE_SCORERS = {
    CuriosityStructure.HIDDEN_FLAW: _score_hidden_flaw,
    CuriosityStructure.ASYMMETRIC_DG: _score_asymmetric_dg,
    CuriosityStructure.TIME_BOMB: _score_time_bomb,
    CuriosityStructure.PARADIGM_SHIFT: _score_paradigm_shift,
    CuriosityStructure.ILLUSION_CONTROL: _score_illusion_control,
}


# MF (existing formula) fallbacks - used when <3 structures score above floor
# These are simplified versions of formulas from trending_idea_bot.py
MF_FORMULAS = {
    "MF-0": {
        "name": "CHOKE POINT",
        "template": "How [Entity] Turned [Location] Into a Hostage",
        "description": "Geographic/strategic control framing",
    },
    "MF-1": {
        "name": "GEOGRAPHIC TRAP",
        "template": "How [Entity] Quietly Weaponized [Geography]",
        "description": "Terrain as weapon framing",
    },
    "MF-2": {
        "name": "EXITS LOCKED",
        "template": "Why [Entity] Can't Escape [Constraint]",
        "description": "No escape framing",
    },
}


def get_viable_structures(
    scores: List[ScoredStructure],
    min_confidence: int = CONFIDENCE_FLOOR,
) -> List[ScoredStructure]:
    """Filter structures to those above confidence floor.

    Args:
        scores: List of scored structures
        min_confidence: Minimum confidence to be viable

    Returns:
        Filtered list of viable structures
    """
    return [s for s in scores if s.confidence >= min_confidence]


def get_mf_fallback_count(viable_count: int, target: int = 3) -> int:
    """Calculate how many MF fallback titles needed.

    Args:
        viable_count: Number of structures above confidence floor
        target: Target number of titles to generate

    Returns:
        Number of MF fallbacks needed
    """
    return max(0, target - viable_count)


def score_structures(story_context: Dict) -> List[ScoredStructure]:
    """Score all 5 structures against story content.

    Args:
        story_context: Dict with 'hook', 'thesis', 'facts' keys

    Returns:
        List of ScoredStructure sorted by confidence descending
    """
    hook = story_context.get("hook", "")
    thesis = story_context.get("thesis", "")
    facts = story_context.get("facts", [])

    scores = []
    for structure in get_main_structures():
        scorer = STRUCTURE_SCORERS[structure]
        confidence = scorer(hook, thesis, facts)
        defn = STRUCTURE_DEFINITIONS[structure]

        scores.append(ScoredStructure(
            structure=structure,
            confidence=confidence,
            reasoning=f"Scored {confidence}/100 for '{defn['gap_mechanism']}'",
        ))

    # Sort by confidence descending
    return sorted(scores, key=lambda s: s.confidence, reverse=True)


class GapTitleEngine:
    """Generate titles using curiosity gap structures."""

    def __init__(self, anthropic_client=None):
        """Initialize engine.

        Args:
            anthropic_client: AnthropicClient instance (lazy loaded if None)
        """
        self._anthropic_client = anthropic_client

    @property
    def anthropic_client(self):
        if self._anthropic_client is None:
            from clients.anthropic_client import AnthropicClient
            self._anthropic_client = AnthropicClient()
        return self._anthropic_client

    def _build_generation_prompt(
        self,
        story_context: Dict,
        scored_structures: List[ScoredStructure],
        pattern_context: str = "",
    ) -> str:
        """Build Claude prompt for title generation."""
        structures_text = "\n".join([
            f"- {s.structure.value} (confidence: {s.confidence}): {s.reasoning}"
            for s in scored_structures
        ])

        prompt = f"""Generate YouTube titles for Power Doctrine channel using curiosity gap structures.

STORY CONTEXT:
Hook: {story_context.get('hook', '')}
Thesis: {story_context.get('thesis', '')}
Key facts: {json.dumps(story_context.get('facts', []))}

STRUCTURES TO USE (generate one title per structure):
{structures_text}

{pattern_context}

For each structure, generate:
1. title text (create cognitive dissonance, force the click)
2. thumbnail_text (2-4 words, ALL CAPS, yin/yang complement to title)
3. thumbnail_approach ("from_hook" or "from_gap")
4. reasoning (why this title works for this structure)

Return JSON only:
{{
  "titles": [
    {{
      "text": "The $100B Mistake Saudi Arabia Is Hiding",
      "structure": "hidden_flaw",
      "confidence": 85,
      "thumbnail_text": "WORTHLESS PIPELINES",
      "thumbnail_approach": "from_gap",
      "reasoning": "Clear financial waste angle"
    }}
  ]
}}"""
        return prompt

    async def _call_claude_for_titles(self, prompt: str) -> Dict:
        """Call Claude to generate titles."""
        response = await self.anthropic_client.generate(
            prompt=prompt,
            model=Models.CLAUDE_SONNET,
            max_tokens=2000,
            temperature=0.7,
        )

        # Parse JSON response
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
            return {"titles": []}

    async def generate_titles(
        self,
        story_context: Dict,
        pattern_library=None,
        target_count: int = 3,
    ) -> List[GeneratedTitle]:
        """Generate titles using curiosity gap structures."""
        # Kill switch check
        if not CURIOSITY_GAP_ENABLED:
            return []

        # Score structures
        scores = score_structures(story_context)
        viable = get_viable_structures(scores)

        # Determine which structures to use
        structures_to_use = viable[:target_count]

        # Get pattern context if library provided
        pattern_context = ""
        if pattern_library:
            gap_patterns = pattern_library.get_curiosity_gap_patterns()
            if gap_patterns:
                pattern_context = "PROVEN PATTERNS:\n" + "\n".join([
                    f"- {p.structure.value}: avg VPH {p.avg_vph_competitors}"
                    for p in gap_patterns if p.avg_vph_competitors
                ])

        if not structures_to_use:
            return []

        # Build prompt and call Claude
        prompt = self._build_generation_prompt(
            story_context,
            structures_to_use,
            pattern_context,
        )

        result = await self._call_claude_for_titles(prompt)

        # Parse response into GeneratedTitle objects
        titles = []
        for item in result.get("titles", []):
            try:
                structure = CuriosityStructure(item.get("structure", "other"))
            except ValueError:
                structure = CuriosityStructure.OTHER

            titles.append(GeneratedTitle(
                text=item.get("text", ""),
                structure=structure,
                structure_confidence=item.get("confidence", 0),
                thumbnail_text=item.get("thumbnail_text", ""),
                thumbnail_approach=item.get("thumbnail_approach", "from_gap"),
                reasoning=item.get("reasoning", ""),
            ))

        # Sort by confidence
        return sorted(titles, key=lambda t: t.structure_confidence, reverse=True)
