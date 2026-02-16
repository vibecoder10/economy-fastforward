"""Title generator for Economy FastForward videos.

Produces titles that follow proven formula patterns.  Each title contains
exactly ONE CAPS word that becomes the red_word in the paired thumbnail.

Six formula families:
  1. The [Noun] TRAP Nobody Sees Coming (Parenthetical)
  2. [Country]'s $[Amount] [Mistake/Gamble] (The [Named Trap])
  3. The Slow DEATH of [System] (And Who Controls What Comes Next)
  4. Why [Country] is [ADJECTIVE]er Than You Think (The Hidden Strategy)
  5. [Number] [Noun] [Warning] (Machiavelli Warned You)
  6. How [Entity] SWALLOWED [Target] (The [X]-Stage Playbook)
"""

import json
from typing import Optional


# ---------------------------------------------------------------------------
# Title formula definitions
# ---------------------------------------------------------------------------
TITLE_FORMULAS = {
    "formula_1": {
        "name": "The [Noun] TRAP Nobody Sees Coming",
        "pattern": "The {noun} {caps_word} Nobody Sees Coming ({parenthetical})",
        "examples": [
            "The Robot TRAP Nobody Sees Coming (A 4-Stage Monopoly)",
            "The Dollar TRAP Nobody Sees Coming (Why Cash Is a Weapon)",
            "The Housing TRAP Nobody Sees Coming (And Who Profits)",
        ],
    },
    "formula_2": {
        "name": "[Country]'s $[Amount] [Mistake/Gamble]",
        "pattern": "{country}'s {amount} {caps_word} ({parenthetical})",
        "examples": [
            "America's $34 Trillion Debt WEAPON (The Machiavellian Strategy)",
            "China's $3 Trillion Dollar TRAP (The Silent Economic War)",
            "Germany's $500 Billion MISTAKE (Why Green Energy Failed)",
        ],
    },
    "formula_3": {
        "name": "The Slow DEATH of [System]",
        "pattern": "The Slow {caps_word} of {system} ({parenthetical})",
        "examples": [
            "The Slow DEATH of the Dollar (And Who Controls What Replaces It)",
            "The Slow COLLAPSE of NATO (And Russia's Play to Replace It)",
            "The Slow DEATH of the Middle Class (And Who's Engineering It)",
        ],
    },
    "formula_4": {
        "name": "Why [Country] is [ADJECTIVE]er Than You Think",
        "pattern": "Why {country} is {caps_word} Than You Think ({parenthetical})",
        "examples": [
            "Why Russia is STRONGER Than You Think (The Machiavellian Energy Play)",
            "Why America is WEAKER Than You Think (The Hidden Debt Pattern)",
            "Why China is RICHER Than You Think (The Strategy Nobody Discusses)",
        ],
    },
    "formula_5": {
        "name": "[Number] [Noun] [Warning]",
        "pattern": "{number} {noun} {caps_word} ({parenthetical})",
        "examples": [
            "7 Economic LIES They Need You to Believe (Machiavelli Warned You)",
            "5 Signs Your Country's Economy is DYING (The Pattern Repeats)",
            "9 Financial TRAPS Designed to Keep You Poor (The System Explained)",
        ],
    },
    "formula_6": {
        "name": "How [Entity] SWALLOWED [Target]",
        "pattern": "How {entity} {caps_word} {target} ({parenthetical})",
        "examples": [
            "How Blackrock SWALLOWED the Housing Market (The 3-Stage Playbook)",
            "How AI SWALLOWED Your Job Market (The 4-Stage Monopoly Trap)",
            "How Debt SWALLOWED the American Dream (The Machiavellian Design)",
        ],
    },
}


