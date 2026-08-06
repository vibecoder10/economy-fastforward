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
    CreateVideoRequest, VideoLedgerResponse, LedgerRow,
)
from database import fetch_all, fetch_one, execute, safe_column
from error_utils import humanize_error
from status_map import (
    get_next_status_supabase, normalize_stage_plan, first_status_for_plan,
    render_path_plays_sfx, render_path_sfx_block_reason, resolve_planned_status,
)
import production_guide
from prompt_defaults import VIDEO_MOTION_SYSTEM_PROMPT, SCRIPT_SYSTEM_PROMPT, THUMBNAIL_SYSTEM_PROMPT, SOUND_CURATION_SYSTEM_PROMPT, SOUND_GENERATION_SYSTEM_PROMPT, RESEARCH_SYSTEM_PROMPT
from typing import Optional, Any
# Single Claude tier source (checklist §3.4 / C35) — see shared.channel_profile.
from actions import CLAUDE_MODELS


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

    C46d fix: a script_validation blob that carries ONLY the generic
    quality-critic record (``{"quality_critic": {...}}`` —
    pipeline_executor._grade_and_maybe_revise_script and
    user_script.accept_external_script both write this key, and neither
    guarantees a sibling "checks" array exists yet) used to fall through to
    the plain-text branch below, find zero `[PASS]`/`[FAIL]` lines, and
    silently return None — dropping the ONE thing the C46d "quality review"
    banner (ScriptVoiceTab) needs to render. "checks" OR "quality_critic"
    now both count as "already valid JSON", so this passes through as-is.
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
        if isinstance(parsed, dict) and ("checks" in parsed or "quality_critic" in parsed):
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
                      early_signal, created_at::text, updated_at::text
               FROM videos WHERE tenant_id = $1 AND status = $2 AND deleted_at IS NULL
               ORDER BY updated_at DESC LIMIT $3 OFFSET $4""",
            tenant_id, status, limit, offset,
        )
    else:
        rows = await fetch_all(
            """SELECT id, video_title, status, thumbnail_url, accent_color, total_cost, views, ctr,
                      early_signal, created_at::text, updated_at::text
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
            early_signal=r.get("early_signal"),
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


async def _resolve_style_preset_id(style_preset_id: Optional[str]) -> Optional[str]:
    """Validate an explicit style_preset_id (checklist §2.1, C20 — the 5 rich
    Python visual-profile engines) against the style_presets catalog.

    Returns the id unchanged when it names a real ACTIVE row; None when the
    field was blank/omitted (the common case — most videos don't pick one).
    Raises 400 for an unknown/inactive id rather than silently dropping it,
    matching this same function's `reference_url` precedent just above
    create_video: a picker UI should never send a bogus id, so surfacing the
    error immediately catches a real bug instead of quietly ignoring the
    creator's explicit choice."""
    style_preset_id = (style_preset_id or "").strip() or None
    if not style_preset_id:
        return None
    row = await fetch_one(
        "SELECT id FROM style_presets WHERE id = $1 AND active = true",
        style_preset_id,
    )
    if not row:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown style preset: {style_preset_id!r}",
        )
    return style_preset_id


async def _resolve_production_style(
    production_style_id: Optional[str],
) -> tuple[Optional[str], Optional[int], Optional[dict]]:
    """Validate and snapshot the high-level public production profile.

    Omitted stays a no-op for pre-migration callers. First-party creation
    surfaces enforce the required pick; the API keeps legacy chat/MCP clients
    releasable while those callers are upgraded in this milestone.
    """
    normalized_id = (production_style_id or "").strip() or None
    if not normalized_id:
        return None, None, None
    from production_styles import get_public_profile, snapshot_profile

    profile = await get_public_profile(normalized_id)
    if not profile:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown production style: {normalized_id!r}",
        )
    snapshot = snapshot_profile(profile)
    return normalized_id, int(snapshot["version"]), snapshot


