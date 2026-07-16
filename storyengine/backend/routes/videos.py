"""Video CRUD + stage transitions."""

import asyncio
import json
import logging
import re
import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from auth import get_tenant_id
from models import (
    VideoSummary, VideoDetail, STAGE_ORDER, PIPELINE_STAGES,
    SceneTextUpdate, SceneToneUpdate, SegmentUpdate, StoryboardModeUpdate,
    CreateVideoRequest,
)
from database import fetch_all, fetch_one, execute, safe_column
from error_utils import humanize_error
from status_map import get_next_status_supabase, normalize_stage_plan, first_status_for_plan
from prompt_defaults import VIDEO_MOTION_SYSTEM_PROMPT, SCRIPT_SYSTEM_PROMPT, THUMBNAIL_SYSTEM_PROMPT, SOUND_CURATION_SYSTEM_PROMPT, SOUND_GENERATION_SYSTEM_PROMPT, RESEARCH_SYSTEM_PROMPT
from typing import Optional, Any


def _strip_md(s: Optional[str]) -> Optional[str]:
    """Strip markdown formatting chars from a label-ish field. The AI producer
    likes to bold framework angles ("**Comic escalation**"); stored raw, the
    asterisks leak into analytics grouping and the UI."""
    if not s:
        return None
    return re.sub(r"[*_`#]", "", s).strip() or None


def _spoken_word_count(text: str) -> int:
    """Deterministic voiceover word count; never trust model self-counts."""
    return len(re.findall(r"\b[\w]+(?:[-'][\w]+)*\b", str(text or "")))


def _unit_display_name(item: Any) -> str:
    if isinstance(item, dict):
        nested = item.get("unit") or item.get("machine")
        if nested and not (item.get("name") or item.get("title") or item.get("designation") or item.get("code")):
            return _unit_display_name(nested)
        name = str(item.get("name") or item.get("title") or "").strip()
        designation = str(item.get("designation") or item.get("code") or "").strip()
        if name and designation and designation.lower() not in name.lower():
            return f"{designation} {name}".strip()
        return name or designation
    return str(item or "").strip()


def _unit_code(text: str) -> str:
    s = str(text or "").upper().replace("–", "-").replace("—", "-")
    for pat in (r"\b(?:X?Y?B|FB)-?\d{1,3}[A-Z]?\b", r"\b[A-Z]{1,4}-\d{1,4}[A-Z]?\b"):
        m = re.search(pat, s)
        if m:
            return m.group(0).replace(" ", "")
    words = re.findall(r"[A-Z0-9]+", s)
    return " ".join(words[:4])