# System prompt for Claude to generate title + variables
TITLE_GENERATION_SYSTEM_PROMPT = """\
You are the title strategist for Economy FastForward, a finance/economics YouTube channel.

Your job: Generate a click-worthy title that follows one of the proven formula patterns.

RULES:
1. The title MUST contain exactly ONE word in ALL CAPS — this is the curiosity trigger.
2. The CAPS word becomes the red highlight in the thumbnail. Pick a word with emotional weight:
   TRAP, DEATH, COLLAPSE, WEAPON, CRISIS, LIES, DYING, SWALLOWED, MISTAKE, STRONGER, WEAKER, RICHER, etc.
3. The main hook (before the parenthetical) should be 6-8 words.
4. The parenthetical reveal should create a curiosity gap.
5. Total title length should be under 70 characters for the main hook.

FORMULA OPTIONS:
1. "The [Noun] {CAPS} Nobody Sees Coming (Parenthetical)"
2. "[Country]'s $[Amount] {CAPS} (Parenthetical)"
3. "The Slow {CAPS} of [System] (Parenthetical)"
4. "Why [Country] is {CAPS} Than You Think (Parenthetical)"
5. "[Number] [Noun] {CAPS} (Parenthetical)"
6. "How [Entity] {CAPS} [Target] (Parenthetical)"

Pick the formula that best fits the video topic. The CAPS word must feel like a revelation.

OUTPUT FORMAT (JSON only, no markdown):
{
  "title": "The full title with ONE CAPS word and parenthetical",
  "caps_word": "THE_CAPS_WORD",
  "formula_used": "formula_1",
  "line_1": "3-4 WORD THUMBNAIL TEXT",
  "line_2": "2-3 WORD SUBTITLE"
}

CRITICAL:
- line_1 and line_2 are for the THUMBNAIL, not the YouTube title
- line_1 should be max 4 words, ALL CAPS, derived from the title's core hook
- line_2 should be max 3 words, ALL CAPS, a question or kicker
- The caps_word MUST appear in line_1
- Together line_1 + line_2 must not exceed 5 words total
"""


class TitleGenerator:
    """Generates matched titles for Economy FastForward videos.

    Uses Anthropic Claude to produce titles following proven formula patterns.
    Each title includes a CAPS word that becomes the red_word in the thumbnail.
    """

    def __init__(self, anthropic_client):
        """Initialize with an existing AnthropicClient instance.

        Args:
            anthropic_client: An initialized AnthropicClient from the pipeline.
        """
        self.anthropic = anthropic_client

    async def generate(
        self,
        video_title: str,
        video_summary: str,
        tags: Optional[list[str]] = None,
        preferred_formula: Optional[str] = None,
    ) -> dict:
        """Generate a title + thumbnail text pair.

        Args:
            video_title: Working title or topic of the video.
            video_summary: Brief description of the video content.
            tags: Optional list of topic tags.
            preferred_formula: Optional formula key (formula_1 through formula_6)
                to force a specific pattern.

        Returns:
            Dict with keys:
                title: str — full YouTube title
                caps_word: str — the ALL CAPS word
                formula_used: str — which formula was selected
                line_1: str — thumbnail primary text (3-4 words, ALL CAPS)
                line_2: str — thumbnail secondary text (2-3 words, ALL CAPS)
        """
        prompt_parts = [
            f'Generate a title for this Economy FastForward video:',
            f'',
            f'WORKING TITLE: "{video_title}"',
            f'VIDEO SUMMARY: {video_summary}',
        ]

        if tags:
            prompt_parts.append(f'TAGS: {", ".join(tags)}')

        if preferred_formula and preferred_formula in TITLE_FORMULAS:
            formula = TITLE_FORMULAS[preferred_formula]
            prompt_parts.extend([
                f'',
                f'USE THIS FORMULA: {formula["name"]}',
                f'Pattern: {formula["pattern"]}',
                f'Examples:',
            ])
            for ex in formula["examples"]:
                prompt_parts.append(f'  - {ex}')

        prompt_parts.extend([
            f'',
            f'Generate the title now. Return JSON only.',
        ])

        user_prompt = '\n'.join(prompt_parts)

        response = await self.anthropic.generate(
            prompt=user_prompt,
            system_prompt=TITLE_GENERATION_SYSTEM_PROMPT,
            model="claude-sonnet-4-5-20250929",
            max_tokens=500,
        )

        # Parse JSON response
        clean = response.replace("```json", "").replace("```", "").strip()
        result = json.loads(clean)

        # Validate required fields
        required = ["title", "caps_word", "formula_used", "line_1", "line_2"]
        for field in required:
            if field not in result:
                raise ValueError(f"Title generation missing required field: {field}")

        # Ensure caps_word is uppercase
        result["caps_word"] = result["caps_word"].upper()

        # Ensure line_1 and line_2 are uppercase
        result["line_1"] = result["line_1"].upper()
        result["line_2"] = result["line_2"].upper()

        # Validate total word count for thumbnail text (max 5 words)
        total_words = len(result["line_1"].split()) + len(result["line_2"].split())
        if total_words > 5:
            print(f"  WARNING: Thumbnail text has {total_words} words (max 5). "
                  f"line_1='{result['line_1']}', line_2='{result['line_2']}'")

        return result
