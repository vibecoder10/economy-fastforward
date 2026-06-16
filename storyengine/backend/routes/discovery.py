"""Discovery Ideas API — AI-generated video ideas from competitor analysis.

Reads competitor_videos from Supabase, uses Claude to generate angles + title options,
stores results in discovery_ideas table. Supports on-demand refresh and one-click launch.
"""

import json
import uuid
from datetime import datetime, date
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel

from auth import get_tenant_id
from database import fetch_all, fetch_one, execute
from error_utils import humanize_error

router = APIRouter(prefix="/api/discovery", tags=["discovery"])


# --- Models ---

class TitleOption(BaseModel):
    title: str
    formula_id: str = ""
    thumbnail_text: str = ""
    score: float = 0


class DiscoveryIdea(BaseModel):
    id: str
    source_type: str
    competitor_title: Optional[str] = None
    competitor_channel: Optional[str] = None
    competitor_url: Optional[str] = None
    competitor_vph: Optional[float] = None
    competitor_thumbnail_url: Optional[str] = None
    our_angle: str
    hook: Optional[str] = None
    framework: Optional[str] = None
    estimated_appeal: Optional[float] = None
    appeal_breakdown: Optional[dict] = None
    title_options: list[dict] = []
    status: str = "fresh"
    batch_date: Optional[str] = None
    created_at: Optional[str] = None
    hook_type: Optional[str] = None
    tone: Optional[str] = None
    title_structure: Optional[str] = None
    thumbnail_style: Optional[str] = None


class LaunchIdeaRequest(BaseModel):
    title_index: int = 0
    video_length_minutes: int = 15


class DiscoveryStatus(BaseModel):
    is_refreshing: bool = False
    last_batch_date: Optional[str] = None
    idea_count: int = 0
    fresh_count: int = 0
    learnings_applied: int = 0  # How many learnings influenced latest idea generation
    error: Optional[str] = None  # Error from last refresh attempt


# --- Background task tracking ---

_refresh_tasks: dict[str, dict] = {}


# --- Endpoints ---

@router.get("/ideas", response_model=List[DiscoveryIdea])
async def get_discovery_ideas(
    status: Optional[str] = Query(None),
    limit: int = Query(20, le=50),
    batch_date: Optional[str] = Query(None),
    tenant_id: str = Depends(get_tenant_id),
):
    """List discovery ideas, sorted by appeal score."""
    conditions = ["di.tenant_id = $1"]
    params: list = [tenant_id]
    idx = 2

    if status:
        conditions.append(f"di.status = ${idx}")
        params.append(status)
        idx += 1
    else:
        # Default: show fresh ideas
        conditions.append(f"di.status = ${idx}")
        params.append("fresh")
        idx += 1

    if batch_date:
        conditions.append(f"di.batch_date = ${idx}")
        params.append(batch_date)
        idx += 1

    where = " AND ".join(conditions)
    query = f"""
        SELECT di.id, di.source_type, di.competitor_title, di.competitor_channel,
               di.competitor_url, di.competitor_vph, di.competitor_thumbnail_url,
               di.our_angle, di.hook, di.framework, di.estimated_appeal, di.appeal_breakdown,
               di.title_options, di.status, di.batch_date::text, di.created_at::text,
               ci.structured_metadata->'hook_dna'->>'type' as hook_type,
               ci.structured_metadata->'content_dna'->>'tone' as tone,
               ci.structured_metadata->'title_dna'->>'structure' as title_structure,
               ci.structured_metadata->'thumbnail_dna'->>'overall_style' as thumbnail_style
        FROM discovery_ideas di
        LEFT JOIN content_intelligence ci
            ON ci.source_id = di.competitor_video_id
            AND ci.tenant_id = di.tenant_id
            AND ci.source_type = 'competitor_transcript'
        WHERE {where}
        ORDER BY di.estimated_appeal DESC NULLS LAST, di.created_at DESC
        LIMIT ${idx}
    """
    params.append(limit)

    try:
        rows = await fetch_all(query, *params)
    except Exception as e:
        # Table may not exist yet
        print(f"Error fetching discovery ideas: {e}")
        return []

    ideas = []
    for row in rows:
        title_opts = row.get("title_options", [])
        if isinstance(title_opts, str):
            try:
                title_opts = json.loads(title_opts)
            except (json.JSONDecodeError, ValueError):
                title_opts = []

        appeal_bd = row.get("appeal_breakdown")
        if isinstance(appeal_bd, str):
            try:
                appeal_bd = json.loads(appeal_bd)
            except (json.JSONDecodeError, ValueError):
                appeal_bd = None

        ideas.append(DiscoveryIdea(
            id=str(row["id"]),
            source_type=row.get("source_type", "competitor"),
            competitor_title=row.get("competitor_title"),
            competitor_channel=row.get("competitor_channel"),
            competitor_url=row.get("competitor_url"),
            competitor_vph=float(row["competitor_vph"]) if row.get("competitor_vph") else None,
            competitor_thumbnail_url=row.get("competitor_thumbnail_url"),
            our_angle=row.get("our_angle", ""),
            hook=row.get("hook"),
            framework=row.get("framework"),
            estimated_appeal=float(row["estimated_appeal"]) if row.get("estimated_appeal") else None,
            appeal_breakdown=appeal_bd,
            title_options=title_opts,
            status=row.get("status", "fresh"),
            batch_date=row.get("batch_date"),
            created_at=row.get("created_at"),
            hook_type=row.get("hook_type"),
            tone=row.get("tone"),
            title_structure=row.get("title_structure"),
            thumbnail_style=row.get("thumbnail_style"),
        ))

    return ideas


