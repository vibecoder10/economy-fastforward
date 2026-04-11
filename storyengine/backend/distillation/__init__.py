"""Content distillation pipeline — raw data → structured intelligence + vector embeddings."""

from distillation.pipeline import (
    distill_competitor_video,
    distill_competitor_transcript,  # backwards compat alias
    backfill_competitor_transcripts,
)

__all__ = [
    "distill_competitor_video",
    "distill_competitor_transcript",
    "backfill_competitor_transcripts",
]