def _normalized_unit_code(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", _unit_code(text).upper())


def _research_card_for_machine(payload: dict, machine: str) -> Optional[dict]:
    if not isinstance(payload, dict):
        return None
    cards = payload.get("unit_research_cards") or payload.get("machine_research_cards") or payload.get("research_cards")
    if not isinstance(cards, list):
        return None
    target_name = _unit_display_name(machine).strip().lower()
    target_code = _normalized_unit_code(machine)
    for card in cards:
        if not isinstance(card, dict):
            continue
        raw_unit = card.get("unit") or card.get("machine") or card.get("name") or card.get("designation") or card.get("title") or ""
        card_name = _unit_display_name(raw_unit).strip().lower()
        card_code = _normalized_unit_code(_unit_display_name(raw_unit))
        if (target_name and card_name == target_name) or (target_code and card_code == target_code):
            return card
        if isinstance(raw_unit, dict):
            nested_name = _unit_display_name(raw_unit).strip().lower()
            nested_code = _normalized_unit_code(_unit_display_name(raw_unit))
            if (target_name and nested_name == target_name) or (target_code and nested_code == target_code):
                return card
        # No substring fallback: B-2 must never match B-21.
    return None


def _research_source_for_machine(payload: dict, machine: str) -> tuple[str, str]:
    card = _research_card_for_machine(payload, machine)
    if card:
        return json.dumps(card, ensure_ascii=False, indent=2)[:9000], "unit_research_card"
    if not isinstance(payload, dict):
        payload = {}
    source = "\n\n".join(
        str(payload.get(k) or "")
        for k in ("fact_sheet", "source_bibliography", "framework_analysis", "historical_parallels")
        if payload.get(k)
    )[:6000]
    return source, "legacy_research_blob"


def _locked_machine_for_scene(payload: dict, scene: int, fallback_text: str = "") -> str:
    roster = payload.get("unit_roster") if isinstance(payload, dict) else None
    if isinstance(roster, list) and 1 <= scene <= len(roster):
        name = _unit_display_name(roster[scene - 1])
        if name:
            return name
    return fallback_text[:120]


def _parse_script_validation(val: Any) -> Optional[str]:
    """Parse script_validation, converting plain-text format to JSON if needed.

    The pipeline stores script_validation as plain text like:
        Editorial validation: PASSED
        [PASS] number_density: 49/19 specific numbers found
        [FAIL] framework_density: 22% framework density

    The frontend expects JSON: {"passed": bool, "checks": [{name, passed, detail}]}
    This function converts the plain text to JSON string so the frontend can parse it.
    If the value is already valid JSON, it passes through unchanged.
    """
    if val is None:
        return None
    if not isinstance(val, str):
        return None
    val = val.strip()
    if not val:
        return None

    # If it's already valid JSON with the expected structure, return as-is
    try:
        parsed = json.loads(val)
        if isinstance(parsed, dict) and "checks" in parsed:
            return val
    except (json.JSONDecodeError, ValueError):
        pass

    # Parse the plain text format
    lines = val.split("\n")
    if not lines:
        return None

    # First line: "Editorial validation: PASSED" or "Editorial validation: FAILED"
    overall_passed = "PASSED" in lines[0].upper() if lines[0] else True

    checks = []
    for line in lines[1:]:
        line = line.strip()
        # Match "[PASS] name: detail", "[FAIL] name: detail", or "[WARN] name: detail".
        m = re.match(r"\[(PASS|FAIL|WARN)\]\s+(\w+):\s*(.*)", line)
        if m:
            detail = m.group(3)
            # N5: carry advisory flags honestly - a WARN tag or an
            # "advisory: "-prefixed detail is warn-severity, and the raw
            # prefix is a machine tag, not user-facing copy.
            advisory = m.group(1) == "WARN" or detail.lower().startswith("advisory: ")
            if detail.lower().startswith("advisory: "):
                detail = detail[len("advisory: "):]
            checks.append({
                "name": m.group(2),
                "passed": m.group(1) != "FAIL",
                "detail": detail,
                "advisory": advisory,
            })

    if not checks:
        return None

    result = {
        "passed": overall_passed,
        "checks": checks,
        "advisory_warnings": [
            check["detail"] for check in checks if check.get("advisory")
        ],
    }
    return json.dumps(result)


def _parse_json_field(val: Any) -> Optional[dict]:
    """Parse a JSON field that might be string or dict.

    Handles double-encoded JSON (JSON string inside JSON string) which can happen
    when data is stored as text in PostgreSQL but was originally JSON.
    """
    if val is None:
        return None
    if isinstance(val, dict):
        return val
    if isinstance(val, str):
        try:
            result = json.loads(val)
            # Handle double-encoded JSON - if result is still a string, parse again
            if isinstance(result, str):
                result = json.loads(result)
            if isinstance(result, dict):
                return result
            return None
        except (json.JSONDecodeError, ValueError):
            return None
    return None


def _parse_stage_plan(val: Any) -> Optional[list]:
    """Parse the pipeline_stages JSONB column (a list of enabled stage keys, or
    None for the full pipeline). asyncpg may hand it back as a list or a JSON
    string depending on codecs."""
    if val is None:
        return None
    if isinstance(val, list):
        return val or None
    if isinstance(val, str):
        try:
            result = json.loads(val)
            return result if isinstance(result, list) and result else None
        except (json.JSONDecodeError, ValueError):
            return None
    return None

router = APIRouter(prefix="/api/videos", tags=["videos"])
logger = logging.getLogger(__name__)


def _next_stage(current: str) -> Optional[str]:
    """Get the next pipeline stage.

    Uses the full 18-stage pipeline order from status_map, not the
    abbreviated 10-stage PIPELINE_STAGES used for UI display dots.
    This ensures intermediate statuses (researching, scripting, etc.)
    can still advance correctly.
    """
    return get_next_status_supabase(current)


@router.get("", response_model=list[VideoSummary])
async def list_videos(
    status: Optional[str] = Query(None),
    limit: int = Query(50, le=100),
    offset: int = Query(0),
    tenant_id: str = Depends(get_tenant_id),
):
    """List videos with optional status filter."""
    if status:
        rows = await fetch_all(
            """SELECT id, video_title, status, thumbnail_url, accent_color, total_cost, views, ctr,
                      created_at::text, updated_at::text
               FROM videos WHERE tenant_id = $1 AND status = $2 AND deleted_at IS NULL
               ORDER BY updated_at DESC LIMIT $3 OFFSET $4""",
            tenant_id, status, limit, offset,
        )
    else:
        rows = await fetch_all(
            """SELECT id, video_title, status, thumbnail_url, accent_color, total_cost, views, ctr,
                      created_at::text, updated_at::text
               FROM videos WHERE tenant_id = $1 AND deleted_at IS NULL
               ORDER BY updated_at DESC LIMIT $2 OFFSET $3""",
            tenant_id, limit, offset,
        )

    return [
        VideoSummary(
            id=str(r["id"]),
            video_title=r.get("video_title"),
            status=r.get("status"),
            thumbnail_url=r.get("thumbnail_url"),
            accent_color=r.get("accent_color", "#00D4AA"),
            total_cost=float(r.get("total_cost") or 0),
            views=r.get("views") or 0,
            ctr=float(r["ctr"]) if r.get("ctr") else None,
            characters_approved_at=r.get("characters_approved_at"),
            story_locked_at=r.get("story_locked_at"),
            created_at=r.get("created_at"),
            updated_at=r.get("updated_at"),
        )
        for r in rows
    ]


_STYLE_PRESET_IDS = {"pixar_3d", "flat_2d", "realistic", "anime", "watercolor", "comic"}


def _normalize_style_preset(value: str) -> Optional[str]:
    """Map a stored visual_style (preset id OR display label like 'Pixar 3D')
    onto one of the six canonical preset ids. None when unmappable."""
    v = (value or "").strip().lower()
    if not v:
        return None
    key = v.replace(" ", "_").replace("-", "_")
    if key in _STYLE_PRESET_IDS:
        return key
    if "pixar" in v or "3d" in v:
        return "pixar_3d"
    if "flat" in v or "2d" in v:
        return "flat_2d"
    if "anime" in v:
        return "anime"
    if "watercolor" in v or "storybook" in v:
        return "watercolor"
    if "comic" in v:
        return "comic"
    if "real" in v or "cinematic" in v or "photo" in v:
        return "realistic"
    return None


@router.get("/style-default")
async def get_style_default(tenant_id: str = Depends(get_tenant_id)):
    """The channel's current visual style as a preset id, so the New Video
    modal can preselect it. The locked channel format wins; otherwise the most
    recent video's style. preset_id is null when the channel has no style
    signal yet (brand-new tenant)."""
    preset, source = None, None
    try:
        from channel_format import get_channel_format, style_preset_for_format
        fmt, locked = await get_channel_format(tenant_id)
        if locked:
            preset = style_preset_for_format(fmt)
            if preset:
                source = "locked_format"
    except Exception as e:  # noqa: BLE001 - fall through to recent-video signal
        logging.getLogger(__name__).warning("style-default: format lookup failed: %s", e)
    if not preset:
        row = await fetch_one(
            """SELECT visual_style FROM videos
               WHERE tenant_id = $1 AND deleted_at IS NULL
                 AND visual_style IS NOT NULL AND btrim(visual_style) <> ''
               ORDER BY created_at DESC LIMIT 1""",
            tenant_id,
        )
        if row and row.get("visual_style"):
            preset = _normalize_style_preset(row["visual_style"])
            if preset:
                source = "recent_video"
    return {"preset_id": preset, "source": source}


@router.post("", response_model=VideoSummary)
async def create_video(
    body: CreateVideoRequest,
    background_tasks: BackgroundTasks,
    tenant_id: str = Depends(get_tenant_id),
):
    """Create a new video idea."""
    from routes.billing import check_plan_limits, increment_usage
    await check_plan_limits(tenant_id, "video")

    from routes.projects import _get_or_create_project

    project = await _get_or_create_project(tenant_id)
    project_id = str(project["id"])

    # Per-video stage plan: which stages this video should run (script-only,
    # script+voice, full video, etc.). When the creator picks a reduced plan it
    # becomes the single source of truth, and the legacy skip_research /
    # skip_voice flags are derived from it so existing gates keep working. A
    # full plan (or none) stores NULL → unchanged full-pipeline behavior.
    plan = normalize_stage_plan(body.pipeline_stages)

    # Static-documentary channels (identity says the format is held images +
    # Ken Burns over narration, e.g. Designed vs Used) never animate: their
    # videos get render_mode='static_docu' and a plan without video/sound.
    # Voice is mandatory there — the narration IS the audio track.
    from static_docu import static_mode_for_tenant, STATIC_RENDER_MODE
    from status_map import static_stage_plan
    render_mode = None
    try:
        if await static_mode_for_tenant(tenant_id):
            render_mode = STATIC_RENDER_MODE
            plan = static_stage_plan(body.pipeline_stages)
    except Exception as e:  # detection must never block creation
        import logging
        logging.getLogger(__name__).warning("static-mode detection failed: %s", e)

    if plan is not None:
        skip_research = "research" not in plan
        skip_voice = "voice" not in plan
    else:
        skip_research = body.skip_research
        skip_voice = body.skip_voice
    writer_guidance = body.writer_guidance
    if render_mode == STATIC_RENDER_MODE:
        skip_voice = False
        # Exact-figures documentary voice: facts come from the research payload
        # (the factual gate enforces it), but the NARRATION must not read its
        # citations aloud — "according to Wikipedia" is not this format's voice.
        writer_guidance = ((writer_guidance or "") + (
            "\n\nATTRIBUTION STYLE: State facts directly with authority. Never "
            "say 'according to Wikipedia' or cite websites/blogs aloud. If a "
            "claim needs an on-air source, attribute it to the institution "
            "(the Army, Congress, GAO, the program office) — otherwise let the "
            "research-verified figure stand on its own.")).strip()

    # Optional "copy this video's style" reference (Create-form modeling path).
    # When a valid YouTube link is given, the video is created in "modeled" mode:
    # the creator's own topic/title is kept and the reference's style is copied
    # onto it (scoped to the switched-on stages) by a background task. The video
    # holds at 'idea_logged' until that copy finishes.
    reference_url = (body.reference_url or "").strip() or None
    reference_youtube_id = None
    if reference_url:
        from routes.model_video import _parse_youtube_id
        reference_youtube_id = _parse_youtube_id(reference_url)
        if not reference_youtube_id:
            raise HTTPException(
                status_code=400,
                detail="That doesn't look like a YouTube link. Paste a youtube.com or youtu.be URL to copy a video's style.",
            )
    is_modeled = reference_youtube_id is not None

    # Where to start: the first enabled stage's status (so a thumbnail-only
    # video begins at 'ready_for_thumbnail', a script-only at 'ready_for_scripting',
    # etc.). Modeled videos hold at 'idea_logged' until the style copy lands. The
    # plan-less legacy path still honors skip_research.
    if is_modeled:
        initial_status = "idea_logged"
    elif plan is not None:
        initial_status = first_status_for_plan(plan)
    else:
        initial_status = "ready_for_scripting" if skip_research else "idea_logged"
    source_val = "modeled" if is_modeled else body.source_url

    style_override = (body.image_style_override or "").strip() or None
    row = await fetch_one(
        """INSERT INTO videos (tenant_id, project_id, video_title, status, source, framework_angle, video_length_minutes, writer_guidance, visual_style, image_style_override, accent_color, aspect_ratio, video_resolution, skip_voice, pipeline_stages, reference_url, render_mode)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, COALESCE($11, '#00D4AA'), $12, $13, $14, $15, $16, $17)
           RETURNING id, video_title, status, thumbnail_url, accent_color, total_cost, views, ctr,
                     created_at::text, updated_at::text""",
        tenant_id, project_id, body.title.strip(), initial_status, source_val, _strip_md(body.framework_angle),
        body.video_length_minutes, writer_guidance, body.visual_style, style_override, body.accent_color,
        body.aspect_ratio, body.video_resolution, skip_voice, json.dumps(plan) if plan is not None else None, reference_url,
        render_mode,
    )

    await increment_usage(tenant_id, "videos_created")

    # Seed the app-owned Drive workspace out of band. Missing credentials or a
    # Drive outage must never roll back an otherwise valid video creation.
    from drive_workspace import sync_video_workspace_fail_soft
    background_tasks.add_task(sync_video_workspace_fail_soft, str(row["id"]), tenant_id)

    # House script format: prepend the saved template (if any) so every script
    # pathway writes in the channel's format. Fail-soft, never blocks creation.
    try:
        from routes.script_templates import apply_default_template
        await apply_default_template(tenant_id, str(row["id"]))
    except Exception as e:
        logging.getLogger(__name__).warning("apply script template failed: %s", e)

    # Locked channel format: default the look when the creator didn't pick one.
    try:
        from channel_format import apply_format_defaults
        await apply_format_defaults(tenant_id, str(row["id"]))
    except Exception as e:
        logging.getLogger(__name__).warning("apply format defaults failed: %s", e)

    # Locked channel cast: attach the series characters from second one.
    try:
        from routes.characters import apply_locked_cast
        await apply_locked_cast(tenant_id, str(row["id"]))
    except Exception as e:
        logging.getLogger(__name__).warning("apply locked cast failed: %s", e)

    # Lock the chosen look in as the channel identity (preset/custom path; the
    # clone path locks in later, when modeling writes the DNA — see model_video).
    if body.lock_in_identity and style_override and not is_modeled:
        try:
            from routes.visual_styles import upsert_active_visual_style
            await upsert_active_visual_style(
                project_id, (body.visual_style_label or "Custom style"), style_override,
            )
        except Exception as e:  # never block video creation on lock-in
            import logging
            logging.getLogger(__name__).warning("lock-in visual style failed: %s", e)

    # Kick off the style copy in the background (scoped to the chosen stages).
    if is_modeled:
        from routes.pipeline import _set_task_status
        from routes.model_video import _run_modeling, TASK_TYPE
        _set_task_status(str(row["id"]), "running", "Copying the video's style…",
                         tenant_id=tenant_id, task_type=TASK_TYPE)
        background_tasks.add_task(
            _run_modeling, tenant_id, str(row["id"]), reference_youtube_id,
            reference_url, plan, True,
            body.lock_in_identity,
        )

    return VideoSummary(
        id=str(row["id"]),
        video_title=row.get("video_title"),
        status=row.get("status"),
        thumbnail_url=row.get("thumbnail_url"),
        accent_color=row.get("accent_color", "#00D4AA"),
        total_cost=float(row.get("total_cost") or 0),
        views=row.get("views") or 0,
        ctr=float(row["ctr"]) if row.get("ctr") else None,
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


@router.get("/{video_id}", response_model=VideoDetail)
async def get_video(video_id: str, tenant_id: str = Depends(get_tenant_id)):
    """Get full video detail."""
    r = await fetch_one(
        """SELECT id, video_title, status, airtable_record_id, headline, source,
                  framework_angle, thematic_framework, hook_script, past_context,
                  present_parallel, future_prediction, writer_guidance, thesis, executive_hook,
                  research_payload, original_dna, script, script_validation, story_bible,
                  thumbnail_url, thumbnail_prompt, thumbnail_style_override,
                  accent_color, visual_style, image_style_override, image_model_override, video_model,
                  dialogue_audio, render_mode, skip_voice, pipeline_stages,
                  video_length_minutes, youtube_url, final_video_url, total_cost, views, ctr, avg_retention,
                  impressions, likes, comments, performance_verdict,
                  source_views, source_channel, source_urls,
                  views_24h, views_48h, views_7d, views_30d,
                  ctr_12h, ctr_24h, ctr_48h, retention_48h,
                  post_mortem_48h, post_mortem_7d,
                  agent_paper_trail, agent_hook_score, agent_body_score, agent_tier, agent_cost,
                  suggested_thumbnail_prompt, suggested_thumbnail_urls,
                  suggested_script, suggested_title, suggestion_source,
                  suggestion_scores, suggestion_status,
                  video_motion_system_prompt,
                  script_system_prompt, thumbnail_system_prompt, sound_system_prompt,
                  characters_approved_at::text, story_locked_at::text,
                  created_at::text, updated_at::text
           FROM videos WHERE id = $1 AND tenant_id = $2 AND deleted_at IS NULL""",
        video_id, tenant_id,
    )
    if not r:
        raise HTTPException(status_code=404, detail="Video not found")

    # Attach each research card's STORED referee verdict as card.readiness so the
    # Research and Script tabs read one backend-owned readiness (no client recompute,
    # failed cards never dropped). Single helper shared by every research_payload path.
    from pipeline_executor import enrich_research_payload_readiness
    research_payload = await enrich_research_payload_readiness(
        tenant_id, video_id, _parse_json_field(r.get("research_payload"))
    )

    return VideoDetail(
        id=str(r["id"]),
        video_title=r.get("video_title"),
        status=r.get("status"),
        airtable_record_id=r.get("airtable_record_id"),
        headline=r.get("headline"),
        source=r.get("source"),
        framework_angle=r.get("framework_angle"),
        thematic_framework=r.get("thematic_framework"),
        hook_script=r.get("hook_script"),
        past_context=r.get("past_context"),
        present_parallel=r.get("present_parallel"),
        future_prediction=r.get("future_prediction"),
        writer_guidance=r.get("writer_guidance"),
        thesis=r.get("thesis"),
        executive_hook=r.get("executive_hook"),
        research_payload=research_payload,
        original_dna=_parse_json_field(r.get("original_dna")),
        script=r.get("script"),
        script_validation=_parse_script_validation(r.get("script_validation")),
        story_bible=r.get("story_bible"),
        thumbnail_url=r.get("thumbnail_url"),
        thumbnail_prompt=r.get("thumbnail_prompt"),
        thumbnail_style_override=r.get("thumbnail_style_override"),
        accent_color=r.get("accent_color", "#00D4AA"),
        visual_style=r.get("visual_style"),
        skip_voice=r.get("skip_voice") or False,
        pipeline_stages=_parse_stage_plan(r.get("pipeline_stages")),
        image_style_override=r.get("image_style_override"),
        image_model_override=r.get("image_model_override"),
        video_model=r.get("video_model"),
        video_length_minutes=float(r["video_length_minutes"]) if r.get("video_length_minutes") else None,
        youtube_url=r.get("youtube_url"),
        final_video_url=r.get("final_video_url"),
        total_cost=float(r.get("total_cost") or 0),
        views=r.get("views") or 0,
        ctr=float(r["ctr"]) if r.get("ctr") else None,
        avg_retention=float(r["avg_retention"]) if r.get("avg_retention") else None,
        impressions=r.get("impressions") or 0,
        likes=r.get("likes") or 0,
        comments=r.get("comments") or 0,
        performance_verdict=r.get("performance_verdict"),
        source_views=r.get("source_views"),
        source_channel=r.get("source_channel"),
        source_urls=r.get("source_urls"),
        views_24h=r.get("views_24h"),
        views_48h=r.get("views_48h"),
        views_7d=r.get("views_7d"),
        views_30d=r.get("views_30d"),
        ctr_12h=float(r["ctr_12h"]) if r.get("ctr_12h") else None,
        ctr_24h=float(r["ctr_24h"]) if r.get("ctr_24h") else None,
        ctr_48h=float(r["ctr_48h"]) if r.get("ctr_48h") else None,
        retention_48h=float(r["retention_48h"]) if r.get("retention_48h") else None,
        post_mortem_48h=r.get("post_mortem_48h"),
        post_mortem_7d=r.get("post_mortem_7d"),
        agent_paper_trail=_parse_json_field(r.get("agent_paper_trail")),
        agent_hook_score=float(r["agent_hook_score"]) if r.get("agent_hook_score") else None,
        agent_body_score=float(r["agent_body_score"]) if r.get("agent_body_score") else None,
        agent_tier=r.get("agent_tier"),
        agent_cost=float(r["agent_cost"]) if r.get("agent_cost") else None,
        suggested_thumbnail_prompt=r.get("suggested_thumbnail_prompt"),
        suggested_thumbnail_urls=_parse_json_field(r.get("suggested_thumbnail_urls")),
        suggested_script=r.get("suggested_script"),
        suggested_title=r.get("suggested_title"),
        suggestion_source=r.get("suggestion_source"),
        suggestion_scores=_parse_json_field(r.get("suggestion_scores")),
        suggestion_status=r.get("suggestion_status"),
        video_motion_system_prompt=r.get("video_motion_system_prompt"),
        script_system_prompt=r.get("script_system_prompt"),
        thumbnail_system_prompt=r.get("thumbnail_system_prompt"),
        sound_system_prompt=r.get("sound_system_prompt"),
        # Selected above but never passed — the client saw null and the
        # banner re-offered "Lock the story" on already-locked videos.
        story_locked_at=r.get("story_locked_at"),
        dialogue_audio=r.get("dialogue_audio"),
        render_mode=r.get("render_mode"),
        created_at=r.get("created_at"),
        updated_at=r.get("updated_at"),
    )


@router.patch("/{video_id}")
async def update_video(video_id: str, body: dict, tenant_id: str = Depends(get_tenant_id)):
    """Update arbitrary video fields (revision_notes, etc.)."""
    video = await fetch_one(
        "SELECT id FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    allowed_fields = {"revision_notes", "video_title", "headline", "thumbnail_prompt", "thumbnail_style_override", "video_motion_system_prompt", "script_system_prompt", "thumbnail_system_prompt", "sound_system_prompt", "dialogue_audio", "aspect_ratio", "video_resolution", "skip_voice"}
    # skip_voice records the guided flow's "skip the voiceover" choice — the
    # Scenes gate reads it (advancing status alone left the gate locked).
    if "skip_voice" in body and not isinstance(body["skip_voice"], bool):
        raise HTTPException(status_code=400, detail="skip_voice must be a boolean")
    # aspect_ratio flows into image/video gen + render — reject anything unexpected.
    if "aspect_ratio" in body and body["aspect_ratio"] not in {"16:9", "9:16", "1:1", "4:3", "3:4"}:
        raise HTTPException(status_code=400, detail="Invalid aspect_ratio")
    # video_resolution is passed to the clip generator — reject anything unexpected.
    if "video_resolution" in body and body["video_resolution"] not in {"480p", "720p"}:
        raise HTTPException(status_code=400, detail="Invalid video_resolution")
    updates = []
    params = []
    idx = 1
    for key, val in body.items():
        if key in allowed_fields:
            updates.append(f"{safe_column(key)} = ${idx}")
            params.append(val)
            idx += 1
    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields to update")

    updates.append("updated_at = now()")
    params.append(video_id)
    idx += 1
    params.append(tenant_id)
    # SECURITY: column names filtered through allowed_fields allowlist + safe_column(), values use $N params
    query = f"UPDATE videos SET {', '.join(updates)} WHERE id = ${idx - 1} AND tenant_id = ${idx}"
    await execute(query, *params)
    return {"status": "updated", "video_id": video_id}


@router.post("/{video_id}/generate-seo")
async def generate_video_seo(video_id: str, tenant_id: str = Depends(get_tenant_id)):
    """Generate channel-appropriate YouTube SEO from the video's own content and store
    it on the video. Channel-agnostic — no hardcoded niche/brand."""
    video = await fetch_one(
        "SELECT id FROM videos WHERE id = $1 AND tenant_id = $2", video_id, tenant_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    from youtube_publish import generate_and_store_seo
    try:
        result = await generate_and_store_seo(video_id, tenant_id)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Couldn't generate SEO: {e}")
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.patch("/{video_id}/seo")
async def save_video_seo(video_id: str, body: dict, tenant_id: str = Depends(get_tenant_id)):
    """Persist creator-edited SEO (title/description/tags) so the upload uses exactly
    what they see on screen."""
    video = await fetch_one(
        "SELECT id FROM videos WHERE id = $1 AND tenant_id = $2", video_id, tenant_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    from youtube_publish import save_seo
    tags = body.get("tags")
    if isinstance(tags, str):
        tags = [t for t in (x.strip() for x in tags.split(",")) if t]
    return await save_seo(
        video_id, tenant_id,
        title=body.get("title"), description=body.get("description"), tags=tags)


@router.patch("/{video_id}/advance")
async def advance_video(video_id: str, to: Optional[str] = None,
                        tenant_id: str = Depends(get_tenant_id)):
    """Move video to the next pipeline stage.

    `to` (optional) jumps FORWARD to a specific status — the guided banner's
    Skip button targets the stage after the skipped element (e.g. skipping
    clips lands at ready_for_thumbnail). Validated by walking the stage
    chain from the current status, so only known, forward statuses work.
    """
    video = await fetch_one(
        "SELECT id, status FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    if to:
        cursor = video["status"]
        found = False
        for _ in range(30):
            cursor = _next_stage(cursor)
            if cursor is None:
                break
            if cursor == to:
                found = True
                break
        if not found:
            raise HTTPException(status_code=400,
                                detail=f"Can't skip to '{to}' from '{video['status']}'")
        next_status = to
    else:
        next_status = _next_stage(video["status"])
    if not next_status:
        raise HTTPException(status_code=400, detail="Video is already at final stage")

    await execute(
        "UPDATE videos SET status = $1, updated_at = now() WHERE id = $2 AND tenant_id = $3",
        next_status, video_id, tenant_id,
    )

    # Log transition
    await execute(
        """INSERT INTO stage_transitions (video_id, tenant_id, from_status, to_status, triggered_by)
           VALUES ($1, $2, $3, $4, 'user')""",
        video_id, tenant_id, video["status"], next_status,
    )

    return {"status": next_status, "previous": video["status"]}


@router.patch("/{video_id}/reject")
async def reject_video(video_id: str, reason: Optional[str] = None, tenant_id: str = Depends(get_tenant_id)):
    """Flag/reject a video."""
    video = await fetch_one(
        "SELECT id, status FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    # Log transition with error
    await execute(
        """INSERT INTO stage_transitions (video_id, tenant_id, from_status, to_status, triggered_by, error_message)
           VALUES ($1, $2, $3, 'rejected', 'user', $4)""",
        video_id, tenant_id, video["status"], reason,
    )

    return {"status": "rejected", "previous": video["status"]}


@router.delete("/{video_id}")
async def delete_video(video_id: str, tenant_id: str = Depends(get_tenant_id)):
    """Soft-delete a video by setting deleted_at timestamp."""
    video = await fetch_one(
        "SELECT id FROM videos WHERE id = $1 AND tenant_id = $2 AND deleted_at IS NULL",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    await execute(
        "UPDATE videos SET deleted_at = now(), updated_at = now() WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    return {"status": "deleted", "video_id": video_id}


@router.get("/{video_id}/assets")
async def get_video_assets(video_id: str, tenant_id: str = Depends(get_tenant_id)):
    """Get all assets for a video."""
    rows = await fetch_all(
        """SELECT id, video_id, scene, image_index, image_url, image_prompt,
                  status, shot_type, hero_shot, sentence_text, video_clip_url,
                  video_prompt, sound_prompt, sound_effect_url, sound_volume,
                  duration_seconds, extraction_flags,
                  created_at::text
           FROM assets WHERE video_id = $1 AND tenant_id = $2
             AND (generation_method IS NULL OR generation_method <> 'variant_candidate')
           ORDER BY scene, image_index""",
        video_id, tenant_id,
    )
    return rows


@router.get("/{video_id}/assets/variants")
async def get_video_asset_variants(
    video_id: str,
    scene: int = Query(...),
    index: int = Query(...),
    tenant_id: str = Depends(get_tenant_id),
):
    """Get variant candidate assets for a specific scene/index."""
    rows = await fetch_all(
        """SELECT id, video_id, scene, image_index, image_url, drive_image_url, image_prompt,
                  status, shot_type, hero_shot, sentence_text, panel_position,
                  generation_method, created_at::text
           FROM assets
           WHERE video_id = $1 AND tenant_id = $2 AND scene = $3 AND image_index = $4
             AND generation_method = 'variant_candidate'
           ORDER BY panel_position, created_at""",
        video_id, tenant_id, scene, index,
    )
    return rows


@router.get("/{video_id}/script")
async def get_video_script(video_id: str, tenant_id: str = Depends(get_tenant_id)):
    """Get full script for a video."""
    rows = await fetch_all(
        """SELECT id, video_id, scene, scene_text, voice_over_url, voice_status,
                  script_status, sources, storyboard_on_off, tone,
                  storyboard_1_url, storyboard_2_url, storyboard_3_url,
                  storyboard_4_url, storyboard_5_url, scene_video_url,
                  storyboard_prompts, storyboard_beat_count, storyboard_status,
                  coverage_directive,
                  created_at::text, updated_at::text
           FROM scripts WHERE video_id = $1 AND tenant_id = $2
           ORDER BY scene NULLS FIRST, created_at""",
        video_id, tenant_id,
    )
    # Backfill scene numbers when null (Airtable imports don't always set them)
    for i, row in enumerate(rows):
        if row.get("scene") is None:
            row["scene"] = i + 1
    return rows


@router.post("/{video_id}/audio-token")
async def create_audio_token(video_id: str, tenant_id=Depends(get_tenant_id)):
    """Generate a short-lived token for audio playback.

    Returns a 5-minute JWT scoped to this video_id + tenant_id.
    Use this token in ?token= query param for audio endpoints instead
    of exposing the full session JWT in URLs.
    """
    import os
    import jwt as pyjwt
    from datetime import datetime, timedelta, timezone

    session_secret = os.getenv("SESSION_SECRET")
    if not session_secret:
        raise HTTPException(status_code=500, detail="SESSION_SECRET not configured")

    audio_token = pyjwt.encode(
        {
            "purpose": "audio",
            "video_id": video_id,
            "tenant_id": str(tenant_id),
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
            "iss": "storyengine",
        },
        session_secret,
        algorithm="HS256",
    )
    return {"token": audio_token}


def _audio_token_tenant(token: Optional[str], video_id: str) -> str:
    """Resolve the tenant behind a browser audio token (?token= on <audio>
    URLs — players can't send headers). Accepts the short-lived audio token
    from POST /audio-token (scope-checked to the video) or a session JWT.
    Dev token only when DEV_MODE=true. Raises 401/403 like a dependency."""
    import os
    import jwt as pyjwt

    # Validate token — required for tenant isolation
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")

    # Dev token: only when DEV_MODE=true and DEV_TOKEN env var is set
    dev_token = os.getenv("DEV_TOKEN")
    if dev_token and token == dev_token and os.getenv("DEV_MODE") == "true":
        return os.getenv("DEV_TENANT_ID", "test-tenant")

    # Validate JWT (short-lived audio token or session JWT)
    session_secret = os.getenv("SESSION_SECRET")
    if not session_secret:
        raise HTTPException(status_code=401, detail="Invalid token")
    try:
        payload = pyjwt.decode(token, session_secret, algorithms=["HS256"])
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except pyjwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
    # Short-lived audio token: verify purpose and video_id scope
    if payload.get("purpose") == "audio" and payload.get("video_id") != video_id:
        raise HTTPException(status_code=403, detail="Token not valid for this video")
    tenant_id = payload.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Invalid token: no tenant")
    return tenant_id


@router.get("/{video_id}/audio/{scene}")
async def get_scene_audio(video_id: str, scene: int, token: Optional[str] = None):
    """Proxy audio from Google Drive for browser playback.

    Google Drive download URLs use 303 redirects that some browsers
    block in Audio elements. This endpoint streams the audio directly.
    Accepts a short-lived audio token (from POST /audio-token) in ?token= param.
    """
    tenant_id = _audio_token_tenant(token, video_id)

    row = await fetch_one(
        "SELECT voice_over_url FROM scripts WHERE video_id = $1 AND tenant_id = $2 AND scene = $3 LIMIT 1",
        video_id, tenant_id, scene,
    )
    if not row or not row.get("voice_over_url"):
        raise HTTPException(status_code=404, detail="No voice audio for this scene")

    url = row["voice_over_url"]

    # Drive public links degrade into HTML interstitials (the bytes say
    # 200 audio/mpeg but contain an HTML page — players sit at 0:00/0:00).
    # Same fix as the image proxy: authorized Drive API download.
    file_id = _drive_file_id(url)
    if file_id:
        from routes.media import _download_via_drive_api
        try:
            data = await asyncio.to_thread(_download_via_drive_api, file_id)
        except Exception as e:
            logger.warning("[audio] drive fetch failed for %s: %s", file_id, str(e)[:200])
            raise HTTPException(status_code=502, detail="Couldn't fetch the audio right now.")
        return Response(content=data, media_type="audio/mpeg", headers={
            "Accept-Ranges": "bytes",
            "Cache-Control": "public, max-age=3600",
        })

    async def stream():
        async with httpx.AsyncClient(follow_redirects=True) as client:
            async with client.stream("GET", url, timeout=60.0) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes(8192):
                    yield chunk

    return StreamingResponse(stream(), media_type="audio/mpeg", headers={
        "Accept-Ranges": "bytes",
        "Cache-Control": "public, max-age=86400",
    })


@router.get("/{video_id}/dialogue-audio/{scene}/{index}")
async def get_dialogue_segment_audio(
    video_id: str, scene: int, index: int, token: Optional[str] = None,
):
    """Stream ONE dialogue segment's MP3 — the Performance Track card's
    per-line audition, so a creator can hear each character's cast voice
    before spending on clips. `index` is the segment's position in the
    scene's dialogue_segments. Same browser-token auth as get_scene_audio."""
    import json as _json

    tenant_id = _audio_token_tenant(token, video_id)

    row = await fetch_one(
        "SELECT dialogue_segments FROM scripts "
        "WHERE video_id = $1 AND tenant_id = $2 AND scene = $3 LIMIT 1",
        video_id, tenant_id, scene,
    )
    raw = (row or {}).get("dialogue_segments")
    if isinstance(raw, str):
        try:
            raw = _json.loads(raw)
        except ValueError:
            raw = None
    if not isinstance(raw, list) or not (0 <= index < len(raw)):
        raise HTTPException(status_code=404, detail="No such dialogue segment")
    url = (raw[index] or {}).get("audio_url")
    if not url:
        raise HTTPException(status_code=404, detail="This line isn't voiced yet")

    file_id = _drive_file_id(url)
    if file_id:
        from routes.media import _download_via_drive_api
        try:
            data = await asyncio.to_thread(_download_via_drive_api, file_id)
        except Exception as e:
            logger.warning("[dialogue-audio] drive fetch failed for %s: %s",
                           file_id, str(e)[:200])
            raise HTTPException(status_code=502, detail="Couldn't fetch the audio right now.")
        return Response(content=data, media_type="audio/mpeg", headers={
            "Accept-Ranges": "bytes",
            "Cache-Control": "public, max-age=3600",
        })

    async def stream():
        async with httpx.AsyncClient(follow_redirects=True) as client:
            async with client.stream("GET", url, timeout=60.0) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes(8192):
                    yield chunk

    return StreamingResponse(stream(), media_type="audio/mpeg", headers={
        "Accept-Ranges": "bytes",
        "Cache-Control": "public, max-age=3600",
    })


@router.patch("/{video_id}/styles")
async def update_video_styles(
    video_id: str,
    visual_style: Optional[str] = None,
    accent_color: Optional[str] = None,
    image_model_override: Optional[str] = None,
    video_model: Optional[str] = None,
    tenant_id: str = Depends(get_tenant_id),
):
    """Update video style override fields."""
    # Verify video exists and belongs to tenant
    video = await fetch_one(
        "SELECT id FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    # Build dynamic update query
    updates = []
    params = []
    param_idx = 1

    if visual_style is not None:
        updates.append(f"visual_style = ${param_idx}")
        params.append(visual_style)
        param_idx += 1

    if accent_color is not None:
        updates.append(f"accent_color = ${param_idx}")
        params.append(accent_color)
        param_idx += 1

    if image_model_override is not None:
        updates.append(f"image_model_override = ${param_idx}")
        params.append(image_model_override)
        param_idx += 1

    if video_model is not None:
        updates.append(f"video_model = ${param_idx}")
        params.append(video_model)
        param_idx += 1

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    # Add updated_at and video_id + tenant_id
    updates.append("updated_at = now()")
    params.append(video_id)
    params.append(tenant_id)

    # SECURITY: column names are hardcoded per-field conditionals, values use $N params
    query = f"UPDATE videos SET {', '.join(updates)} WHERE id = ${param_idx} AND tenant_id = ${param_idx + 1}"
    await execute(query, *params)

    return {
        "status": "updated",
        "video_id": video_id,
        "updated_fields": {
            "visual_style": visual_style,
            "accent_color": accent_color,
            "image_model_override": image_model_override,
            "video_model": video_model,
        },
    }


@router.post("/{video_id}/accept-suggestion")
async def accept_suggestion(video_id: str, request: dict, tenant_id: str = Depends(get_tenant_id)):
    """Accept agent suggestions — copies selected suggested_* fields to current fields."""
    accept_fields = request.get("accept", [])  # ["script", "title", "thumbnail"]

    # Verify video exists and belongs to tenant
    video = await fetch_one(
        "SELECT id FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    # Build SET clauses dynamically based on what's being accepted
    set_clauses = []
    if "script" in accept_fields:
        set_clauses.append("script = suggested_script")
    if "title" in accept_fields:
        set_clauses.append("video_title = suggested_title")
    if "thumbnail" in accept_fields:
        set_clauses.append("thumbnail_prompt = suggested_thumbnail_prompt")

    if not set_clauses:
        raise HTTPException(status_code=400, detail="No fields specified to accept")

    # Also clear suggestion fields and set status
    set_clauses.extend([
        "suggested_script = NULL",
        "suggested_title = NULL",
        "suggested_thumbnail_prompt = NULL",
        "suggested_thumbnail_urls = NULL",
        "suggestion_source = NULL",
        "suggestion_scores = NULL",
        "suggestion_status = 'accepted'",
        "updated_at = NOW()",
    ])

    # SECURITY: SET clauses are fully hardcoded strings (column = column or NULL/literal), no user input in clause text
    query = f"UPDATE videos SET {', '.join(set_clauses)} WHERE id = $1 AND tenant_id = $2"
    await execute(query, video_id, tenant_id)

    return {"status": "ok", "video_id": video_id, "accepted": accept_fields}


@router.post("/{video_id}/reject-suggestion")
async def reject_suggestion(video_id: str, tenant_id: str = Depends(get_tenant_id)):
    """Reject agent suggestions — clears all suggested_* fields."""
    # Verify video exists and belongs to tenant
    video = await fetch_one(
        "SELECT id FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    await execute("""
        UPDATE videos SET
            suggested_script = NULL,
            suggested_title = NULL,
            suggested_thumbnail_prompt = NULL,
            suggested_thumbnail_urls = NULL,
            suggestion_source = NULL,
            suggestion_scores = NULL,
            suggestion_status = 'rejected',
            updated_at = NOW()
        WHERE id = $1 AND tenant_id = $2
    """, video_id, tenant_id)

    return {"status": "ok", "video_id": video_id}


@router.patch("/{video_id}/scenes/{scene}/text")
async def update_scene_text(
    video_id: str, scene: int, body: SceneTextUpdate, tenant_id: str = Depends(get_tenant_id)
):
    result = await execute(
        "UPDATE scripts SET scene_text = $1, updated_at = now() "
        "WHERE video_id = $2 AND scene = $3 AND tenant_id = $4",
        body.text, video_id, scene, tenant_id,
    )
    if not result or "UPDATE 0" in result:
        raise HTTPException(404, "Scene not found")
    return {"status": "updated", "scene": scene}


@router.patch("/{video_id}/scenes/{scene}/tone")
async def update_scene_tone(
    video_id: str, scene: int, body: SceneToneUpdate, tenant_id: str = Depends(get_tenant_id)
):
    valid_tones = {"serious", "conversational", "urgent", "concise"}
    if body.tone not in valid_tones:
        raise HTTPException(400, f"Invalid tone. Must be one of: {valid_tones}")
    await execute(
        "UPDATE scripts SET tone = $1, updated_at = now() "
        "WHERE video_id = $2 AND scene = $3 AND tenant_id = $4",
        body.tone, video_id, scene, tenant_id,
    )
    return {"status": "updated", "scene": scene, "tone": body.tone}


@router.get("/{video_id}/scenes/{scene}/segments")
async def get_scene_segments(
    video_id: str, scene: int, tenant_id: str = Depends(get_tenant_id)
):
    rows = await fetch_all(
        "SELECT id, image_index, sentence_text, shot_type, status, "
        "duration_seconds, image_prompt "
        "FROM assets WHERE video_id = $1 AND scene = $2 AND tenant_id = $3 "
        "AND (generation_method IS NULL OR generation_method <> 'variant_candidate') "
        "ORDER BY image_index",
        video_id, scene, tenant_id,
    )
    segments = []
    cumulative_start = 0.0
    for row in rows:
        text = row.get("sentence_text") or ""
        word_count = len(text.split()) if text else 0
        db_duration = row.get("duration_seconds")
        duration = round(float(db_duration), 1) if db_duration is not None else round(word_count / 2.5, 1)
        segments.append({
            "id": str(row["id"]),
            "image_index": row.get("image_index"),
            "sentence_text": text,
            "shot_type": row.get("shot_type"),
            "status": row.get("status"),
            "word_count": word_count,
            "duration_seconds": duration,
            "cumulative_start": round(cumulative_start, 1),
            "image_prompt": row.get("image_prompt"),
        })
        cumulative_start += duration
    return {"scene": scene, "segments": segments}


@router.put("/{video_id}/scenes/{scene}/segments")
async def update_scene_segments(
    video_id: str, scene: int, body: SegmentUpdate, tenant_id: str = Depends(get_tenant_id)
):
    updated = 0
    for seg in body.segments:
        result = await execute(
            "UPDATE assets SET sentence_text = $1, updated_at = now() "
            "WHERE video_id = $2 AND scene = $3 AND image_index = $4 AND tenant_id = $5 "
            "AND (generation_method IS NULL OR generation_method <> 'variant_candidate')",
            seg["sentence_text"], video_id, scene, seg["image_index"], tenant_id,
        )
        if result and "UPDATE 1" in result:
            updated += 1
    return {"status": "updated", "scene": scene, "updated_count": updated}


@router.patch("/{video_id}/storyboard-mode")
async def update_storyboard_mode(
    video_id: str, body: StoryboardModeUpdate, tenant_id: str = Depends(get_tenant_id)
):
    value = "On" if body.enabled else "Off"
    await execute(
        "UPDATE scripts SET storyboard_on_off = $1, updated_at = now() "
        "WHERE video_id = $2 AND tenant_id = $3",
        value, video_id, tenant_id,
    )
    return {"status": "updated", "storyboard_mode": value}


@router.post("/{video_id}/lock-story")
async def lock_story(video_id: str, tenant_id: str = Depends(get_tenant_id)):
    """Lock the storyboard: the explicit, reviewed moment before image spend.

    Requires at least one storyboard grid to exist — you can't lock a story
    you haven't seen. Unlocked again via /unlock-story while iterating.
    """
    video = await fetch_one(
        "SELECT id FROM videos WHERE id = $1 AND tenant_id = $2 AND deleted_at IS NULL",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    grids = await fetch_one(
        "SELECT count(*) AS c FROM scripts WHERE video_id = $1 AND tenant_id = $2 "
        "AND (storyboard_1_url IS NOT NULL OR storyboard_2_url IS NOT NULL OR storyboard_3_url IS NOT NULL)",
        video_id, tenant_id,
    )
    if not grids or int(grids.get("c") or 0) == 0:
        raise HTTPException(
            status_code=400,
            detail="Generate storyboard grids first — locking means you've reviewed the boards.",
        )

    await execute(
        "UPDATE videos SET story_locked_at = now(), updated_at = now() "
        "WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    return {"status": "locked"}


@router.post("/{video_id}/unlock-story")
async def unlock_story(video_id: str, tenant_id: str = Depends(get_tenant_id)):
    """Unlock to keep iterating on boards (does not delete anything)."""
    await execute(
        "UPDATE videos SET story_locked_at = NULL, updated_at = now() "
        "WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    return {"status": "unlocked"}


@router.delete("/{video_id}/storyboards")
async def clear_all_storyboards(
    video_id: str,
    tenant_id: str = Depends(get_tenant_id),
):
    """Clear all storyboard prompt/image fields and restore original image prompts."""
    result = await execute(
        """UPDATE scripts
           SET storyboard_prompts = NULL,
               storyboard_beat_count = NULL,
               storyboard_status = NULL,
               storyboard_1_url = NULL,
               storyboard_2_url = NULL,
               storyboard_3_url = NULL,
               storyboard_4_url = NULL,
               storyboard_5_url = NULL,
               updated_at = now()
           WHERE video_id = $1 AND tenant_id = $2""",
        video_id,
        tenant_id,
    )
    # Restore original image prompts (undo storyboard enrichment)
    await execute(
        """UPDATE assets
           SET image_prompt = original_image_prompt,
               updated_at = now()
           WHERE video_id = $1 AND tenant_id = $2
             AND original_image_prompt IS NOT NULL
             AND original_image_prompt != ''""",
        video_id,
        tenant_id,
    )
    return {"status": "cleared", "scope": "all", "video_id": video_id, "result": result}


@router.delete("/{video_id}/storyboards/{scene}")
async def clear_scene_storyboard(
    video_id: str,
    scene: int,
    tenant_id: str = Depends(get_tenant_id),
):
    """Clear storyboard prompt/image fields for a single scene and restore original prompts."""
    result = await execute(
        """UPDATE scripts
           SET storyboard_prompts = NULL,
               storyboard_beat_count = NULL,
               storyboard_status = NULL,
               storyboard_1_url = NULL,
               storyboard_2_url = NULL,
               storyboard_3_url = NULL,
               storyboard_4_url = NULL,
               storyboard_5_url = NULL,
               updated_at = now()
           WHERE video_id = $1 AND scene = $2 AND tenant_id = $3""",
        video_id,
        scene,
        tenant_id,
    )
    if not result or "UPDATE 0" in result:
        raise HTTPException(status_code=404, detail="Scene not found")
    # Restore original image prompts for this scene
    await execute(
        """UPDATE assets
           SET image_prompt = original_image_prompt,
               updated_at = now()
           WHERE video_id = $1 AND scene = $2 AND tenant_id = $3
             AND original_image_prompt IS NOT NULL
             AND original_image_prompt != ''""",
        video_id,
        scene,
        tenant_id,
    )
    return {"status": "cleared", "scope": "scene", "video_id": video_id, "scene": scene}


def _drive_file_id(url: str | None) -> str | None:
    if not url:
        return None
    m = re.search(r"[?&]id=([\w-]+)", url) or re.search(r"/d/([\w-]+)", url)
    return m.group(1) if m else None


def _trash_drive_file(file_id: str) -> None:
    """Move a Drive file to trash (recoverable for 30 days)."""
    import sys
    from pathlib import Path
    pipeline_path = Path(__file__).resolve().parents[3] / "skills" / "video-pipeline"
    if str(pipeline_path) not in sys.path:
        sys.path.insert(0, str(pipeline_path))
    from shared.clients.google_client import GoogleClient
    GoogleClient().drive_service.files().update(
        fileId=file_id, body={"trashed": True}
    ).execute()


@router.delete("/{video_id}/storyboards/{scene}/{beat}")
async def clear_storyboard_slot(
    video_id: str,
    scene: int,
    beat: int,
    tenant_id: str = Depends(get_tenant_id),
):
    """Remove ONE storyboard grid image — prompts and the other boards stay.

    The whole-scene clear wipes prompts too (full redo); this is the X button
    for "just this picture is wrong". The Drive copy is trashed so the folder
    matches what's on screen, and regeneration only fills the empty slot
    (the bot skips beats that already have grids).
    """
    if beat < 1 or beat > 5:
        raise HTTPException(status_code=400, detail="Beat must be 1-5")

    col = f"storyboard_{beat}_url"
    row = await fetch_one(
        f"SELECT id, {col} AS url FROM scripts WHERE video_id = $1 AND scene = $2 AND tenant_id = $3",
        video_id, scene, tenant_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Scene not found")
    if not row.get("url"):
        raise HTTPException(status_code=404, detail="No storyboard image in that slot")

    # Only downgrade the scene status when the removed slot is one of the
    # ACTIVE beats — clearing a stray out-of-range slot shouldn't un-complete
    # a scene whose real boards are all still there.
    await execute(
        f"""UPDATE scripts
            SET {col} = NULL,
                storyboard_status = CASE WHEN storyboard_status = 'grids_generated'
                                          AND $2::int <= COALESCE(storyboard_beat_count, 1)
                                         THEN 'prompts_ready' ELSE storyboard_status END,
                updated_at = now()
            WHERE id = $1""",
        row["id"], beat,
    )

    file_id = _drive_file_id(row["url"])
    if file_id:
        try:
            await asyncio.to_thread(_trash_drive_file, file_id)
        except Exception as e:
            logger.warning("[storyboard] couldn't trash Drive file %s: %s", file_id, str(e)[:200])

    return {"status": "cleared", "scope": "slot", "scene": scene, "beat": beat}


@router.delete("/{video_id}/extracted-panels")
async def clear_all_extracted_panels(
    video_id: str,
    tenant_id: str = Depends(get_tenant_id),
):
    """Clear all extracted panel images, preserving segment rows."""
    result = await execute(
        """UPDATE assets
           SET image_url = NULL, status = 'pending',
               generation_method = NULL, updated_at = now()
           WHERE video_id = $1 AND tenant_id = $2
             AND generation_method = 'storyboard_extract'
             AND image_url IS NOT NULL""",
        video_id,
        tenant_id,
    )
    cleared = int(result.split()[-1]) if result else 0
    return {"status": "cleared", "cleared_count": cleared, "video_id": video_id}


@router.delete("/{video_id}/extracted-panels/{asset_id}")
async def clear_extracted_panel(
    video_id: str,
    asset_id: str,
    tenant_id: str = Depends(get_tenant_id),
):
    """Clear a single extracted panel image, preserving the segment row."""
    result = await execute(
        """UPDATE assets
           SET image_url = NULL, status = 'pending',
               generation_method = NULL, updated_at = now()
           WHERE id = $1 AND video_id = $2 AND tenant_id = $3""",
        asset_id,
        video_id,
        tenant_id,
    )
    if not result or "UPDATE 0" in result:
        raise HTTPException(status_code=404, detail="Asset not found")
    return {"status": "cleared", "asset_id": asset_id}


@router.post("/{video_id}/storyboard-grid-upload")
async def upload_storyboard_grid(
    video_id: str,
    scene: int = Form(...),
    beat: int = Form(...),
    file: UploadFile = File(...),
    tenant_id: str = Depends(get_tenant_id),
):
    """Upload a manually-created storyboard grid image.

    Saves to Google Drive and updates the scripts table.
    Used when API generation fails (e.g. content policy blocks).
    """
    from storage import upload_bytes

    # Verify scene exists
    script = await fetch_one(
        "SELECT id FROM scripts WHERE video_id = $1 AND scene = $2 AND tenant_id = $3",
        video_id, scene, tenant_id,
    )
    if not script:
        raise HTTPException(status_code=404, detail=f"Scene {scene} not found")

    if beat < 1 or beat > 5:
        raise HTTPException(status_code=400, detail="Beat must be 1-5")

    # Read file and upload to storage. Same Drive subfolder + filename the
    # storyboard bot uses, so a manual upload REPLACES the bot's grid in
    # place instead of orphaning it in a separate "grids" folder.
    data = await file.read()
    path = f"{video_id}/storyboard/S{scene}-B{beat}.png"
    perm_url = await upload_bytes(data, path, content_type=file.content_type or "image/png")

    # SECURITY: column name built from validated integer (1-5 only, checked above).
    # Values use parameterized $1/$2 — no injection risk.
    assert 1 <= beat <= 5, "beat validated above"
    col = f"storyboard_{beat}_url"
    await execute(
        f"UPDATE scripts SET {col} = $1, updated_at = now() WHERE id = $2",
        perm_url, script["id"],
    )

    # Check if all beats now have grids → set status to grids_generated
    updated = await fetch_one(
        """SELECT storyboard_beat_count,
                  storyboard_1_url, storyboard_2_url, storyboard_3_url,
                  storyboard_4_url, storyboard_5_url
           FROM scripts WHERE id = $1""",
        script["id"],
    )
    beat_count = int(updated.get("storyboard_beat_count") or 1)
    all_present = all(
        updated.get(f"storyboard_{i}_url")
        for i in range(1, beat_count + 1)
    )
    if all_present:
        await execute(
            "UPDATE scripts SET storyboard_status = 'grids_generated', updated_at = now() WHERE id = $1",
            script["id"],
        )

    return {"status": "uploaded", "url": perm_url, "scene": scene, "beat": beat, "all_grids_complete": all_present}


@router.post("/{video_id}/script/set")
async def set_video_script(
    video_id: str,
    body: dict,
    tenant_id=Depends(get_tenant_id),
):
    """Install the creator's OWN script on this video verbatim ("use this
    script"): scenes split + persisted like a generated script, but
    script_source='user_supplied' so run_script skips generation and no
    grading/gates rewrite their words. Body: {"script_text": "..."}."""
    text = str((body or {}).get("script_text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="script_text is required.")
    from user_script import set_user_script
    try:
        result = await set_user_script(tenant_id, video_id, text)
    except ValueError as e:
        raise HTTPException(status_code=404 if "not found" in str(e).lower() else 400,
                            detail=str(e))
    return {"status": "ok", **result}


@router.post("/{video_id}/script/tag-dialogue")
async def tag_dialogue(video_id: str, tenant_id=Depends(get_tenant_id)):
    """Run the dialogue intelligence pass: detect whether this script performs
    character dialogue, tag every scene's performance timeline, and cast a
    stable voice per character. Idempotent; runs automatically after the
    script stage for new videos — this endpoint is the manual/retro trigger."""
    from dialogue_intelligence import tag_video_dialogue, cast_character_voices
    try:
        result = await tag_video_dialogue(video_id, tenant_id)
        if result.get("dialogue_mode") == "character_dialogue":
            result["voices"] = await cast_character_voices(video_id, tenant_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=humanize_error(e, context="We couldn't analyze the dialogue for this video"))


@router.get("/{video_id}/dialogue-map")
async def get_dialogue_map(video_id: str, tenant_id=Depends(get_tenant_id)):
    """Per-scene dialogue timeline for UI badges (💬 who speaks where).

    Returns scenes with their dialogue_segments (text/speaker/duration only —
    audio URLs stay server-side; the animatic fetches audio via the proxy).
    """
    import json as _json
    video = await fetch_one(
        "SELECT dialogue_mode FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    if (video.get("dialogue_mode") or "") != "character_dialogue":
        return {"dialogue_mode": video.get("dialogue_mode"), "scenes": []}
    rows = await fetch_all(
        "SELECT scene, dialogue_segments FROM scripts WHERE video_id = $1 AND tenant_id = $2 ORDER BY scene",
        video_id, tenant_id,
    )
    scenes = []
    for r in rows:
        raw = r.get("dialogue_segments")
        if isinstance(raw, str):
            try:
                raw = _json.loads(raw)
            except ValueError:
                raw = None
        if not raw:
            continue
        scenes.append({
            "scene": r["scene"],
            "segments": [
                # index = position in dialogue_segments — the per-line audio
                # route (GET dialogue-audio/{scene}/{index}) is keyed on it.
                {"index": i, "type": s.get("type"), "speaker": s.get("speaker"),
                 "text": s.get("text"), "duration": s.get("duration"),
                 "voiced": bool(s.get("audio_url"))}
                for i, s in enumerate(raw)
            ],
        })
    return {"dialogue_mode": "character_dialogue", "scenes": scenes}


@router.delete("/{video_id}/clips/{asset_id}")
async def delete_clip(video_id: str, asset_id: str, tenant_id=Depends(get_tenant_id)):
    """Remove ONE clip (the card's hover-X): clears video_clip_url so the card
    returns to its still picture, and trashes the Drive copy so the folder
    matches the screen. The picture and motion prompt are untouched."""
    row = await fetch_one(
        "SELECT video_clip_url FROM assets WHERE id = $1 AND video_id = $2 AND tenant_id = $3",
        asset_id, video_id, tenant_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Clip not found")
    url = row.get("video_clip_url") or ""
    # SECURITY: tenant ownership verified above; id+tenant repeated in WHERE
    await execute(
        "UPDATE assets SET video_clip_url = NULL, video_duration = NULL, updated_at = now() "
        "WHERE id = $1 AND tenant_id = $2",
        asset_id, tenant_id,
    )
    m = re.search(r"[?&]id=([\w-]+)", url) or re.search(r"/d/([\w-]+)", url)
    if m:
        try:
            from routes.media import _drive_service
            _drive_service().files().update(fileId=m.group(1), body={"trashed": True}).execute()
        except Exception as e:
            logger.warning("clip Drive trash failed for %s: %s", asset_id, str(e)[:120])
    return {"status": "deleted", "asset_id": asset_id}


@router.post("/{video_id}/assets/{asset_id}/recrop")
async def recrop_asset(
    video_id: str,
    asset_id: str,
    background_tasks: BackgroundTasks,
    tenant_id=Depends(get_tenant_id),
):
    """One-tap 'Re-crop this picture' for a red bad-crop badge: re-crops the
    asset's whole storyboard beat with self-healing grid geometry (a split
    crop never comes alone; free, replaces Drive content in place), then
    AUTO RE-ANIMATES any clips the new pictures made stale (~$0.10 each).
    Background task — the clip regens take ~40s apiece; watch the task pill."""
    from routes.pipeline import _set_task_status, _get_task_status, _clear_task_status, _is_task_active
    from pipeline_executor import PipelineExecutor

    if _is_task_active(video_id, tenant_id):
        raise HTTPException(status_code=409, detail="Task already running")
    _set_task_status(video_id, "running", "Re-cropping this picture's storyboard beat…",
                     tenant_id=tenant_id)

    async def _run():
        try:
            executor = PipelineExecutor(tenant_id)
            result = await executor.run_recrop_panel(video_id, asset_id)
            _set_task_status(video_id, result.get("status", "unknown"),
                             result.get("message") or result.get("error"),
                             tenant_id=tenant_id)
        except Exception as e:
            _set_task_status(video_id, "failed", str(e), tenant_id=tenant_id)
        finally:
            await asyncio.sleep(30)
            _clear_task_status(video_id, tenant_id)

    background_tasks.add_task(_run)
    return {"video_id": video_id, "status": "running",
            "message": "Re-crop started — stale clips re-animate automatically"}


@router.post("/{video_id}/assets/{asset_id}/fix-text")
async def fix_text_card(
    video_id: str,
    asset_id: str,
    background_tasks: BackgroundTasks,
    tenant_id=Depends(get_tenant_id),
):
    """One-tap 'Fix text' for a garbled title/word card: redraws it via GPT Image 2
    (best for legible lettering) using the current panel as the style reference. Replaces
    the card image in place and clears any stale clip. Background task — watch the pill."""
    from routes.pipeline import _set_task_status, _get_task_status, _clear_task_status, _is_task_active
    from pipeline_executor import PipelineExecutor

    if _is_task_active(video_id, tenant_id):
        raise HTTPException(status_code=409, detail="Task already running")
    _set_task_status(video_id, "running", "Fixing the card's text with GPT Image 2…",
                     tenant_id=tenant_id)

    async def _run():
        try:
            executor = PipelineExecutor(tenant_id)
            result = await executor.run_fix_text_card(video_id, asset_id)
            _set_task_status(video_id, result.get("status", "unknown"),
                             result.get("message") or result.get("error"),
                             tenant_id=tenant_id)
        except Exception as e:
            _set_task_status(video_id, "failed", str(e), tenant_id=tenant_id)
        finally:
            await asyncio.sleep(30)
            _clear_task_status(video_id, tenant_id)

    background_tasks.add_task(_run)
    return {"video_id": video_id, "status": "running",
            "message": "Fixing card text with GPT Image 2…"}


@router.post("/{video_id}/scenes/{scene}/rewrite")
async def rewrite_scene_text(
    video_id: str,
    scene: int,
    tenant_id: str = Depends(get_tenant_id),
):
    """AI-rewrite ONE scene's narration in place (static documentary workflow:
    each scene is one machine's unit paragraph — dial in a single machine
    without re-rolling the whole script). Uses the channel's script system
    prompt + the video's research payload, keeps 95-120 words, then clears
    that scene's voice so the next voice run re-records only this scene."""
    import json as _json
    import httpx as _httpx
    from vault import get_secret
    from prompt_defaults import SCRIPT_SYSTEM_PROMPT

    video = await fetch_one(
        "SELECT id, video_title, render_mode, research_payload FROM videos "
        "WHERE id = $1 AND tenant_id = $2 AND deleted_at IS NULL", video_id, tenant_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    row = await fetch_one(
        "SELECT scene_text FROM scripts WHERE video_id = $1 AND tenant_id = $2 AND scene = $3",
        video_id, tenant_id, scene)
    if not row or not (row.get("scene_text") or "").strip():
        raise HTTPException(status_code=404, detail="Scene has no text yet")

    api_key = await get_secret("anthropic_api_key", tenant_id)
    if not api_key:
        raise HTTPException(status_code=400,
                            detail="Anthropic API key required. Configure it in Settings > API Keys.")

    system_prompt = await _channel_default_prompt(tenant_id, "script", SCRIPT_SYSTEM_PROMPT)

    rp = video.get("research_payload")
    if isinstance(rp, str):
        try:
            rp = _json.loads(rp)
        except (ValueError, TypeError):
            rp = {}
    if not isinstance(rp, dict):
        rp = {}

    roster = rp.get("unit_roster")
    marker = str(rp.get("documentary_style") or rp.get("pipeline_style") or "").strip().lower()
    has_machine_marker = (
        marker in {"machine_documentary", "designed_vs_used", "dvsu"}
        or isinstance(rp.get("machine_discovery_buckets"), dict)
        or isinstance(rp.get("unit_research_hold_validation"), dict)
    )
    machine_documentary = (
        (video.get("render_mode") or "") == "static_docu"
        and has_machine_marker
        and isinstance(roster, list)
        and 3 <= len(roster) <= 40
    )
    locked_machine = _locked_machine_for_scene(rp, scene, row.get("scene_text") or "")
    if machine_documentary:
        card = _research_card_for_machine(rp, locked_machine)
        if card is None:
            raise HTTPException(
                status_code=409,
                detail=f"Machine rewrite requires the saved research card for {locked_machine}",
            )
        research_source = _json.dumps(card, ensure_ascii=False, indent=2)[:9000]
        research_source_kind = "unit_research_card"
    else:
        # Preserve the pre-existing generic scene-rewrite behavior outside the
        # machine-documentary silo. Animation/narrative stays fact-sheet/global.
        fact_sheet = rp.get("fact_sheet") or ""
        research_source = fact_sheet if isinstance(fact_sheet, str) else _json.dumps(fact_sheet)
        research_source = research_source[:6000]
        research_source_kind = "fact_sheet"

    def _clean_response(text: str) -> str:
        cleaned = str(text or "").strip()
        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned).strip()
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()
        cleaned = re.sub(r"^(?:scene|paragraph|machine)\s*\d*\s*[:\-]\s*", "", cleaned, flags=re.I).strip()
        # Preserve newlines until the one-paragraph gate has run.
        return cleaned.strip()

    def _validation_warnings(text: str) -> list[str]:
        warnings: list[str] = []
        wc = _spoken_word_count(text)
        if not text.strip():
            warnings.append("empty paragraph")
        if "\n" in text:
            warnings.append("must be exactly one paragraph")
        if wc < 95 or wc > 120:
            warnings.append(f"word count {wc} outside 95-120 rewrite range")
        code = _normalized_unit_code(locked_machine)
        normalized_text = re.sub(r"[^A-Z0-9]", "", text.upper())
        if code and code not in normalized_text:
            warnings.append(f"missing locked machine designation {code}")
        return warnings

    async def _claude_paragraph(prompt: str, max_tokens: int = 450, temperature: float = 0.25) -> str:
        async with _httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                         "content-type": "application/json"},
                json={"model": "claude-sonnet-4-6", "max_tokens": max_tokens,
                      "temperature": temperature,
                      "system": system_prompt,
                      "messages": [{"role": "user", "content": prompt}]})
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail=humanize_error(
                f"Claude {resp.status_code}", context="Couldn't rewrite this scene"))
        return _clean_response(resp.json()["content"][0]["text"])

    machine_contract = (
        f"LOCKED MACHINE FOR THIS SCENE: {locked_machine}\n"
        "Use 95-120 words inclusive. A 90-word result must be expanded. "
        if machine_documentary
        else "Keep it a self-contained unit of 95 to 120 words. "
    )
    task = (
        f'Video: "{video.get("video_title", "")}"\n\n'
        + machine_contract
        + "Rewrite the following SINGLE unit paragraph — one machine, one paragraph. "
        "Obey every channel law in your instructions. Use ONLY supported facts from the research source below; "
        "hedge anything uncertain; never speak source names aloud. "
        "Output ONLY the rewritten paragraph, nothing else.\n\n"
        f"CURRENT PARAGRAPH:\n{row['scene_text']}\n\n"
        f"RESEARCH SOURCE ({research_source_kind}):\n{research_source}"
    )
    try:
        new_text = await _claude_paragraph(
            task,
            max_tokens=450 if machine_documentary else 600,
            temperature=0.35 if machine_documentary else 0.25,
        )
        warnings = _validation_warnings(new_text) if machine_documentary else []
        if machine_documentary and warnings:
            repair_task = (
                f"Repair this SINGLE DVsU machine paragraph for LOCKED MACHINE: {locked_machine}.\n"
                f"Validation warnings: {'; '.join(warnings)}\n\n"
                "Return exactly ONE spoken paragraph, 95-120 words inclusive. Expand any result below 95 and cut any result above 120. "
                "No markdown, labels, bullets, or citations. Preserve the engineering thesis, one surprising fact, and a clean final irony/reversal. "
                "Cut secondary specs and timeline filler. Use only the research source.\n\n"
                f"BAD PARAGRAPH:\n{new_text}\n\n"
                f"RESEARCH SOURCE ({research_source_kind}):\n{research_source}"
            )
            new_text = await _claude_paragraph(repair_task, max_tokens=380, temperature=0.15)
            warnings = _validation_warnings(new_text)
        if warnings:
            raise HTTPException(status_code=502, detail="Rewrite failed validation after repair: " + "; ".join(warnings))
        new_text = " ".join(new_text.split())
    except _httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Failed to reach Claude API")
    if not new_text or _spoken_word_count(new_text) < 40:
        raise HTTPException(status_code=502, detail="Rewrite came back too short — try again")

    # Save the paragraph; clear this scene's voice so only it re-records.
    await execute(
        """UPDATE scripts SET scene_text = $4, voice_over_url = NULL,
               voice_duration_seconds = NULL, voice_status = NULL
           WHERE video_id = $1 AND tenant_id = $2 AND scene = $3""",
        video_id, tenant_id, scene, new_text)
    # Keep videos.script in sync (it is the display/export copy).
    scenes_rows = await fetch_all(
        "SELECT scene_text FROM scripts WHERE video_id = $1 AND tenant_id = $2 "
        "AND scene_text IS NOT NULL ORDER BY scene", video_id, tenant_id)
    await execute(
        "UPDATE videos SET script = $3, updated_at = now() WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id, "\n\n".join(r["scene_text"] for r in scenes_rows))

    return {"scene": scene, "text": new_text, "word_count": _spoken_word_count(new_text)}


async def _channel_default_prompt(tenant_id, prompt_key: str, fallback: str) -> str:
    """The prompt this channel actually runs with when a video has no
    per-video override: tenant custom prompt first, neutral template second.
    Mirrors the pipeline's resolve order (per-video > tenant > neutral) so
    the per-video editor shows the REAL default instead of the generic
    engine text (seen live on DvsU: the box displayed 'general educational
    content channel' while the tenant's custom prompt was what actually ran
    — and saving that generic text would have silently overridden the
    channel's prompt for the video)."""
    try:
        row = await fetch_one(
            "SELECT prompt_text FROM tenant_prompt_defaults WHERE tenant_id = $1 AND prompt_key = $2",
            tenant_id, prompt_key,
        )
        if row and (row.get("prompt_text") or "").strip():
            return row["prompt_text"]
    except Exception:  # noqa: BLE001 — display helper, never block
        pass
    return fallback


@router.get("/defaults/video-motion-prompt")
async def get_default_video_motion_prompt(tenant_id=Depends(get_tenant_id)):
    """Return the channel's effective video motion system prompt."""
    return {"prompt": await _channel_default_prompt(tenant_id, "video_motion", VIDEO_MOTION_SYSTEM_PROMPT)}


@router.get("/defaults/script-prompt")
async def get_default_script_prompt(tenant_id=Depends(get_tenant_id)):
    """Return the channel's effective script system prompt."""
    return {"prompt": await _channel_default_prompt(tenant_id, "script", SCRIPT_SYSTEM_PROMPT)}


@router.get("/defaults/thumbnail-prompt")
async def get_default_thumbnail_prompt(tenant_id=Depends(get_tenant_id)):
    """Return the channel's effective thumbnail system prompt."""
    return {"prompt": await _channel_default_prompt(tenant_id, "thumbnail", THUMBNAIL_SYSTEM_PROMPT)}


@router.get("/defaults/sound-curation-prompt")
async def get_default_sound_curation_prompt(tenant_id=Depends(get_tenant_id)):
    """Return the channel's effective sound curation system prompt."""
    return {"prompt": await _channel_default_prompt(tenant_id, "sound_curation", SOUND_CURATION_SYSTEM_PROMPT)}


@router.get("/defaults/sound-generation-prompt")
async def get_default_sound_generation_prompt(tenant_id=Depends(get_tenant_id)):
    """Return the channel's effective sound generation system prompt."""
    return {"prompt": await _channel_default_prompt(tenant_id, "sound_generation", SOUND_GENERATION_SYSTEM_PROMPT)}


@router.get("/defaults/research-prompt")
async def get_default_research_prompt(tenant_id=Depends(get_tenant_id)):
    """Return the channel's effective research system prompt."""
    return {"prompt": await _channel_default_prompt(tenant_id, "research", RESEARCH_SYSTEM_PROMPT)}


from pydantic import BaseModel as _BaseModel


class SuggestTitlesRequest(_BaseModel):
    topic: str
    context: Optional[str] = None
    count: int = 5


@router.post("/suggest-titles")
async def suggest_titles(
    body: SuggestTitlesRequest,
    tenant_id: str = Depends(get_tenant_id),
):
    """Generate AI title suggestions for a given topic using Claude."""
    from routes.billing import increment_usage
    from vault import get_secret

    topic = body.topic.strip()
    if not topic:
        raise HTTPException(status_code=400, detail="Topic is required")

    # Route through the shared text-LLM resolver: the tenant's own Claude key
    # if they have one, otherwise their kie.ai key (one key for everything).
    from kie_unified import get_text_client_for_tenant, MissingGenerationKeyError
    try:
        text_client = await get_text_client_for_tenant(tenant_id)
    except MissingGenerationKeyError:
        raise HTTPException(
            status_code=400,
            detail="Add a Claude or kie.ai API key in Settings → API Keys.",
        )

    # Read `projects` first — that's what the Profile UI edits; channel_profiles
    # is the legacy onboarding store and can be stale.
    channel_name, channel_niche = "", ""
    try:
        project = await fetch_one(
            "SELECT name, niche FROM projects WHERE tenant_id = $1 LIMIT 1",
            tenant_id,
        )
        if project:
            # projects row is the source of truth (the Profile UI manages it);
            # use as-is so a blank name doesn't resurrect stale onboarding values.
            channel_name = project.get("name") or ""
            channel_niche = project.get("niche") or ""
        else:
            profile = await fetch_one(
                "SELECT channel_name, niche FROM channel_profiles WHERE tenant_id = $1",
                tenant_id,
            )
            if profile:
                channel_name = profile.get("channel_name") or ""
                channel_niche = profile.get("niche") or ""
    except Exception:
        pass

    channel_ctx = ""
    if channel_name or channel_niche:
        channel_ctx = f"\nChannel: {channel_name}. Niche: {channel_niche}."

    prompt = (
        f"Generate {body.count} compelling YouTube video title options for this topic."
        f"{channel_ctx}\n\nTopic: {topic}\n"
        + (f"Additional context: {body.context}\n" if body.context else "")
        + "\nRules:\n"
        "- Each title should use a different angle or hook structure\n"
        "- Titles should be 8-12 words, curiosity-driven\n"
        "- Include power words, numbers, or tension where natural\n"
        "- No clickbait that cannot be delivered on\n\n"
        'Return ONLY a JSON array of strings. Example: ["Title One", "Title Two"]'
    )

    try:
        # Titles are short but high-stakes (they drive views), and the cost
        # delta vs Haiku is negligible on so few tokens — use Sonnet for the
        # sharper hooks. Works on both the Anthropic and kie.ai paths.
        text = await text_client.generate(
            prompt,
            model="claude-sonnet-4-6",
            max_tokens=1024,
        )

        # Models (especially via kie.ai) often wrap the array in prose or a
        # ```json fence — extract the array instead of failing on strict parse.
        import re as _re
        raw = text.strip()
        try:
            titles = json.loads(raw)
        except json.JSONDecodeError:
            m = _re.search(r"\[.*\]", raw, _re.DOTALL)
            if not m:
                raise
            titles = json.loads(m.group(0))
        if not isinstance(titles, list):
            titles = [str(titles)]

        await increment_usage(tenant_id, "api_calls")

        return {"titles": titles[: body.count], "topic": topic}

    except json.JSONDecodeError:
        raise HTTPException(
            status_code=502, detail="Failed to parse title suggestions"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=humanize_error(str(e), context="We couldn't generate title ideas"),
        )


@router.get("/{video_id}/export-manifest")
async def get_export_manifest(video_id: str, tenant_id: str = Depends(get_tenant_id)):
    """Return all downloadable assets for a video as a manifest."""
    try:
        video = await fetch_one(
            """SELECT id, video_title, status, final_video_url, thumbnail_url,
                      drive_folder_link, youtube_url
               FROM videos WHERE id = $1 AND tenant_id = $2""",
            video_id, tenant_id,
        )
    except Exception:
        raise HTTPException(status_code=404, detail="Video not found")
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    assets_rows = await fetch_all(
        """SELECT scene, image_index, image_url, video_clip_url, sound_effect_url
           FROM assets WHERE video_id = $1 AND tenant_id = $2
           ORDER BY scene, image_index""",
        video_id, tenant_id,
    )

    scripts_rows = await fetch_all(
        """SELECT scene, voice_over_url
           FROM scripts WHERE video_id = $1 AND tenant_id = $2
           ORDER BY scene""",
        video_id, tenant_id,
    )

    return {
        "video_id": str(video["id"]),
        "video_title": video["video_title"],
        "status": video["status"],
        "final_video_url": video["final_video_url"],
        "thumbnail_url": video["thumbnail_url"],
        "drive_folder_link": video["drive_folder_link"],
        "youtube_url": video["youtube_url"],
        "assets": [
            {
                "scene": a["scene"],
                "image_index": a["image_index"],
                "image_url": a["image_url"],
                "video_clip_url": a["video_clip_url"],
                "sound_effect_url": a["sound_effect_url"],
            }
            for a in assets_rows
        ],
        "voice_tracks": [
            {"scene": s["scene"], "voice_over_url": s["voice_over_url"]}
            for s in scripts_rows
        ],
    }


# =============================================================================
# Script <-> Google Drive sync
#
# Let the creator edit a video's script as an editable Google Doc in THEIR OWN
# Drive (any AI tool, they own the data) and mirror edits back to Postgres.
# Postgres stays the operational source of truth — the pipeline only ever reads
# scripts.scene_text / videos.script; the Doc is an explicit, directional mirror:
#   Push (Postgres -> Doc): POST .../script/push-to-drive
#   Pull (Doc -> Postgres): POST .../script/sync-from-drive
# Scene mapping rides on dead-simple "### SCENE n" marker lines; Pull fails loud
# if they're gone rather than mis-mapping. See tasks/script-drive-sync-spec.md.
# =============================================================================

# Lenient scene-marker matcher: tolerates missing '###', a trailing title, ':',
# extra whitespace, any case — but requires the literal word SCENE + a number.
_SCENE_HEADER_RE = re.compile(r"^\s*#{0,3}\s*scene\s+(\d+)\b.*$", re.IGNORECASE)


def _build_tenant_google_client(refresh_token: str):
    """Build a GoogleClient bound to ONE tenant's Drive refresh token.

    The token was minted by the GOOGLE_OAUTH_* OAuth app (routes/google_auth.py),
    so it MUST be refreshed with those same creds — not GoogleClient's default
    GOOGLE_CLIENT_* (a separate app used for app-owned storage). Falls back to the
    GOOGLE_CLIENT_* names if the OAuth ones aren't set (single-app deployments).
    """
    import sys
    import os
    from pathlib import Path
    pipeline_path = Path(__file__).resolve().parents[3] / "skills" / "video-pipeline"
    if str(pipeline_path) not in sys.path:
        sys.path.insert(0, str(pipeline_path))
    from shared.clients.google_client import GoogleClient
    client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID") or os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET") or os.getenv("GOOGLE_CLIENT_SECRET")
    return GoogleClient(
        client_id=client_id, client_secret=client_secret, refresh_token=refresh_token
    )


def _build_script_doc_text(title: str, scenes) -> str:
    """Render scene rows into a scene-delimited, human-editable Doc body."""
    lines = [
        f'StoryEngine script — "{title}"',
        "",
        'Edit the words under each "### SCENE n" line. Keep those scene lines '
        "exactly as they are so your changes sync back to StoryEngine.",
        "",
    ]
    for i, s in enumerate(scenes, start=1):
        n = s.get("scene") if s.get("scene") is not None else i
        text = (s.get("scene_text") or "").strip()
        lines.append(f"### SCENE {n}")
        lines.append("")
        lines.append(text)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _parse_script_doc(text: str) -> dict:
    """Split a pushed Doc back into {scene_number: scene_text} by its scene
    markers. Requires at least one marker — raises ValueError otherwise so Pull
    fails loud instead of silently mis-mapping the whole script."""
    sections: dict[int, str] = {}
    current = None
    buf: list[str] = []
    for line in (text or "").split("\n"):
        m = _SCENE_HEADER_RE.match(line)
        if m:
            if current is not None:
                sections[current] = "\n".join(buf).strip()
            current = int(m.group(1))
            buf = []
        elif current is not None:
            buf.append(line)
    if current is not None:
        sections[current] = "\n".join(buf).strip()
    if not sections:
        raise ValueError(
            "Couldn't find any '### SCENE n' lines in the Doc — keep those scene "
            "markers intact so StoryEngine can map your edits back."
        )
    return sections


def _parse_drive_time(s):
    """Parse Drive's RFC-3339 modifiedTime string into a tz-aware datetime."""
    from datetime import datetime
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


async def _clear_scene_downstream(video_id: str, scene: int, tenant_id: str):
    """A pulled text change makes that scene's voice/images/clips stale. Mirror
    delete_clip's URL-nulling (proven safe) across voice + image + clip so the
    scene visibly needs regeneration instead of silently shipping old media."""
    await execute(
        "UPDATE scripts SET voice_over_url = NULL, voice_status = NULL, "
        "voice_duration_seconds = NULL, updated_at = now() "
        "WHERE video_id = $1 AND scene = $2 AND tenant_id = $3",
        video_id, scene, tenant_id,
    )
    await execute(
        "UPDATE assets SET image_url = NULL, drive_image_url = NULL, "
        "video_url = NULL, video_clip_url = NULL, video_duration = NULL, "
        "updated_at = now() "
        "WHERE video_id = $1 AND scene = $2 AND tenant_id = $3",
        video_id, scene, tenant_id,
    )


@router.post("/{video_id}/drive-workspace/sync")
async def sync_drive_workspace(video_id: str, tenant_id: str = Depends(get_tenant_id)):
    """Manually create/refresh the app-owned Drive workspace for this video."""
    from drive_workspace import sync_video_workspace
    try:
        return await sync_video_workspace(video_id, tenant_id)
    except LookupError:
        raise HTTPException(404, "Video not found")
    except Exception as e:  # noqa: BLE001
        logger.warning("workspace sync failed for %s: %s", video_id, str(e)[:200])
        raise HTTPException(502, humanize_error(e, context="We couldn't sync the Drive workspace"))


@router.post("/{video_id}/script/push-to-drive")
async def push_script_to_drive(video_id: str, tenant_id: str = Depends(get_tenant_id)):
    """Push (Postgres -> Doc): write the full script as a scene-delimited,
    editable Google Doc in the creator's own Drive; remember the Doc id.

    Creates the Doc on first push (drive.file scope -> app-owned, so we can always
    read it back for Pull), overwrites it on subsequent pushes."""
    video = await fetch_one(
        "SELECT id, video_title, drive_script_doc_id FROM videos "
        "WHERE id = $1 AND tenant_id = $2 AND deleted_at IS NULL",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(404, "Video not found")

    profile = await fetch_one(
        "SELECT google_drive_refresh_token, google_drive_folder_id "
        "FROM channel_profiles WHERE tenant_id = $1",
        tenant_id,
    )
    if not profile or not profile.get("google_drive_refresh_token"):
        raise HTTPException(400, "Google Drive isn't connected. Connect it in Settings first.")

    scenes = await fetch_all(
        "SELECT scene, scene_text FROM scripts "
        "WHERE video_id = $1 AND tenant_id = $2 "
        "ORDER BY scene NULLS FIRST, created_at",
        video_id, tenant_id,
    )
    if not scenes:
        raise HTTPException(400, "No script to push yet — generate the script first.")

    title = (video.get("video_title") or "Untitled").strip() or "Untitled"
    doc_text = _build_script_doc_text(title, scenes)
    existing_doc_id = video.get("drive_script_doc_id")
    refresh_token = profile["google_drive_refresh_token"]
    folder_id = profile.get("google_drive_folder_id") or None

    def _push():
        client = _build_tenant_google_client(refresh_token)
        doc_id = existing_doc_id
        if not doc_id:
            # Create in My Drive root (app-owned), then best-effort tuck into the
            # creator's connected folder — under drive.file a move into a folder
            # the app didn't create may 403, which must NOT fail the whole push.
            created = client.create_document(f"Script — {title}", None)
            doc_id = created.get("id")
            if not doc_id:
                raise RuntimeError("Google Docs is unavailable right now — try again shortly.")
            if folder_id:
                try:
                    client.drive_service.files().update(
                        fileId=doc_id, addParents=folder_id,
                        removeParents="root", fields="id, parents",
                    ).execute()
                except Exception as move_err:  # noqa: BLE001 - best effort
                    logger.info(
                        "script doc folder-move skipped for %s: %s",
                        doc_id, str(move_err)[:120],
                    )
        if not client.replace_document_body(doc_id, doc_text):
            raise RuntimeError("Couldn't write the script into the Doc — try again shortly.")
        return doc_id, client.get_document_url(doc_id), client.get_file_modified_time(doc_id)

    try:
        doc_id, doc_url, modified = await asyncio.to_thread(_push)
    except Exception as e:  # noqa: BLE001
        logger.warning("push_script_to_drive failed for %s: %s", video_id, str(e)[:200])
        raise HTTPException(502, humanize_error(e, context="We couldn't sync your script to Drive"))

    await execute(
        "UPDATE videos SET drive_script_doc_id = $1, drive_script_synced_at = now(), "
        "drive_script_doc_modified_at = $2, updated_at = now() "
        "WHERE id = $3 AND tenant_id = $4",
        doc_id, _parse_drive_time(modified), video_id, tenant_id,
    )
    return {"doc_id": doc_id, "doc_url": doc_url, "status": "pushed"}


@router.post("/{video_id}/script/sync-from-drive")
async def sync_script_from_drive(
    video_id: str, force: bool = Query(False), tenant_id: str = Depends(get_tenant_id)
):
    """Pull (Doc -> Postgres): read the Drive Doc, map scenes by their
    '### SCENE n' markers, update changed scenes' text, and clear those scenes'
    voice/images/clips so they regenerate. Drive-wins on an explicit pull, but if
    BOTH sides changed since the last sync we return conflict:true (unless
    ?force=true) so the UI can confirm before overwriting."""
    video = await fetch_one(
        "SELECT id, drive_script_doc_id, drive_script_synced_at, "
        "drive_script_doc_modified_at FROM videos "
        "WHERE id = $1 AND tenant_id = $2 AND deleted_at IS NULL",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(404, "Video not found")
    doc_id = video.get("drive_script_doc_id")
    if not doc_id:
        raise HTTPException(400, "No Drive Doc yet — push the script to Drive first.")

    profile = await fetch_one(
        "SELECT google_drive_refresh_token FROM channel_profiles WHERE tenant_id = $1",
        tenant_id,
    )
    if not profile or not profile.get("google_drive_refresh_token"):
        raise HTTPException(400, "Google Drive isn't connected. Connect it in Settings first.")
    refresh_token = profile["google_drive_refresh_token"]

    def _read():
        client = _build_tenant_google_client(refresh_token)
        return client.get_file_modified_time(doc_id), client.read_document_text(doc_id)

    try:
        modified, text = await asyncio.to_thread(_read)
    except Exception as e:  # noqa: BLE001
        logger.warning("sync_script_from_drive read failed for %s: %s", video_id, str(e)[:200])
        raise HTTPException(502, humanize_error(e, context="We couldn't read your script from Drive"))
    if text is None:
        raise HTTPException(502, "Couldn't read the Doc from Drive — try again shortly.")

    modified_dt = _parse_drive_time(modified)
    last_doc_modified = video.get("drive_script_doc_modified_at")
    # Fast path: Drive hasn't changed since our last sync.
    if not force and modified_dt and last_doc_modified and modified_dt <= last_doc_modified:
        return {"changed": False, "scenes_changed": [], "message": "No new edits in Drive."}

    try:
        parsed = _parse_script_doc(text)
    except ValueError as e:
        raise HTTPException(422, str(e))

    # Conflict guard: both the in-app script and the Doc changed since last sync.
    synced_at = video.get("drive_script_synced_at")
    if not force and synced_at:
        app_row = await fetch_one(
            "SELECT max(updated_at) AS last FROM scripts "
            "WHERE video_id = $1 AND tenant_id = $2",
            video_id, tenant_id,
        )
        app_last = (app_row or {}).get("last")
        doc_changed = last_doc_modified is None or bool(modified_dt and modified_dt > last_doc_modified)
        if app_last and app_last > synced_at and doc_changed:
            return {
                "changed": False,
                "conflict": True,
                "scenes_changed": [],
                "message": "Both StoryEngine and the Drive Doc changed since the last "
                           "sync. Syncing will overwrite the in-app script with the "
                           "Doc's text.",
            }

    current = await fetch_all(
        "SELECT id, scene, scene_text FROM scripts "
        "WHERE video_id = $1 AND tenant_id = $2 ORDER BY scene NULLS FIRST, created_at",
        video_id, tenant_id,
    )
    row_by_scene = {}
    for i, row in enumerate(current, start=1):
        n = row.get("scene") if row.get("scene") is not None else i
        row_by_scene[n] = row

    changed_scenes = []
    for scene_num in sorted(parsed.keys()):
        row = row_by_scene.get(scene_num)
        if row is None:
            continue  # Doc has a scene we don't have a row for — MVP maps onto existing scenes only.
        new_text = parsed[scene_num]
        if (new_text or "").strip() != (row.get("scene_text") or "").strip():
            await execute(
                "UPDATE scripts SET scene_text = $1, updated_at = now() "
                "WHERE id = $2 AND tenant_id = $3",
                new_text, row["id"], tenant_id,
            )
            changed_scenes.append(scene_num)
            if row.get("scene") is not None:
                await _clear_scene_downstream(video_id, row["scene"], tenant_id)

    if changed_scenes:
        rebuilt = await fetch_all(
            "SELECT scene_text FROM scripts WHERE video_id = $1 AND tenant_id = $2 "
            "ORDER BY scene NULLS FIRST, created_at",
            video_id, tenant_id,
        )
        full = "\n\n".join(
            (r.get("scene_text") or "").strip()
            for r in rebuilt if (r.get("scene_text") or "").strip()
        )
        await execute(
            "UPDATE videos SET script = $1, updated_at = now() WHERE id = $2 AND tenant_id = $3",
            full, video_id, tenant_id,
        )

    # Mark this Drive version consumed (runs last so synced_at > scripts.updated_at).
    await execute(
        "UPDATE videos SET drive_script_synced_at = now(), "
        "drive_script_doc_modified_at = $1, updated_at = now() "
        "WHERE id = $2 AND tenant_id = $3",
        modified_dt, video_id, tenant_id,
    )
    return {
        "changed": bool(changed_scenes),
        "scenes_changed": changed_scenes,
        "message": (
            f"Synced {len(changed_scenes)} scene(s) from Drive. Their voice/images/clips "
            "were cleared and need regenerating."
            if changed_scenes else "Doc read OK — no scene text differed."
        ),
    }


@router.get("/{video_id}/script/drive-status")
async def script_drive_status(video_id: str, tenant_id: str = Depends(get_tenant_id)):
    """Lightweight status for the Script tab's Drive controls: is Drive connected,
    does a Doc exist, and has the Doc been edited since our last sync (badge)?"""
    video = await fetch_one(
        "SELECT drive_script_doc_id, drive_script_synced_at, drive_script_doc_modified_at "
        "FROM videos WHERE id = $1 AND tenant_id = $2 AND deleted_at IS NULL",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(404, "Video not found")
    profile = await fetch_one(
        "SELECT google_drive_refresh_token FROM channel_profiles WHERE tenant_id = $1",
        tenant_id,
    )
    connected = bool(profile and profile.get("google_drive_refresh_token"))
    doc_id = video.get("drive_script_doc_id")
    synced_at = video.get("drive_script_synced_at")

    drive_newer = False
    drive_modified = None
    if connected and doc_id:
        refresh_token = profile["google_drive_refresh_token"]

        def _check():
            return _build_tenant_google_client(refresh_token).get_file_modified_time(doc_id)

        try:
            drive_modified = await asyncio.to_thread(_check)
            md = _parse_drive_time(drive_modified)
            last = video.get("drive_script_doc_modified_at")
            drive_newer = bool(md and (last is None or md > last))
        except Exception as e:  # noqa: BLE001 - badge is best-effort
            logger.info("drive-status modifiedTime check skipped: %s", str(e)[:120])

    return {
        "connected": connected,
        "doc_id": doc_id,
        "doc_url": f"https://docs.google.com/document/d/{doc_id}/edit" if doc_id else None,
        "synced_at": synced_at.isoformat() if synced_at else None,
        "drive_modified_at": drive_modified,
        "drive_newer": drive_newer,
    }