@router.get("/status", response_model=DiscoveryStatus)
async def get_discovery_status(tenant_id: str = Depends(get_tenant_id)):
    """Check refresh status and latest batch info."""
    is_refreshing = tenant_id in _refresh_tasks and _refresh_tasks[tenant_id].get("running", False)

    last_batch = None
    idea_count = 0
    fresh_count = 0

    try:
        row = await fetch_one(
            "SELECT MAX(batch_date)::text as last_date, COUNT(*) as total FROM discovery_ideas WHERE tenant_id = $1",
            tenant_id,
        )
        if row:
            last_batch = row.get("last_date")
            idea_count = row.get("total", 0)

        fresh_row = await fetch_one(
            "SELECT COUNT(*) as count FROM discovery_ideas WHERE tenant_id = $1 AND status = 'fresh'",
            tenant_id,
        )
        if fresh_row:
            fresh_count = fresh_row.get("count", 0)
    except Exception as e:
        print(f"Error getting discovery status: {e}")

    # Get learnings count from last refresh task or from DB
    learnings_applied = 0
    if tenant_id in _refresh_tasks:
        learnings_applied = _refresh_tasks[tenant_id].get("learnings_applied", 0)
    if not learnings_applied:
        try:
            lr = await fetch_one(
                "SELECT COUNT(*) as count FROM learnings WHERE tenant_id = $1 AND active = true AND confidence >= 40",
                tenant_id,
            )
            learnings_applied = lr.get("count", 0) if lr else 0
        except Exception:
            pass

    # Get error from last refresh if any
    error = None
    if tenant_id in _refresh_tasks and not is_refreshing:
        error = _refresh_tasks[tenant_id].get("error")

    return DiscoveryStatus(
        is_refreshing=is_refreshing,
        last_batch_date=last_batch,
        idea_count=idea_count,
        fresh_count=fresh_count,
        learnings_applied=learnings_applied,
        error=error,
    )


@router.post("/refresh")
async def refresh_discovery_ideas(
    background_tasks: BackgroundTasks,
    tenant_id: str = Depends(get_tenant_id),
):
    """Trigger on-demand idea generation from competitor data."""
    if tenant_id in _refresh_tasks and _refresh_tasks[tenant_id].get("running", False):
        return {"status": "already_running", "message": "Refresh already in progress"}

    batch_id = str(uuid.uuid4())[:8]
    _refresh_tasks[tenant_id] = {"running": True, "batch_id": batch_id, "started": datetime.now().isoformat()}

    background_tasks.add_task(_run_discovery_generation, tenant_id, batch_id)

    return {"status": "started", "batch_id": batch_id, "message": "Generating ideas from competitor data..."}