def _resolve_script_profile(script_profile: Optional[str]) -> Optional[str]:
    """Validate an explicit script_profile (checklist §2.3, C24 — the
    editorial-voice engines in shared.profiles.script) against the real
    profile registry.

    Returns the id unchanged when it names a real registered profile; None
    when the field was blank/omitted (the common case — most videos never
    pick one, and the executor's _resolve_script_profile_id falls back to
    "neutral_v1" for them). Raises 400 for an unknown id — same posture as
    _resolve_style_preset_id just above: a picker UI (or the copilot) should
    never send a bogus id, so surfacing the error immediately catches a real
    bug instead of quietly ignoring the creator's explicit choice.

    No DB round-trip needed (unlike style_preset_id): the catalog is a small
    code-reviewed Python registry (list_profiles()), not admin-mutable table
    data — same "no new DB table" rationale as camera_preset_id's
    get_move() check in routes/assets.py."""
    script_profile = (script_profile or "").strip() or None
    if not script_profile:
        return None
    import sys
    from pathlib import Path
    pipeline_path = Path(__file__).resolve().parents[3] / "skills" / "video-pipeline"
    if str(pipeline_path) not in sys.path:
        sys.path.insert(0, str(pipeline_path))
    from shared.profiles.script import list_profiles
    if script_profile not in list_profiles():
        raise HTTPException(
            status_code=400,
            detail=f"Unknown script profile: {script_profile!r}",
        )
    return script_profile


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
    from routes.billing import check_plan_limits, enforce_video_length_cap, increment_usage
    await check_plan_limits(tenant_id, "video")
    await enforce_video_length_cap(tenant_id, body.video_length_minutes)

    from routes.projects import _get_or_create_project

    project = await _get_or_create_project(tenant_id)
    project_id = str(project["id"])

    # Per-video stage plan: which stages this video should run (script-only,
    # script+voice, full video, etc.). When the creator picks a reduced plan it
    # becomes the single source of truth, and the legacy skip_research /
    # skip_voice flags are derived from it so existing gates keep working. A
    # full plan (or none) stores NULL → unchanged full-pipeline behavior.
    plan = normalize_stage_plan(body.pipeline_stages)

    (
        production_style_id,
        production_style_version,
        production_style_snapshot,
    ) = await _resolve_production_style(body.production_style_id)

    # Static-documentary channels (identity says the format is held images +
    # Ken Burns over narration, e.g. Designed vs Used) never animate: their
    # videos get render_mode='static_docu' and a plan without video/sound.
    # Voice is mandatory there — the narration IS the audio track.
    from static_docu import static_mode_for_tenant, STATIC_RENDER_MODE
    from status_map import static_stage_plan
    render_mode = None
    production_runtime = None
    if production_style_snapshot:
        from production_styles import runtime_values
        production_runtime = runtime_values(production_style_snapshot)
        render_mode = production_runtime["render_mode"]
        if render_mode == STATIC_RENDER_MODE:
            plan = static_stage_plan(body.pipeline_stages)
    else:
        try:
            if await static_mode_for_tenant(tenant_id):
                render_mode = STATIC_RENDER_MODE
                plan = static_stage_plan(body.pipeline_stages)
        except Exception as e:  # detection must never block legacy creation
            import logging
            logging.getLogger(__name__).warning("static-mode detection failed: %s", e)

    if plan is not None:
        skip_research = "research" not in plan
        skip_voice = "voice" not in plan
    else:
        skip_research = body.skip_research
        skip_voice = body.skip_voice
    writer_guidance = body.writer_guidance
    if production_style_snapshot:
        from production_styles import merge_script_guidance
        writer_guidance = merge_script_guidance(
            writer_guidance,
            production_style_snapshot,
        )
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
    # P5/migration 116: a skip_voice=true set at creation (reduced stage plan
    # or the legacy explicit flag) is always a creator choice, never the
    # dialogue_intelligence auto-detector (that only ever runs later, once a
    # script exists) — stamp 'manual' so it's never auto-reverted. false
    # needs no provenance yet.
    skip_voice_source = "manual" if skip_voice else None

    # Optional reference (a YouTube link) puts the video in "modeled" mode.
    # Two shapes share this one INSERT (checklist C38 — create-surface
    # convergence, killed model_video.py's own parallel INSERT):
    #   - title + reference_url ("copy this video's style" — the New Video
    #     form / chat's clone path): the creator's own topic/title is kept,
    #     the reference's style is copied onto it (scoped to the switched-on
    #     stages) by a background task. preserve_topic=True.
    #   - reference_url ALONE, no title (Model A Video — the creator hasn't
    #     picked a topic yet): a placeholder title holds the row until the
    #     background task derives a brand-new modeled idea (title, research,
    #     full style) from the reference. preserve_topic=False.
    # Either way the video holds at 'idea_logged' until that background task
    # lands.
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

    title = (body.title or "").strip()
    if not title and not is_modeled:
        raise HTTPException(status_code=400, detail="Title is required.")
    preserve_topic = is_modeled and bool(title)
    if is_modeled and not title:
        title = "Modeling a reference video…"

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
    # C13b (checklist §C13b): auto-derive render_style ONLY when the
    # creator's explicit style choice unambiguously maps onto one of the
    # six canonical presets — reusing _normalize_style_preset, the SAME
    # classifier GET /style-default already trusts, not a new guess.
    # image_style_override wins (the higher-priority per-video look, same
    # precedence _resolve_style uses); ambiguous/freeform text on both
    # leaves render_style NULL (undeclared), never a wrong guess.
    from channel_format import render_style_for_preset
    render_style = None
    for _raw in (style_override, body.visual_style):
        if _raw:
            _preset = _normalize_style_preset(_raw)
            if _preset:
                render_style = render_style_for_preset(_preset)
                break
    # The production profile supplies the canonical structural visual engine
    # (Power Doctrine's desktop integration uses cinematic_illustration).
    # A creator's explicit look-engine choice still wins as an override.
    style_preset_id = await _resolve_style_preset_id(
        body.style_preset_id
        or (
            production_runtime["visual_profile"]
            if production_runtime
            else None
        )
    )
    script_profile = _resolve_script_profile(
        production_runtime["script_profile"]
        if production_runtime
        else body.script_profile
    )
    dialogue_audio = (
        production_runtime["dialogue_audio"]
        if production_runtime
        else None
    )

    # max_spend (checklist §3.3/C36 column, now also settable AT creation —
    # see CreateVideoRequest.max_spend). Same validation as the PATCH path
    # (routes/videos.py update_video, just below): must be a positive number
    # or omitted/None. A bad value here must never silently disable the cap
    # or brick every paid action, so reject it outright instead of coercing.
    max_spend = body.max_spend
    if max_spend is not None:
        try:
            max_spend = float(max_spend)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="max_spend must be a number or null")
        if max_spend <= 0:
            raise HTTPException(status_code=400, detail="max_spend must be greater than 0 (or omitted for no cap)")

    row = await fetch_one(
        """INSERT INTO videos (tenant_id, project_id, video_title, status, source, framework_angle, video_length_minutes, writer_guidance, visual_style, image_style_override, accent_color, aspect_ratio, video_resolution, skip_voice, skip_voice_source, pipeline_stages, reference_url, render_mode, render_style, style_preset_id, script_profile, production_style_id, production_style_version, production_style_snapshot, dialogue_audio, max_spend)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, COALESCE($11, '#00D4AA'), $12, $13, $14, $15, $16, $17, $18, $19, $20, $21, $22, $23, $24, $25, $26)
           RETURNING id, video_title, status, thumbnail_url, accent_color, total_cost, views, ctr,
                     created_at::text, updated_at::text""",
        tenant_id, project_id, title, initial_status, source_val, _strip_md(body.framework_angle),
        body.video_length_minutes, writer_guidance, body.visual_style, style_override, body.accent_color,
        body.aspect_ratio, body.video_resolution, skip_voice, skip_voice_source,
        json.dumps(plan) if plan is not None else None, reference_url,
        render_mode, render_style, style_preset_id, script_profile,
        production_style_id, production_style_version,
        json.dumps(production_style_snapshot) if production_style_snapshot else None,
        dialogue_audio, max_spend,
    )

    await increment_usage(tenant_id, "videos_created")

    # Seed the app-owned Drive workspace out of band. Missing credentials or a
    # Drive outage must never roll back an otherwise valid video creation.
    from drive_workspace import sync_video_workspace_fail_soft
    background_tasks.add_task(sync_video_workspace_fail_soft, str(row["id"]), tenant_id)

    # Silent channel-identity inheritance bug (found live 2026-07-27): a video
    # about "a dystopian world... bugs" came out narrated as PocoAPoco's
    # Ryan/Vanessa two-hander because these three fail-soft steps ran
    # unconditionally for every new video, regardless of what the creator
    # actually asked for. `apply_channel_identity is False` is the explicit
    # opt-out (DirectorHome's free-text entry box sets it) — None/True (every
    # other caller: New Video form, MCP, chat producer, queue, autopilot, the
    # clone/model path) keeps the original always-inherit behavior, since for
    # those callers inheriting the channel's identity IS the point.
    if body.apply_channel_identity is not False:
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

    # Kick off the modeling in the background: preserve_topic=True scopes it
    # to a style copy onto the creator's own topic (the chosen stages only);
    # preserve_topic=False (Model A Video — see is_modeled/title block above)
    # derives a brand-new idea from the reference instead.
    if is_modeled:
        from routes.pipeline import _set_task_status
        from routes.model_video import _run_modeling, TASK_TYPE
        _set_task_status(
            str(row["id"]), "running",
            "Copying the video's style…" if preserve_topic else "Queued for modeling…",
            tenant_id=tenant_id, task_type=TASK_TYPE,
        )
        background_tasks.add_task(
            _run_modeling, tenant_id, str(row["id"]), reference_youtube_id,
            reference_url, plan, preserve_topic,
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
                  accent_color, visual_style, image_style_override, style_preset_id, script_profile,
                  production_style_id, production_style_version, production_style_snapshot,
                  custom_film_plan_id, custom_film_plan_revision,
                  custom_film_plan_hash, custom_film_quote_inputs_hash,
                  custom_film_approval_hash, custom_film_approved_at::text,
                  image_model_override, video_model,
                  dialogue_audio, dialogue_mode, render_mode, render_style, skip_voice, pipeline_stages, research_skipped,
                  video_length_minutes, youtube_url, final_video_url, total_cost, max_spend, views, ctr, avg_retention,
                  impressions, likes, comments, performance_verdict,
                  source_views, source_channel, source_urls,
                  views_24h, views_48h, views_7d, views_30d,
                  ctr_12h, ctr_24h, ctr_48h, retention_48h,
                  early_signal, early_signal_evidence, early_signal_at::text,
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
    custom_film_plan = None
    if r.get("custom_film_plan_id"):
        from custom_film_contract import load_current_plan
        custom_film_plan = await load_current_plan(tenant_id, video_id)

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
        research_skipped=r.get("research_skipped") or False,
        image_style_override=r.get("image_style_override"),
        style_preset_id=r.get("style_preset_id"),
        script_profile=r.get("script_profile"),
        production_style_id=r.get("production_style_id"),
        production_style_version=r.get("production_style_version"),
        production_style_snapshot=_parse_json_field(r.get("production_style_snapshot")),
        custom_film_plan_id=(
            str(r["custom_film_plan_id"]) if r.get("custom_film_plan_id") else None
        ),
        custom_film_plan_revision=r.get("custom_film_plan_revision"),
        custom_film_plan_hash=r.get("custom_film_plan_hash"),
        custom_film_quote_inputs_hash=r.get("custom_film_quote_inputs_hash"),
        custom_film_approval_hash=r.get("custom_film_approval_hash"),
        custom_film_approved_at=r.get("custom_film_approved_at"),
        custom_film_plan=custom_film_plan,
        image_model_override=r.get("image_model_override"),
        video_model=r.get("video_model"),
        video_length_minutes=float(r["video_length_minutes"]) if r.get("video_length_minutes") else None,
        youtube_url=r.get("youtube_url"),
        final_video_url=r.get("final_video_url"),
        total_cost=float(r.get("total_cost") or 0),
        # Selected above but never passed — the app could never show a user
        # their own spend cap even though PATCH .../max_spend wrote it fine.
        max_spend=float(r["max_spend"]) if r.get("max_spend") is not None else None,
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
        early_signal=r.get("early_signal"),
        early_signal_evidence=_parse_json_field(r.get("early_signal_evidence")),
        early_signal_at=r.get("early_signal_at"),
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
        dialogue_mode=r.get("dialogue_mode"),
        render_mode=r.get("render_mode"),
        # Whether run_render will mix this video's sound effects into the
        # final output — the ONE source of truth (status_map.
        # render_path_plays_sfx) shared with routes/pipeline.py's sound
        # endpoints, actions.py's "sound" verb, and pipeline_executor.py's
        # auto-advance skip. The frontend reads this instead of re-deriving
        # the custom_film_plan_id/render_mode/dialogue_audio/dialogue_mode
        # branches in TypeScript.
        sound_effects_supported=render_path_plays_sfx(r),
        sound_effects_unsupported_reason=render_path_sfx_block_reason(r),
        # Channel-style routing guardrail (migration 089/C13b): surfaced in
        # C14 as the "Channel look" control (Animated / Realistic / Auto).
        render_style=r.get("render_style"),
        created_at=r.get("created_at"),
        updated_at=r.get("updated_at"),
    )


