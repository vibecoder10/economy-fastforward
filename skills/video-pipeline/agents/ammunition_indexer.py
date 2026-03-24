"""Ammunition Indexer — bridges research payload into categorized ammunition for agents.

This is a PURE function module — no Claude calls, no async, no API dependencies.
It takes the 14-field research payload and indexes it into categories that
agents can consume directly in their prompts.

The research payload fields:
  headline, thesis, executive_hook, fact_sheet, historical_parallels,
  framework_analysis, character_dossier, narrative_arc, counter_arguments,
  visual_seeds, source_bibliography, themes, psychological_angles,
  narrative_arc_suggestion
"""

from __future__ import annotations

import re
from typing import Any, Dict, List


def index_ammunition(research_payload: dict) -> dict:
    """Index research payload into ammunition categories for agents.

    Args:
        research_payload: The 14-field research payload from research_agent.py.
            All fields are optional — missing fields produce empty lists.

    Returns:
        {
            "hook_ammunition": [...],      # Best facts for hooks (highest surprise value)
            "body_ammunition": {...},       # Facts organized by narrative purpose
            "cta_ammunition": [...],        # Actionable data points
            "weapons_ammunition": [...],    # Most quotable lines, strongest claims
        }
    """
    if not research_payload or not isinstance(research_payload, dict):
        return _empty_ammunition()

    return {
        "hook_ammunition": _extract_hook_ammunition(research_payload),
        "body_ammunition": _extract_body_ammunition(research_payload),
        "cta_ammunition": _extract_cta_ammunition(research_payload),
        "weapons_ammunition": _extract_weapons_ammunition(research_payload),
    }


def _empty_ammunition() -> dict:
    """Return empty ammunition structure."""
    return {
        "hook_ammunition": [],
        "body_ammunition": {
            "incentive_chain": [],
            "money_trail": [],
            "proof_points": [],
            "character_facts": [],
        },
        "cta_ammunition": [],
        "weapons_ammunition": [],
    }


def _extract_lines(text: str) -> List[str]:
    """Split text into non-empty, trimmed lines/bullet points."""
    if not text or not isinstance(text, str):
        return []
    # Split on newlines, strip bullets/dashes/numbers, filter empty
    lines = []
    for line in text.split("\n"):
        cleaned = line.strip()
        # Strip leading bullet markers: -, *, numbered (1., 2.), etc.
        cleaned = re.sub(r"^[-*•]\s*", "", cleaned)
        cleaned = re.sub(r"^\d+[.)]\s*", "", cleaned)
        cleaned = cleaned.strip()
        if cleaned and len(cleaned) > 10:  # Skip very short fragments
            lines.append(cleaned)
    return lines


def _has_number(text: str) -> bool:
    """Check if text contains a specific number (dollar amount, percentage, year, etc.)."""
    return bool(re.search(r"\$[\d,.]+|\d+%|\b\d{4}\b|\b\d+[,.]?\d*\s*(billion|million|trillion|thousand)\b", text, re.IGNORECASE))


def _extract_hook_ammunition(payload: dict) -> List[str]:
    """Extract top 5 most surprising facts for hooks.

    Sources: fact_sheet (primary), historical_parallels (secondary).
    Prioritizes lines containing specific numbers — those have highest surprise value.
    """
    candidates = []

    # Primary: fact_sheet
    fact_sheet = payload.get("fact_sheet", "")
    candidates.extend(_extract_lines(fact_sheet))

    # Secondary: historical_parallels
    parallels = payload.get("historical_parallels", "")
    candidates.extend(_extract_lines(parallels))

    # Sort: lines with numbers first (higher surprise value), then by length (more specific = better)
    numbered = [c for c in candidates if _has_number(c)]
    non_numbered = [c for c in candidates if not _has_number(c)]

    # Numbers first, then non-numbers, both sorted by length descending (more detail = more surprising)
    ranked = sorted(numbered, key=len, reverse=True) + sorted(non_numbered, key=len, reverse=True)

    return ranked[:5]


def _extract_body_ammunition(payload: dict) -> Dict[str, List[str]]:
    """Extract facts organized by narrative purpose for the body agent.

    Categories:
      - incentive_chain: Why actors do what they do (from framework_analysis)
      - money_trail: Financial flows and amounts (from fact_sheet, lines with $)
      - proof_points: Evidence and data (from fact_sheet, lines with numbers)
      - character_facts: Key figures and their actions (from character_dossier)
    """
    result: Dict[str, List[str]] = {
        "incentive_chain": [],
        "money_trail": [],
        "proof_points": [],
        "character_facts": [],
    }

    # Incentive chain from framework_analysis
    framework = payload.get("framework_analysis", "")
    result["incentive_chain"] = _extract_lines(framework)[:5]

    # Money trail: lines with dollar amounts from fact_sheet
    fact_lines = _extract_lines(payload.get("fact_sheet", ""))
    result["money_trail"] = [l for l in fact_lines if re.search(r"\$[\d,.]+", l)][:5]

    # Proof points: lines with numbers (but not just dollar amounts)
    result["proof_points"] = [l for l in fact_lines if _has_number(l)][:5]

    # Character facts from character_dossier
    dossier = payload.get("character_dossier", "")
    result["character_facts"] = _extract_lines(dossier)[:5]

    return result


def _extract_cta_ammunition(payload: dict) -> List[str]:
    """Extract actionable data points for CTAs.

    Sources: counter_arguments (what to watch for), narrative_arc (conclusions/implications).
    Focus on lines that suggest action or forward-looking implications.
    """
    candidates = []

    # Counter arguments — these show what to watch for
    counter = payload.get("counter_arguments", "")
    candidates.extend(_extract_lines(counter))

    # Narrative arc — conclusions and what happens next
    arc = payload.get("narrative_arc", "")
    arc_lines = _extract_lines(arc)
    # Prefer lines that suggest forward-looking action
    action_words = re.compile(r"\b(watch|monitor|prepare|expect|signal|indicator|track|notice|look for|pay attention)\b", re.IGNORECASE)
    forward_lines = [l for l in arc_lines if action_words.search(l)]
    other_lines = [l for l in arc_lines if not action_words.search(l)]
    candidates.extend(forward_lines)
    candidates.extend(other_lines)

    return candidates[:5]


def _extract_weapons_ammunition(payload: dict) -> List[str]:
    """Extract most quotable lines and strongest claims for the weapons check.

    Sources: thesis (core argument), executive_hook (strongest opening), fact_sheet (data).
    These are the lines that should survive any edit — the "weapons" of the script.
    """
    candidates = []

    # Thesis — the core argument (always a weapon)
    thesis = payload.get("thesis", "")
    if thesis and isinstance(thesis, str) and len(thesis.strip()) > 10:
        candidates.append(thesis.strip())

    # Executive hook — the strongest opening line
    hook = payload.get("executive_hook", "")
    if hook and isinstance(hook, str) and len(hook.strip()) > 10:
        candidates.append(hook.strip())

    # Strongest claims from fact_sheet (lines with numbers are strongest)
    fact_lines = _extract_lines(payload.get("fact_sheet", ""))
    numbered_facts = [l for l in fact_lines if _has_number(l)]
    candidates.extend(sorted(numbered_facts, key=len, reverse=True)[:3])

    return candidates[:5]
