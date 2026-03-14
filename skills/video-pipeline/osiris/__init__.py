"""
Osiris v2 - Competitor Intelligence Module.

A read-only intelligence layer that collects competitor video data,
builds a growing knowledge base, and provides recommendations.

Phase 1: Competitor Intelligence
  - Scrapes ALL competitor videos (not just winners)
  - Persists to Competitor Videos table for long-term learning
  - Calculates VPH (views per hour) for performance scoring

Usage:
    python -m osiris.competitor_scraper
    python -m osiris.competitor_scraper --dry-run

Design Principles:
  - READ ONLY: Never writes to pipeline tables (Ideas, Scripts, Images)
  - SONNET ONLY: No Opus API calls (cost control)
  - NON-BLOCKING: Failures don't kill the pipeline
  - IDEMPOTENT: Safe to run multiple times (deduplicates by video_id)
"""

__version__ = "2.0.0"
