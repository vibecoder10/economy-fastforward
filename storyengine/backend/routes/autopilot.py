"""Autopilot API endpoints for dashboard and control.

All data is read from Supabase (NOT Airtable - that's legacy).
Tables used:
- competitor_videos: Scraped competitor videos with VPH metrics
- learnings: Patterns learned from video performance
- autopilot_config: Per-tenant autopilot settings
- videos: Our video production data
"""

import os
import math
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, List, Dict
from datetime import datetime, timedelta
from auth import get_tenant_id
from database import fetch_all, fetch_one, execute

router = APIRouter(prefix="/api/autopilot", tags=["autopilot"])

# Background task status — updated by main.py background loops
# Keys: scrape, youtube_sync, learning_extraction, title_analysis
_bg_task_status: Dict[str, Dict[str, dict]] = {}


# --- Models ---

class ConfidenceBreakdown(BaseModel):
    """Breakdown of confidence score components."""
    vph_score: float = 0
    vph_reasoning: str = ""
    freshness_score: float = 0
    freshness_reasoning: str = ""
    intelligence_score: float = 0
    intelligence_reasoning: str = ""
    total_score: float = 0


class AutopilotState(BaseModel):
    enabled: bool = True
    last_cycle: Optional[str] = None
    videos_produced: int = 0
    channel_avg_ctr: float = 0.0
    next_production_date: Optional[str] = None
    days_until_next: int = 0


class AutopilotConfig(BaseModel):
    videos_per_month: int = 15
    production_interval_days: int = 2
    videos_per_scrape: int = 10
    weights: dict = {
        "competitor_vph": 0.55,
        "timing_freshness": 0.45,
    }
    thresholds: dict = {
        "min_confidence_score": 60,
        "min_competitor_vph": 50,
        "max_idea_age_days": 7,
        "ctr_success_threshold": 4.0,
        "ctr_failure_threshold": 2.5,
    }


class CompetitorCandidate(BaseModel):
    id: str
    title: str
    source: str
    url: Optional[str] = None
    vph: float = 0
    hours_old: float = 0
    confidence: float = 0
    confidence_breakdown: Optional[ConfidenceBreakdown] = None
    published_date: Optional[str] = None
    modeled: bool = False


class Learning(BaseModel):
    id: str
    pattern: str
    category: str
    effect: str
    confidence: float = 0
    sample_size: int = 0
    avg_ctr: Optional[float] = None


class AutopilotSummary(BaseModel):
    state: AutopilotState
    config: AutopilotConfig
    candidates: List[CompetitorCandidate]
    learnings: List[Learning]


# --- Helper Functions ---

# Cache niche recommendations per tenant (refreshed on each request cycle)
_niche_recs_cache: Dict[str, dict] = {}


async def _get_niche_recommendations(tenant_id: str) -> Optional[dict]:
    """Get niche intelligence recommendations for scoring.

    Returns serialized recommendations dict from IntelligenceAdvisor.
    Cached per-request cycle (dict cleared after each endpoint call).
    """
    try:
        from distillation.advisor import get_advisor
        advisor = get_advisor()
        recs = await advisor.get_recommendations(tenant_id)
        return recs.to_dict() if recs.sample_size > 0 else None
    except Exception as e:
        import logging
        logging.getLogger("storyengine").warning("Niche recommendations unavailable: %s", e)
        return None


async def _get_proven_patterns(tenant_id: str) -> list[str]:
    """Fetch proven title/hook patterns from learnings table (KEEP verdicts with decent confidence)."""
    try:
        rows = await fetch_all(
            """SELECT pattern FROM learnings
               WHERE tenant_id = $1 AND active = true
                 AND category IN ('title', 'hook')
                 AND confidence >= 55
               ORDER BY confidence DESC LIMIT 20""",
            tenant_id,
        )
        return [r["pattern"] for r in (rows or [])]
    except Exception:
        return []


def _title_matches_patterns(title: str, patterns: list[str]) -> bool:
    """Check if a title matches any proven patterns (question, number, caps, formula keywords)."""
    if not patterns or not title:
        return False
    title_lower = title.lower()
    for pattern in patterns:
        p = pattern.lower()
        # Match pattern keywords against title
        if "question" in p and "?" in title:
            return True
        if "number" in p and any(c.isdigit() for c in title):
            return True
        if "how" in p and title_lower.startswith("how "):
            return True
        if "why" in p and title_lower.startswith("why "):
            return True
        if "what" in p and title_lower.startswith("what "):
            return True
        if "list" in p and any(c.isdigit() for c in title):
            return True
        # Direct keyword overlap
        pattern_words = set(p.split()) - {"the", "a", "an", "in", "of", "for", "with", "and", "or"}
        title_words = set(title_lower.split())
        if len(pattern_words & title_words) >= 2:
            return True
    return False