@router.post("/ideas/{idea_id}/launch")
async def launch_idea(
    idea_id: str,
    body: LaunchIdeaRequest,
    background_tasks: BackgroundTasks,
    tenant_id: str = Depends(get_tenant_id),
):
    """One-click launch: create video from idea and start pipeline."""
    from routes.billing import check_plan_limits, increment_usage
    await check_plan_limits(tenant_id, "video")

    # Fetch the idea
    idea = await fetch_one(
        "SELECT * FROM discovery_ideas WHERE id = $1 AND tenant_id = $2",
        idea_id, tenant_id,
    )
    if not idea:
        raise HTTPException(status_code=404, detail="Idea not found")

    if idea.get("status") == "launched":
        raise HTTPException(status_code=400, detail="Idea already launched")

    # Get selected title
    title_opts = idea.get("title_options", [])
    if isinstance(title_opts, str):
        try:
            title_opts = json.loads(title_opts)
        except (json.JSONDecodeError, ValueError):
            title_opts = []

    title_index = min(body.title_index, len(title_opts) - 1) if title_opts else 0
    selected_title = title_opts[title_index] if title_opts else {}
    video_title = selected_title.get("title", idea.get("our_angle", "Untitled"))

    # Resolve project for tenant
    from routes.projects import _get_or_create_project
    project = await _get_or_create_project(tenant_id)
    project_id = str(project["id"])

    # Create video record pre-filled with idea data
    result = await fetch_one(
        """INSERT INTO videos (
            tenant_id, project_id, video_title, status, headline,
            hook_script, framework_angle, thesis,
            video_length_minutes, source,
            thumbnail_text, reference_url,
            created_at
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, now())
        RETURNING id""",
        tenant_id,
        project_id,
        video_title,
        "idea_logged",
        video_title,
        idea.get("hook"),
        idea.get("framework"),
        idea.get("our_angle"),
        body.video_length_minutes,
        f"discovery_{idea.get('source_type', 'competitor')}",
        selected_title.get("thumbnail_text"),
        idea.get("competitor_url"),
    )
    video_id = str(result["id"])
    await increment_usage(tenant_id, "videos_created")

    # Update idea status
    await execute(
        """UPDATE discovery_ideas
           SET status = 'launched', selected_title_index = $1, launched_video_id = $2, updated_at = now()
           WHERE id = $3""",
        title_index, video_id, idea_id,
    )

    # Trigger full pipeline in background (research → script → voice → ...)
    async def _run_full_pipeline():
        from pipeline_executor import PipelineExecutor
        executor = PipelineExecutor(tenant_id)
        result = await executor.run_research(video_id)
        if result.get("status") == "failed":
            return

        # Auto-cascade through pipeline steps until terminal, approval gate, or failure
        terminal = {"rendered", "uploaded", "uploaded_draft", "done", "published"}
        for _ in range(20):  # Safety limit
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
        "video_id": video_id,
        "video_title": video_title,
        "message": "Video created and research started",
    }


@router.post("/ideas/{idea_id}/dismiss")
async def dismiss_idea(
    idea_id: str,
    tenant_id: str = Depends(get_tenant_id),
):
    """Mark an idea as dismissed."""
    await execute(
        "UPDATE discovery_ideas SET status = 'dismissed', updated_at = now() WHERE id = $1 AND tenant_id = $2",
        idea_id, tenant_id,
    )
    return {"status": "dismissed", "idea_id": idea_id}


# --- Background Generation Logic ---

