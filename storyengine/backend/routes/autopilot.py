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

def calculate_confidence_with_breakdown(vph: float, hours_old: float) -> ConfidenceBreakdown:
    """Calculate confidence score with detailed breakdown for explainability."""
    MAX_VPH = 50000.0  # VPH above this gets max score (adjusted for real data)
    MAX_HOURS = 168.0  # 7 days - older than this gets 0 freshness

    # VPH score (log scale) - 55% weight
    if vph <= 0:
        vph_score = 0
        vph_reasoning = "No VPH data"
    else:
        # Log scale: VPH 100 = ~37%, VPH 1000 = ~64%, VPH 10000 = ~85%, VPH 50000 = 100%
        vph_score = min(100, (math.log10(max(1, vph)) / math.log10(MAX_VPH)) * 100)
        if vph >= 10000:
            vph_reasoning = f"Excellent VPH ({vph:,.0f}) - viral potential"
        elif vph >= 1000:
            vph_reasoning = f"Strong VPH ({vph:,.0f}) - proven appeal"
        elif vph >= 100:
            vph_reasoning = f"Good VPH ({vph:,.0f}) - moderate interest"
        else:
            vph_reasoning = f"Low VPH ({vph:,.0f}) - limited traction"

    # Freshness score (linear decay) - 45% weight
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

    # Weighted combination
    total_score = round(vph_score * 0.55 + freshness_score * 0.45, 1)

    return ConfidenceBreakdown(
        vph_score=round(vph_score, 1),
        vph_reasoning=vph_reasoning,
        freshness_score=round(freshness_score, 1),
        freshness_reasoning=freshness_reasoning,
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
            """SELECT id, video_id, title, url, channel, channel_url,
                      views, vph, hours_old, published_date, modeled
               FROM competitor_videos
               WHERE tenant_id = $1
                 AND (modeled = false OR modeled IS NULL)
                 AND vph >= $2
               ORDER BY vph DESC
               LIMIT 20""",
            tenant_id, min_vph,
        )

        for row in rows:
            vph = float(row.get("vph") or 0)
            hours_old = float(row.get("hours_old") or 0)

            breakdown = calculate_confidence_with_breakdown(vph, hours_old)

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
    """Get competitor video candidates from Supabase."""
    candidates = []
    try:
        # Build query based on include_modeled flag
        if include_modeled:
            query = """SELECT id, video_id, title, url, channel, channel_url,
                              views, vph, hours_old, published_date, modeled
                       FROM competitor_videos
                       WHERE tenant_id = $1 AND vph >= $2
                       ORDER BY vph DESC
                       LIMIT $3"""
        else:
            query = """SELECT id, video_id, title, url, channel, channel_url,
                              views, vph, hours_old, published_date, modeled
                       FROM competitor_videos
                       WHERE tenant_id = $1
                         AND vph >= $2
                         AND (modeled = false OR modeled IS NULL)
                       ORDER BY vph DESC
                       LIMIT $3"""

        rows = await fetch_all(query, tenant_id, min_vph, limit * 2)

        for row in rows:
            vph = float(row.get("vph") or 0)
            hours_old = float(row.get("hours_old") or 0)

            breakdown = calculate_confidence_with_breakdown(vph, hours_old)

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
        result["has_transcript"] = row.get("distilled_at") is not None or include_transcript

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

    # 2. Get or create project
    from routes.projects import _get_or_create_project
    project = await _get_or_create_project(tenant_id)
    project_id = str(project["id"])

    # 3. Create video record
    video_title = candidate.get("title", "Untitled")
    channel = candidate.get("channel", "competitor")
    result = await fetch_one(
        """INSERT INTO videos (
            tenant_id, project_id, video_title, status, headline,
            source, reference_url, created_at
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, now())
        RETURNING id""",
        tenant_id, project_id, video_title, "idea_logged",
        video_title, f"autopilot_{channel}", candidate.get("url"),
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
    }