def calculate_confidence_with_breakdown(
    vph: float, hours_old: float,
    intelligence: dict = None,
    learnings_match: bool = False,
    niche_recs: dict = None,
) -> ConfidenceBreakdown:
    """Calculate confidence score with detailed breakdown for explainability.

    Scoring weights: VPH 45%, Freshness 35%, Intelligence 20%.
    Intelligence score considers: distilled DNA quality, engagement signals,
    learnings pattern matches, and niche intelligence alignment.

    Args:
        niche_recs: Niche recommendations dict from IntelligenceAdvisor.
            Used to boost candidates whose DNA matches best-performing patterns.
            Expected keys: hook_type, title_structure, topics (from candidate DNA).
    """
    MAX_VPH = 50000.0
    MAX_HOURS = 168.0

    # VPH score (log scale) - 45% weight
    if vph <= 0:
        vph_score = 0
        vph_reasoning = "No VPH data"
    else:
        vph_score = min(100, (math.log10(max(1, vph)) / math.log10(MAX_VPH)) * 100)
        if vph >= 10000:
            vph_reasoning = f"Excellent VPH ({vph:,.0f}) - viral potential"
        elif vph >= 1000:
            vph_reasoning = f"Strong VPH ({vph:,.0f}) - proven appeal"
        elif vph >= 100:
            vph_reasoning = f"Good VPH ({vph:,.0f}) - moderate interest"
        else:
            vph_reasoning = f"Low VPH ({vph:,.0f}) - limited traction"

    # Freshness score (linear decay) - 35% weight
    if hours_old >= MAX_HOURS:
        freshness_score = 0
        freshness_reasoning = f"Old ({hours_old:.0f}h) - topic may be stale"
    elif hours_old <= 0:
        freshness_score = 100
        freshness_reasoning = "Brand new - maximum freshness"
    else:
        freshness_score = (1 - hours_old / MAX_HOURS) * 100
        if hours_old < 24:
            freshness_reasoning = f"Very fresh ({hours_old:.0f}h) - trending now"
        elif hours_old < 48:
            freshness_reasoning = f"Fresh ({hours_old:.0f}h) - still timely"
        elif hours_old < 96:
            freshness_reasoning = f"Recent ({hours_old:.0f}h) - relevant"
        else:
            freshness_reasoning = f"Getting old ({hours_old:.0f}h) - urgency declining"

    # Intelligence score - 20% weight
    # Factors: engagement signals, learnings match, niche intelligence alignment
    intel_score = 0
    intel_reasons = []

    if intelligence:
        # Has distilled intelligence = we understand this video's DNA
        if intelligence.get("has_dna"):
            intel_score += 15
            intel_reasons.append("distilled DNA available")

        # High like ratio = strong audience resonance
        like_ratio = intelligence.get("like_ratio")
        if like_ratio and like_ratio > 0.04:
            intel_score += 15
            intel_reasons.append(f"high engagement ({like_ratio:.1%} like ratio)")
        elif like_ratio and like_ratio > 0.02:
            intel_score += 5

        # Virality signal (views >> subscriber count)
        vsr = intelligence.get("views_per_sub_ratio")
        if vsr and vsr > 2.0:
            intel_score += 15
            intel_reasons.append(f"viral breakout ({vsr:.1f}x subs)")
        elif vsr and vsr > 1.0:
            intel_score += 8
            intel_reasons.append(f"above-audience reach ({vsr:.1f}x subs)")

        # Niche intelligence alignment — boost if candidate DNA matches best patterns
        if niche_recs and intelligence.get("has_dna"):
            candidate_hook = intelligence.get("hook_type")
            candidate_title_struct = intelligence.get("title_structure")
            candidate_topics = intelligence.get("topics") or []

            best_hook = (niche_recs.get("hook") or {}).get("type")
            best_title = (niche_recs.get("title_structure") or {}).get("structure")
            best_topics = [t["topic"] for t in (niche_recs.get("top_topics") or [])]

            if candidate_hook and best_hook and candidate_hook == best_hook:
                intel_score += 15
                intel_reasons.append(f"uses top hook ({best_hook})")

            if candidate_title_struct and best_title and candidate_title_struct == best_title:
                intel_score += 10
                intel_reasons.append(f"uses top title structure ({best_title})")

            if candidate_topics and best_topics:
                matching = set(candidate_topics) & set(best_topics)
                if matching:
                    intel_score += 10
                    intel_reasons.append(f"covers top topic{'s' if len(matching) > 1 else ''}")

    if learnings_match:
        intel_score += 15
        intel_reasons.append("matches proven patterns")

    intel_score = min(100, intel_score)
    intelligence_reasoning = ", ".join(intel_reasons) if intel_reasons else "No intelligence data"

    # Weighted combination: VPH 45%, Freshness 35%, Intelligence 20%
    total_score = round(vph_score * 0.45 + freshness_score * 0.35 + intel_score * 0.20, 1)

    return ConfidenceBreakdown(
        vph_score=round(vph_score, 1),
        vph_reasoning=vph_reasoning,
        freshness_score=round(freshness_score, 1),
        freshness_reasoning=freshness_reasoning,
        intelligence_score=round(intel_score, 1),
        intelligence_reasoning=intelligence_reasoning,
        total_score=total_score,
    )


