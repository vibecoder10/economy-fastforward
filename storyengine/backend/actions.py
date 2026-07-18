"""The shared action layer — one registry for every door (PARITY-PLAN Phase 1).

Everything that can DRIVE a video lives here: the verb registry (what an action
is, what it costs, what must exist first), the honest cost estimator, the compact
video summary they both read, and the two background-step factories (single
action, autobuild chain). Chat (routes/chat.py), the HTTP routes
(routes/pipeline.py), and the future agent brain all call THESE — no door keeps
its own copy of what the pipeline can do.

Extracted verbatim from routes/chat.py (the co-pilot section) so chat, buttons,
and the copilot stay behaviorally identical. Lazy-imports PipelineExecutor and
the routes.pipeline task-status helpers inside the step factories to avoid
circular imports (routes/pipeline.py imports this module at module level).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from fastapi import HTTPException

from database import execute, fetch_one
from status_map import is_at_or_past_stage

logger = logging.getLogger(__name__)

# Per-clip prices mirror the frontend's CLIP_COST_PER_MODEL (next-action.ts) so the
# co-pilot's "~$X" matches the page's Est. Cost. Pictures are $0.08 each.
CLIP_COST = {"grok-imagine": 0.10, "veo-3.1-fast": 0.30, "veo-3.1-quality": 1.25, "seedance-2-fast": 0.30}
PICTURE_COST = 0.08
# Flat per-run estimates for the other paid stages — named here (C08,
# checklist §0.3b) so generation_ledger writes in pipeline_executor.py reuse
# the SAME number the confirm card already quotes, instead of a second copy.
# These were inline literals in estimate_cost() below before C08; still rough
# (not per-scene/per-character-metered) — full single-sourcing is C09.
VOICE_COST_ESTIMATE = 0.30
SOUND_COST_ESTIMATE = 0.20
THUMBNAIL_COST = 0.10

# verb -> how to run it. `calls` = ordered (executor method, passes a scene= kwarg).
# `paid` => hold behind a confirm card in the dock. `needs` = the prerequisite that
# must already exist, or the action is refused politely. `edit` => the verb accepts
# a free-text change applied via apply_followup_edit before the re-run.
ACTIONS: dict[str, dict[str, Any]] = {
    "script":      {"calls": [("run_script", False)], "paid": True, "needs": None, "edit": True,
                    "doing": "writing the script", "label": "Write the script"},
    "characters":  {"calls": [("run_characters", False)], "paid": True, "needs": "scenes",
                    "doing": "designing the cast", "label": "Design the characters"},
    # Unified on the coverage path (GOAL v2 Phase 0): the dock now draws via coverage
    # (the live image generator), not the old 3x3 grid handlers. "storyboards" = the
    # cheap single-sheet preview; "images" = the real per-shot multi-angle pictures.
    "storyboards": {"calls": [("run_storyboard_sheet", True)], "paid": True,
                    "needs": "scenes", "doing": "drawing the storyboards", "label": "Generate storyboards"},
    "images":      {"calls": [("run_coverage_images", True)], "paid": True, "needs": "scenes", "edit": True,
                    "doing": "making the pictures", "label": "Generate the pictures"},
    "voice":       {"calls": [("run_voice", True)], "paid": True, "needs": "scenes",
                    "doing": "recording the voiceover", "label": "Generate the voiceover"},
    "animate":     {"calls": [("run_clip_generation", True)], "paid": True, "needs": "pictures",
                    "doing": "animating", "label": "Animate"},
    "sound":       {"calls": [("run_sound_prompts", False), ("run_sound_effects", False)], "paid": True,
                    "needs": "pictures", "doing": "designing the sound", "label": "Add sound"},
    "thumbnail":   {"calls": [("run_thumbnail", False)], "paid": True, "needs": None, "edit": True,
                    "doing": "redoing the thumbnail", "label": "Redo the thumbnail"},
    "render":      {"calls": [("run_render", False)], "paid": True, "needs": "clips",
                    "doing": "rendering the final video", "label": "Render the final video"},
    # --- Phase 2 parity verbs: everything a UI button can do, chat can do -----
    "research":    {"calls": [("run_research", False)], "paid": True, "needs": None,
                    "doing": "researching the topic", "label": "Run research"},
    "seo":         {"runner": "seo", "paid": True, "needs": "scenes",
                    "doing": "writing the YouTube SEO", "label": "Write the YouTube SEO"},
    # Free in dollars but it PUBLISHES (unlisted) — paid=True so it always confirms.
    "upload":      {"calls": [("run_upload", False)], "paid": True, "needs": "rendered",
                    "doing": "uploading to YouTube", "label": "Upload to YouTube (unlisted)"},
    "approve_cast": {"runner": "approve_cast", "paid": False, "needs": "cast",
                    "doing": "locking in the cast", "label": "Approve the cast"},
    "approve_environments": {"runner": "approve_environments", "paid": False, "needs": None,
                    "doing": "locking in the locations", "label": "Approve the locations"},
    "skip_environments": {"runner": "skip_environments", "paid": False, "needs": None,
                    "doing": "skipping locations", "label": "Skip locations"},
    "lock":        {"runner": "lock", "paid": False, "needs": None,
                    "doing": "locking the story", "label": "Lock the story"},
    "unlock":      {"runner": "unlock", "paid": False, "needs": None,
                    "doing": "unlocking the story", "label": "Unlock the story"},
    "drive_push":  {"runner": "drive_push", "paid": False, "needs": "scenes",
                    "doing": "sending the script to Google Drive", "label": "Send script to Drive"},
    "drive_sync":  {"runner": "drive_sync", "paid": False, "needs": None,
                    "doing": "pulling the script from Google Drive", "label": "Pull script from Drive"},
    "advance":     {"runner": "advance", "paid": False, "needs": None,
                    "doing": "moving to the next stage", "label": "Skip to the next stage"},
    # meta verb: build auto-runs the pipeline to the next checkpoint — to the pictures
    # if we're before them, else all the way to a finished video. NOT one step.
    "build":       {"calls": None, "paid": True, "needs": None,
                    "doing": "building your video", "label": "Build the video"},
}

# Plain-English reason an action can't run yet (gate keyed by `needs`).
NEEDS_REASON = {
    "scenes":   "the script hasn't been broken into scenes yet — I'd write the script first",
    "pictures": "there are no pictures to work from yet — I'd make the pictures first",
    "clips":    "nothing's been animated yet — I'd animate the scenes first",
    "cast":     "no characters have been designed yet — I'd design the cast first",
    "rendered": "the video hasn't been rendered yet — I'd render it first",
}

# Statuses BEFORE the pictures-review checkpoint — the auto-build keeps advancing
# while the video is in one of these; it stops the moment it reaches
# ready_for_images (pictures generated, awaiting review).
BUILD_TO_PICTURES = {
    "idea_logged", "approved", "ready_for_scripting", "ready_for_voice",
    "ready_for_image_prompts", "ready_for_storyboards",
    "ready_for_storyboard_images", "ready_for_storyboard_extraction",
}
DONE_STATUSES = {"rendered", "uploaded", "uploaded_draft", "done", "published"}
PICTURES_READY_MSG = ("Your pictures are ready — review them, then say “animate it” or “finish it” "
                      "and I'll take it the rest of the way.")

# stage -> (executor methods to re-run in order, the column free-text guidance is
# appended to). Columns are a fixed whitelist, safe to inline in SQL.
FOLLOWUP_STAGES: dict[str, dict[str, Any]] = {
    "script":    {"methods": ["run_script"],                "column": "writer_guidance",      "doing": "rewriting the script"},
    "images":    {"methods": ["run_prompts", "run_images"], "column": "image_style_override", "doing": "remaking the visuals"},
    "thumbnail": {"methods": ["run_thumbnail"],             "column": "thumbnail_prompt",     "doing": "redoing the thumbnail"},
    "render":    {"methods": ["run_render"],                "column": None,                   "doing": "re-rendering the video"},
}


async def apply_followup_edit(tenant_id, video_id, stage: str, edit: dict) -> None:
    """Write the requested change onto the video's stage-guidance column(s) before the
    re-run. Length is structured (video_length_minutes); everything else is appended as
    free-text guidance the stage already reads."""
    cfg = FOLLOWUP_STAGES.get(stage)
    if not cfg:
        return
    mins = edit.get("video_length_minutes")
    if stage == "script" and isinstance(mins, (int, float)) and int(mins) > 0:
        await execute(
            "UPDATE videos SET video_length_minutes = $1, updated_at = now() "
            "WHERE id = $2 AND tenant_id = $3",
            int(mins), video_id, tenant_id,
        )
    col = cfg.get("column")
    note = (edit.get("guidance_append") or "").strip()
    if col and note:
        # col comes from FOLLOWUP_STAGES (our own whitelist), so inlining is safe.
        await execute(
            f"UPDATE videos SET {col} = "
            f"trim(both E'\\n' from coalesce({col}, '') || E'\\n' || $1), updated_at = now() "
            f"WHERE id = $2 AND tenant_id = $3",
            note, video_id, tenant_id,
        )


async def video_summary(tenant_id, video_id: str) -> Optional[dict[str, Any]]:
    """Compact, current state of the video for the classifier, the gate, the cost
    estimate, and read answers — all from the video row + scripts + assets."""
    v = await fetch_one(
        "SELECT video_title, status, video_length_minutes, video_model, script_validation "
        "FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not v:
        return None
    sc = await fetch_one(
        "SELECT count(*) FILTER (WHERE scene_text IS NOT NULL) AS scenes, "
        "count(*) FILTER (WHERE storyboard_1_url IS NOT NULL) AS boards, "
        "count(*) FILTER (WHERE voice_over_url IS NOT NULL OR voice_status = 'Done') AS voiced, "
        "max(scene) AS max_scene "
        "FROM scripts WHERE video_id = $1 AND tenant_id = $2 AND scene IS NOT NULL",
        video_id, tenant_id,
    )
    a = await fetch_one(
        "SELECT count(*) FILTER (WHERE image_url IS NOT NULL) AS pics, "
        "count(*) FILTER (WHERE video_clip_url IS NOT NULL) AS clips "
        "FROM assets WHERE video_id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    c = await fetch_one(
        "SELECT count(*) AS n FROM video_characters WHERE video_id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    model = v.get("video_model") or "grok-imagine"
    pics, clips = int(a["pics"] or 0), int(a["clips"] or 0)
    cost = round(pics * PICTURE_COST + clips * CLIP_COST.get(model, 0.10), 2)
    return {
        "title": v.get("video_title") or "Untitled",
        "status": v.get("status") or "unknown",
        "length_min": v.get("video_length_minutes"),
        "model": model,
        "scenes": int(sc["scenes"] or 0),
        "boards": int(sc["boards"] or 0),
        "voiced": int(sc["voiced"] or 0),
        "max_scene": int(sc["max_scene"] or 0),
        "pics": pics,
        "clips": clips,
        "cast": int(c["n"] or 0),
        "spent": cost,
        "validation": str(v.get("script_validation") or "").strip()[:600],
    }


def blocked_reason(verb: str, summary: dict[str, Any]) -> Optional[str]:
    """Return a plain-English reason this action can't run yet, or None if it's allowed."""
    needs = (ACTIONS.get(verb) or {}).get("needs")
    if needs == "scenes" and summary["scenes"] == 0:
        return NEEDS_REASON["scenes"]
    if needs == "pictures" and summary["pics"] == 0:
        return NEEDS_REASON["pictures"]
    if needs == "clips" and summary["clips"] == 0:
        return NEEDS_REASON["clips"]
    if needs == "cast" and summary.get("cast", 0) == 0:
        return NEEDS_REASON["cast"]
    if needs == "rendered" and not is_at_or_past_stage(summary["status"], "rendered"):
        return NEEDS_REASON["rendered"]
    return None


async def estimate_cost(tenant_id, video_id, verb: str, scene: Optional[int], summary: dict[str, Any]) -> tuple[float, str]:
    """A rough but honest dollar estimate for a paid action, mirroring the page's
    counts. Per-scene actions price just that scene's pictures/clips."""
    model = summary["model"]
    clip = CLIP_COST.get(model, 0.10)
    if verb == "animate":
        n = summary["pics"]
        if scene is not None:
            row = await fetch_one(
                "SELECT count(*) AS n FROM assets WHERE video_id=$1 AND tenant_id=$2 AND scene=$3 AND image_url IS NOT NULL",
                video_id, tenant_id, scene,
            )
            n = int((row or {}).get("n") or 0) or 4  # fall back to a small guess
        cost = n * clip
    elif verb == "images":
        n = summary["pics"] or max(1, summary["scenes"]) * 6  # ~6 shots/scene when none exist yet
        if scene is not None:
            n = 6
        cost = n * PICTURE_COST
    elif verb == "storyboards":
        cost = (1 if scene is not None else max(1, summary["scenes"])) * PICTURE_COST
    elif verb == "voice":
        cost = VOICE_COST_ESTIMATE
    elif verb == "sound":
        cost = SOUND_COST_ESTIMATE
    elif verb == "thumbnail":
        cost = THUMBNAIL_COST
    elif verb == "script":
        cost = 0.02
    elif verb == "research":
        cost = 0.05
    elif verb == "seo":
        cost = 0.02
    elif verb == "characters":
        # ~$0.03 per 4-view character sheet; use the current cast count or a small default.
        row = await fetch_one(
            "SELECT count(*) AS n FROM video_characters WHERE video_id=$1 AND tenant_id=$2",
            video_id, tenant_id)
        cost = (int((row or {}).get("n") or 0) or 4) * 0.03
    elif verb == "render":
        cost = 0.0
    elif verb == "build":
        # Rough: pictures phase ~= scenes * ~6 shots * $0.08; finish phase ~= the
        # clips. Scenes unknown on a fresh video -> assume ~5.
        scenes = summary["scenes"] or 5
        if summary["status"] in BUILD_TO_PICTURES:
            cost = scenes * 6 * PICTURE_COST
        else:
            cost = (summary["pics"] or scenes * 6) * clip
    else:
        cost = 0.0
    text = "no extra cost" if cost <= 0 else f"~${cost:.2f}"
    return round(cost, 2), text