@router.patch("/{video_id}")
async def update_video(video_id: str, body: dict, tenant_id: str = Depends(get_tenant_id)):
    """Update arbitrary video fields (revision_notes, etc.)."""
    video = await fetch_one(
        "SELECT id, dialogue_mode, render_mode, skip_voice FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    allowed_fields = {"revision_notes", "video_title", "headline", "thumbnail_prompt", "thumbnail_style_override", "video_motion_system_prompt", "script_system_prompt", "thumbnail_system_prompt", "sound_system_prompt", "dialogue_audio", "aspect_ratio", "video_resolution", "skip_voice", "render_style", "script_profile", "max_spend", "style_preset_id"}
    # skip_voice records the guided flow's "skip the voiceover" choice — the
    # Scenes gate reads it (advancing status alone left the gate locked).
    if "skip_voice" in body and not isinstance(body["skip_voice"], bool):
        raise HTTPException(status_code=400, detail="skip_voice must be a boolean")
    # P5/migration 116: a skip_voice key arriving in the request body at all
    # is always an explicit creator action through this generic PATCH path
    # (GuidedNextStep's skip button sends {skip_voice: true} directly) —
    # stamp provenance 'manual' so dialogue_intelligence.tag_video_dialogue's
    # bidirectional auto-revert never touches it. Captured BEFORE the
    # grok_native auto-fill below (which also injects "skip_voice" into
    # body) so both paths are covered.
    stamp_skip_voice_manual = "skip_voice" in body
    # U3 — dialogue voice folds into Animate: a creator who explicitly picks
    # grok_native (Grok performs the line, ElevenLabs STS re-voices in the
    # pinned cast voice — carries_own_line) for a character-dialogue video is
    # opting OUT of the separate voice-over stage as surely as the tagging
    # hook's majority-dialogue detection does. Mirrors
    # dialogue_intelligence.tag_video_dialogue's guards: only flips
    # false->true (never overrides a caller who set skip_voice explicitly in
    # the same request, and never un-skips), and never for a static_docu
    # video (voice IS the narration there — not that a static video would
    # ever carry character_dialogue, but belt-and-suspenders). This is a
    # creator choice (grok_native), not the dialogue detector — 'manual' too.
    if (
        body.get("dialogue_audio") == "grok_native"
        and "skip_voice" not in body
        and not video.get("skip_voice")
        and (video.get("render_mode") or "") != "static_docu"
        and (video.get("dialogue_mode") or "") == "character_dialogue"
    ):
        body = dict(body)
        body["skip_voice"] = True
        stamp_skip_voice_manual = True
    # aspect_ratio flows into image/video gen + render — reject anything unexpected.
    if "aspect_ratio" in body and body["aspect_ratio"] not in {"16:9", "9:16", "1:1", "4:3", "3:4"}:
        raise HTTPException(status_code=400, detail="Invalid aspect_ratio")
    # video_resolution is passed to the clip generator — reject anything unexpected.
    if "video_resolution" in body and body["video_resolution"] not in {"480p", "720p"}:
        raise HTTPException(status_code=400, detail="Invalid video_resolution")
    # render_style (migration 089/C13b): the channel-style routing guardrail's
    # gate value. None/null explicitly CLEARS it back to "undeclared" (the
    # money-safe default — shared.model_router treats unset as "don't
    # upgrade tiers"), so null is a valid write here, not a no-op.
    if "render_style" in body and body["render_style"] not in {"animated", "realistic", None}:
        raise HTTPException(status_code=400, detail="Invalid render_style")
    # script_profile (C24, checklist §2.3): the ScriptVoiceTab's "Script
    # voice" selector writes through this same generic update path (the
    # spec's "existing video-update path"). Re-validate against the real
    # registry here too — a request built by hand (or a stale client) must
    # not silently store a bogus profile id.
    if "script_profile" in body:
        body["script_profile"] = _resolve_script_profile(body.get("script_profile"))
    # style_preset_id (checklist C47 — this generic update path previously only
    # accepted a style_preset_id at CREATE time; there was no way to set/clear
    # it afterward at all. Reuses create_video's own `_resolve_style_preset_id`
    # validator verbatim rather than a second catalog check, same posture as
    # render_style/script_profile just above.
    if "style_preset_id" in body:
        body["style_preset_id"] = await _resolve_style_preset_id(body.get("style_preset_id"))
    # max_spend (migration 103, checklist §3.3/C36): the optional per-video
    # budget ceiling the money gate consults. null CLEARS it (no cap — the
    # default), same "null is a valid write" pattern as render_style above.
    # Anything else must be a real non-negative number — a bad value here
    # would either silently disable the cap (if ignored) or brick every paid
    # action (if it somehow parsed as 0/negative), so reject it outright.
    if "max_spend" in body and body["max_spend"] is not None:
        try:
            parsed = float(body["max_spend"])
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="max_spend must be a number or null")
        if parsed <= 0:
            raise HTTPException(status_code=400, detail="max_spend must be greater than 0 (or null to remove the cap)")
        body["max_spend"] = parsed
    updates = []
    params = []
    idx = 1
    for key, val in body.items():
        if key in allowed_fields:
            updates.append(f"{safe_column(key)} = ${idx}")
            params.append(val)
            idx += 1
    # P5/migration 116: skip_voice_source is server-derived, never a
    # client-writable field (kept out of allowed_fields on purpose) — stamped
    # here whenever this request touched skip_voice through an explicit
    # creator action (see stamp_skip_voice_manual above).
    if stamp_skip_voice_manual:
        updates.append(f"{safe_column('skip_voice_source')} = ${idx}")
        params.append("manual")
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
        title=body.get("title"), description=body.get("description"), tags=tags,
        category_id=body.get("category_id"))


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
        "SELECT id, status, pipeline_stages, custom_film_plan_id, render_mode, "
        "dialogue_audio, dialogue_mode FROM videos WHERE id = $1 AND tenant_id = $2",
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

    # Reroute around any stage this video can't actually run — the creator's
    # pipeline_stages plan (as every other status write already honors via
    # PipelineExecutor._update_video_status/_enabled_stages) AND, since C-sfx,
    # a render path that can never play sound effects (status_map.
    # render_path_plays_sfx). This is the ONE raw `UPDATE videos SET status`
    # in the codebase that used to bypass that chokepoint entirely — the
    # human "Advance" button used by every production tab could park an
    # SFX-blocked video at ready_for_sound_design/effects even though the
    # executor-driven paths never would. Reusing PipelineExecutor's own
    # static helper (not a re-derived copy) keeps this in the SAME single
    # source of truth as every other reroute.
    from pipeline_executor import PipelineExecutor
    plan_stages = PipelineExecutor._enabled_stages(video)
    if plan_stages:
        next_status = resolve_planned_status(next_status, plan_stages)

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
        """SELECT id, video_id, scene, image_index, image_url, drive_image_url,
                  image_prompt,
                  status, shot_type, hero_shot, sentence_text, video_clip_url,
                  video_prompt, sound_prompt, sound_effect_url, sound_volume,
                  duration_seconds, extraction_flags, image_model,
                  routed_model, routing_reason, model_used, model_override,
                  camera_movement, camera_preset_id,
                  carries_own_line, clip_speech_start, clip_speech_end,
                  assigned_dialogue, generation_method, caption::text AS caption,
                  video_duration, assigned_video_duration, video_status,
                  created_at::text
           FROM assets WHERE video_id = $1 AND tenant_id = $2
             AND (generation_method IS NULL OR generation_method <> 'variant_candidate')
           ORDER BY scene, image_index""",
        video_id, tenant_id,
    )
    return rows


