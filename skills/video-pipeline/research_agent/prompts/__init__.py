"""Prompt templates for Research Intelligence Agent.

This module contains specialized prompts for:
- Deep dive research (Phase 2)
- Framework mapping
- Narrative building
- Title/thumbnail generation
"""

from .deep_dive_prompts import (
    PROMPT_2_1_INITIAL_RESEARCH,
    PROMPT_2_2_GAP_ANALYSIS,
    PROMPT_2_3_FACT_CONSOLIDATION,
    PROMPT_3_1_STRATEGIC_ANALYSIS,
    PROMPT_3_2_FINAL_COMPILATION,
)

__all__ = [
    "PROMPT_2_1_INITIAL_RESEARCH",
    "PROMPT_2_2_GAP_ANALYSIS",
    "PROMPT_2_3_FACT_CONSOLIDATION",
    "PROMPT_3_1_STRATEGIC_ANALYSIS",
    "PROMPT_3_2_FINAL_COMPILATION",
]