async def ensure_scriptable(tenant_id, video_id) -> None:
    """'Write the script' straight from an idea: skip past research the same
    plan-aware way autobuild does, so the script verb never trips the
    ready_for_scripting status gate on an idea_logged/approved/researching
    video (the creator saying 'no research, just write it' must simply work)."""
    from status_map import parse_stage_plan, resolve_planned_status
    row = await fetch_one(
        "SELECT status, pipeline_stages FROM videos WHERE id=$1 AND tenant_id=$2",
        video_id, tenant_id)
    prev = (row or {}).get("status") or ""
    if prev not in ("idea_logged", "approved", "researching"):
        return
    to_status = resolve_planned_status("ready_for_scripting", parse_stage_plan(row.get("pipeline_stages")))
    await execute("UPDATE videos SET status=$1, updated_at=now() WHERE id=$2 AND tenant_id=$3",
                  to_status, video_id, tenant_id)
    try:
        await execute(
            "INSERT INTO stage_transitions (video_id, tenant_id, from_status, to_status, triggered_by) "
            "VALUES ($1, $2, $3, $4, 'auto')",
            video_id, tenant_id, prev, to_status)
    except Exception:  # noqa: BLE001
        pass


def make_action_step(tenant_id, video_id: str, calls: list, *, scene: Optional[int] = None,
                     start_msg: str = "On it…"):
    """Run an action's executor methods in order, passing scene= to the ones that
    accept it. Same task-status channel as the rest so the page's trackers light
    up. Stops on the first error."""
    from pipeline_executor import PipelineExecutor
    from routes.pipeline import _clear_task_status, _set_task_status

    async def _run():
        _set_task_status(video_id, "running", start_msg, tenant_id=tenant_id)
        try:
            if any(name == "run_script" for name, _ in calls):
                try:
                    await ensure_scriptable(tenant_id, video_id)
                except Exception:  # noqa: BLE001
                    pass
            executor = PipelineExecutor(tenant_id)
            result: dict = {}
            for name, takes_scene in calls:
                method = getattr(executor, name, None)
                if method is None:
                    result = {"status": "failed", "error": f"Unknown stage '{name}'"}
                    break
                kwargs = {"scene": scene} if (takes_scene and scene is not None) else {}
                result = await method(video_id, **kwargs) or {}
                if result.get("error"):
                    break
            _set_task_status(video_id, result.get("status", "completed"),
                             result.get("error") or result.get("message"), tenant_id=tenant_id)
        except Exception as e:  # noqa: BLE001
            _set_task_status(video_id, "failed", str(e), tenant_id=tenant_id)
        finally:
            await asyncio.sleep(30)
            _clear_task_status(video_id, tenant_id)

    return _run