# --- Endpoints ---

@router.get("/summary", response_model=AutopilotSummary)
async def get_autopilot_summary(tenant_id: str = Depends(get_tenant_id)):
    """Get full autopilot status, config, candidates, and learnings.

    All data comes from Supabase tables:
    - videos: Production stats
    - competitor_videos: Candidate ideas with VPH
    - learnings: Patterns from performance analysis
    - autopilot_config: User settings (optional)
    """

    # Get video stats from Supabase
    video_count = await fetch_one(
        "SELECT COUNT(*) as count FROM videos WHERE tenant_id = $1",
        tenant_id,
    )
    avg_ctr = await fetch_one(
        "SELECT AVG(ctr) as avg FROM videos WHERE tenant_id = $1 AND ctr IS NOT NULL",
        tenant_id,
    )

    # Try to get autopilot config from Supabase (table may not exist yet)
    config_row = None
    try:
        config_row = await fetch_one(
            "SELECT * FROM autopilot_config WHERE tenant_id = $1",
            tenant_id,
        )
    except Exception as e:
        print(f"Note: autopilot_config table may not exist: {e}")

    if config_row:
        import json as _json
        _w = config_row.get("weights", {})
        _t = config_row.get("thresholds", {})
        if isinstance(_w, str):
            _w = _json.loads(_w)
        if isinstance(_t, str):
            _t = _json.loads(_t)
        config = AutopilotConfig(
            videos_per_month=config_row.get("videos_per_month", 15),
            production_interval_days=config_row.get("production_interval_days", 2),
            videos_per_scrape=config_row.get("videos_per_scrape", 10),
            weights=_w,
            thresholds=_t,
        )
        enabled = config_row.get("enabled", True)
        last_cycle = config_row.get("last_cycle")
    else:
        config = AutopilotConfig()
        enabled = True
        last_cycle = None

    state = AutopilotState(
        enabled=enabled,
        last_cycle=last_cycle.isoformat() if last_cycle else None,
        videos_produced=video_count["count"] if video_count else 0,
        channel_avg_ctr=round(float(avg_ctr["avg"]), 1) if avg_ctr and avg_ctr["avg"] else 0.0,
        days_until_next=config.production_interval_days,
        next_production_date=(datetime.now() + timedelta(days=config.production_interval_days)).strftime("%Y-%m-%d"),
    )

    # Get competitor candidates from Supabase
    candidates = []
    try:
        min_vph = config.thresholds.get("min_competitor_vph", 50)
        rows = await fetch_all(
            """SELECT cv.id, cv.video_id, cv.title, cv.url, cv.channel, cv.channel_url,
                      cv.views, cv.vph, cv.hours_old, cv.published_date, cv.modeled,
                      cv.like_ratio, cv.views_per_sub_ratio, cv.distilled_at,
                      COALESCE(
                          ci.structured_metadata->'hook_dna'->>'type',
                          ci.structured_metadata->'hook'->>'type'
                      ) as hook_type,
                      COALESCE(
                          ci.structured_metadata->'title_dna'->>'structure',
                          ci.structured_metadata->'title'->>'structure'
                      ) as title_structure,
                      COALESCE(
                          ci.structured_metadata->'content_dna'->'topic_tags',
                          ci.structured_metadata->'content'->'topic_tags'
                      ) as topic_tags
               FROM competitor_videos cv
               LEFT JOIN content_intelligence ci
                   ON ci.source_id = cv.id AND ci.tenant_id = cv.tenant_id
                   AND ci.source_type = 'competitor_transcript'
               WHERE cv.tenant_id = $1
                 AND (cv.modeled = false OR cv.modeled IS NULL)
                 AND cv.vph >= $2
               ORDER BY cv.vph DESC
               LIMIT 20""",
            tenant_id, min_vph,
        )

        # Fetch proven learnings patterns + niche recommendations in parallel
        proven_patterns = await _get_proven_patterns(tenant_id)
        niche_recs = await _get_niche_recommendations(tenant_id)

        for row in rows:
            vph = float(row.get("vph") or 0)
            hours_old = float(row.get("hours_old") or 0)

            # Parse topic_tags from JSONB
            topic_tags = row.get("topic_tags")
            if isinstance(topic_tags, str):
                import json as _j
                try:
                    topic_tags = _j.loads(topic_tags)
                except (ValueError, TypeError):
                    topic_tags = None

            intel = {
                "has_dna": row.get("distilled_at") is not None,
                "like_ratio": float(row["like_ratio"]) if row.get("like_ratio") else None,
                "views_per_sub_ratio": float(row["views_per_sub_ratio"]) if row.get("views_per_sub_ratio") else None,
                "hook_type": row.get("hook_type"),
                "title_structure": row.get("title_structure"),
                "topics": topic_tags if isinstance(topic_tags, list) else None,
            }
            learnings_match = _title_matches_patterns(row.get("title", ""), proven_patterns)

            breakdown = calculate_confidence_with_breakdown(vph, hours_old, intel, learnings_match, niche_recs)

            candidates.append(CompetitorCandidate(
                id=str(row["id"]),
                title=row.get("title", "Unknown"),
                source=row.get("channel", "Unknown"),
                url=row.get("url"),
                vph=vph,
                hours_old=hours_old,
                confidence=breakdown.total_score,
                confidence_breakdown=breakdown,
                published_date=row.get("published_date").isoformat() if row.get("published_date") else None,
                modeled=row.get("modeled", False),
            ))

        # Sort by confidence score
        candidates.sort(key=lambda c: c.confidence, reverse=True)
        candidates = candidates[:10]  # Top 10

    except Exception as e:
        print(f"Error fetching competitors from Supabase: {e}")

    # Get learnings from Supabase
    learnings = []
    try:
        rows = await fetch_all(
            """SELECT id, category, pattern, confidence, sample_size, avg_ctr, avg_retention
               FROM learnings
               WHERE tenant_id = $1 AND active = true
               ORDER BY confidence DESC
               LIMIT 10""",
            tenant_id,
        )

        for row in rows:
            avg_ctr_val = row.get("avg_ctr")
            effect = f"+{float(avg_ctr_val):.1f}% CTR" if avg_ctr_val else ""

            learnings.append(Learning(
                id=str(row["id"]),
                pattern=row.get("pattern", ""),
                category=row.get("category", "general"),
                effect=effect,
                confidence=float(row.get("confidence") or 0),
                sample_size=int(row.get("sample_size") or 0),
                avg_ctr=float(avg_ctr_val) if avg_ctr_val else None,
            ))
    except Exception as e:
        print(f"Error fetching learnings from Supabase: {e}")

    return AutopilotSummary(
        state=state,
        config=config,
        candidates=candidates,
        learnings=learnings,
    )


