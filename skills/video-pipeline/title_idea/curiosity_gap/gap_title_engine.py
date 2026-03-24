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
    # Financial amounts (with or without $ sign)
    if re.search(r'(\$\d+|\d+\s*(billion|trillion|million|percent|b\b|m\b))', content):
        score += 25
    # Waste/failure concepts (expanded)
    if any(word in content for word in [
        'waste', 'wasted', 'mistake', 'failed', 'failure', 'empty',
        'unused', 'worthless', 'abandoned', 'useless', 'pointless',
        'backfired', 'blunder', 'bungled', 'flop', 'flopped',
        'idle', 'sitting', 'rotting', 'crumbling', 'rusting',
    ]):
        score += 25
    # Concealment concepts (expanded)
    if any(word in content for word in [
        'hiding', 'hidden', 'secret', 'cover', 'conceal', 'quietly',
        'nobody told', 'nobody knows', 'unreported', 'silently',
        'swept under', 'buried', 'suppressed',
    ]):
        score += 20
    # Bad bet / wrong strategy concepts
    if any(word in content for word in [
        'bet', 'gamble', 'gambled', 'miscalculated', 'overestimated',
        'wrong', 'shifted', 'obsolete', 'stranded', 'bet everything',
        'backfire', 'shortsighted', 'hubris',
    ]):
        score += 15
    # Scale amplifiers
    if any(word in content for word in [
        'billion', 'trillion', 'million', 'massive', 'enormous',
        'colossal', '100b', '500m', 'hundreds of',
    ]):
        score += 15

    return min(100, score)


def _score_asymmetric_dg(hook: str, thesis: str, facts: List[str]) -> int:
    """Score for asymmetric_dg: small vs big, David vs Goliath."""
    content = f"{hook} {thesis} {' '.join(facts)}".lower()

    score = 0
    # Small/cheap thing (expanded)
    if any(word in content for word in [
        'small', 'tiny', 'cheap', 'simple', 'basic', 'primitive',
        'homemade', 'improvised', 'low-cost', 'inexpensive',
        '$500', '$100', '$50', 'few hundred', 'fraction',
    ]):
        score += 25
    # Fear/threat from powerful entity (expanded)
    if any(word in content for word in [
        'terrified', 'afraid', 'fear', 'scared', 'worried',
        'nightmare', 'threat', 'vulnerable', 'powerless',
        'can\'t stop', 'cannot stop', 'helpless',
    ]):
        score += 20
    # Big/powerful entity (expanded)
    if any(word in content for word in [
        'navy', 'military', 'army', 'superpower', 'pentagon',
        'billion-dollar', 'trillion', 'aircraft carrier', 'fleet',
        'empire', 'giant', 'goliath', 'massive', 'powerful',
    ]):
        score += 20
    # Outcome concepts (expanded)
    if any(word in content for word in [
        'beat', 'defeat', 'destroy', 'stop', 'cripple', 'sink',
        'neutralize', 'outmaneuver', 'outsmart', 'overwhelm',
    ]):
        score += 15
    # Small weapon/tool examples (expanded)
    if any(word in content for word in [
        'drone', 'boat', 'missile', 'plastic', 'raft', 'swarm',
        'explosive', 'mine', 'device', 'weapon',
    ]):
        score += 10

    return min(100, score)


def _score_time_bomb(hook: str, thesis: str, facts: List[str]) -> int:
    """Score for time_bomb: long-term traps, delayed consequences."""
    content = f"{hook} {thesis} {' '.join(facts)}".lower()

    score = 0
    # Time patterns (expanded)
    if re.search(r'(\d+[- ]year|\d+[- ]decade|\d+ years|\d+ decades)', content):
        score += 30
    # Trap concepts (expanded)
    if any(word in content for word in [
        'trap', 'trapped', 'walked into', 'locked in', 'locked into',
        'stuck', 'cornered', 'boxed in', 'no way out', 'no escape',
        'painted into', 'checkmate', 'inevitable',
    ]):
        score += 25
    # Long-term timeframes (expanded)
    if any(word in content for word in [
        'decade', 'decades', 'long-term', 'slow', 'gradual',
        'years ago', 'seeds', 'building', 'brewing', 'festering',
        'accumulating', 'compounding', 'generation',
    ]):
        score += 20
    # Setup/planting concepts (expanded)
    if any(word in content for word in [
        'set up', 'planted', 'waiting', 'ticking', 'dormant',
        'laid the groundwork', 'sowed', 'roots', 'foundation',
    ]):
        score += 15
    # Trigger/consequence concepts (expanded)
    if any(word in content for word in [
        'trigger', 'explode', 'collapse', 'unravel', 'implode',
        'come due', 'reckoning', 'chickens come home', 'finally',
        'about to', 'on the verge', 'tipping point',
    ]):
        score += 10

    return min(100, score)