async def _run_discovery_generation(tenant_id: str, batch_id: str):
    """Generate ideas from recent competitor videos using Claude.

    Reads top competitor videos from Supabase, sends them to Claude API
    to generate our angle + 3 title options per video.
    """
    try:
        # Same text-LLM resolver scripts use: tenant's own Claude key if set,
        # otherwise their kie.ai key (one key for everything).
        from kie_unified import get_text_client_for_tenant, MissingGenerationKeyError
        try:
            text_client = await get_text_client_for_tenant(tenant_id)
        except MissingGenerationKeyError:
            print(f"[Discovery] No Claude or kie.ai API key for tenant {tenant_id}")
            _refresh_tasks[tenant_id] = {"running": False, "error": "No Claude or kie.ai API key configured. Add one in Settings → API Keys."}
            return

        # Fetch recent high-VPH competitor videos (not yet modeled)
        # Use distilled intelligence when available, fall back to raw transcript
        competitors = await fetch_all(
            """SELECT cv.id, cv.video_id, cv.title, cv.url, cv.channel, cv.vph,
                      cv.hours_old, cv.published_date, cv.thumbnail_url, cv.duration_seconds,
                      cv.distilled_at,
                      ci.summary as distilled_summary,
                      ci.structured_metadata as distilled_metadata,
                      CASE WHEN cv.distilled_at IS NOT NULL THEN NULL
                           ELSE LEFT(cv.transcript, 500) END as transcript_hook
               FROM competitor_videos cv
               LEFT JOIN content_intelligence ci
                   ON ci.source_id = cv.id AND ci.tenant_id = cv.tenant_id
                   AND ci.source_type = 'competitor_transcript'
               WHERE cv.tenant_id = $1
                 AND cv.vph >= 50
                 AND cv.hours_old <= 720
                 AND (cv.modeled = false OR cv.modeled IS NULL)
               ORDER BY cv.vph DESC
               LIMIT 15""",
            tenant_id,
        )

        if not competitors:
            # Check if there are ANY competitor videos to give a better error
            total = await fetch_one(
                "SELECT COUNT(*) as count FROM competitor_videos WHERE tenant_id = $1",
                tenant_id,
            )
            total_count = total.get("count", 0) if total else 0

            # Debug: check VPH distribution
            vph_stats = await fetch_one(
                "SELECT MAX(vph) as max_vph, AVG(vph) as avg_vph, COUNT(*) FILTER (WHERE vph > 0) as with_vph FROM competitor_videos WHERE tenant_id = $1",
                tenant_id,
            )
            max_vph = float(vph_stats.get("max_vph") or 0) if vph_stats else 0
            avg_vph = float(vph_stats.get("avg_vph") or 0) if vph_stats else 0
            with_vph = int(vph_stats.get("with_vph") or 0) if vph_stats else 0

            if total_count == 0:
                msg = "No competitor videos in database. Scrape competitor channels first."
            else:
                msg = f"No eligible competitor videos (need VPH >= 50, hours_old <= 720). {total_count} total, {with_vph} with VPH > 0, max VPH: {max_vph:.1f}, avg VPH: {avg_vph:.1f}. Try scraping channels with more popular videos."
            print(f"[Discovery] {msg}")
            _refresh_tasks[tenant_id] = {"running": False, "error": msg}
            return

        # Build competitor list for Claude (prefer distilled intelligence over raw transcript)
        comp_list = []
        for c in competitors:
            entry = {
                "title": c.get("title", ""),
                "channel": c.get("channel", ""),
                "vph": float(c.get("vph", 0)),
                "hours_old": float(c.get("hours_old", 0)),
                "url": c.get("url", ""),
            }
            # Use distilled intelligence when available (richer + cheaper)
            if c.get("distilled_summary"):
                entry["summary"] = c["distilled_summary"]
                metadata = c.get("distilled_metadata")
                if metadata:
                    import json
                    if isinstance(metadata, str):
                        metadata = json.loads(metadata)
                    # Hook DNA
                    hook = metadata.get("hook_dna") or metadata.get("hook", {})
                    if hook.get("opening_line"):
                        entry["opening_hook"] = hook["opening_line"]
                    if hook.get("type"):
                        entry["hook_type"] = hook["type"]
                    # Content DNA
                    content = metadata.get("content_dna") or metadata.get("content", {})
                    topics = content.get("topic_tags", [])
                    if topics:
                        entry["topics"] = topics
                    if content.get("tone"):
                        entry["tone"] = content["tone"]
                    # Title DNA
                    title_dna = metadata.get("title_dna", {})
                    if title_dna.get("structure"):
                        entry["title_structure"] = title_dna["structure"]
                    if title_dna.get("curiosity_mechanism"):
                        entry["curiosity_mechanism"] = title_dna["curiosity_mechanism"]
                    # Thumbnail DNA
                    thumb = metadata.get("thumbnail_dna", {})
                    if thumb.get("overall_style"):
                        entry["thumbnail_style"] = thumb["overall_style"]
                    if thumb.get("face_emotion"):
                        entry["thumbnail_emotion"] = thumb["face_emotion"]
                    # Retention DNA
                    retention = metadata.get("retention_dna", {})
                    if retention.get("first_hook_seconds"):
                        entry["hook_duration"] = retention["first_hook_seconds"]
                    # Engagement signals
                    engagement = metadata.get("engagement_signals", {})
                    if engagement.get("controversy_level"):
                        entry["controversy"] = engagement["controversy_level"]
            else:
                # Fall back to raw transcript snippet (first 300 chars)
                transcript_hook = c.get("transcript_hook") or ""
                if transcript_hook:
                    entry["opening_hook"] = transcript_hook.strip()
            comp_list.append(entry)

        # Call Claude to generate ideas
        import httpx

        # Get learning context from Supabase for prompt injection
        learnings_context = await _get_learnings_context(tenant_id)

        # Get channel identity for tenant-aware prompt (not hardcoded)
        channel_name, channel_niche = "", ""
        try:
            profile = await fetch_one(
                "SELECT channel_name, niche FROM channel_profiles WHERE tenant_id = $1",
                tenant_id,
            )
            if profile:
                channel_name = profile.get("channel_name", "")
                channel_niche = profile.get("niche", "")
            if not channel_name:
                # Fallback to projects table
                project = await fetch_one(
                    "SELECT name, niche FROM projects WHERE tenant_id = $1 LIMIT 1",
                    tenant_id,
                )
                if project:
                    channel_name = project.get("name", "")
                    channel_niche = channel_niche or project.get("niche", "")
            if not channel_name:
                # Final fallback to tenant name
                tenant = await fetch_one("SELECT name FROM tenants WHERE id = $1", tenant_id)
                if tenant:
                    channel_name = tenant.get("name", "")
        except Exception as e:
            print(f"[Discovery] Error loading channel profile: {e}")

        prompt = _build_discovery_prompt(comp_list, learnings_context, channel_name, channel_niche)
        try:
            text = await text_client.generate(
                prompt,
                model="claude-haiku-4-5-20251001",
                max_tokens=4096,
            )
        except Exception as e:
            print(f"[Discovery] Generation error: {e}")
            _refresh_tasks[tenant_id] = {"running": False, "error": f"Idea generation failed: {e}"}
            return

        # Parse Claude's response
        ideas = _parse_ideas_response(text)

        # Store ideas in database
        today = date.today()
        inserted = 0
        for idea in ideas:
            # Find matching competitor for metadata
            comp_match = next(
                (c for c in competitors if c.get("title", "").lower() in idea.get("source_title", "").lower()
                 or idea.get("source_title", "").lower() in c.get("title", "").lower()),
                None,
            )

            comp_id = str(comp_match["id"]) if comp_match else None
            comp_title = comp_match.get("title") if comp_match else idea.get("source_title")
            comp_channel = comp_match.get("channel") if comp_match else None
            comp_url = comp_match.get("url") if comp_match else None
            comp_vph = float(comp_match.get("vph", 0)) if comp_match else None

            # Use yt-dlp thumbnail URL if available, fallback to hqdefault
            thumb_url = comp_match.get("thumbnail_url") if comp_match else None
            if not thumb_url and comp_url and "youtube.com" in str(comp_url):
                vid_id = comp_url.split("v=")[-1].split("&")[0] if "v=" in str(comp_url) else None
                if vid_id:
                    thumb_url = f"https://img.youtube.com/vi/{vid_id}/hqdefault.jpg"

            try:
                await execute(
                    """INSERT INTO discovery_ideas (
                        tenant_id, source_type, competitor_video_id, competitor_title,
                        competitor_channel, competitor_url, competitor_vph,
                        competitor_thumbnail_url,
                        our_angle, hook, framework, estimated_appeal,
                        appeal_breakdown, title_options, status,
                        batch_date, batch_id
                    ) VALUES ($1, $2, $3::uuid, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13::jsonb, $14::jsonb, 'fresh', $15, $16)""",
                    tenant_id,
                    "competitor",
                    comp_id,
                    comp_title,
                    comp_channel,
                    comp_url,
                    comp_vph,
                    thumb_url,
                    idea.get("our_angle") or "No angle specified",
                    idea.get("hook"),
                    idea.get("framework"),
                    float(idea["estimated_appeal"]) if idea.get("estimated_appeal") is not None else None,
                    json.dumps(idea["appeal_breakdown"]) if idea.get("appeal_breakdown") else None,
                    json.dumps(idea.get("title_options") or []),
                    today,
                    batch_id,
                )
                inserted += 1
            except Exception as e:
                print(f"[Discovery] Error inserting idea: {e}")
                import traceback
                traceback.print_exc()
                # Log the problematic data for debugging
                print(f"[Discovery]   comp_id={comp_id}, comp_vph={comp_vph}, appeal={idea.get('estimated_appeal')}")
                print(f"[Discovery]   title_options type={type(idea.get('title_options'))}")

        # Count learnings that influenced these ideas
        learnings_count = learnings_context.count("•") if learnings_context else 0

        print(f"[Discovery] Generated {inserted} ideas from {len(competitors)} competitors for tenant {tenant_id} (influenced by {learnings_count} learnings)")
        if inserted == 0 and len(competitors) > 0:
            msg = f"Claude returned {len(ideas)} ideas from {len(competitors)} competitors but 0 were saved. Parsed ideas: {len(ideas)}. This may indicate a response parsing issue."
            print(f"[Discovery] WARNING: {msg}")
            _refresh_tasks[tenant_id] = {"running": False, "error": msg, "ideas_generated": 0, "batch_id": batch_id, "learnings_applied": learnings_count}
        else:
            _refresh_tasks[tenant_id] = {"running": False, "ideas_generated": inserted, "batch_id": batch_id, "learnings_applied": learnings_count}

    except Exception as e:
        print(f"[Discovery] Error: {e}")
        _refresh_tasks[tenant_id] = {
            "running": False,
            "error": humanize_error(e, context="Idea generation failed"),
        }


