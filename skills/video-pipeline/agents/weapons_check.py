"""Weapons Check — the quality enforcer for every block of text.

Scores every block on two dimensions:
- Invention Novelty (0-10): Does this feel like a genuine breakthrough?
- Copy Intensity (0-10): Is it sharp enough someone would screenshot it?

The weapons check is the final quality gate before a script ships.
It catches filler (blocks that say nothing new) and bland copy
(blocks that inform but don't captivate). Both are viewer killers.

Granularity is tier-controlled:
- "none": skip entirely (FAST tier)
- "act": score each act as a whole (STANDARD tier)
- "line": score every 2-3 sentence block (PREMIUM tier)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import List, Optional

from agents.config import WeaponsConfig


@dataclass
class ScoredBlock:
    """A block of text with its weapons scores."""
    text: str
    label: str  # e.g. "Act 2" or "Act 3, Block 2"
    novelty: int  # 0-10
    intensity: int  # 0-10
    reasoning: str = ""
    is_filler: bool = False  # Both < filler_threshold
    needs_rewrite: bool = False  # Either < min threshold


@dataclass
class WeaponsReport:
    """Full weapons check report."""
    blocks: List[ScoredBlock] = field(default_factory=list)
    filler_blocks: List[ScoredBlock] = field(default_factory=list)
    rewrite_blocks: List[ScoredBlock] = field(default_factory=list)
    pass_rate: float = 1.0  # Fraction of blocks that passed

    def to_dict(self) -> dict:
        return {
            "total_blocks": len(self.blocks),
            "filler_count": len(self.filler_blocks),
            "rewrite_count": len(self.rewrite_blocks),
            "pass_rate": round(self.pass_rate, 2),
            "blocks": [
                {
                    "label": b.label,
                    "novelty": b.novelty,
                    "intensity": b.intensity,
                    "is_filler": b.is_filler,
                    "needs_rewrite": b.needs_rewrite,
                    "reasoning": b.reasoning,
                }
                for b in self.blocks
            ],
        }


class WeaponsCheck:
    """Score text blocks on invention novelty and copy intensity."""

    def __init__(self, config: WeaponsConfig, claude_client=None):
        """Initialize weapons check.

        Args:
            config: Weapons check configuration (granularity, thresholds)
            claude_client: Claude client instance (lazy-loaded if None)
        """
        self.config = config
        self._claude = claude_client

    async def _get_claude(self):
        """Lazy-load Claude client."""
        if self._claude is None:
            from shared.clients.anthropic_client import AnthropicClient
            self._claude = AnthropicClient()
        return self._claude

    async def check(self, script: str, granularity: Optional[str] = None) -> WeaponsReport:
        """Run weapons check on a full script.

        Args:
            script: Full script text (all acts)
            granularity: Override config granularity ("none", "act", "line")

        Returns:
            WeaponsReport with scored blocks and flagged issues
        """
        level = granularity or self.config.granularity

        if level == "none":
            return WeaponsReport()

        # Split script into blocks based on granularity
        blocks = self._split_into_blocks(script, level)

        if not blocks:
            return WeaponsReport()

        # Score all blocks
        scored = []
        for label, text in blocks:
            scored_block = await self._score_block(text, label)
            scored.append(scored_block)

        # Classify blocks
        filler = [b for b in scored if b.is_filler]
        rewrite = [b for b in scored if b.needs_rewrite and not b.is_filler]
        passed = [b for b in scored if not b.needs_rewrite and not b.is_filler]
        pass_rate = len(passed) / len(scored) if scored else 1.0

        return WeaponsReport(
            blocks=scored,
            filler_blocks=filler,
            rewrite_blocks=rewrite,
            pass_rate=pass_rate,
        )

    def _split_into_blocks(self, script: str, granularity: str) -> List[tuple]:
        """Split script into labeled blocks.

        Args:
            script: Full script text
            granularity: "act" or "line"

        Returns:
            List of (label, text) tuples
        """
        if granularity == "act":
            return self._split_by_acts(script)
        elif granularity == "line":
            return self._split_by_lines(script)
        return []

    def _split_by_acts(self, script: str) -> List[tuple]:
        """Split script into acts using act labels."""
        # Match patterns like "ACT 2", "Act 2", "## Act 2", etc.
        act_pattern = re.compile(
            r'(?:^|\n)\s*(?:#{0,3}\s*)?(?:ACT|Act)\s+(\d+)[^\n]*\n',
            re.MULTILINE,
        )

        matches = list(act_pattern.finditer(script))
        if not matches:
            # No act labels found — treat entire script as one block
            return [("Full Script", script.strip())]

        blocks = []
        for i, match in enumerate(matches):
            act_num = match.group(1)
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(script)
            text = script[start:end].strip()
            if text:
                blocks.append((f"Act {act_num}", text))

        return blocks

    def _split_by_lines(self, script: str) -> List[tuple]:
        """Split script into 2-3 sentence blocks within each act."""
        acts = self._split_by_acts(script)
        blocks = []

        for act_label, act_text in acts:
            # Split into sentences (rough heuristic)
            sentences = re.split(r'(?<=[.!?])\s+', act_text)
            sentences = [s.strip() for s in sentences if s.strip()]

            # Group into blocks of 2-3 sentences
            block_num = 1
            for i in range(0, len(sentences), 3):
                chunk = sentences[i:i + 3]
                text = " ".join(chunk)
                if text:
                    blocks.append((f"{act_label}, Block {block_num}", text))
                    block_num += 1

        return blocks

    async def _score_block(self, text: str, label: str) -> ScoredBlock:
        """Score a single block on novelty and intensity."""
        claude = await self._get_claude()

        prompt = f"""Score this script block on 2 dimensions. Be STRICT.