def _score_paradigm_shift(hook: str, thesis: str, facts: List[str]) -> int:
    """Score for paradigm_shift: reframing, hidden truths."""
    content = f"{hook} {thesis} {' '.join(facts)}".lower()

    score = 0
    # Evidence/proof concepts (expanded)
    if any(word in content for word in [
        'proves', 'proof', 'evidence', 'map', 'reveals', 'shows',
        'demonstrates', 'exposes', 'uncovers', 'confirms',
    ]):
        score += 25
    # Already happening concepts (expanded)
    if any(word in content for word in [
        'already', 'begun', 'started', 'happening', 'underway',
        'in motion', 'unfolding', 'right now', 'as we speak',
    ]):
        score += 20
    # Belief challenge concepts (expanded)
    if any(word in content for word in [
        'think', 'believe', 'assume', 'reality', 'actually',
        'really', 'truth', 'myth', 'lie', 'misconception',
        'wrong about', 'misunderstand', 'didn\'t know',
    ]):
        score += 20
    # Big event reframes (expanded)
    if any(word in content for word in [
        'wwiii', 'war', 'conflict', 'crisis', 'collapse',
        'revolution', 'shift', 'change everything', 'new era',
    ]):
        score += 15
    # Hidden/overlooked concepts (expanded)
    if any(word in content for word in [
        'missing', 'overlooked', 'ignored', 'nobody noticed',
        'under the radar', 'quietly', 'without anyone knowing',
        'blind spot', 'invisible',
    ]):
        score += 15

    return min(100, score)


def _score_illusion_control(hook: str, thesis: str, facts: List[str]) -> int:
    """Score for illusion_control: personal stakes, affects YOU."""
    content = f"{hook} {thesis} {' '.join(facts)}".lower()

    score = 0
    # Direct personal address (expanded)
    if any(word in content for word in [
        'your', 'you', 'everyone', 'every american', 'we all',
        'our', 'us', 'ordinary people', 'average person',
        'consumers', 'citizens', 'taxpayers',
    ]):
        score += 30
    # Financial personal stakes (expanded)
    if any(word in content for word in [
        'bank', 'money', 'savings', 'wallet', 'paycheck',
        '401k', 'retirement', 'mortgage', 'debt', 'income',
        'grocery', 'rent', 'bills', 'afford',
    ]):
        score += 25
    # Control/power concepts (expanded)
    if any(word in content for word in [
        'control', 'controls', 'chokepoint', 'leverage', 'power over',
        'dictate', 'determine', 'decide', 'manipulate', 'rig',
    ]):
        score += 20
    # Impact concepts (expanded)
    if any(word in content for word in [
        'affect', 'impact', 'change', 'hit', 'hurt', 'harm',
        'feel', 'notice', 'see', 'experience',
    ]):
        score += 15
    # Price/cost concepts (expanded)
    if any(word in content for word in [
        'price', 'cost', 'pay', 'inflation', 'expensive',
        'rising', 'skyrocket', 'surge', 'double', 'triple',
    ]):
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

    async def _generate_mf_titles(
        self,
        story_context: Dict,
        count: int = 3,
    ) -> List[GeneratedTitle]:
        """Generate titles using MF fallback formulas.

        Args:
            story_context: Dict with hook, thesis, facts
            count: Number of titles to generate

        Returns:
            List of GeneratedTitle using MF formulas
        """
        mf_ids = list(MF_FORMULAS.keys())[:count]

        prompt = f"""Generate YouTube titles using these formula templates.

STORY CONTEXT:
Hook: {story_context.get('hook', '')}
Thesis: {story_context.get('thesis', '')}

FORMULAS TO USE:
{chr(10).join([f"- {mf_id}: {MF_FORMULAS[mf_id]['template']}" for mf_id in mf_ids])}

For each formula:
1. Replace [Entity], [Location], etc. with story-specific values
2. Generate thumbnail_text (2-4 words, ALL CAPS)
3. Use thumbnail_approach "from_gap"

Return JSON only:
{{
  "titles": [
    {{
      "text": "How Iran Turned Hormuz Into a Hostage",
      "structure": "other",
      "confidence": 50,
      "thumbnail_text": "CHOKEPOINT",
      "thumbnail_approach": "from_gap",
      "reasoning": "MF-0 CHOKE POINT formula"
    }}
  ]
}}"""

        result = await self._call_claude_for_titles(prompt)

        titles = []
        for item in result.get("titles", []):
            titles.append(GeneratedTitle(
                text=item.get("text", ""),
                structure=CuriosityStructure.OTHER,
                structure_confidence=item.get("confidence", 50),
                thumbnail_text=item.get("thumbnail_text", ""),
                thumbnail_approach="from_gap",
                reasoning=item.get("reasoning", "MF fallback"),
            ))

        return titles

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

        # Check if we need MF fallbacks
        mf_count = get_mf_fallback_count(len(structures_to_use), target_count)

        if mf_count > 0 and not structures_to_use:
            # All structures below floor - pure MF fallback
            return await self._generate_mf_titles(story_context, target_count)

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
