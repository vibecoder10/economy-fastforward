"""
Osiris v2 - Intelligence Layer for Economy FastForward.

A read-only intelligence layer that collects performance data,
extracts patterns, and feeds learnings back into video generation.

Phase 1: Competitor Intelligence
  - Scrapes ALL competitor videos (not just winners)
  - Persists to Competitor Videos table for long-term learning
  - Calculates VPH (views per hour) for performance scoring

Phase 2: Performance Learning
  - Analyzes YOUR channel's YouTube metrics (CTR, retention)
  - Runs post-mortems at 48h and 7d milestones
  - Extracts learnings and persists to Osiris Learnings table
  - Injects learnings into generation prompts (titles, hooks, thumbnails)

Usage:
    # Competitor scraper (Phase 1)
    python -m osiris
    python -m osiris --dry-run

    # Performance analyzer (Phase 2)
    python -m osiris analyze
    python -m osiris analyze --dry-run

Design Principles:
  - READ ONLY: Never writes to pipeline tables (Ideas, Scripts, Images)
  - SONNET ONLY: No Opus API calls (cost control)
  - NON-BLOCKING: Failures don't kill the pipeline
  - IDEMPOTENT: Safe to run multiple times
  - GRACEFUL: Returns empty strings if no learnings available
"""

__version__ = "2.0.0"

from .title_analyzer import TitleAnalyzer, run_title_analysis

__all__ = ["TitleAnalyzer", "run_title_analysis"]