@router.get("/candidates", response_model=List[CompetitorCandidate])
async def get_candidates(
    limit: int = Query(20, le=50),
    min_vph: float = Query(50),
    include_modeled: bool = Query(False),
    tenant_id: str = Depends(get_tenant_id)
):
    """Get competitor video candidates from Supabase with intelligence-enriched scoring."""
    candidates = []
    try:
        # Build query with LEFT JOIN for intelligence DNA
        modeled_filter = "" if include_modeled else "AND (cv.modeled = false OR cv.modeled IS NULL)"
        query = f"""SELECT cv.id, cv.video_id, cv.title, cv.url, cv.channel, cv.channel_url,
                          cv.views, cv.vph, cv.hours_old, cv.published_date, cv.modeled,
                          cv.like_ratio, cv.views_per_sub_ratio, cv.distilled_at,
                          COALESCE(
                              ci.structured_metadata->'hook_dna'->>'type',
                              ci.structured_metadata->'hook'->>'type'
                          ) as hook_type,
                          COALESCE(
                              ci.structured_metadata->'title_dna'->>'structure',
                              ci.structured_metadata->'title'->>'structure'
                          ) as title_structure,
                          COALESCE(
                              ci.structured_metadata->'content_dna'->'topic_tags',
                              ci.structured_metadata->'content'->'topic_tags'
                          ) as topic_tags
                   FROM competitor_videos cv
                   LEFT JOIN content_intelligence ci
                       ON ci.source_id = cv.id AND ci.tenant_id = cv.tenant_id
                       AND ci.source_type = 'competitor_transcript'
                   WHERE cv.tenant_id = $1 AND cv.vph >= $2
                     {modeled_filter}
                   ORDER BY cv.vph DESC
                   LIMIT $3"""

        rows = await fetch_all(query, tenant_id, min_vph, limit * 2)

        # Fetch proven learnings patterns + niche recommendations
        proven_patterns = await _get_proven_patterns(tenant_id)
        niche_recs = await _get_niche_recommendations(tenant_id)

        for row in rows:
            vph = float(row.get("vph") or 0)
            hours_old = float(row.get("hours_old") or 0)

            topic_tags = row.get("topic_tags")
            if isinstance(topic_tags, str):
                import json as _j
                try:
                    topic_tags = _j.loads(topic_tags)
                except (ValueError, TypeError):
                    topic_tags = None

            intel = {
                "has_dna": row.get("distilled_at") is not None,
                "like_ratio": float(row["like_ratio"]) if row.get("like_ratio") else None,
                "views_per_sub_ratio": float(row["views_per_sub_ratio"]) if row.get("views_per_sub_ratio") else None,
                "hook_type": row.get("hook_type"),
                "title_structure": row.get("title_structure"),
                "topics": topic_tags if isinstance(topic_tags, list) else None,
            }
            learnings_match = _title_matches_patterns(row.get("title", ""), proven_patterns)

            breakdown = calculate_confidence_with_breakdown(vph, hours_old, intel, learnings_match, niche_recs)

            candidates.append(CompetitorCandidate(
                id=str(row["id"]),
                title=row.get("title", "Unknown"),
                source=row.get("channel", "Unknown"),
                url=row.get("url"),
                vph=vph,
                hours_old=hours_old,
                confidence=breakdown.total_score,
                confidence_breakdown=breakdown,
                published_date=row.get("published_date").isoformat() if row.get("published_date") else None,
                modeled=row.get("modeled", False),
            ))

        candidates.sort(key=lambda c: c.confidence, reverse=True)
        candidates = candidates[:limit]
    except Exception as e:
        print(f"Error fetching candidates from Supabase: {e}")

    return candidates