@router.get("/{video_id}/production-guide")
async def get_video_production_guide(video_id: str, tenant_id: str = Depends(get_tenant_id)):
    """Ordered stage checklist for this video (done/in_progress/not_started/
    skipped_by_format), concrete gaps, and a next_step recommendation — same
    query the get_production_guide MCP tool uses (routes/mcp.py's
    _call_get_production_guide), so the UI and the co-pilot never disagree."""
    guide = await production_guide.get_production_guide(tenant_id, video_id)
    if guide is None:
        raise HTTPException(status_code=404, detail="Video not found")
    return guide


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
                  generation_method, image_model, created_at::text
           FROM assets
           WHERE video_id = $1 AND tenant_id = $2 AND scene = $3 AND image_index = $4
             AND generation_method = 'variant_candidate'
           ORDER BY panel_position, created_at""",
        video_id, tenant_id, scene, index,
    )
    return rows


@router.get("/{video_id}/ledger", response_model=VideoLedgerResponse)
async def get_video_ledger(video_id: str, tenant_id: str = Depends(get_tenant_id)):
    """Actual-spend receipts for this video (checklist §0.3d / C10) — backs the
    cost chip's drawer and the copilot's "how much has this cost?" answer.
    Tenant-scoped read over generation_ledger, the ONLY write path into
    videos.total_cost (see generation_ledger.py). `total_cost` here is read
    straight off the videos row (already the SUM(actual_cost) rollup —
    generation_ledger.record_ledger_entry recomputes it on every write) so
    the chip and the drawer can never disagree on the headline number, even
    if a row were ever added/corrected out of band."""
    video = await fetch_one(
        "SELECT id, total_cost FROM videos WHERE id = $1 AND tenant_id = $2 AND deleted_at IS NULL",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    rows = await fetch_all(
        """SELECT stage, model, units, unit_cost, actual_cost, kie_task_id, created_at::text
           FROM generation_ledger
           WHERE video_id = $1 AND tenant_id = $2
           ORDER BY created_at""",
        video_id, tenant_id,
    )

    by_stage: dict[str, float] = {}
    for r in rows:
        stage = r.get("stage") or "other"
        by_stage[stage] = round(by_stage.get(stage, 0.0) + float(r.get("actual_cost") or 0), 2)

    return VideoLedgerResponse(
        video_id=video_id,
        total_cost=float(video.get("total_cost") or 0),
        by_stage=by_stage,
        rows=[
            LedgerRow(
                stage=r.get("stage") or "other",
                model=r.get("model"),
                units=float(r.get("units") or 0),
                unit_cost=float(r.get("unit_cost") or 0),
                actual_cost=float(r.get("actual_cost") or 0),
                kie_task_id=r.get("kie_task_id"),
                created_at=r.get("created_at"),
            )
            for r in rows
        ],
    )


@router.get("/{video_id}/script")
async def get_video_script(video_id: str, tenant_id: str = Depends(get_tenant_id)):
    """Get full script for a video."""
    rows = await fetch_all(
        """SELECT id, video_id, scene, scene_text, voice_over_url, voice_status,
                  script_status, sources, storyboard_on_off, tone,
                  storyboard_1_url, storyboard_2_url, storyboard_3_url,
                  storyboard_4_url, storyboard_5_url, scene_video_url,
                  storyboard_prompts, storyboard_beat_count, storyboard_status,
                  storyboard_errors, coverage_directive,
                  created_at::text, updated_at::text
           FROM scripts WHERE video_id = $1 AND tenant_id = $2
           ORDER BY scene NULLS FIRST, created_at""",
        video_id, tenant_id,
    )
    # Backfill scene numbers when null (Airtable imports don't always set them)
    for i, row in enumerate(rows):
        if row.get("scene") is None:
            row["scene"] = i + 1
        # storyboard_errors (migration 113) is JSONB — asyncpg hands it back
        # as raw JSON text, not a parsed dict (same trap _coerce_evidence
        # guards against in channel_patterns.py). Parse it here so the
        # frontend's ScriptScene.storyboard_errors gets a real object, not a
        # double-encoded string.
        se = row.get("storyboard_errors")
        if isinstance(se, str) and se.strip():
            try:
                row["storyboard_errors"] = json.loads(se)
            except (json.JSONDecodeError, ValueError):
                row["storyboard_errors"] = None
        elif not isinstance(se, dict):
            row["storyboard_errors"] = None
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


def _full_script_hash(text: str) -> str:
    """Same normalize-then-sha1 shape as scripts/coverage_to_app.py's
    _scene_text_hash (whitespace-collapsed before hashing, so a re-wrap or a
    stray space never counts as a "real" change) — applied to the FULL
    videos.script text rather than one scene. D7-2 (STORY-LAWS S6): this is
    what characters_hash/environments_hash pin video_characters/
    video_environments to, so a script rewrite can be detected later."""
    import hashlib
    return hashlib.sha1(" ".join((text or "").split()).encode()).hexdigest()


async def _flag_stale_cast_and_environments(video_id: str, tenant_id: str) -> None:
    """D7-2 (STORY-LAWS S6 — a real production video rendered characters from
    a script that didn't yet contain them): after ANY write to videos.script,
    compare its current hash against characters_hash/environments_hash — the
    hash of the script text design_characters / run_environments_design_step
    actually generated the current cast/environments FROM (stamped at
    generation time, see routes/characters.py::design_characters and
    routes/environments.py::run_environments_design_step). On a mismatch,
    flag every video_characters/video_environments row for this video
    status='stale' — NEVER delete; a wrong deletion re-triggers a real-money
    redraw. A family with no stamp yet (characters_hash/environments_hash
    still NULL — nothing generated, or generated before this migration) is
    left alone: nothing to compare against, nothing to flag.

    This is the ONE place the recompute-and-compare runs. Callers: this
    module's own sync_video_script (the D7-1/D7-1b choke point already
    shared by update_scene_text, rewrite_scene_text and chat.py's
    _apply_prompt_draft), the Drive pull-sync path below, and the two
    pipeline/Custom-Film inline-sync sites that write videos.script directly
    without going through sync_video_script (pipeline_executor.py's
    _save_machine_script_block, custom_film_production_runner.py's _script).

    Advisory-only, same contract as update_scene_text's S1/S3 re-check
    above: a failure here (unreachable DB, etc.) must never block the script
    write that triggered it."""
    try:
        row = await fetch_one(
            "SELECT script, characters_hash, environments_hash FROM videos "
            "WHERE id = $1 AND tenant_id = $2",
            video_id, tenant_id,
        )
        if not row:
            return
        current_hash = _full_script_hash(row.get("script") or "")
        if row.get("characters_hash") and row["characters_hash"] != current_hash:
            await execute(
                "UPDATE video_characters SET status = 'stale', updated_at = now() "
                "WHERE video_id = $1 AND tenant_id = $2 AND status != 'stale'",
                video_id, tenant_id,
            )
        if row.get("environments_hash") and row["environments_hash"] != current_hash:
            await execute(
                "UPDATE video_environments SET status = 'stale', updated_at = now() "
                "WHERE video_id = $1 AND tenant_id = $2 AND status != 'stale'",
                video_id, tenant_id,
            )
    except Exception:  # noqa: BLE001 — advisory only, must never block the write
        logger.warning("D7-2 staleness flag failed for video %s (advisory, ignored)",
                       video_id, exc_info=True)


async def sync_video_script(video_id: str, tenant_id: str) -> list:
    """Recompute videos.script from scripts.scene_text. videos.script is not
    just the display/export copy — it is the ONLY thing routes/characters.py
    `_extract_cast` reads when a video has no Story Bible yet (`_get_video`
    selects `videos.script`, `_extract_cast` reads `video.get("script")`).
    Call this after ANY write to scripts.scene_text, or a cast/character
    build kicked off right after can still be built from stale text.

    Extracted (D7-1b) from update_scene_text and rewrite_scene_text, which
    each carried this exact two-statement block inline (D7-1), once
    routes/chat.py's free-text script save (`_apply_prompt_draft`, the
    THIRD ungated `scripts.scene_text` writer D7-1's sweep found) needed the
    same fix — three verbatim copies crossed the line into "extract it."
    Returns the fetched rows so a caller that also needs them for a
    story-law re-check (rewrite_scene_text) doesn't have to re-query.

    D7-2: also the single choke point for the cast/environments staleness
    flag (_flag_stale_cast_and_environments) — every writer that funnels
    through here gets it for free."""
    sync_rows = await fetch_all(
        "SELECT scene, location, scene_text FROM scripts WHERE video_id = $1 AND tenant_id = $2 "
        "AND scene_text IS NOT NULL ORDER BY scene", video_id, tenant_id)
    await execute(
        "UPDATE videos SET script = $3, updated_at = now() WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id, "\n\n".join(r["scene_text"] for r in sync_rows))
    await _flag_stale_cast_and_environments(video_id, tenant_id)
    return sync_rows


@router.patch("/{video_id}/scenes/{scene}/text")
async def update_scene_text(
    video_id: str, scene: int, body: SceneTextUpdate, tenant_id: str = Depends(get_tenant_id)
):
    # D6-3 (S3 repair leg): a plain text edit must not silently revert the
    # scene's location. If the new text happens to supply a fresh LOCATION
    # header, adopt it (and strip it from the stored narration, same as
    # every generation path — it must never be spoken); otherwise the edit
    # carries NO location signal at all, so COALESCE($5, location) leaves
    # the existing column exactly as it was rather than blanking it.
    #
    # S7-A: same repair-leg treatment for ACTION:, its stage-direction
    # sibling. LOCATION: and ACTION: may coexist as the text's two leading
    # header lines in EITHER order (extract_scene_location/extract_scene_
    # action each tolerate the other one preceding them — see story_laws'
    # _extract_leading_header), so location is extracted first and action is
    # extracted from WHAT'S LEFT — this correctly strips both regardless of
    # which header the editor put first, and leaves the body untouched when
    # neither is present.
    import story_laws
    new_location, after_location_text = story_laws.extract_scene_location(body.text)
    new_action, stored_text = story_laws.extract_scene_action(after_location_text)
    result = await execute(
        "UPDATE scripts SET scene_text = $1, location = COALESCE($5, location), "
        "action = COALESCE($6, action), "
        "updated_at = now() "
        "WHERE video_id = $2 AND scene = $3 AND tenant_id = $4",
        stored_text, video_id, scene, tenant_id, new_location, new_action,
    )
    if not result or "UPDATE 0" in result:
        raise HTTPException(404, "Scene not found")

    # D7-1: keep videos.script in sync — it is not just the display/export
    # copy, it is the ONLY thing routes/characters.py `_extract_cast` reads
    # when a video has no Story Bible yet. Before this fix, a scene edit
    # here updated `scripts.scene_text` only — a cast regenerated right
    # after would still be built from the scene text as it was BEFORE the
    # edit. (D7-1b: extracted into sync_video_script, shared with
    # rewrite_scene_text below and routes/chat.py's script-save path — see
    # that function's docstring.)
    await sync_video_script(video_id, tenant_id)

    # D7-3: this scene's own text just changed, so its stored board plan
    # (coverage_directive) and its voice/images/clips are stale too — the
    # Drive pull-sync path below has always cleared these on a text change;
    # this manual edit endpoint must too, or its board plan silently keeps
    # reusing a directive planned from the pre-edit text. Advisory only,
    # same contract as the S1/S3 re-check right below — a failure here must
    # never fail the edit that triggered it.
    try:
        await _clear_scene_downstream(video_id, scene, tenant_id)
    except Exception:  # noqa: BLE001 — advisory only, must never block the edit
        logger.warning(
            "D7-3 downstream clear failed for video %s scene %s (advisory, ignored)",
            video_id, scene, exc_info=True,
        )

    # D6-3b: an edit that carries the OLD location forward (or adopts a new
    # one) can still put THIS scene's text out of step with S3 — e.g. the
    # location column didn't change but the rewritten prose now describes a
    # different place, or a fresh header was adopted that now clashes with
    # sibling scenes. Re-run the deterministic gate for the whole video and
    # surface it. Warn only, never block — an edit must always be allowed to
    # save; see story_laws.check_scene_location_law for the hard/warn split.
    warnings: list[str] = []
    s1_warnings: list[str] = []
    try:
        rows = await fetch_all(
            "SELECT scene, location, scene_text FROM scripts WHERE video_id = $1 "
            "AND tenant_id = $2 ORDER BY scene",
            video_id, tenant_id,
        )
        row_dicts = [dict(r) for r in (rows or [])]
        law_check = story_laws.check_scene_location_law(row_dicts)
        this_scene_issues = [
            v["detail"] for v in law_check["violations"] if v["scene"] == scene
        ] + [
            w["detail"] for w in law_check["warnings"] if w["scene"] == scene
        ]
        warnings = this_scene_issues

        # D6-4 (S1 repair leg): same re-check, same warn-only treatment —
        # an edit that changes this scene's text (or carries a changed
        # location forward) can introduce or fix an unnarrated location
        # change against its neighbour, so re-run S1 too. Separate response
        # key (story_law_s1_warnings) rather than merging into S3's, so an
        # existing caller reading story_law_s3_warnings sees no behavior
        # change.
        # An S1 warning concerns a PAIR of scenes (from_scene/to_scene) —
        # surface it if the edited scene is EITHER half, not just when it
        # equals "scene" (the destination), or an edit to the OUTGOING
        # scene of an unnarrated pair would silently show no warning at all.
        s1_check = story_laws.check_location_transit_law(row_dicts)
        s1_warnings = [
            w["detail"] for w in s1_check["warnings"]
            if scene in (w.get("from_scene"), w.get("to_scene"))
        ]
    except Exception:  # noqa: BLE001 — advisory only, must never block the edit
        pass

    return {
        "status": "updated", "scene": scene,
        "story_law_s3_warnings": warnings,
        "story_law_s1_warnings": s1_warnings,
    }


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
    # strict_folder: backend's shared app-owned Drive identity — see
    # google_client.py's DEFAULT_PARENT_FOLDER_ID docstring.
    GoogleClient(strict_folder=True).drive_service.files().update(
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

    if await _is_task_active(video_id, tenant_id):
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

    if await _is_task_active(video_id, tenant_id):
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
                json={"model": CLAUDE_MODELS["anthropic"]["smart"], "max_tokens": max_tokens,
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

    # D6-3 (S3 repair leg): this rewrite is a single-scene, single-paragraph
    # regeneration — its own contract already bans labels/markdown in the
    # output ("No markdown, labels, bullets, or citations", machine_contract
    # above), so it is never asked to (and must not) emit a LOCATION header.
    # The scene's location must therefore carry forward from BEFORE the
    # rewrite unchanged, never dropped — the same COALESCE(new, location)
    # shape update_scene_text uses, except here new_location is always None
    # (nothing above ever produces one), so this is simply "leave it alone",
    # made explicit rather than an accident of the SET clause omitting it.
    import story_laws
    new_location, new_text = story_laws.extract_scene_location(new_text)
    # Save the paragraph; clear this scene's voice so only it re-records.
    await execute(
        """UPDATE scripts SET scene_text = $4, location = COALESCE($5, location),
               voice_over_url = NULL, voice_duration_seconds = NULL, voice_status = NULL
           WHERE video_id = $1 AND tenant_id = $2 AND scene = $3""",
        video_id, tenant_id, scene, new_text, new_location)
    # Keep videos.script in sync (it is the display/export copy). D7-1b:
    # extracted into sync_video_script (shared with update_scene_text above
    # and routes/chat.py's script-save path) — it also returns the rows so
    # the S3/S1 re-check below can reuse them instead of re-querying.
    scenes_rows = await sync_video_script(video_id, tenant_id)

    # D7-3: the rewrite above already nulled this scene's voice inline (its
    # own UPDATE, right above) but never touched its images/clips or its
    # stored board plan — so a rewritten scene kept showing storyboard
    # frames drawn from the pre-rewrite paragraph. _clear_scene_downstream
    # covers all of it (voice is a harmless re-null); advisory only, same
    # contract as the S1/S3 re-check right below.
    try:
        await _clear_scene_downstream(video_id, scene, tenant_id)
    except Exception:  # noqa: BLE001 — advisory only, must never block the rewrite
        logger.warning(
            "D7-3 downstream clear failed for video %s scene %s (advisory, ignored)",
            video_id, scene, exc_info=True,
        )

    # D6-3b (S3 repair leg re-check): the rewritten paragraph could now
    # describe a different place than the carried-forward location, or
    # clash with a sibling scene's. Warn only, never block a regenerate.
    s3_warnings: list[str] = []
    s1_warnings: list[str] = []
    try:
        row_dicts = [dict(r) for r in (scenes_rows or [])]
        law_check = story_laws.check_scene_location_law(row_dicts)
        s3_warnings = [
            v["detail"] for v in law_check["violations"] if v["scene"] == scene
        ] + [
            w["detail"] for w in law_check["warnings"] if w["scene"] == scene
        ]

        # D6-4 (S1 repair leg re-check): same warn-only re-check as
        # update_scene_text above. An S1 warning concerns a PAIR of scenes,
        # so match on either from_scene or to_scene, not just "scene".
        s1_check = story_laws.check_location_transit_law(row_dicts)
        s1_warnings = [
            w["detail"] for w in s1_check["warnings"]
            if scene in (w.get("from_scene"), w.get("to_scene"))
        ]
    except Exception:  # noqa: BLE001 — advisory only, must never block the rewrite
        pass

    return {"scene": scene, "text": new_text, "word_count": _spoken_word_count(new_text),
            "story_law_s3_warnings": s3_warnings,
            "story_law_s1_warnings": s1_warnings}


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
            model=CLAUDE_MODELS["anthropic"]["smart"],
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
    """A text change makes that scene's voice/images/clips stale, and its
    stored board plan no longer describes what boards were drawn from. Mirror
    delete_clip's URL-nulling (proven safe) across voice + image + clip so the
    scene visibly needs regeneration instead of silently shipping old media —
    and null coverage_directive_hash alongside them (D7-3): the coverage gate
    (scripts/coverage_to_app.py:4404-4452) only reuses a scene's saved
    coverage_directive while that hash matches the scene's CURRENT text, so
    clearing it forces a scoped re-plan of JUST this scene next time boards
    run, without re-billing every other scene's plan. This never deletes a
    row and never touches coverage_directive's TEXT itself — only the hash
    pointer that gates its reuse — same flag/clear-never-delete contract as
    _flag_stale_cast_and_environments.

    Called from the Drive pull-sync path below AND (D7-3) from
    update_scene_text/rewrite_scene_text, so a manual edit invalidates the
    same things a Drive-pulled edit always has."""
    await execute(
        "UPDATE scripts SET voice_over_url = NULL, voice_status = NULL, "
        "voice_duration_seconds = NULL, coverage_directive_hash = NULL, "
        "updated_at = now() "
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
        # D7-2 (S6): this writes videos.script directly rather than going
        # through sync_video_script above, so it needs its own call to the
        # same staleness check.
        await _flag_stale_cast_and_environments(video_id, tenant_id)

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