def make_autobuild_step(tenant_id, video_id: str, *, target: str = "pictures",
                        start_msg: str = "Building your video…"):
    """Chain the pipeline automatically instead of running one step. target='pictures'
    runs research -> script -> (voice) -> storyboards -> pictures and STOPS at the
    pictures-review checkpoint; target='finish' runs the rest (clips + render) to a
    finished video, auto-passing the review gates. Robust: research failure is
    non-fatal (skips to script), voice is best-effort (no key -> skipped), and the
    loop is hard-capped + stops on no-progress so it can never run away."""
    from pipeline_executor import PipelineExecutor
    from routes.pipeline import _clear_task_status, _set_task_status
    from status_map import get_next_status_supabase, parse_stage_plan, resolve_planned_status

    async def _advance(to_status: str):
        # Honor the video's reduced stage plan: a raw natural-next status here
        # would drag a reduced-plan video into a disabled stage (e.g. a static
        # documentary into sound/animate). Reroute to the next ENABLED stage.
        prow = await fetch_one(
            "SELECT pipeline_stages FROM videos WHERE id=$1 AND tenant_id=$2",
            video_id, tenant_id)
        plan = parse_stage_plan((prow or {}).get("pipeline_stages"))
        to_status = resolve_planned_status(to_status, plan)
        prev = await fetch_one(
            "SELECT status FROM videos WHERE id=$1 AND tenant_id=$2", video_id, tenant_id)
        await execute("UPDATE videos SET status=$1, updated_at=now() WHERE id=$2 AND tenant_id=$3",
                      to_status, video_id, tenant_id)
        # Log a real stage transition so the chat progress card's live SSE updates — a raw
        # status UPDATE alone left the card frozen on an old step while the build moved on.
        try:
            await execute(
                "INSERT INTO stage_transitions (video_id, tenant_id, from_status, to_status, triggered_by) "
                "VALUES ($1, $2, $3, $4, 'auto')",
                video_id, tenant_id, (prev or {}).get("status") or "", to_status)
        except Exception:  # noqa: BLE001
            pass

    async def _run():
        _set_task_status(video_id, "running", start_msg, tenant_id=tenant_id)
        try:
            ex = PipelineExecutor(tenant_id)
            # Build-to-pictures skips the voiceover; if we're now finishing, lay it down first
            # (the render needs an audio track). run_voice can nudge the status backwards, so
            # snapshot and restore it. Guarded on missing audio so we never double-charge.
            if target == "finish":
                try:
                    missing = await fetch_one(
                        "SELECT 1 AS x FROM scripts WHERE video_id=$1 AND tenant_id=$2 "
                        "AND voice_over_url IS NULL LIMIT 1", video_id, tenant_id)
                    if missing:
                        snap = await fetch_one(
                            "SELECT status FROM videos WHERE id=$1 AND tenant_id=$2", video_id, tenant_id)
                        _set_task_status(video_id, "running", "Recording the voiceover…", tenant_id=tenant_id)
                        await ex.run_voice(video_id)
                        if snap and snap.get("status"):
                            await _advance(snap["status"])
                except Exception:  # noqa: BLE001
                    pass
            last = None
            for _ in range(18):  # hard cap — the pipeline is ~14 stages deep
                video = await ex._get_video(video_id)
                if not video:
                    _set_task_status(video_id, "failed", "Video not found", tenant_id=tenant_id)
                    return
                status = video.get("status")
                if target == "pictures" and status not in BUILD_TO_PICTURES:
                    _set_task_status(video_id, "completed", PICTURES_READY_MSG, tenant_id=tenant_id)
                    return
                if target == "finish" and status in DONE_STATUSES:
                    _set_task_status(video_id, "completed", "Your video is rendered — take a look!", tenant_id=tenant_id)
                    return
                if status == last:  # no progress — never loop forever
                    _set_task_status(video_id, "completed", f"Paused at {status}.", tenant_id=tenant_id)
                    return
                last = status
                # Skip the optional research step — it's slow/flaky (web/YouTube blocks)
                # and the script writes fine from the topic. Go straight to the script;
                # the creator can run research on demand. This was the actual stall.
                # EXCEPTION: static documentaries (client channels built on exact
                # figures) MUST research first — their scripts are written from the
                # verified research payload, and the factual gate depends on it.
                if status in ("idea_logged", "approved"):
                    if (video.get("render_mode") or "") == "static_docu":
                        _set_task_status(video_id, "running",
                                         "Researching the topic (real web search)…",
                                         tenant_id=tenant_id)
                        r = await ex.run_research(video_id) or {}
                        if r.get("status") == "ready_for_scripting":
                            continue
                        # Research failed — a static doc without facts is worse
                        # than no doc; stop instead of writing from thin air.
                        _set_task_status(video_id, "failed",
                                         r.get("error") or "Research failed — can't verify facts for this format.",
                                         tenant_id=tenant_id)
                        return
                    # C06a: an EXPLICIT research request (workflow:"research", or any
                    # custom plan that names "research") must not be silently skipped
                    # by the default-skip below. parse_stage_plan returns None for
                    # "no plan" (the ordinary full pipeline) — that default case keeps
                    # skipping, byte-identical to before. Only a plan that actually
                    # NAMES "research" counts as explicit; a None plan is unrestricted,
                    # not "requested".
                    research_plan = parse_stage_plan(video.get("pipeline_stages"))
                    if research_plan is not None and "research" in research_plan:
                        _set_task_status(video_id, "running",
                                         "Researching the topic (real web search)…",
                                         tenant_id=tenant_id)
                        r = await ex.run_research(video_id) or {}
                        if r.get("status") == "ready_for_scripting":
                            continue
                        # The creator explicitly asked for research — don't fall
                        # through to a from-thin-air script on failure; that would
                        # silently drop the exact thing they asked for.
                        _set_task_status(video_id, "failed",
                                         r.get("error") or "Research failed.",
                                         tenant_id=tenant_id)
                        return
                    # Record the skip so the UI can be honest about it (P0.5 —
                    # users previously had no way to know their video wasn't
                    # researched). Cleared back to FALSE the moment research
                    # actually runs (pipeline_executor.run_research), whether
                    # via the transparency chip's one-tap enable or otherwise.
                    try:
                        await execute(
                            "UPDATE videos SET research_skipped = TRUE WHERE id=$1 AND tenant_id=$2",
                            video_id, tenant_id)
                    except Exception:  # noqa: BLE001 — the build must not fail on this
                        pass
                    await _advance("ready_for_scripting")
                    continue
                # IMAGE PHASE: draw the pictures via the COVERAGE flow — the same path the
                # Scenes-page "pictures" button uses (generate_coverage_for_video). Coverage
                # builds its own cast sheet from the script when no characters are locked
                # (chat auto-builds don't lock a cast), then saves real picture assets.
                # The status-map image stages now also route to coverage (run_coverage_stage,
                # GOAL v2 Phase 0); we call coverage directly here so the chat build controls
                # its own progress updates and stops at the pictures-review checkpoint.
                if status in ("ready_for_image_prompts", "ready_for_storyboards",
                              "ready_for_storyboard_images", "ready_for_storyboard_extraction"):
                    # Satisfy the storyboard gates (env skipped, characters approved) and
                    # write the Story Bible (continuity anchor for the shot directives).
                    await execute(
                        "UPDATE videos SET environments_approved_at = COALESCE(environments_approved_at, now()), "
                        "characters_approved_at = COALESCE(characters_approved_at, now()), "
                        "updated_at = now() WHERE id = $1 AND tenant_id = $2",
                        video_id, tenant_id)
                    # STATIC-DOCU videos take one archival image per segment
                    # (no cast, no story bible, no multi-angle coverage) — the
                    # image is the whole shot, held over the narration.
                    if (video.get("render_mode") or "") == "static_docu":
                        _set_task_status(video_id, "running", "Creating one image per segment…", tenant_id=tenant_id)

                        def _static_progress(m):
                            _set_task_status(video_id, "running", m, tenant_id=tenant_id)

                        from static_docu import generate_static_images_for_video
                        st = await generate_static_images_for_video(
                            video_id, tenant_id, progress=_static_progress) or {}
                        if st.get("status") == "completed":
                            await _advance("ready_for_images")
                            continue
                        _set_task_status(video_id, "failed", st.get("error") or "Couldn't create the images.", tenant_id=tenant_id)
                        return
                    try:
                        await ex.run_story_bible(video_id)
                    except Exception:  # noqa: BLE001
                        pass
                    _set_task_status(video_id, "running", "Drawing the storyboard pictures…", tenant_id=tenant_id)

                    def _cov_progress(m):
                        _set_task_status(video_id, "running", m, tenant_id=tenant_id)

                    from scripts.coverage_to_app import generate_coverage_for_video
                    cov = await generate_coverage_for_video(video_id, tenant_id, progress=_cov_progress) or {}
                    if cov.get("status") == "completed":
                        await _advance("ready_for_images")
                        continue  # next loop: ready_for_images is the stop point
                    _set_task_status(video_id, "failed", cov.get("error") or "Couldn't draw the pictures.", tenant_id=tenant_id)
                    return
                _set_task_status(video_id, "running", "Working on it…", tenant_id=tenant_id)
                result = await ex.run_next_step(video_id) or {}
                rs = result.get("status")
                if rs == "needs_approval":
                    if status == "ready_for_voice":
                        # Voice isn't needed to review the pictures and it's the slowest paid
                        # step, so build-to-pictures skips it and advances. The finish flow lays
                        # the voiceover down before the render (see the finish guard in _run).
                        if target != "pictures":
                            try:
                                await ex.run_voice(video_id)  # best-effort; no voice key -> skip
                            except Exception:  # noqa: BLE001
                                pass
                        nxt = get_next_status_supabase(status)
                        if nxt:
                            await _advance(nxt)
                        continue
                    if target == "finish" and status in ("ready_for_images", "ready_for_thumbnail"):
                        # A "finished" video includes its thumbnail — generate it
                        # before passing the gate (previously the gate was passed
                        # without ever running the thumbnail bot). Best-effort:
                        # a thumbnail failure never blocks the render.
                        if status == "ready_for_thumbnail" and not (video.get("thumbnail_url") or "").strip():
                            _set_task_status(video_id, "running", "Designing the thumbnail…", tenant_id=tenant_id)
                            try:
                                await ex.run_thumbnail(video_id)
                            except Exception:  # noqa: BLE001
                                pass
                        nxt = get_next_status_supabase(status)  # already reviewed -> pass the gate
                        if nxt:
                            await _advance(nxt)
                        continue
                    msg = PICTURES_READY_MSG if status == "ready_for_images" else (result.get("message") or "Paused for your review.")
                    _set_task_status(video_id, "completed", msg, tenant_id=tenant_id)
                    return
                if rs == "failed":
                    if status in ("idea_logged", "approved"):  # research is optional — keep going
                        await _advance("ready_for_scripting")
                        continue
                    _set_task_status(video_id, "failed", result.get("error") or "A step failed.", tenant_id=tenant_id)
                    return
                if rs == "idle":
                    _set_task_status(video_id, "completed", f"Reached {status}.", tenant_id=tenant_id)
                    return
                # completed — the handler advanced the status; loop continues.
            _set_task_status(video_id, "completed", "Build paused — say “keep going” to continue.", tenant_id=tenant_id)
        except Exception as e:  # noqa: BLE001
            _set_task_status(video_id, "failed", str(e), tenant_id=tenant_id)
        finally:
            await asyncio.sleep(20)
            _clear_task_status(video_id, tenant_id)

    return _run


