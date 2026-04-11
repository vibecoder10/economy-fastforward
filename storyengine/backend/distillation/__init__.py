"""Content distillation pipeline — raw data → structured intelligence + vector embeddings."""

from distillation.pipeline import (
    distill_competitor_video,
    distill_competitor_transcript,  # backwards compat alias
    backfill_competitor_transcripts,
)
from distillation.advisor import IntelligenceAdvisor, get_advisor
from distillation.meta_analyzer import generate_niche_meta_insights

__all__ = [
    "distill_competitor_video",
    "distill_competitor_transcript",
    "backfill_competitor_transcripts",
    "IntelligenceAdvisor",
    "get_advisor",
    "generate_niche_meta_insights",
]