@router.get("/candidates/{candidate_id}")
async def get_candidate_detail(
    candidate_id: str,
    include_transcript: bool = Query(default=False),
    tenant_id: str = Depends(get_tenant_id),
):
    """Get a single competitor video with full details.

    Transcript is lazy-loaded only when include_transcript=true.
    Prefers distilled intelligence (summary + metadata) over raw transcript.
    """
    # Base query without transcript (saves 10-20 KB egress)
    cols = """id, video_id, title, url, channel, channel_url,
              views, vph, hours_old, published_date, modeled,
              thumbnail_url, description, duration_seconds, likes, distilled_at"""
    if include_transcript:
        cols += ", transcript"

    row = await fetch_one(
        f"""SELECT {cols}
           FROM competitor_videos
           WHERE id = $1 AND tenant_id = $2""",
        candidate_id, tenant_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Candidate not found")

    vph = float(row.get("vph") or 0)
    hours_old = float(row.get("hours_old") or 0)
    breakdown = calculate_confidence_with_breakdown(vph, hours_old)

    result = {
        "id": str(row["id"]),
        "title": row.get("title", "Unknown"),
        "source": row.get("channel", "Unknown"),
        "url": row.get("url"),
        "vph": vph,
        "hours_old": hours_old,
        "confidence": breakdown.total_score,
        "confidence_breakdown": breakdown,
        "published_date": row.get("published_date").isoformat() if row.get("published_date") else None,
        "modeled": row.get("modeled", False),
        "thumbnail_url": row.get("thumbnail_url"),
        "description": row.get("description"),
        "duration_seconds": float(row["duration_seconds"]) if row.get("duration_seconds") else None,
        "likes": row.get("likes"),
    }

    # Include distilled intelligence if available (cheap — ~1 KB vs 15 KB transcript)
    if row.get("distilled_at"):
        intel = await fetch_one(
            """SELECT summary, structured_metadata
               FROM content_intelligence
               WHERE source_id = $1 AND tenant_id = $2 AND source_type = 'competitor_transcript'""",
            candidate_id, tenant_id,
        )
        if intel:
            import json
            metadata = intel["structured_metadata"]
            if isinstance(metadata, str):
                metadata = json.loads(metadata)
            result["intelligence"] = {
                "summary": intel["summary"],
                "metadata": metadata,
            }

    # Only include raw transcript when explicitly requested
    if include_transcript:
        result["transcript"] = row.get("transcript")
    else:
        result["transcript"] = None

    # Signal whether content is available (distilled intelligence or raw transcript)
    result["has_intelligence"] = row.get("distilled_at") is not None
    result["has_transcript"] = include_transcript or row.get("distilled_at") is not None

    return result


@router.get("/learnings", response_model=List[Learning])
async def get_learnings(
    category: Optional[str] = None,
    limit: int = Query(20, le=50),
    tenant_id: str = Depends(get_tenant_id)
):
    """Get learned patterns from Supabase."""
    learnings = []
    try:
        if category:
            query = """SELECT id, category, pattern, confidence, sample_size, avg_ctr, avg_retention
                       FROM learnings
                       WHERE tenant_id = $1 AND active = true AND category = $2
                       ORDER BY confidence DESC
                       LIMIT $3"""
            rows = await fetch_all(query, tenant_id, category, limit)
        else:
            query = """SELECT id, category, pattern, confidence, sample_size, avg_ctr, avg_retention
                       FROM learnings
                       WHERE tenant_id = $1 AND active = true
                       ORDER BY confidence DESC
                       LIMIT $2"""
            rows = await fetch_all(query, tenant_id, limit)

        for row in rows:
            avg_ctr_val = row.get("avg_ctr")
            effect = f"+{float(avg_ctr_val):.1f}% CTR" if avg_ctr_val else ""

            learnings.append(Learning(
                id=str(row["id"]),
                pattern=row.get("pattern", ""),
                category=row.get("category", "general"),
                effect=effect,
                confidence=float(row.get("confidence") or 0),
                sample_size=int(row.get("sample_size") or 0),
                avg_ctr=float(avg_ctr_val) if avg_ctr_val else None,
            ))
    except Exception as e:
        print(f"Error fetching learnings from Supabase: {e}")

    return learnings


class ConfigUpdate(BaseModel):
    """Request body for config updates."""
    videos_per_month: Optional[int] = None
    production_interval_days: Optional[int] = None
    videos_per_scrape: Optional[int] = None
    weights: Optional[dict] = None
    thresholds: Optional[dict] = None


@router.post("/config")
async def update_config(
    body: ConfigUpdate,
    tenant_id: str = Depends(get_tenant_id)
):
    """Update autopilot configuration in Supabase."""
    # Check if config exists
    existing = await fetch_one(
        "SELECT id FROM autopilot_config WHERE tenant_id = $1",
        tenant_id,
    )

    videos_per_month = body.videos_per_month
    production_interval_days = body.production_interval_days

    # Auto-calculate interval if only videos_per_month is provided
    if videos_per_month is not None and production_interval_days is None:
        production_interval_days = max(1, 30 // videos_per_month)

    if existing:
        # Update existing config
        updates = []
        params = [tenant_id]
        param_idx = 2

        if videos_per_month is not None:
            updates.append(f"videos_per_month = ${param_idx}")
            params.append(videos_per_month)
            param_idx += 1

        if production_interval_days is not None:
            updates.append(f"production_interval_days = ${param_idx}")
            params.append(production_interval_days)
            param_idx += 1

        if body.videos_per_scrape is not None:
            updates.append(f"videos_per_scrape = ${param_idx}")
            params.append(body.videos_per_scrape)
            param_idx += 1

        if body.weights is not None:
            import json as _j
            updates.append(f"weights = ${param_idx}::jsonb")
            params.append(_j.dumps(body.weights))
            param_idx += 1

        if body.thresholds is not None:
            import json as _j
            updates.append(f"thresholds = ${param_idx}::jsonb")
            params.append(_j.dumps(body.thresholds))
            param_idx += 1

        if updates:
            updates.append("updated_at = NOW()")
            # SECURITY: column names are hardcoded per-field conditionals, values use $N params
            query = f"UPDATE autopilot_config SET {', '.join(updates)} WHERE tenant_id = $1"
            await execute(query, *params)
    else:
        # Create new config
        import json as _j
        cols = ["tenant_id", "videos_per_month", "production_interval_days"]
        vals = [tenant_id, videos_per_month or 15, production_interval_days or 2]
        if body.weights is not None:
            cols.append("weights")
            vals.append(_j.dumps(body.weights))
        if body.thresholds is not None:
            cols.append("thresholds")
            vals.append(_j.dumps(body.thresholds))
        placeholders = ", ".join(f"${i+1}::jsonb" if c in ("weights", "thresholds") else f"${i+1}" for i, c in enumerate(cols))
        # SECURITY: column names from hardcoded cols list, values use $N params with explicit ::jsonb casts
        await execute(
            f"INSERT INTO autopilot_config ({', '.join(cols)}) VALUES ({placeholders})",
            *vals,
        )

    # Return updated config
    config_row = await fetch_one(
        "SELECT * FROM autopilot_config WHERE tenant_id = $1",
        tenant_id,
    )

    if config_row:
        import json as _json
        _w = config_row.get("weights", {})
        _t = config_row.get("thresholds", {})
        if isinstance(_w, str):
            _w = _json.loads(_w)
        if isinstance(_t, str):
            _t = _json.loads(_t)
        config = AutopilotConfig(
            videos_per_month=config_row.get("videos_per_month", 15),
            production_interval_days=config_row.get("production_interval_days", 2),
            videos_per_scrape=config_row.get("videos_per_scrape", 10),
            weights=_w,
            thresholds=_t,
        )
    else:
        config = AutopilotConfig()

    return {
        "status": "ok",
        "config": config.model_dump(),
    }


class ToggleRequest(BaseModel):
    """Request body for toggle."""
    enabled: bool


@router.post("/toggle")
async def toggle_autopilot(
    body: ToggleRequest,
    tenant_id: str = Depends(get_tenant_id)
):
    """Enable or disable autopilot in Supabase."""
    # Check if config exists
    existing = await fetch_one(
        "SELECT id FROM autopilot_config WHERE tenant_id = $1",
        tenant_id,
    )

    if existing:
        await execute(
            "UPDATE autopilot_config SET enabled = $1, updated_at = NOW() WHERE tenant_id = $2",
            body.enabled, tenant_id,
        )
    else:
        await execute(
            "INSERT INTO autopilot_config (tenant_id, enabled) VALUES ($1, $2)",
            tenant_id, body.enabled,
        )

    return {"status": "ok", "enabled": body.enabled}


@router.post("/launch/{candidate_id}")
async def launch_candidate(
    candidate_id: str,
    background_tasks: BackgroundTasks,
    tenant_id: str = Depends(get_tenant_id),
):
    """Launch production for a specific candidate.

    Creates a video record from the competitor video and triggers the full
    pipeline (research → script → voice → images → render → upload).
    """
    # 1. Fetch candidate (only columns needed for launch — skip transcript)
    candidate = await fetch_one(
        """SELECT id, video_id, title, url, channel, channel_url, views, vph,
                  hours_old, published_date, modeled, our_video_id, thumbnail_url
           FROM competitor_videos WHERE id = $1 AND tenant_id = $2""",
        candidate_id, tenant_id,
    )
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    if candidate.get("our_video_id"):
        raise HTTPException(status_code=400, detail="Candidate already launched")

    # 2. Fetch distilled intelligence to pass through pipeline
    intel_context = None
    try:
        intel = await fetch_one(
            """SELECT summary, structured_metadata
               FROM content_intelligence
               WHERE source_id = $1 AND tenant_id = $2 AND source_type = 'competitor_transcript'""",
            candidate_id, tenant_id,
        )
        if intel:
            import json as _json
            metadata = intel["structured_metadata"]
            if isinstance(metadata, str):
                metadata = _json.loads(metadata)
            # Build learning context for script generation
            parts = []
            hook = metadata.get("hook_dna") or metadata.get("hook", {})
            if hook.get("type"):
                parts.append(f"Proven hook type: {hook['type']}")
            if hook.get("opening_line"):
                parts.append(f"Competitor opening: {hook['opening_line']}")
            content = metadata.get("content_dna") or metadata.get("content", {})
            if content.get("tone"):
                parts.append(f"Content tone: {content['tone']}")
            if content.get("topic_tags"):
                parts.append(f"Topics: {', '.join(content['topic_tags'][:5])}")
            title_dna = metadata.get("title_dna", {})
            if title_dna.get("curiosity_mechanism"):
                parts.append(f"Curiosity mechanism: {title_dna['curiosity_mechanism']}")
            retention = metadata.get("retention_dna", {})
            if retention.get("key_retention_moments"):
                parts.append(f"Retention triggers: {', '.join(str(m) for m in retention['key_retention_moments'][:3])}")
            if parts:
                intel_context = "\n".join(parts)
    except Exception as e:
        print(f"[Autopilot] Intel fetch for launch (non-blocking): {e}")

    # 3. Get learnings context for this tenant
    learnings_text = ""
    try:
        learnings_rows = await fetch_all(
            """SELECT category, pattern, avg_ctr FROM learnings
               WHERE tenant_id = $1 AND active = true AND confidence >= 55
               ORDER BY confidence DESC LIMIT 10""",
            tenant_id,
        )
        if learnings_rows:
            lines = [f"- [{r['category']}] {r['pattern']} (CTR: {float(r['avg_ctr']):.1f}%)"
                     for r in learnings_rows if r.get("avg_ctr")]
            if lines:
                learnings_text = "Proven patterns from your channel:\n" + "\n".join(lines)
    except Exception:
        pass

    # 4. Get or create project
    from routes.projects import _get_or_create_project
    project = await _get_or_create_project(tenant_id)
    project_id = str(project["id"])

    # 5. Create video record with intelligence context
    video_title = candidate.get("title", "Untitled")
    channel = candidate.get("channel", "competitor")

    # Combine intel + learnings into system prompt guidance for script generation
    system_guidance = ""
    if intel_context:
        system_guidance += f"## Competitor DNA (from distilled intelligence)\n{intel_context}\n\n"
    if learnings_text:
        system_guidance += f"## Channel Learnings\n{learnings_text}\n\n"

    result = await fetch_one(
        """INSERT INTO videos (
            tenant_id, project_id, video_title, status, headline,
            source, reference_url, script_system_prompt, created_at
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, now())
        RETURNING id""",
        tenant_id, project_id, video_title, "idea_logged",
        video_title, f"autopilot_{channel}", candidate.get("url"),
        system_guidance or None,
    )
    video_id = str(result["id"])

    # 4. Mark candidate as modeled
    await execute(
        """UPDATE competitor_videos
           SET modeled = true, modeled_at = NOW(), our_video_id = $1
           WHERE id = $2 AND tenant_id = $3""",
        video_id, candidate_id, tenant_id,
    )

    # 5. Trigger full pipeline in background
    async def _run_full_pipeline():
        from pipeline_executor import PipelineExecutor
        executor = PipelineExecutor(tenant_id)
        res = await executor.run_research(video_id)
        if res.get("status") == "failed":
            return
        terminal = {"rendered", "uploaded", "uploaded_draft", "done", "published"}
        for _ in range(20):
            video = await fetch_one("SELECT status FROM videos WHERE id = $1", video_id)
            status = (video or {}).get("status", "")
            if status in terminal:
                break
            step_result = await executor.run_next_step(video_id)
            step_status = step_result.get("status", "")
            if step_status in ("failed", "needs_approval", "idle"):
                break

    background_tasks.add_task(_run_full_pipeline)

    return {
        "status": "launched",
        "candidate_id": candidate_id,
        "video_id": video_id,
        "video_title": video_title,
        "message": "Video created and pipeline started",
    }


@router.get("/tasks")
async def get_background_task_status(tenant_id: str = Depends(get_tenant_id)):
    """Get status of all 4 background autopilot tasks.

    Returns last_run, is_running, last_error for each task:
    scrape, youtube_sync, learning_extraction, title_analysis.
    Also includes user-triggered task status from niche and youtube_sync routes.
    """
    tenant_status = _bg_task_status.get(tenant_id, {})

    # Merge with user-triggered task status from niche._scrape_tasks and youtube_sync._sync_tasks
    from routes.niche import _scrape_tasks
    from routes.youtube_sync import _sync_tasks

    scrape_user = _scrape_tasks.get(tenant_id, {})
    sync_user = _sync_tasks.get(tenant_id, {})

    def _task_info(bg_key: str, user_task: dict = None) -> dict:
        bg = tenant_status.get(bg_key, {})
        is_running = bg.get("is_running", False)
        # If a user-triggered task is also running, reflect that
        if user_task and user_task.get("running"):
            is_running = True
        return {
            "last_run": bg.get("last_run"),
            "is_running": is_running,
            "last_error": bg.get("last_error"),
        }

    return {
        "scrape": _task_info("scrape", scrape_user),
        "youtube_sync": _task_info("youtube_sync", sync_user),
        "learning_extraction": _task_info("learning_extraction"),
        "title_analysis": _task_info("title_analysis"),
        "distillation": _task_info("distillation"),
    }


@router.get("/recommendations")
async def get_niche_recommendations(
    tenant_id: str = Depends(get_tenant_id),
):
    """Get data-backed niche intelligence recommendations for the dashboard.

    Returns best-performing hook type, thumbnail style, title structure,
    publish timing, and top topics — all correlated with VPH performance.
    Used by the autopilot dashboard to display intelligence-driven suggestions.
    """
    recs = await _get_niche_recommendations(tenant_id)
    if not recs:
        return {
            "status": "insufficient_data",
            "message": "Need at least 5 distilled competitor videos for recommendations",
            "recommendations": None,
        }
    return {
        "status": "ok",
        "recommendations": recs,
    }