async def _get_learnings_context(tenant_id: str) -> str:
    """Query Supabase learnings + title_insights, format for prompt injection.

    This is the READ side of the learning loop. When videos perform well/poorly,
    patterns are extracted and stored in the learnings table. This function reads
    those patterns and formats them for Claude to use when generating new titles.
    """
    sections = []

    try:
        # 1. Title learnings from our own video performance
        title_learnings = await fetch_all(
            """SELECT pattern, avg_ctr, sample_size, confidence
               FROM learnings
               WHERE tenant_id = $1 AND active = true AND category = 'title'
                 AND confidence >= 40 AND sample_size >= 2
               ORDER BY avg_ctr DESC NULLS LAST LIMIT 5""",
            tenant_id,
        )
        if title_learnings:
            lines = ["## Channel-Specific Title Performance",
                      "Based on your channel's historical data:"]
            for row in title_learnings:
                ctr = float(row["avg_ctr"]) if row.get("avg_ctr") else 0
                n = int(row.get("sample_size", 0))
                conf = float(row.get("confidence", 0))
                verdict = "PROVEN" if conf >= 60 else "AVOID" if conf <= 40 else "TESTING"
                lines.append(f"- {row['pattern']}: avg {ctr:.1f}% CTR ({n} videos) [{verdict}]")
            sections.append("\n".join(lines))

        # 2. Hook learnings
        hook_learnings = await fetch_all(
            """SELECT pattern, avg_ctr, avg_retention, sample_size
               FROM learnings
               WHERE tenant_id = $1 AND active = true AND category = 'hook'
                 AND confidence >= 40
               ORDER BY avg_retention DESC NULLS LAST LIMIT 4""",
            tenant_id,
        )
        if hook_learnings:
            lines = ["## Hook Performance"]
            for row in hook_learnings:
                ret = float(row["avg_retention"]) if row.get("avg_retention") else 0
                ctr_str = f", {float(row['avg_ctr']):.1f}% CTR" if row.get("avg_ctr") else ""
                lines.append(f"- {row['pattern']}: {ret:.0f}% retention{ctr_str}")
            sections.append("\n".join(lines))

        # 3. Framework learnings
        fw_learnings = await fetch_all(
            """SELECT pattern, avg_ctr, avg_retention, sample_size
               FROM learnings
               WHERE tenant_id = $1 AND active = true AND category = 'framework'
                 AND confidence >= 40
               ORDER BY avg_ctr DESC NULLS LAST LIMIT 4""",
            tenant_id,
        )
        if fw_learnings:
            lines = ["## Framework Performance"]
            for row in fw_learnings:
                ctr = float(row["avg_ctr"]) if row.get("avg_ctr") else 0
                ret = float(row["avg_retention"]) if row.get("avg_retention") else 0
                lines.append(f"- {row['pattern']}: {ctr:.1f}% CTR, {ret:.0f}% retention")
            sections.append("\n".join(lines))

        # 4. Title insights from competitor analysis
        insights = await fetch_all(
            """SELECT pattern_name, description, avg_vph, count, confidence
               FROM title_insights
               WHERE tenant_id = $1 AND confidence >= 50
               ORDER BY avg_vph DESC NULLS LAST LIMIT 5""",
            tenant_id,
        )
        if insights:
            lines = ["## Competitor Title Patterns (What Works in This Niche)"]
            for row in insights:
                vph = float(row["avg_vph"]) if row.get("avg_vph") else 0
                lines.append(f"- {row['pattern_name']}: avg {vph:.0f} VPH ({row.get('count', 0)} videos)")
                if row.get("description"):
                    lines.append(f"  {row['description']}")
            sections.append("\n".join(lines))

        # 5. Script/hook learnings from our own videos
        script_learnings = await fetch_all(
            """SELECT pattern, avg_ctr, avg_retention, sample_size
               FROM learnings
               WHERE tenant_id = $1 AND active = true AND category = 'script'
                 AND confidence >= 40
               ORDER BY avg_retention DESC NULLS LAST LIMIT 4""",
            tenant_id,
        )
        if script_learnings:
            lines = ["## Script Structure Performance"]
            for row in script_learnings:
                ret = float(row["avg_retention"]) if row.get("avg_retention") else 0
                ctr = float(row["avg_ctr"]) if row.get("avg_ctr") else 0
                lines.append(f"- {row['pattern']}: {ret:.0f}% retention, {ctr:.1f}% CTR ({row.get('sample_size', 0)} videos)")
            sections.append("\n".join(lines))

    except Exception as e:
        print(f"[Discovery] Error loading learnings context: {e}")

    # 6. Niche intelligence recommendations (from distilled competitor DNA)
    try:
        from distillation.advisor import get_advisor
        advisor = get_advisor()
        recs = await advisor.get_recommendations(tenant_id)
        intel_context = recs.to_prompt_context()
        if intel_context:
            sections.append(intel_context)
    except Exception as e:
        print(f"[Discovery] Error loading intelligence recommendations: {e}")

    if not sections:
        return ""

    return "\n\nCHANNEL PERFORMANCE DATA (Use this to inform your title suggestions — favor proven patterns, avoid anti-patterns):\n\n" + "\n\n".join(sections)