BLOCK ({label}):
"{text}"

SCORING DIMENSIONS (score each 0-10):

1. INVENTION_NOVELTY — Does this feel like a genuine breakthrough or insight?
   0 = Wikipedia summary, 3 = common knowledge restated, 5 = interesting angle,
   7 = "I didn't know that", 9 = "that changes everything", 10 = genuinely novel

2. COPY_INTENSITY — Is it sharp enough someone would screenshot this?
   0 = textbook prose, 3 = serviceable writing, 5 = well-written,
   7 = quotable line, 9 = "I need to share this", 10 = instant classic

Respond with ONLY a JSON object:
{{
  "novelty": {{"score": N, "reasoning": "..."}},
  "intensity": {{"score": N, "reasoning": "..."}}
}}"""

        response = await claude.generate(
            prompt=prompt,
            system="You are a ruthless script quality enforcer. You score invention novelty "
                   "and copy intensity. Most blocks score 4-6. A 7+ means genuinely good. "
                   "Never inflate. Filler gets a 2-3.",
            max_tokens=300,
        )

        return self._parse_block_score(response, text, label)

    def _parse_block_score(self, response: str, text: str, label: str) -> ScoredBlock:
        """Parse Claude's block scoring response."""
        try:
            raw = response.strip()
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0]
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0]

            data = json.loads(raw.strip())

            novelty_data = data.get("novelty", {})
            intensity_data = data.get("intensity", {})

            novelty = int(novelty_data.get("score", 5)) if isinstance(novelty_data, dict) else 5
            intensity = int(intensity_data.get("score", 5)) if isinstance(intensity_data, dict) else 5

            novelty = min(10, max(0, novelty))
            intensity = min(10, max(0, intensity))

            novelty_reasoning = novelty_data.get("reasoning", "") if isinstance(novelty_data, dict) else ""
            intensity_reasoning = intensity_data.get("reasoning", "") if isinstance(intensity_data, dict) else ""
            reasoning = f"Novelty: {novelty_reasoning} | Intensity: {intensity_reasoning}"

        except (json.JSONDecodeError, KeyError, TypeError):
            novelty = 5
            intensity = 5
            reasoning = "Parse error — defaulted to neutral scores"

        is_filler = (novelty < self.config.filler_threshold and
                     intensity < self.config.filler_threshold)
        needs_rewrite = (novelty < self.config.min_novelty or
                         intensity < self.config.min_intensity)

        return ScoredBlock(
            text=text,
            label=label,
            novelty=novelty,
            intensity=intensity,
            reasoning=reasoning,
            is_filler=is_filler,
            needs_rewrite=needs_rewrite,
        )