# --- Phase 2 runners ----------------------------------------------------------
#
# Verbs that aren't PipelineExecutor methods run through these instead: each
# reuses the SAME route handler (or helper) the UI button calls, catches its
# HTTPException, and returns the chat-facing line. Signature is uniform:
# (tenant_id, video_id, background_tasks, pending) -> str.

async def _runner_seo(tenant_id, video_id, background_tasks, pending) -> str:
    from routes.pipeline import _clear_task_status, _set_task_status

    async def _run():
        _set_task_status(video_id, "running", "Writing the YouTube SEO…", tenant_id=tenant_id)
        try:
            from youtube_publish import generate_and_store_seo
            result = await generate_and_store_seo(video_id, tenant_id) or {}
            if result.get("error"):
                _set_task_status(video_id, "failed", result["error"], tenant_id=tenant_id)
            else:
                _set_task_status(video_id, "completed", "SEO written — it's on the Upload tab.", tenant_id=tenant_id)
        except Exception as e:  # noqa: BLE001
            _set_task_status(video_id, "failed", str(e), tenant_id=tenant_id)
        finally:
            await asyncio.sleep(20)
            _clear_task_status(video_id, tenant_id)

    background_tasks.add_task(_run)
    return ("On it — writing the YouTube title, description, and tags from the video's own "
            "content. They'll be on the Upload tab in a minute.")