def _build_discovery_prompt(competitors: list[dict], learnings_context: str = "",
                            channel_name: str = "", channel_niche: str = "") -> str:
    """Build the Claude prompt for idea generation.

    Includes static Master Formula rules + dynamic learnings from Supabase.
    Channel identity is pulled from the database — no hardcoded channel names.
    """
    # Build competitor list with transcript hooks when available
    comp_lines = []
    for c in competitors:
        line = f"- \"{c['title']}\" by {c['channel']} (VPH: {c['vph']:.0f}, {c['hours_old']:.0f}h old, URL: {c['url']})"
        if c.get("opening_hook"):
            # Show first ~200 chars of their opening for hook analysis
            hook_preview = c["opening_hook"][:200].replace("\n", " ")
            line += f"\n  Opening: \"{hook_preview}...\""
        comp_lines.append(line)
    comp_text = "\n".join(comp_lines)

    # Dynamic channel identity (falls back to generic if not configured)
    ch_name = channel_name or "your YouTube channel"
    ch_niche = channel_niche or "educational content"

    # Master Formula title rules (from title_patterns.json)
    mf_rules = """
TITLE RULES (Master Formula System):
- MF-0: "How [Entity] [Clear Action] [Target]" — Maximum clarity, S-tier
- MF-1: "How [Entity] Secretly/Quietly [Evil Action] [Mechanism]" — Hidden exposé, S-tier
- MF-2: "Why [Country/Entity] [Dramatic Present-Tense Claim]" — Causal authority, S-tier
- MF-6: "[Country]'s [Ominous Adjective] [Decline Noun]" — Compact authority, A-tier

Hard rules:
- 30-55 characters (HARD CEILING at 55)
- First word after How/Why MUST be a proper noun
- NEVER use "YOU/YOUR" — declarative statements only
- NEVER use ALL CAPS except acronyms (US, NATO, PBOC)
- Prefer "How" or "Why" openers — highest CTR in this niche
- Use numbers/dollar amounts when available (+15-25% CTR)
- Negative framing outperforms positive by 63%
- Thumbnail text: EXACTLY 2 words, strategic judgment (e.g., CHOKE POINT, POWER GRAB)
"""

    return f"""You are a YouTube content strategist for a {ch_niche} channel called "{ch_name}".
Analyze what makes these competitor videos successful — their titles, hooks, and structures — then generate unique angles for OUR channel.

{mf_rules}
{learnings_context}

Below are recent high-performing competitor videos (sorted by Views Per Hour).
When an "Opening:" is shown, that's the competitor's actual opening hook — study what makes it compelling:

{comp_text}

For the TOP 5 most promising videos, generate a unique angle for OUR channel. For each:

1. **source_title**: The competitor video title you're modeling
2. **our_angle**: Our unique take (2-3 sentences) — NOT a copy, but inspired by the same topic
3. **hook**: A compelling 15-second opening hook (study the competitor openings above for inspiration)
4. **framework**: The analytical framework (e.g., "Machiavellian Power Analysis", "Systems Thinking", "Game Theory")
5. **estimated_appeal**: Score 1-10 for how well this fits our channel
6. **appeal_breakdown**: Object with scores for {{  "timeliness": 1-10, "audience_fit": 1-10, "content_gap": 1-10, "virality": 1-10, "depth_potential": 1-10, "visual_potential": 1-10 }}
7. **title_options**: Array of exactly 3 title options, each with:
   - **title**: The video title (compelling, specific, under 55 chars, follow Master Formula rules above)
   - **formula_id**: Which MF formula used (e.g., "MF-0", "MF-1", "MF-2", "MF-6")
   - **thumbnail_text**: Short bold text for thumbnail (EXACTLY 2 words, strategic judgment)
   - **score**: Predicted CTR score 1-10

Return ONLY valid JSON array. No markdown, no explanation. Example format:
[
  {{
    "source_title": "...",
    "our_angle": "...",
    "hook": "...",
    "framework": "...",
    "estimated_appeal": 8,
    "appeal_breakdown": {{ "timeliness": 9, "audience_fit": 8, "content_gap": 7, "virality": 8, "depth_potential": 9, "visual_potential": 7 }},
    "title_options": [
      {{ "title": "...", "formula_id": "MF-2", "thumbnail_text": "CHOKE POINT", "score": 8 }},
      {{ "title": "...", "formula_id": "MF-1", "thumbnail_text": "POWER GRAB", "score": 7 }},
      {{ "title": "...", "formula_id": "MF-0", "thumbnail_text": "PROXY WAR", "score": 6 }}
    ]
  }}
]"""


def _parse_ideas_response(text: str) -> list[dict]:
    """Parse Claude's JSON response with fallback chain."""
    # Try direct parse
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
    except (json.JSONDecodeError, ValueError):
        pass

    # Try removing markdown fences
    import re
    cleaned = re.sub(r"```(?:json)?\s*", "", text).strip()
    cleaned = re.sub(r"```\s*$", "", cleaned).strip()
    try:
        result = json.loads(cleaned)
        if isinstance(result, list):
            return result
    except (json.JSONDecodeError, ValueError):
        pass

    # Try extracting JSON array
    match = re.search(r"\[[\s\S]*\]", text)
    if match:
        try:
            result = json.loads(match.group())
            if isinstance(result, list):
                return result
        except (json.JSONDecodeError, ValueError):
            pass

    print(f"[Discovery] Failed to parse Claude response: {text[:200]}")
    return []