async def _runner_approve_cast(tenant_id, video_id, background_tasks, pending) -> str:
    from routes.characters import approve_cast
    try:
        await approve_cast(video_id, background_tasks, tenant_id=tenant_id)
    except HTTPException as e:
        return f"I can't approve the cast yet — {e.detail}"
    return ("On it — locking in the cast. I'm rewriting each character's description from "
            "their approved portrait so the pictures stay on-model; storyboards unlock when it's done.")


async def _runner_approve_environments(tenant_id, video_id, background_tasks, pending) -> str:
    from routes.environments import approve_environments
    try:
        await approve_environments(video_id, background_tasks, tenant_id=tenant_id)
    except HTTPException as e:
        return f"I can't approve the locations yet — {e.detail}"
    return "On it — locking in the locations. Storyboards unlock when it's done."


async def _runner_skip_environments(tenant_id, video_id, background_tasks, pending) -> str:
    from routes.environments import skip_environments
    try:
        await skip_environments(video_id, tenant_id=tenant_id)
    except HTTPException as e:
        return f"Couldn't skip the locations — {e.detail}"
    return ("Done — marked this video as having no distinct locations, so storyboards are "
            "unlocked. Designing environments later re-opens the approval.")


async def _runner_lock(tenant_id, video_id, background_tasks, pending) -> str:
    from routes.videos import lock_story
    try:
        await lock_story(video_id, tenant_id=tenant_id)
    except HTTPException as e:
        return f"I can't lock the story yet — {e.detail}"
    return "Story locked — the boards are frozen before image spend. Say “unlock the story” to keep iterating."


async def _runner_unlock(tenant_id, video_id, background_tasks, pending) -> str:
    from routes.videos import unlock_story
    try:
        await unlock_story(video_id, tenant_id=tenant_id)
    except HTTPException as e:
        return f"Couldn't unlock the story — {e.detail}"
    return "Story unlocked — edit away. Lock it again before generating pictures."


async def _runner_drive_push(tenant_id, video_id, background_tasks, pending) -> str:
    from routes.videos import push_script_to_drive
    try:
        res = await push_script_to_drive(video_id, tenant_id=tenant_id) or {}
    except HTTPException as e:
        return f"Couldn't send the script to Drive — {e.detail}"
    url = (res.get("doc_url") or "").strip()
    tail = f" It's here: {url}" if url else ""
    return ("Done — the script is a Google Doc in your Drive now." + tail +
            " Edit it there, then say “pull the script from Drive” and I'll bring the changes back.")


async def _runner_drive_sync(tenant_id, video_id, background_tasks, pending) -> str:
    from routes.videos import sync_script_from_drive
    try:
        res = await sync_script_from_drive(video_id, force=False, tenant_id=tenant_id) or {}
    except HTTPException as e:
        return f"Couldn't pull from Drive — {e.detail}"
    if res.get("conflict"):
        return ("Careful — the script changed BOTH here and in the Doc since the last sync. "
                "Pull from the Script tab (it asks before overwriting) or tell me which side should win.")
    if res.get("changed"):
        n = len(res.get("scenes_changed") or [])
        return (f"Pulled your Drive edits — {n} scene{'s' if n != 1 else ''} updated. "
                "Those scenes' voice and pictures were reset so they regenerate to match.")
    return res.get("message") or "Your script already matches the Drive Doc — nothing to pull."


async def _runner_advance(tenant_id, video_id, background_tasks, pending) -> str:
    from routes.videos import advance_video
    try:
        res = await advance_video(video_id, tenant_id=tenant_id) or {}
    except HTTPException as e:
        return f"Couldn't skip ahead — {e.detail}"
    ns = str(res.get("status") or "").replace("_", " ")
    return (f"Done — skipped ahead{f' to {ns}' if ns else ''}. "
            "Say “build it” anytime and I'll take it from here.")


RUNNERS = {
    "advance": _runner_advance,
    "seo": _runner_seo,
    "approve_cast": _runner_approve_cast,
    "approve_environments": _runner_approve_environments,
    "skip_environments": _runner_skip_environments,
    "lock": _runner_lock,
    "unlock": _runner_unlock,
    "drive_push": _runner_drive_push,
    "drive_sync": _runner_drive_sync,
}
