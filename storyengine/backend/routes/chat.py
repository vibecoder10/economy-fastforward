"""Chat-first creative producer — the conversational intake layer.

A guided conversation (the Step 1-8 flow): the creator describes a video, Claude
(the producer, see producer_prompt.py) asks only what's missing, offers selector
cards, proposes a production plan, and on approval CREATES the video and kicks off
the pipeline. Follow-up messages after creation drive that video's pipeline.

This module owns conversation state + the spec->video mapping + the kickoff. It
REUSES create_video (routes/videos.py) and PipelineExecutor.run_next_step — it does
not reinvent video creation or stage logic. Tenant isolation is manual: every query
carries `WHERE tenant_id = $1` (the pool sets no app.tenant_id GUC).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from auth import get_tenant_id
from database import execute, fetch_all, fetch_one
from models import CreateVideoRequest
from producer_prompt import build_system_prompt, call_producer
from vault import get_secret

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])

# Workflow card value -> raw pipeline_stages handed to create_video, which runs
# normalize_stage_plan (status_map.py:283) and pulls in prerequisites. None = the
# full pipeline (stored as NULL — the historical default).
WORKFLOW_STAGES: dict[str, Optional[list[str]]] = {
    "full": None,
    "research": ["research"],
    "script": ["script"],
    "script_assets": ["script", "images"],
    # "custom" -> spec.custom_stages
}

_GREETING = (
    "Tell me about the video you want to make — one sentence is plenty. "
    "For example: “a video about a dragon who finds a lonely owner, becomes "
    "his best friend, and they go on an adventure.”"
)

# The length slider's floor (matches the frontend: 5s..30min in 5s steps).
LENGTH_MIN_SECONDS = 5


def _format_runtime(secs: int) -> str:
    if secs < 60:
        return f"{secs} seconds"
    m, s = divmod(secs, 60)
    return f"{m} min" if s == 0 else f"{m} min {s} sec"


# --- request / response -----------------------------------------------------

class ChatTurnRequest(BaseModel):
    conversation_id: Optional[str] = None
    message: Optional[str] = None
    selections: Optional[dict[str, Any]] = None
    approve: bool = False
    start_onboarding: bool = False  # launch the "Start Here" setup flow
    # The in-pipeline chat dock sends the video it's scoped to on every turn. Its
    # presence means "this is the co-pilot dock" — find-or-create one conversation
    # per video AND hold paid/destructive actions behind a confirm card.
    video_id: Optional[str] = None
    # What the creator is looking at in the dock, so "this image" / "image 1"
    # resolves without naming the scene: {"scene": int, "index": int, "tab": str}.
    ui_context: Optional[dict[str, Any]] = None


class ChatTurnResponse(BaseModel):
    conversation_id: str
    assistant_text: str
    cards: Optional[list[dict[str, Any]]] = None
    plan: Optional[dict[str, Any]] = None
    ready_to_create: bool = False
    video_id: Optional[str] = None
    phase: str = "asking"  # asking | plan | created


# --- json/jsonb helpers (asyncpg may hand JSONB back as str or parsed) -------

def _as_list(val: Any) -> list:
    if val is None:
        return []
    if isinstance(val, str):
        try:
            return json.loads(val)
        except (json.JSONDecodeError, ValueError):
            return []
    return val if isinstance(val, list) else []


def _as_dict(val: Any) -> dict:
    if val is None:
        return {}
    if isinstance(val, str):
        try:
            return json.loads(val)
        except (json.JSONDecodeError, ValueError):
            return {}
    return val if isinstance(val, dict) else {}


def _assistant_turn(data: dict[str, Any]) -> dict[str, str]:
    """A transcript entry for an assistant turn — store the raw JSON so the model
    sees its own prior cards/plan on replay."""
    return {"role": "assistant", "content": json.dumps(data)}


def _selections_to_text(selections: dict[str, Any]) -> str:
    parts = []
    for k, v in selections.items():
        if k == "length":  # the slider sends seconds — show it as a runtime so the producer reasons in real time
            try:
                parts.append(f"length: ~{_format_runtime(max(LENGTH_MIN_SECONDS, int(float(v))))}")
                continue
            except (TypeError, ValueError):
                pass
        parts.append(f"{k}: {v}")
    return "My choices — " + ", ".join(parts)


def _stamp_length_default(data: dict[str, Any]) -> None:
    """Pre-set the length slider to the producer's recommended length so it opens on the
    director's suggestion (in seconds), not the generic 1-minute floor. Works in both the
    asking phase (the producer puts recommended_minutes on the length card) and the plan
    phase (falls back to the plan spec's video_length_minutes)."""
    cards = data.get("cards")
    if not isinstance(cards, list):
        return
    plan = data.get("plan")
    spec = plan.get("spec") if isinstance(plan, dict) else None
    spec_min = None
    if isinstance(spec, dict):
        try:
            spec_min = float(spec.get("video_length_minutes") or 0) or None
        except (TypeError, ValueError):
            spec_min = None
    for c in cards:
        if not (isinstance(c, dict) and (c.get("id") == "length" or c.get("type") == "slider")):
            continue
        mins = None
        try:
            mins = float(c.get("recommended_minutes")) if c.get("recommended_minutes") is not None else None
        except (TypeError, ValueError):
            mins = None
        mins = mins or spec_min
        if not mins:
            continue
        secs = max(LENGTH_MIN_SECONDS, int(round(mins * 60)))
        if secs > 0:
            c["recommended_seconds"] = secs


# --- conversation persistence (tenant-scoped) -------------------------------

async def _load_conversation(conversation_id: str, tenant_id) -> Optional[dict]:
    return await fetch_one(
        """SELECT id, project_id, video_id, transcript, state, phase
             FROM chat_conversations WHERE id = $1 AND tenant_id = $2""",
        conversation_id, tenant_id,
    )


async def _create_conversation(tenant_id) -> dict:
    return await fetch_one(
        """INSERT INTO chat_conversations (tenant_id)
           VALUES ($1)
           RETURNING id, project_id, video_id, transcript, state, phase""",
        tenant_id,
    )


async def _persist(conversation_id, tenant_id, transcript, state, phase, video_id=None) -> None:
    await execute(
        """UPDATE chat_conversations
              SET transcript = $1, state = $2, phase = $3,
                  video_id = COALESCE($4, video_id), updated_at = now()
            WHERE id = $5 AND tenant_id = $6""",
        json.dumps(transcript), json.dumps(state), phase, video_id,
        conversation_id, tenant_id,
    )


# --- pipeline kickoff: chain the build (reuses the task-status channel) ------

# Statuses BEFORE the pictures-review checkpoint — the auto-build keeps advancing
# while the video is in one of these; it stops the moment it reaches
# ready_for_images (pictures generated, awaiting review).
_BUILD_TO_PICTURES = {
    "idea_logged", "approved", "ready_for_scripting", "ready_for_voice",
    "ready_for_image_prompts", "ready_for_storyboards",
    "ready_for_storyboard_images", "ready_for_storyboard_extraction",
}
_DONE_STATUSES = {"rendered", "uploaded", "uploaded_draft", "done", "published"}
_PICTURES_READY_MSG = ("Your pictures are ready — review them, then say “animate it” or “finish it” "
                       "and I'll take it the rest of the way.")


def _make_autobuild_step(tenant_id, video_id: str, *, target: str = "pictures",
                         start_msg: str = "Building your video…"):
    """Chain the pipeline automatically instead of running one step. target='pictures'
    runs research -> script -> (voice) -> storyboards -> pictures and STOPS at the
    pictures-review checkpoint; target='finish' runs the rest (clips + render) to a
    finished video, auto-passing the review gates. Robust: research failure is
    non-fatal (skips to script), voice is best-effort (no key -> skipped), and the
    loop is hard-capped + stops on no-progress so it can never run away."""
    from pipeline_executor import PipelineExecutor
    from routes.pipeline import _clear_task_status, _set_task_status
    from status_map import get_next_status_supabase

    async def _advance(to_status: str):
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
                if target == "pictures" and status not in _BUILD_TO_PICTURES:
                    _set_task_status(video_id, "completed", _PICTURES_READY_MSG, tenant_id=tenant_id)
                    return
                if target == "finish" and status in _DONE_STATUSES:
                    _set_task_status(video_id, "completed", "Your video is rendered — take a look!", tenant_id=tenant_id)
                    return
                if status == last:  # no progress — never loop forever
                    _set_task_status(video_id, "completed", f"Paused at {status}.", tenant_id=tenant_id)
                    return
                last = status
                # Skip the optional research step — it's slow/flaky (web/YouTube blocks)
                # and the script writes fine from the topic. Go straight to the script;
                # the creator can run research on demand. This was the actual stall.
                if status in ("idea_logged", "approved"):
                    await _advance("ready_for_scripting")
                    continue
                # IMAGE PHASE: draw the pictures via the COVERAGE flow — the same path the
                # Scenes-page "pictures" button uses (generate_coverage_for_video). Coverage
                # builds its own cast sheet from the script when no characters are locked
                # (chat auto-builds don't lock a cast), then saves real picture assets.
                # The old status-map storyboard handlers no-op now, so we call coverage
                # directly, then stop at the pictures-review checkpoint.
                if status in ("ready_for_image_prompts", "ready_for_storyboards",
                              "ready_for_storyboard_images", "ready_for_storyboard_extraction"):
                    # Satisfy the storyboard gates (env skipped, characters approved) and
                    # write the Story Bible (continuity anchor for the shot directives).
                    await execute(
                        "UPDATE videos SET environments_approved_at = COALESCE(environments_approved_at, now()), "
                        "characters_approved_at = COALESCE(characters_approved_at, now()), "
                        "updated_at = now() WHERE id = $1 AND tenant_id = $2",
                        video_id, tenant_id)
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
                        nxt = get_next_status_supabase(status)  # already reviewed -> pass the gate
                        if nxt:
                            await _advance(nxt)
                        continue
                    msg = _PICTURES_READY_MSG if status == "ready_for_images" else (result.get("message") or "Paused for your review.")
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


# --- spec -> create-video mapping -------------------------------------------

def _spec_to_create_request(spec: dict[str, Any]) -> CreateVideoRequest:
    """Map the producer's plan.spec onto CreateVideoRequest. The stage plan is
    DERIVED from the workflow card here, never trusted from free text — create_video
    then normalizes it (prereqs)."""
    workflow = (spec.get("workflow") or "full").strip()
    if workflow == "custom":
        stages = spec.get("custom_stages") or None
    else:
        stages = WORKFLOW_STAGES.get(workflow, None)

    try:
        length = int(spec.get("video_length_minutes") or 10)
    except (TypeError, ValueError):
        length = 10
    length = max(1, length)

    aspect = spec.get("aspect_ratio")
    if aspect not in ("16:9", "9:16"):
        aspect = "16:9"

    # Resolve the chosen style preset (id -> the canonical LOOK sentence the
    # generator front-loads). Falls back to a free-text look if the creator
    # described their own style instead of picking a preset.
    from producer_prompt import VISUAL_PRESETS
    preset_id = (spec.get("visual_style") or "").strip()
    preset = VISUAL_PRESETS.get(preset_id)
    if preset:
        visual_style = preset_id
        visual_style_label = preset["label"]
        image_style_override = preset["look"]
    else:
        visual_style = None
        visual_style_label = spec.get("visual_style_label")
        image_style_override = spec.get("image_style_override")

    return CreateVideoRequest(
        title=(spec.get("title") or "Untitled video").strip(),
        framework_angle=spec.get("framework_angle"),
        writer_guidance=spec.get("writer_guidance"),
        video_length_minutes=length,
        visual_style=visual_style,
        image_style_override=image_style_override,
        visual_style_label=visual_style_label,
        lock_in_identity=bool(spec.get("lock_in_identity", False)),
        aspect_ratio=aspect,
        pipeline_stages=stages,
    )


# --- branches ----------------------------------------------------------------

async def _handle_approve(spec, conversation_id, tenant_id, transcript, state, background_tasks):
    from routes.videos import create_video

    # The creator's actual card picks are authoritative over the LLM's spec.
    selections = state.get("selections") or {}
    if selections.get("style"):
        spec = {**spec, "visual_style": selections["style"]}
    # Length slider sends SECONDS (5s..1800s). The pipeline length is int minutes,
    # so round (min 1) and keep the exact target in writer_guidance so short
    # videos aren't silently treated as a full minute.
    if selections.get("length"):
        try:
            secs = max(LENGTH_MIN_SECONDS, int(float(selections["length"])))
            spec = {**spec, "video_length_minutes": max(1, round(secs / 60))}
            wg = (spec.get("writer_guidance") or "").strip()
            spec["writer_guidance"] = f"{wg}\nTarget runtime: ~{_format_runtime(secs)} ({secs}s total).".strip()
        except (TypeError, ValueError):
            pass

    req = _spec_to_create_request(spec)
    try:
        summary = await create_video(body=req, background_tasks=background_tasks, tenant_id=tenant_id)
    except HTTPException as e:
        # Plan limit (402) or bad input — return a friendly turn, never a raw error.
        msg = (
            "Looks like you're out of video credits on your plan. Upgrade and I'll get right on it."
            if e.status_code == 402
            else (e.detail if isinstance(e.detail, str) else "I couldn't start that one — mind trying again?")
        )
        transcript.append(_assistant_turn({"assistant_text": msg, "phase": "plan"}))
        await _persist(conversation_id, tenant_id, transcript, state, "plan")
        return ChatTurnResponse(
            conversation_id=conversation_id, assistant_text=msg,
            ready_to_create=True, phase="plan",
        )

    video_id = summary.id
    # Auto-build the whole thing up to the pictures (research -> script -> pictures),
    # then it pauses for review — not a single step.
    background_tasks.add_task(_make_autobuild_step(
        tenant_id, video_id, target="pictures",
        start_msg=f"Building “{spec.get('title') or 'your video'}” — research, script, then the pictures…"))
    title = spec.get("title") or "your video"
    assistant_text = (
        f"Love it. I'm building “{title}” now — I'll research it, write the script, and generate the "
        "pictures, then pause so you can review them. Follow along right here."
    )
    transcript.append(_assistant_turn({"assistant_text": assistant_text, "phase": "created"}))
    await _persist(conversation_id, tenant_id, transcript, state, "created", video_id=video_id)
    return ChatTurnResponse(
        conversation_id=conversation_id, assistant_text=assistant_text,
        video_id=video_id, phase="created",
    )


# --- follow-up edits (Phase 5): a message after the video exists -------------
#
# The creator iterates in plain English ("make it shorter", "redo the thumbnail",
# "make the thumbnail more aggressive"). One Claude call classifies the request into a
# target stage + the change to apply; we write that change onto the stage's guidance
# column and re-run just that stage, reporting back in plain English. Reuses the proven
# direct-Anthropic JSON call (_claude_json) + the tenant's Vault key. Unclear requests
# get a clarifying ask; "keep going" advances the pipeline (the old behavior).

# stage -> (executor methods to re-run in order, the column free-text guidance is
# appended to). Columns are a fixed whitelist, safe to inline in SQL.
FOLLOWUP_STAGES: dict[str, dict[str, Any]] = {
    "script":    {"methods": ["run_script"],                "column": "writer_guidance",      "doing": "rewriting the script"},
    "images":    {"methods": ["run_prompts", "run_images"], "column": "image_style_override", "doing": "remaking the visuals"},
    "thumbnail": {"methods": ["run_thumbnail"],             "column": "thumbnail_prompt",     "doing": "redoing the thumbnail"},
    "render":    {"methods": ["run_render"],                "column": None,                   "doing": "re-rendering the video"},
}


async def _apply_followup_edit(tenant_id, video_id, stage: str, edit: dict) -> None:
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


# --- co-pilot (the in-pipeline chat dock) -----------------------------------
#
# A conversation bound to a video can RUN the pipeline by voice. One classifier
# call maps the message + a compact state summary onto a READ (answer a question,
# free) or an ACTION (one pipeline verb, optional scene). Anything that spends
# money or overwrites work is held behind a one-tap confirm card (pending_action
# in the conversation state); reads run immediately. Reuses PipelineExecutor + the
# task-status channel so the pipeline page's existing live trackers reflect work.
# Supersedes _handle_followup (it folds in FOLLOWUP_STAGES via _apply_followup_edit
# for the edit-style verbs). The confirm gate only applies to the DOCK (a request
# that carries video_id); the home CreatedCard follow-up keeps its immediate runs.

# Per-clip prices mirror the frontend's CLIP_COST_PER_MODEL (next-action.ts) so the
# co-pilot's "~$X" matches the page's Est. Cost. Pictures are $0.08 each.
_CLIP_COST = {"grok-imagine": 0.10, "veo-3.1-fast": 0.30, "veo-3.1-quality": 1.25, "seedance-2-fast": 0.30}
_PICTURE_COST = 0.08

# verb -> how to run it. `calls` = ordered (executor method, passes a scene= kwarg).
# `paid` => hold behind a confirm card in the dock. `needs` = the prerequisite that
# must already exist, or the action is refused politely. `edit` => the verb accepts
# a free-text change applied via _apply_followup_edit before the re-run.
COPILOT_ACTIONS: dict[str, dict[str, Any]] = {
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
    # meta verb: build auto-runs the pipeline to the next checkpoint — to the pictures
    # if we're before them, else all the way to a finished video. NOT one step.
    "build":       {"calls": None, "paid": True, "needs": None,
                    "doing": "building your video", "label": "Build the video"},
}
# Plain-English reason an action can't run yet (gate keyed by `needs`).
_NEEDS_REASON = {
    "scenes":   "the script hasn't been broken into scenes yet — I'd write the script first",
    "pictures": "there are no pictures to work from yet — I'd make the pictures first",
    "clips":    "nothing's been animated yet — I'd animate the scenes first",
}
COPILOT_CONFIDENCE = 0.55


async def _conversation_for_video(tenant_id, video_id: str) -> Optional[dict]:
    """Find-or-create ONE conversation bound to this video so the dock resumes the
    whole backstory. Verifies the video belongs to the tenant first (a foreign id
    would otherwise mint a junk row; every downstream query is tenant-scoped anyway)."""
    owns = await fetch_one(
        "SELECT id FROM videos WHERE id = $1 AND tenant_id = $2", video_id, tenant_id
    )
    if not owns:
        return None
    row = await fetch_one(
        """SELECT id, project_id, video_id, transcript, state, phase
             FROM chat_conversations
            WHERE tenant_id = $1 AND video_id = $2
            ORDER BY updated_at DESC LIMIT 1""",
        tenant_id, video_id,
    )
    if row:
        return row
    return await fetch_one(
        """INSERT INTO chat_conversations (tenant_id, video_id, phase)
           VALUES ($1, $2, 'created')
           RETURNING id, project_id, video_id, transcript, state, phase""",
        tenant_id, video_id,
    )


async def _copilot_summary(tenant_id, video_id: str) -> Optional[dict[str, Any]]:
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
    model = v.get("video_model") or "grok-imagine"
    pics, clips = int(a["pics"] or 0), int(a["clips"] or 0)
    cost = round(pics * _PICTURE_COST + clips * _CLIP_COST.get(model, 0.10), 2)
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
        "spent": cost,
        "validation": str(v.get("script_validation") or "").strip()[:600],
    }


def _summary_line(s: dict[str, Any]) -> str:
    line = (
        f'Video: "{s["title"]}" — status {s["status"]}, target length {s.get("length_min") or "?"} min, '
        f'animation model {s["model"]}.\n'
        f'Progress: {s["scenes"]} scenes written ({s.get("voiced", 0)} voiced), {s["boards"]} storyboards, '
        f'{s["pics"]} pictures made, {s["clips"]} clips animated. Spent so far ~${s["spent"]:.2f}.'
    )
    val = (s.get("validation") or "").strip()
    if val:
        # The creator can see these on the page; the co-pilot must not contradict them.
        line += ("\nScript-check results (these are REAL and visible to the creator — quote them "
                 "accurately; if a [FAIL] line is present, never claim nothing failed):\n" + val)
    return line


def _action_blocked(verb: str, summary: dict[str, Any]) -> Optional[str]:
    """Return a plain-English reason this action can't run yet, or None if it's allowed."""
    needs = (COPILOT_ACTIONS.get(verb) or {}).get("needs")
    if needs == "scenes" and summary["scenes"] == 0:
        return _NEEDS_REASON["scenes"]
    if needs == "pictures" and summary["pics"] == 0:
        return _NEEDS_REASON["pictures"]
    if needs == "clips" and summary["clips"] == 0:
        return _NEEDS_REASON["clips"]
    return None


async def _estimate_cost(tenant_id, video_id, verb: str, scene: Optional[int], summary: dict[str, Any]) -> tuple[float, str]:
    """A rough but honest dollar estimate for a paid action, mirroring the page's
    counts. Per-scene actions price just that scene's pictures/clips."""
    model = summary["model"]
    clip = _CLIP_COST.get(model, 0.10)
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
        cost = n * _PICTURE_COST
    elif verb == "storyboards":
        cost = (1 if scene is not None else max(1, summary["scenes"])) * _PICTURE_COST
    elif verb == "voice":
        cost = 0.30
    elif verb == "sound":
        cost = 0.20
    elif verb == "thumbnail":
        cost = 0.10
    elif verb == "script":
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
        if summary["status"] in _BUILD_TO_PICTURES:
            cost = scenes * 6 * _PICTURE_COST
        else:
            cost = (summary["pics"] or scenes * 6) * clip
    else:
        cost = 0.0
    text = "no extra cost" if cost <= 0 else f"~${cost:.2f}"
    return round(cost, 2), text


def _confirm_card(verb: str, scene: Optional[int], cost_text: str) -> dict[str, Any]:
    """Smallest-change confirm: a single-select card the frontend already renders;
    the dock reads the pick back as selections.confirm_action = yes|no."""
    cfg = COPILOT_ACTIONS[verb]
    what = cfg["label"] + (f" — scene {scene}" if scene is not None else "")
    return {
        "id": "confirm_action", "label": what, "type": "single",
        "options": [
            {"value": "yes", "label": f"Do it · {cost_text}"},
            {"value": "no", "label": "Cancel"},
        ],
    }


def _make_copilot_step(tenant_id, video_id: str, calls: list, *, scene: Optional[int] = None,
                       start_msg: str = "On it…"):
    """Run an action's executor methods in order, passing scene= to the ones that
    accept it. Same task-status channel as the rest so the page's trackers light
    up. Stops on the first error."""
    from pipeline_executor import PipelineExecutor
    from routes.pipeline import _clear_task_status, _set_task_status

    async def _run():
        _set_task_status(video_id, "running", start_msg, tenant_id=tenant_id)
        try:
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


async def _run_pending_action(tenant_id, video_id, pending: dict, background_tasks) -> str:
    """Kick off a confirmed action and return the 'on it' line."""
    verb = pending["verb"]
    scene = pending.get("scene")
    cfg = COPILOT_ACTIONS[verb]
    # Edit-style verbs apply the creator's change to the stage guidance first.
    if cfg.get("edit") and pending.get("change"):
        await _apply_followup_edit(
            tenant_id, video_id, verb,
            {"guidance_append": pending["change"], "video_length_minutes": pending.get("length_min")},
        )
    doing = cfg["doing"] + (f" for scene {scene}" if scene is not None else "")
    if verb == "build":
        target = pending.get("target") or "pictures"
        msg = ("On it — building your video. I'll run research, script and the pictures, then stop so "
               "you can review them." if target == "pictures"
               else "On it — finishing your video (animating the clips and rendering). I'll update you here.")
        background_tasks.add_task(_make_autobuild_step(tenant_id, video_id, target=target, start_msg=msg))
        return msg
    background_tasks.add_task(
        _make_copilot_step(tenant_id, video_id, cfg["calls"], scene=scene, start_msg=f"On it — {doing}…")
    )
    return f"On it — {doing} now. I'll update you right here."


async def _handle_copilot(body, conversation_id, tenant_id, transcript, state, video_id, background_tasks):
    """The video-scoped co-pilot turn. Classify -> read (answer) or action (run, with
    a confirm gate in the dock). `docked` (request carries video_id) decides whether
    paid actions confirm first; the home CreatedCard follow-up keeps immediate runs."""
    docked = bool(getattr(body, "video_id", None))
    msg = (body.message or "").strip()
    sel = body.selections or {}
    ui_context = getattr(body, "ui_context", None) or {}

    async def _reply(text, cards=None):
        transcript.append(_assistant_turn({"assistant_text": text, "cards": cards, "phase": "created"}))
        await _persist(conversation_id, tenant_id, transcript, state, "created", video_id=video_id)
        return ChatTurnResponse(conversation_id=conversation_id, assistant_text=text,
                                cards=cards, video_id=video_id, phase="created")

    # --- confirm handshake: turn 2 of a paid/destructive action ---
    if "confirm_action" in sel:
        pending = state.get("pending_action")
        state["pending_action"] = None
        if sel["confirm_action"] == "yes" and pending:
            line = await _run_pending_action(tenant_id, video_id, pending, background_tasks)
            return await _reply(line)
        return await _reply("No problem — left it as it is. Tell me what you'd like instead.")

    # --- prompt studio: apply (or cancel) a proposed prompt rewrite ---
    if "prompt_apply" in sel:
        draft = state.get("prompt_draft")
        state["prompt_draft"] = None
        if sel["prompt_apply"] == "yes" and draft:
            # The dock sends the (possibly hand-edited) prompt text — full edit access.
            edited = (sel.get("prompt_text") or "").strip()
            if edited:
                draft = {**draft, "draft": edited}
            line = await _apply_prompt_draft(tenant_id, video_id, draft, background_tasks)
            return await _reply(line)
        return await _reply("No problem — kept the original prompt. Tell me what else you'd like.")

    if msg:
        transcript.append({"role": "user", "content": msg})
    if not msg:
        return await _reply("Ask me anything about this video, or tell me what to do next — e.g. "
                            "“animate scene 2”, “redo the thumbnail”, or “how much has this cost?”")

    summary = await _copilot_summary(tenant_id, video_id)
    if not summary:
        return await _reply("I can't find that video anymore — it may have been deleted.")

    # The co-pilot's intelligence needs a text model. Keyless tenants get the
    # friendly key prompt (reused from onboarding), never a crash.
    try:
        from kie_unified import get_text_client_for_tenant
        client = await get_text_client_for_tenant(tenant_id)
    except Exception:  # noqa: BLE001 — no key configured at all
        client = None
    if client is None:
        return await _reply(
            "I just need an API key to think this through. Add your Kie.ai or Anthropic key under "
            "Profile → API Keys, then tell me again — I'll take it from there."
        )
    # AnthropicDirectClient.generate defaults to a stale model id; pass the current
    # one (the Kie client keeps its own valid default). Mirrors coverage_to_app.py.
    copilot_model = "claude-sonnet-4-6" if type(client).__name__ == "AnthropicDirectClient" else None

    # While a proposed prompt is open, plain text REFINES it (no spend). Bail words
    # drop the draft; otherwise feed the words back as more direction and redraft.
    draft = state.get("prompt_draft")
    if draft and msg and not sel:
        low = msg.lower()
        if any(w in low for w in ("cancel", "never mind", "nevermind", "forget it", "leave it", "no thanks")):
            state["prompt_draft"] = None
            return await _reply("No problem — kept the original. What else can I do?")
        new = await _rewrite_prompt(client, copilot_model, draft["surface"], draft["draft"], msg, summary["model"])
        if new:
            draft["draft"] = new
            state["prompt_draft"] = draft
            return await _reply(
                f"Updated the prompt for {draft['label']} — review and tweak it below, then apply "
                "(or keep adjusting in words).", cards=[_prompt_apply_card(draft, new)])
        return await _reply("I couldn't adjust that — try wording it a different way?")

    prompt = (
        "You are the in-app co-pilot for ONE video. The creator can (a) ASK a question, (b) tell you to RUN a "
        "production step, or (c) work on a generation PROMPT (view it, get suggestions, or rewrite/enhance it "
        "for a specific shot). Decide which.\n\n"
        + _summary_line(summary) + "\n"
        + (f"They are currently viewing scene {ui_context.get('scene')}"
           + (f", image {ui_context.get('index')}" if ui_context.get("index") else "")
           + ".\n" if ui_context.get("scene") else "")
        + f'\nThe creator said: "{msg}"\n\n'
        "ACTIONS (kind=action, exact verb): script, characters, storyboards, images, voice, animate, sound, "
        "thumbnail, render — for RUNNING/redoing a SINGLE step. 'characters' = design or REDESIGN the CAST "
        "(the character reference sheets): 'redesign the cast', 'redo the characters', 'regenerate the cast', "
        "'design the characters', 'change how Tom looks'. NEVER map a cast/character request to 'script'. "
        "'animate' is ONE scene (give the scene). "
        "Use 'build' when they want the whole video built or moved forward — 'build it', 'make the video', "
        "'do it', 'run it all', 'keep going', 'generate it', 'finish it', 'animate everything'. build runs "
        "the pipeline automatically to the next checkpoint, NOT one step.\n"
        "PROMPT work (kind=prompt) when they talk about the PROMPT itself — 'rewrite/enhance the prompt', "
        "'show me the prompt', 'suggest improvements', 'make a better prompt', 'image 1 looks off, rewrite its "
        "prompt to…'. Then set surface (image=a picture | motion=a clip's motion | thumbnail | script), "
        "op (view=show current | suggest=ideas only, no change | rewrite=write a new one to apply), the "
        "scene/index of the shot (use the 'currently viewing' one if they say 'this' and name no shot), and "
        "the direction.\n"
        "If they're ASKING about state (cost/status/what's left/why), kind=read and answer from the numbers.\n\n"
        "Return ONE JSON object and nothing else:\n"
        '{"kind":"read|action|prompt",'
        '"verb":"script|characters|storyboards|images|voice|animate|sound|thumbnail|render|build|none",'
        '"surface":"image|motion|thumbnail|script|null",'
        '"op":"view|suggest|rewrite|null",'
        '"scene":<int or null>,"index":<int picture/shot number or null>,'
        '"change":"<for action edits: a concrete instruction; else empty>",'
        '"direction":"<for prompt rewrite: the enhancement instruction; else empty>",'
        '"length_min":<int or null>,'
        '"answer":"<for read: a friendly, specific 1-2 sentence answer using the numbers>",'
        '"reply":"<for action: one friendly sentence; for none: a clarifying question>",'
        '"confidence":<0.0-1.0>}'
    )
    try:
        from producer_prompt import _extract_json
        gen_kwargs: dict[str, Any] = {"prompt": prompt, "max_tokens": 700, "temperature": 0.2}
        if copilot_model:
            gen_kwargs["model"] = copilot_model
        raw = await client.generate(**gen_kwargs)
        data = json.loads(_extract_json(raw))
    except Exception as e:  # noqa: BLE001
        logger.warning("copilot: classify failed: %s", e)
        return await _reply("I didn't quite catch that — want me to change the script, the pictures, the "
                            "thumbnail, animate a scene, or render it?")

    kind = (data.get("kind") or "").strip()
    verb = (data.get("verb") or "none").strip()
    reply = (data.get("reply") or "").strip()
    conf = float(data.get("confidence") or 0)

    # --- prompt studio: view / suggest / rewrite a generation prompt ---
    if kind == "prompt":
        return await _handle_prompt_op(client, copilot_model, tenant_id, video_id,
                                       summary, data, ui_context, state, _reply)

    # --- read: answer immediately, no spend ---
    if kind == "read" or verb == "none":
        answer = (data.get("answer") or reply or "").strip()
        if not answer:
            answer = (f'“{summary["title"]}” is at {summary["status"]}: {summary["scenes"]} scenes, '
                      f'{summary["pics"]} pictures, {summary["clips"]} clips. Spent so far ~${summary["spent"]:.2f}.')
        return await _reply(answer)

    if verb not in COPILOT_ACTIONS or conf < COPILOT_CONFIDENCE:
        return await _reply(reply or "Happy to help — want me to change the script, the pictures, the "
                            "thumbnail, the voice, animate a scene, add sound, or render it?")

    # --- legality gate: refuse politely if the prerequisite isn't there ---
    blocked = _action_blocked(verb, summary)
    if blocked:
        return await _reply(f"I can't {COPILOT_ACTIONS[verb]['label'].lower()} yet — {blocked}. "
                            "Want me to do that first?")

    scene = data.get("scene")
    scene = int(scene) if isinstance(scene, (int, float)) else None
    cfg = COPILOT_ACTIONS[verb]

    # --- free vs paid ---
    if not cfg["paid"]:
        line = await _run_pending_action(
            tenant_id, video_id,
            {"verb": verb, "scene": scene, "change": data.get("change"), "length_min": data.get("length_min")},
            background_tasks,
        )
        return await _reply(line)

    # Paid. The home follow-up runs immediately (preserves Phase 5 behavior); the
    # dock holds it behind a one-tap confirm card.
    pending = {"verb": verb, "scene": scene, "change": (data.get("change") or "").strip(),
               "length_min": data.get("length_min")}
    if verb == "build":
        # To pictures if we're before them, else finish the rest.
        pending["target"] = "pictures" if summary["status"] in _BUILD_TO_PICTURES else "finish"
    if not docked:
        line = await _run_pending_action(tenant_id, video_id, pending, background_tasks)
        return await _reply(line)

    _cost, cost_text = await _estimate_cost(tenant_id, video_id, verb, scene, summary)
    state["pending_action"] = pending
    # Deterministic, confirmation-clear message — NOT the model's free-text reply, which
    # tended to say "Generating now…" even though this is gated behind a tap (the money
    # gate). State what will run + the cost + that a tap is needed; no contradiction.
    where = f" for scene {scene}" if scene is not None else ""
    intro = (f"Ready when you are — I'll {cfg['label'].lower()}{where} ({cost_text}). "
             "Tap to run it, or tell me to change anything first.")
    return await _reply(intro, cards=[_confirm_card(verb, scene, cost_text)])


# --- prompt studio (full prompt-edit access) --------------------------------
#
# The co-pilot can READ, SUGGEST improvements to, or REWRITE any generation prompt
# — the per-shot picture prompt (assets.image_prompt) and motion prompt
# (assets.video_prompt), the thumbnail prompt (videos.thumbnail_prompt), and a
# scene's script text (scripts.scene_text). A rewrite is model-aware (it knows the
# image model and the chosen video model) and is PROPOSED, not applied: the creator
# reviews the new prompt, keeps refining it in words, and only on approval does it
# save + regenerate that one shot. Reuses the same one-shot routes the Scenes page
# uses (redraw_asset_image / run_clip_generation(force) / run_thumbnail).

_PROMPT_SURFACES = {"image", "motion", "thumbnail", "script"}
_IMAGE_GUIDE = ("Target: GPT Image 2 drawing ONE cinematic 16:9 frame. Keep the locked characters' exact looks. "
                "Be concrete and visual — subject, action, composition, lighting, lens, mood. One flowing prompt, no lists.")
_THUMB_GUIDE = ("Target: a high-CTR YouTube thumbnail. Bold focal subject, strong emotion/expression, high contrast, "
                "readable at small size, minimal text. One flowing image prompt.")
_SCRIPT_GUIDE = ("Target: the spoken script for this scene. Keep the story beats and characters; sharpen the hook, "
                 "clarity, pacing and voice. Return the rewritten scene text only.")
# Motion guidance keyed by the chosen video model (self-contained — no import risk).
_MOTION_MODEL_GUIDE = {
    "grok-imagine":     "Target: Grok Imagine motion (~6-10s). You MAY name one simple camera move. Keep motion physical and clear.",
    "seedance-2-fast":  "Target: Seedance 2.0 cinematic motion (6-10s). Camera control + first/last frame supported — you may specify a camera move and pacing.",
    "veo-3.1-fast":     "Target: Veo 3.1 (8s). NO in-prompt camera control — describe the SUBJECT's motion and the action, not camera operation. Rich cinematic detail works.",
    "veo-3.1-quality":  "Target: Veo 3.1 (8s). NO in-prompt camera control — describe the SUBJECT's motion and the action. Rich cinematic detail works.",
}


def _surface_guide(surface: str, video_model: str) -> str:
    if surface == "image":
        return _IMAGE_GUIDE
    if surface == "thumbnail":
        return _THUMB_GUIDE
    if surface == "script":
        return _SCRIPT_GUIDE
    return _MOTION_MODEL_GUIDE.get(video_model, "Target: a short motion clip from the picture. Describe the motion and action clearly.")


async def _resolve_prompt_target(tenant_id, video_id, surface, scene, index, ui_context, summary) -> dict[str, Any]:
    """Point a prompt op at a concrete thing + read its current prompt. Falls back to
    the scene/image the creator is viewing; returns {"error": <ask>} when ambiguous."""
    ui = ui_context or {}
    if surface in ("image", "motion"):
        sc = scene if scene is not None else ui.get("scene")
        if sc is None:
            return {"error": "Which scene's shot do you mean? e.g. “image 1 in scene 2”."}
        rows = await fetch_all(
            "SELECT id, image_index, image_prompt, video_prompt, image_url "
            "FROM assets WHERE video_id=$1 AND tenant_id=$2 AND scene=$3 ORDER BY image_index",
            video_id, tenant_id, int(sc),
        )
        if not rows:
            return {"error": f"Scene {sc} doesn't have pictures yet — want me to make them first?"}
        idx = index if index is not None else ui.get("index")
        if idx is None:
            if len(rows) == 1:
                row, idx = rows[0], 1
            else:
                return {"error": f"Scene {sc} has {len(rows)} pictures — which one? (e.g. “image 1”)."}
        else:
            n = int(idx)
            if n < 1 or n > len(rows):
                return {"error": f"Scene {sc} has {len(rows)} pictures — pick 1 to {len(rows)}."}
            row, idx = rows[n - 1], n
        if surface == "motion" and not row.get("image_url"):
            return {"error": f"Scene {sc} image {idx} hasn't been drawn yet — make the picture first."}
        cur = (row.get("image_prompt" if surface == "image" else "video_prompt") or "").strip()
        cost = _PICTURE_COST if surface == "image" else _CLIP_COST.get(summary["model"], 0.10)
        noun = "picture" if surface == "image" else "clip"
        return {"surface": surface, "asset_id": str(row["id"]), "scene": int(sc), "index": int(idx),
                "label": f"scene {sc} {noun} {idx}", "current": cur, "apply_cost": cost}
    if surface == "thumbnail":
        v = await fetch_one("SELECT thumbnail_prompt FROM videos WHERE id=$1 AND tenant_id=$2", video_id, tenant_id)
        return {"surface": "thumbnail", "label": "the thumbnail",
                "current": ((v or {}).get("thumbnail_prompt") or "").strip(), "apply_cost": 0.10}
    if surface == "script":
        sc = scene if scene is not None else ui.get("scene")
        if sc is None:
            return {"error": "Which scene's script do you mean? e.g. “the script for scene 2”."}
        r = await fetch_one(
            "SELECT scene_text FROM scripts WHERE video_id=$1 AND tenant_id=$2 AND scene=$3",
            video_id, tenant_id, int(sc),
        )
        if not r or not (r.get("scene_text") or "").strip():
            return {"error": f"Scene {sc} doesn't have written text yet."}
        return {"surface": "script", "scene": int(sc), "label": f"scene {sc}'s script",
                "current": r["scene_text"].strip(), "apply_cost": 0.0}
    return {"error": "I can work on the picture, motion, thumbnail, or script prompt — which one?"}


async def _rewrite_prompt(client, model_for_call, surface, current, direction, video_model) -> str:
    guide = _surface_guide(surface, video_model)
    p = ("You are refining a generation prompt. Rewrite it to honor the creator's direction and optimize it for "
         "the target. PRESERVE the original intent and any specific characters/objects — never invent new ones.\n\n"
         f"{guide}\n\nCURRENT PROMPT:\n{current or '(empty — write a strong one from the direction)'}\n\n"
         f"CREATOR'S DIRECTION: {direction or '(no specific direction — just make it noticeably stronger)'}\n\n"
         "Return ONLY the rewritten prompt text, nothing else.")
    kw: dict[str, Any] = {"prompt": p, "max_tokens": 900, "temperature": 0.5}
    if model_for_call:
        kw["model"] = model_for_call
    try:
        return ((await client.generate(**kw)) or "").strip()
    except Exception as e:  # noqa: BLE001
        logger.warning("copilot: rewrite failed: %s", e)
        return ""


async def _suggest_prompt(client, model_for_call, surface, current, video_model) -> str:
    guide = _surface_guide(surface, video_model)
    p = ("Give the creator 3-5 short, concrete suggestions to improve this generation prompt for the target. "
         "Don't rewrite it — just the bullet suggestions.\n\n"
         f"{guide}\n\nCURRENT PROMPT:\n{current or '(empty)'}\n\nReturn a short friendly message with the bullets.")
    kw: dict[str, Any] = {"prompt": p, "max_tokens": 600, "temperature": 0.4}
    if model_for_call:
        kw["model"] = model_for_call
    try:
        return ((await client.generate(**kw)) or "").strip()
    except Exception as e:  # noqa: BLE001
        logger.warning("copilot: suggest failed: %s", e)
        return ""


def _prompt_apply_card(target: dict[str, Any], draft_text: str) -> dict[str, Any]:
    """The proposed prompt as a one-tap card. `body` carries the full prompt so the
    dock can show it in an EDITABLE field — Apply sends back whatever's in that box
    (so the creator has full edit access), falling back to this draft if untouched."""
    cost = float(target.get("apply_cost") or 0)
    verb = {"image": "redraw", "motion": "re-animate", "thumbnail": "redo", "script": "save"}[target["surface"]]
    do = "Save it" if target["surface"] == "script" else \
        f"Apply & {verb} · {'no extra cost' if cost <= 0 else f'~${cost:.2f}'}"
    return {"id": "prompt_apply", "label": f"Apply to {target['label']}?", "type": "single",
            "body": draft_text,
            "options": [{"value": "yes", "label": do}, {"value": "no", "label": "Cancel"}]}


def _make_prompt_regen(tenant_id, video_id: str, surface: str, *, asset_id: Optional[str] = None,
                       start_msg: str = "Applying your prompt…"):
    """Regenerate just the one shot a prompt was applied to (or no-op for script),
    on the same task-status channel the page already watches."""
    from pipeline_executor import PipelineExecutor
    from routes.pipeline import _clear_task_status, _set_task_status

    async def _run():
        _set_task_status(video_id, "running", start_msg, tenant_id=tenant_id)
        try:
            if surface == "image":
                from scripts.coverage_to_app import redraw_asset_image
                result = await redraw_asset_image(video_id, tenant_id, asset_id) or {}
            elif surface == "motion":
                result = await PipelineExecutor(tenant_id).run_clip_generation(
                    video_id, asset_id=asset_id, force=True) or {}
            elif surface == "thumbnail":
                result = await PipelineExecutor(tenant_id).run_thumbnail(video_id) or {}
            else:
                result = {"status": "completed"}
            _set_task_status(video_id, result.get("status", "completed"),
                             result.get("error") or result.get("message"), tenant_id=tenant_id)
        except Exception as e:  # noqa: BLE001
            _set_task_status(video_id, "failed", str(e), tenant_id=tenant_id)
        finally:
            await asyncio.sleep(20)
            _clear_task_status(video_id, tenant_id)

    return _run


async def _apply_prompt_draft(tenant_id, video_id, draft: dict[str, Any], background_tasks) -> str:
    """Save the approved prompt to the right column, then regenerate that one shot."""
    surface, text, label = draft["surface"], draft["draft"], draft["label"]
    if surface == "image":
        await execute("UPDATE assets SET image_prompt=$1, updated_at=now() WHERE id=$2 AND tenant_id=$3",
                      text, draft["asset_id"], tenant_id)
        background_tasks.add_task(_make_prompt_regen(tenant_id, video_id, "image", asset_id=draft["asset_id"],
                                                     start_msg=f"Redrawing {label}…"))
        return f"Saved and redrawing {label} now — I'll update you here."
    if surface == "motion":
        await execute("UPDATE assets SET video_prompt=$1, updated_at=now() WHERE id=$2 AND tenant_id=$3",
                      text, draft["asset_id"], tenant_id)
        background_tasks.add_task(_make_prompt_regen(tenant_id, video_id, "motion", asset_id=draft["asset_id"],
                                                     start_msg=f"Re-animating {label}…"))
        return f"Saved and re-animating {label} now — I'll update you here."
    if surface == "thumbnail":
        await execute("UPDATE videos SET thumbnail_prompt=$1, updated_at=now() WHERE id=$2 AND tenant_id=$3",
                      text, video_id, tenant_id)
        background_tasks.add_task(_make_prompt_regen(tenant_id, video_id, "thumbnail",
                                                     start_msg="Redoing the thumbnail…"))
        return "Saved and redoing the thumbnail now — I'll update you here."
    # script: just save the new scene text; downstream art is regenerated separately.
    await execute("UPDATE scripts SET scene_text=$1, updated_at=now() WHERE video_id=$2 AND scene=$3 AND tenant_id=$4",
                  text, video_id, draft["scene"], tenant_id)
    return (f"Done — I've updated {label}. If you've already storyboarded this scene, you may want to "
            "redo its pictures so they match.")


async def _handle_prompt_op(client, model_for_call, tenant_id, video_id, summary, data,
                            ui_context, state, _reply):
    """view / suggest / rewrite a generation prompt. Rewrite proposes a draft + a
    one-tap apply card; refinement happens via free text on the next turns."""
    surface = (data.get("surface") or "").strip()
    op = (data.get("op") or "rewrite").strip()
    scene = data.get("scene"); scene = int(scene) if isinstance(scene, (int, float)) else None
    index = data.get("index"); index = int(index) if isinstance(index, (int, float)) else None
    direction = (data.get("direction") or data.get("change") or "").strip()
    if surface not in _PROMPT_SURFACES:
        return await _reply("I can rewrite the picture, motion, thumbnail, or script prompt — which one, "
                            "and for which shot?")
    target = await _resolve_prompt_target(tenant_id, video_id, surface, scene, index, ui_context, summary)
    if target.get("error"):
        return await _reply(target["error"])

    if op == "view":
        cur = target["current"] or "(no prompt saved for this one yet)"
        return await _reply(f"Here's the current prompt for {target['label']}:\n\n{cur}")
    if op == "suggest":
        s = await _suggest_prompt(client, model_for_call, surface, target["current"], summary["model"])
        return await _reply(s or "I couldn't read that one — try again?")

    # rewrite -> propose a draft, hold it for one-tap apply.
    new = await _rewrite_prompt(client, model_for_call, surface, target["current"], direction, summary["model"])
    if not new:
        return await _reply("I couldn't draft that — want to try again with a little more direction?")
    state["prompt_draft"] = {"surface": surface, "asset_id": target.get("asset_id"), "scene": target.get("scene"),
                             "index": target.get("index"), "label": target["label"], "draft": new,
                             "apply_cost": target.get("apply_cost", 0.0)}
    return await _reply(
        f"Here's a stronger prompt for {target['label']} — tweak it below if you like, then apply "
        "(or just tell me how to adjust it in words).",
        cards=[_prompt_apply_card(target, new)])


# --- onboarding ("Start Here") step-machine ---------------------------------
#
# A deterministic conversational flow that sets up a new creator: intent (tell
# stories vs automate a channel) -> what to automate -> connect channel (paste
# URL) -> add 1-3 competitors -> a soft pitch for the Advanced tier -> done, then
# the producer takes over. State lives in the conversation row's `state` JSONB
# (mode + onboarding_step + collected intent/goals/channel). Reliability matters
# here, so it's a step-machine, not a free LLM agent — it reuses the dormant
# routes/onboarding.py functions for the real work.

ONBOARDING_INTENT_CARD = {
    "id": "intent", "label": "What brings you here?", "type": "single",
    "options": [
        {"value": "automate", "label": "Automate my channel", "hint": "Ideas, scripts, voiceovers, thumbnails, whole videos"},
        {"value": "stories", "label": "Tell stories", "hint": "Narrative videos, shorts, films"},
    ],
}
ONBOARDING_GOALS_CARD = {
    "id": "goals", "label": "What should I handle for you?", "type": "multi",
    "options": [
        {"value": "ideas", "label": "Video ideas"},
        {"value": "scripts", "label": "Scripts"},
        {"value": "voiceover", "label": "Voiceovers"},
        {"value": "thumbnails", "label": "Thumbnails"},
        {"value": "full_video", "label": "Whole videos"},
        {"value": "all", "label": "All of the above"},
    ],
}
ONBOARDING_UPSELL_CARD = {
    "id": "upsell", "label": "", "type": "single",
    "options": [
        {"value": "tell_more", "label": "Tell me more"},
        {"value": "carry_on", "label": "Let's keep rolling"},
    ],
}
_UPSELL_TEXT = (
    "One last thing 👀 — our **Advanced tier** adds two things that really move the "
    "needle: **Smart Analytics** watches what's working on your channel (and your "
    "competitors') and tells you *why* your winners win, and the **Autopilot engine** "
    "can research, script, and queue videos for you on a schedule — hands-off. No "
    "pressure at all: everything here works great without it, and you can switch it "
    "on anytime from Billing. Want the 30-second version, or shall we keep rolling?"
)
_UPSELL_DETAIL = (
    "Quick pitch: with Advanced on, StoryEngine studies your real performance — CTR, "
    "retention, what your audience rewards — and feeds those lessons into every script, "
    "title, and thumbnail, so the engine gets smarter the more you publish. Autopilot "
    "then runs the whole loop: finds ideas from your niche + competitors, writes and "
    "queues videos, and keeps your channel fed without you lifting a finger. It's the "
    "difference between *making videos* and *growing a channel*. Flip it on anytime in "
    "Billing — for now, let's make something. 🚀"
)

_SKIP_WORDS = {"skip", "no", "none", "n/a", "nope", "later"}

# --- API-key onboarding step ------------------------------------------------
# A brand-new tenant has NO generation key, and StoryEngine has no shared key
# (get_text_client_for_tenant raises if neither anthropic_api_key nor
# kie_ai_api_key is set). So before anything that needs Claude, we walk them
# through pasting one — Kie.ai recommended (one key = text + images + video),
# Anthropic accepted (auto-detected). The key arrives as composer text; we save
# it to the Vault and validate it with the same test_api_key the Settings page
# uses, so a bad paste is caught here instead of failing three steps later.
_KEY_URL = "https://kie.ai/api-key"
_KEY_PROMPT = (
    "Quick bit of setup: StoryEngine runs on **your own AI key**, so your work stays "
    "private and you only pay for what you make. I recommend **Kie.ai** — one key powers "
    "scripts, voices, images, and video.\n\n"
    "**Get your key in about 2 minutes:**\n"
    f"1. [Open kie.ai to create your key →]({_KEY_URL}) — sign up and add a few dollars of credit\n"
    "2. Click **Create API Key**, then copy it\n"
    "3. Paste it right here in the chat 👇\n\n"
    "Already have an Anthropic (Claude) key? Paste that instead — I'll detect it automatically."
)


def _pick_key(raw: str):
    """Pull an API key out of a pasted message and route it to the right Vault slot.

    Returns (slot, key) on success, or (None, friendly_error) when it's not a key
    we accept. Keys have no spaces, so if they pasted a sentence we take the longest
    token; surrounding quotes are stripped. Only Anthropic uses the `sk-ant-` prefix,
    so detection is unambiguous; an `sk-` (OpenAI) key is the one common wrong paste
    worth calling out."""
    if not raw:
        return None, None
    token = max(raw.replace('"', " ").replace("'", " ").split(), key=len, default="")
    if token.startswith("sk-ant-"):
        return "anthropic_api_key", token
    if token.startswith("sk-"):
        return None, ("That looks like an OpenAI key. I need your **Kie.ai** key, or an "
                      "Anthropic key that starts with `sk-ant-`.")
    if len(token) >= 16:
        return "kie_ai_api_key", token
    return None, "Paste the whole key — it's a long string with no spaces."


async def _has_generation_key(tenant_id) -> bool:
    """True if this tenant already has a usable text/image key — so returning
    users (and Ryan testing) aren't forced to re-paste during a manual restart."""
    from vault import get_secret
    for slot in ("anthropic_api_key", "kie_ai_api_key"):
        try:
            if await get_secret(slot, tenant_id):
                return True
        except Exception:  # noqa: BLE001 — a missing key is the common case, not an error
            pass
    return False


# --- account-connect steps (YouTube analytics + Google Drive) ---------------
# Two optional, skippable OAuth steps. The frontend renders a "Connect" button
# (it owns the per-tenant auth_url via getYouTube/DriveConnectUrl), sends the
# user same-tab to Google, and the existing callbacks return to "/?connected=…"
# so ChatHome resumes onboarding. The OAuth callback persists the tokens, so the
# chat step just records intent and advances — either choice moves on.
ONBOARDING_CONNECT_YT_CARD = {
    "id": "connect_yt", "label": "", "type": "single",
    "options": [
        {"value": "connected", "label": "I've connected it"},
        {"value": "skip", "label": "Skip for now"},
    ],
}
ONBOARDING_CONNECT_DRIVE_CARD = {
    "id": "connect_drive", "label": "", "type": "single",
    "options": [
        {"value": "connected", "label": "I've connected it"},
        {"value": "skip", "label": "Skip for now"},
    ],
}
_CONNECT_YT_TEXT = (
    "Now let's connect your **YouTube analytics** — this lets me learn what's already working "
    "on your channel (your real views, retention, and winners) and post finished videos straight "
    "to YouTube for you.\n\n"
    "Tap **Connect YouTube** below, approve access in the Google window, and I'll bring you right "
    "back here. (Optional — tap **Skip for now** to do it later.)"
)
_CONNECT_DRIVE_TEXT = (
    "One more: **Google Drive**, so I can save your scripts, images, and finished videos straight "
    "to your own Drive.\n\n"
    "Tap **Connect Google Drive**, approve access, and I'll bring you back here. (Optional — you "
    "can skip and add it later.)"
)


def _guess_intent(msg: str) -> Optional[str]:
    m = (msg or "").lower()
    if any(w in m for w in ("stor", "narrativ", "film", "fiction", "short film")):
        return "stories"
    if any(w in m for w in ("automat", "channel", "youtube", "faceless", "grow")):
        return "automate"
    return None


def _parse_urls(msg: str) -> list[str]:
    """Pull channel URLs / @handles out of a free-text reply (space/comma/newline sep)."""
    import re
    if not msg:
        return []
    tokens = re.split(r"[\s,]+", msg.strip())
    out = []
    for t in tokens:
        t = t.strip()
        if not t:
            continue
        if "youtube.com" in t or "youtu.be" in t or t.startswith("@") or t.startswith("http"):
            out.append(t)
    return out


async def _ob_reply(conversation_id, tenant_id, transcript, state, text,
                    *, cards=None, phase="onboarding", video_id=None):
    transcript.append(_assistant_turn({"assistant_text": text, "phase": phase, "cards": cards}))
    await _save_creator_brief(tenant_id, state)  # mirror durable facts as they're collected
    await _persist(conversation_id, tenant_id, transcript, state, phase, video_id=video_id)
    return ChatTurnResponse(
        conversation_id=conversation_id, assistant_text=text,
        cards=cards, phase=phase, video_id=video_id,
    )


_GOAL_LABELS = {
    "ideas": "video ideas", "scripts": "scripts", "voiceover": "voiceovers",
    "thumbnails": "thumbnails", "full_video": "whole videos",
}


def _creator_brief(state: dict) -> str:
    """A compact 'who you're talking to' note injected into EVERY producer turn so
    it remembers the onboarding (intent, goals, channel, competitors) across the
    handoff — and tailors itself (e.g. thumbnails-only -> thumbnail workflow)."""
    bits: list[str] = []
    intent = state.get("intent")
    if intent == "stories":
        bits.append("They're here to tell stories (narrative / film).")
    elif intent == "automate":
        bits.append("They're here to automate their channel.")
    goals = state.get("goals") or []
    if "all" in goals:
        bits.append("They want the full pipeline (ideas → script → visuals → video).")
    elif goals:
        bits.append("They want help with: " + ", ".join(_GOAL_LABELS.get(g, g) for g in goals) + ".")
    if state.get("channel"):
        bits.append(f"Their channel: {state['channel']}.")
    comps = state.get("competitors") or []
    if comps:
        bits.append("Channels they model: " + ", ".join(str(c) for c in comps[:3]) + ".")
    if state.get("niche_angle"):
        bits.append(f"Their chosen niche/angle: {state['niche_angle']}.")
    if not bits:
        return ""
    tailor = ""
    if goals == ["thumbnails"]:
        tailor = " They mainly want THUMBNAILS — default to the thumbnail-only workflow and keep questions minimal."
    elif goals and "full_video" not in goals and "all" not in goals:
        tailor = f" Default the workflow to match what they asked for ({', '.join(goals)}), not a full video, unless they say otherwise."
    return "WHO YOU'RE TALKING TO (from their setup — remember this): " + " ".join(bits) + tailor


async def _modeled_runtime_hint(tenant_id) -> str:
    """A length anchor for the producer: the typical runtime of the videos this creator
    models (their competitors' winners). Real data — competitor_videos.duration_seconds is
    populated at modeling time. Fail-soft; empty when there's nothing solid to anchor on."""
    try:
        row = await fetch_one(
            "SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY duration_seconds) AS med "
            "FROM competitor_videos WHERE tenant_id = $1 AND duration_seconds > 0",
            tenant_id,
        )
        med = int((row or {}).get("med") or 0)
    except Exception:  # noqa: BLE001
        return ""
    if med < 30:
        return ""
    return (f"\nLENGTH ANCHOR: the videos this creator models typically run ~{_format_runtime(med)}. "
            "Lean toward that as your recommended length unless the specific story clearly needs "
            "shorter or longer — and say so.")


# The durable subset of conversation `state` that defines a creator across sessions.
_BRIEF_KEYS = ("intent", "goals", "niche_angle", "channel", "competitors")


async def _save_creator_brief(tenant_id, state) -> None:
    """Persist the durable creator facts onto channel_profiles so the producer
    remembers them in FUTURE conversations (each page load starts a fresh one).
    Upsert + JSONB-merge — the row may not exist yet for a brand-new tenant, and we
    never want to clobber facts captured in an earlier step. Fail-soft."""
    brief = {k: state[k] for k in _BRIEF_KEYS if state.get(k)}
    if not brief:
        return
    try:
        await execute(
            """INSERT INTO channel_profiles (tenant_id, creator_brief)
               VALUES ($1, $2::jsonb)
               ON CONFLICT (tenant_id)
               DO UPDATE SET creator_brief = COALESCE(channel_profiles.creator_brief, '{}'::jsonb) || $2::jsonb,
                             updated_at = now()""",
            tenant_id, json.dumps(brief),
        )
    except Exception as e:  # noqa: BLE001 — memory is best-effort, never block a turn
        logger.warning("chat: save creator_brief failed: %s", e)


async def _hydrate_creator_brief(tenant_id, state) -> None:
    """Fill empty conversation `state` from the durable brief so a fresh conversation
    still knows the channel/goals/niche. Only fills MISSING keys (this conversation's
    own choices win). Fail-soft."""
    try:
        row = await fetch_one(
            "SELECT creator_brief FROM channel_profiles WHERE tenant_id = $1", tenant_id
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("chat: hydrate creator_brief failed: %s", e)
        return
    for k, v in _as_dict((row or {}).get("creator_brief")).items():
        if v and not state.get(k):
            state[k] = v


async def _wait_for_scrape(state) -> None:
    """Bounded wait (~40s) for the background competitor scrape to finish."""
    import asyncio
    job_id = state.get("competitor_job")
    if not job_id:
        return
    try:
        from routes.onboarding import _analyze_jobs
        for _ in range(20):
            st = (_analyze_jobs.get(job_id) or {}).get("status")
            if st and st != "processing":
                break
            await asyncio.sleep(2)
    except Exception:  # noqa: BLE001
        pass


async def _recent_competitor_rows(tenant_id) -> list[dict[str, Any]]:
    """The competitors' best PAST-WEEK videos (falls back to newest if none recent)."""
    rows = await fetch_all(
        """SELECT title, channel, views, vph, hours_old
             FROM competitor_videos
            WHERE tenant_id = $1 AND title IS NOT NULL
              AND hours_old IS NOT NULL AND hours_old <= 240
            ORDER BY vph DESC NULLS LAST, views DESC NULLS LAST
            LIMIT 12""",
        tenant_id,
    )
    if not rows:
        rows = await fetch_all(
            """SELECT title, channel, views, vph, hours_old
                 FROM competitor_videos
                WHERE tenant_id = $1 AND title IS NOT NULL
                ORDER BY published_date DESC NULLS LAST, views DESC NULLS LAST
                LIMIT 12""",
            tenant_id,
        )
    return rows or []


def _video_lines(rows) -> list[str]:
    out = []
    for r in rows[:10]:
        v = int(r.get("views") or 0)
        hrs = r.get("hours_old")
        when = f", {round(hrs / 24, 1)}d ago" if hrs else ""
        out.append(f'- "{r.get("title")}" ({r.get("channel") or "competitor"}) — {v:,} views{when}')
    return out


def _claude_json(api_key: str, prompt: str, max_tokens: int = 1400) -> dict:
    """One direct-Anthropic JSON call (sync; invoke via asyncio.to_thread)."""
    import anthropic
    from producer_prompt import ANTHROPIC_DIRECT_BASE_URL, MODEL, _extract_json
    client = anthropic.Anthropic(api_key=api_key, base_url=ANTHROPIC_DIRECT_BASE_URL)
    resp = client.messages.create(
        model=MODEL, max_tokens=max_tokens, messages=[{"role": "user", "content": prompt}]
    )
    text = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text")
    return json.loads(_extract_json(text))


async def _propose_modeling_angles(tenant_id, state) -> Optional[dict[str, Any]]:
    """Summarize the competitors' winning format + propose 4 concrete ways the
    creator could make it their OWN niche (so a beginner has real directions)."""
    import asyncio
    await _wait_for_scrape(state)
    rows = await _recent_competitor_rows(tenant_id)
    if not rows:
        return None
    api_key = await get_secret("anthropic_api_key", tenant_id)
    if not api_key:
        return None
    prompt = (
        "A creator wants to model this competitor channel. Their recent top videos:\n"
        + "\n".join(_video_lines(rows))
        + "\n\nIn ONE short line, summarize the winning FORMAT (what makes these work). Then propose 4 DISTINCT, "
        "concrete ways this creator could make that format their OWN niche — each an ownable angle a beginner could "
        "run with (e.g. swap the language, swap the theme/scenario, swap the audience, narrow the focus). "
        'Return ONE JSON object: {"format_summary":"...","angles":[{"label":"<short ownable niche>",'
        '"description":"<one line>"}]}. Exactly 4 angles.'
    )
    try:
        data = await asyncio.to_thread(_claude_json, api_key, prompt, 1200)
        if isinstance(data, dict) and isinstance(data.get("angles"), list) and data["angles"]:
            return {"format_summary": data.get("format_summary", ""), "angles": data["angles"][:4]}
        return None
    except Exception as e:  # noqa: BLE001
        logger.warning("onboarding: modeling angles failed: %s", e)
        return None


async def _generate_competitor_ideas(tenant_id, state, niche: Optional[str] = None) -> Optional[list[dict[str, Any]]]:
    """3 data-backed ideas modeled on the competitors' PAST-WEEK winners. When
    `niche` is set, the ideas target the creator's chosen niche while modeling the
    winning format; otherwise they model the competitors directly. Direct key.
    Returns None only when there's genuinely no recent competitor data."""
    import asyncio
    await _wait_for_scrape(state)
    rows = await _recent_competitor_rows(tenant_id)
    if not rows:
        return None
    api_key = await get_secret("anthropic_api_key", tenant_id)
    if not api_key:
        return None
    if niche:
        ask = (
            f"The creator wants to make videos in THIS niche/angle: {niche}.\n"
            "Propose 3 video ideas FOR THE CREATOR'S NICHE that MODEL the winning format above (hooks, structure, "
            "packaging) — adapted to their niche, NOT copies of the competitor's exact topic. Each reasoning must "
            "cite the specific competitor video + its view count + how recent it is, AND say how the idea adapts the "
            "format to the creator's niche."
        )
    else:
        ask = (
            "Pick the 3 strongest and propose 3 video ideas this creator should make now, each MODELED on one of the "
            "above. Each reasoning must cite the specific source video + its view count + how recent it is."
        )
    prompt = (
        "These are the top videos from this creator's competitor channels over the PAST WEEK:\n"
        + "\n".join(_video_lines(rows))
        + "\n\n" + ask
        + '\n\nReturn ONE JSON object and nothing else: {"ideas":[{"title":"...","reasoning":"...",'
        '"source_title":"<the competitor video>","script_structure":"<one line>"}]}. Exactly 3 ideas. '
        "Ground every reasoning in the real numbers above."
    )
    try:
        data = await asyncio.to_thread(_claude_json, api_key, prompt, 1500)
        ideas = data.get("ideas") if isinstance(data, dict) else None
        ideas = (ideas or [])[:3] or None
        if ideas:
            # Phase 3: score the ideas against the YouTube idea gates + rubric,
            # rank best-first, drop rejects. Fail-open inside the helper.
            ideas = await _score_and_rank_ideas(api_key, ideas, rows, niche)
        return ideas
    except Exception as e:  # noqa: BLE001
        logger.warning("onboarding: idea generation failed: %s", e)
        return None


async def _score_and_rank_ideas(api_key, ideas, rows, niche) -> list[dict[str, Any]]:
    """Phase 3 idea scorer: judge the generated ideas against the YouTube idea
    gates + rubric, rank them best-first, and drop weak ones.

    The idea sets the video's ceiling, so this is the highest-leverage gate. It
    runs one direct-Anthropic call (same pattern as the generator), attaches a
    `_score`/`_verdict` to each idea, sorts best-first, and drops 'reject'-verdict
    ideas - but only while at least 2 remain, so the creator always sees a couple
    of options. Fail-open: on any error the original ideas are returned unchanged
    (a scoring hiccup must never leave the creator with no ideas).
    """
    import asyncio
    if not ideas:
        return ideas
    try:
        listed = "\n".join(
            f'{i}. title: "{idea.get("title")}" | structure: '
            f'{idea.get("script_structure") or ""} | rationale: {idea.get("reasoning") or ""}'
            for i, idea in enumerate(ideas)
        )
        prompt = (
            "You are a ruthless YouTube head of programming. Score these video IDEAS for a "
            f"{niche or 'this creator'} channel against what actually wins on YouTube. The idea "
            "sets the ceiling, so be strict.\n\n"
            "Proven competitor winners (real recent data):\n" + "\n".join(_video_lines(rows)) + "\n\n"
            "IDEAS TO SCORE (by index):\n" + listed + "\n\n"
            "For each idea, run the GATES, then score the RUBRIC.\n"
            "GATES (any fail => verdict 'reject'): proven_analog (a real winner above proves this "
            "format is wanted); packageable (you could write a <=65-char curiosity title AND a "
            "<=3-element thumbnail with one clear visual moment); not_copy (a viewer who saw the "
            "source would still get something genuinely NEW).\n"
            "RUBRIC, 0-100 each: outlier_proof, click_potential, curiosity_gap, visual_moment, "
            "broad_appeal, novelty, differentiation.\n"
            "verdict: 'strong' (overall 75+), 'ok' (55-74), 'reject' (under 55 or any gate fails).\n"
            'Return ONE JSON object and nothing else: {"scores":[{"index":int,'
            '"verdict":"strong|ok|reject","score":int}]}. Exactly one entry per idea index.'
        )
        data = await asyncio.to_thread(_claude_json, api_key, prompt, 900)
        raw = data.get("scores") if isinstance(data, dict) else None
        by_index = {
            int(s["index"]): s for s in (raw or [])
            if isinstance(s, dict) and isinstance(s.get("index"), int)
        }
        if not by_index:
            return ideas
        ranked = [
            {**idea,
             "_score": int(by_index.get(i, {}).get("score") or 0),
             "_verdict": str(by_index.get(i, {}).get("verdict") or "ok").lower()}
            for i, idea in enumerate(ideas)
        ]
        ranked.sort(key=lambda x: x.get("_score", 0), reverse=True)
        # Drop rejects, but keep at least 2 so the creator always has a choice.
        kept = [x for x in ranked if x.get("_verdict") != "reject"]
        return kept if len(kept) >= 2 else ranked
    except Exception as e:  # noqa: BLE001
        logger.warning("onboarding: idea scoring failed (fail-open): %s", e)
        return ideas


async def _seed_producer(conversation_id, tenant_id, state, seed_text):
    """Hand off into the producer seeded with a chosen/typed idea: start a fresh
    producer transcript and run one intake turn."""
    state["mode"] = "producer"
    state["onboarding_step"] = "done"
    api_key = await get_secret("anthropic_api_key", tenant_id)
    transcript = [{"role": "user", "content": seed_text}]
    if not api_key:
        msg = "I just need an Anthropic API key to draft this — add one under Profile → API Keys."
        transcript.append(_assistant_turn({"assistant_text": msg, "phase": "asking"}))
        await _persist(conversation_id, tenant_id, transcript, state, "asking")
        return ChatTurnResponse(conversation_id=conversation_id, assistant_text=msg, phase="asking")
    brief = _creator_brief(state) + await _modeled_runtime_hint(tenant_id)
    data = call_producer(transcript, build_system_prompt(brief), api_key=api_key)
    _stamp_length_default(data)
    transcript.append(_assistant_turn(data))
    plan = data.get("plan") if isinstance(data.get("plan"), dict) else None
    if plan and isinstance(plan.get("spec"), dict):
        state["last_spec"] = plan["spec"]
    phase = "plan" if plan else "asking"
    await _persist(conversation_id, tenant_id, transcript, state, phase)
    return ChatTurnResponse(
        conversation_id=conversation_id, assistant_text=data.get("assistant_text", ""),
        cards=data.get("cards") if isinstance(data.get("cards"), list) else None,
        plan=plan, ready_to_create=bool(plan), phase=phase,
    )


async def _present_ideas_turn(conversation_id, tenant_id, transcript, state, ideas):
    """Render 3 data-backed ideas as tappable cards; move to the 'ideas' step."""
    state["pitched_ideas"] = ideas
    state["mode"] = "onboarding"
    state["onboarding_step"] = "ideas"
    lines, opts = [], []
    for i, idea in enumerate(ideas):
        why = (idea.get("reasoning") or "").strip()
        src1 = idea.get("source_title") or (idea.get("source_titles") or [None])[0]
        srcline = f"  ↳ modeled on: “{src1}”" if src1 else ""
        badge = "🔥 " if idea.get("_verdict") == "strong" else ""
        lines.append(f"**{i + 1}. {badge}{idea.get('title')}**\n{why}{(chr(10) + srcline) if srcline else ''}")
        opts.append({"value": str(i), "label": (idea.get("title") or "Idea")[:70], "hint": why[:140]})
    niche = state.get("niche_angle")
    n = len(ideas)
    intro = (f"Here are **{n} ideas for “{niche}”**, modeled on what's winning:\n\n" if niche
             else f"Here are **{n} ideas I'd model**, and why:\n\n")
    text = intro + "\n\n".join(lines) + "\n\nTap one and I'll start building it — or just type your own idea below."
    card = {"id": "idea_choice", "label": "Pick one to build", "type": "single", "options": opts}
    return await _ob_reply(conversation_id, tenant_id, transcript, state, text, cards=[card])


async def _finish_onboarding(conversation_id, tenant_id, transcript, state, background_tasks):
    """Mark onboarding done, then help the creator MODEL their competitors: summarize
    the winning format and propose concrete ways to make it their OWN niche. They
    pick a direction (the 'modeling' step) -> we pitch 3 ideas in that niche. Falls
    back gracefully if there's no recent competitor data yet."""
    try:
        from routes.onboarding import complete_onboarding
        await complete_onboarding(tenant_id=tenant_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("onboarding: complete failed: %s", e)

    angles = await _propose_modeling_angles(tenant_id, state)
    if angles and angles.get("angles"):
        state["modeling"] = angles
        state["mode"] = "onboarding"
        state["onboarding_step"] = "modeling"
        a = angles["angles"]
        lines = [f"**{i + 1}. {x.get('label')}** — {x.get('description', '')}" for i, x in enumerate(a)]
        text = (
            "You're all set! 🎉 Here's what's working on your competitors: "
            + (angles.get("format_summary") or "strong, repeatable hooks")
            + "\n\nThere are a few ways to make this **your own** — pick a direction (or just type the niche "
            "you want to own):\n\n" + "\n".join(lines)
        )
        opts = [
            {"value": str(i), "label": (x.get("label") or "Angle")[:60], "hint": (x.get("description") or "")[:140]}
            for i, x in enumerate(a)
        ]
        card = {"id": "modeling_angle", "label": "How do you want to model it?", "type": "single", "options": opts}
        return await _ob_reply(conversation_id, tenant_id, transcript, state, text, cards=[card])

    # No recent competitor data yet — hand off honestly (never "ask me").
    state["mode"] = "producer"
    state["onboarding_step"] = "done"
    text = (
        "You're all set! 🎉 I pulled your competitor channel(s), but couldn't find enough of their "
        "recent videos to model from yet — they may still be importing. Paste another channel under "
        "Competitors, or just tell me what you'd like to make and I'll run with it."
    )
    fresh = [_assistant_turn({"assistant_text": text, "phase": "asking"})]
    await _persist(conversation_id, tenant_id, fresh, state, "asking")
    return ChatTurnResponse(conversation_id=conversation_id, assistant_text=text, phase="asking")


async def _handle_onboarding(body, conversation_id, tenant_id, transcript, state, background_tasks):
    sel = body.selections or {}
    msg = (body.message or "").strip()
    entering = state.get("mode") != "onboarding"
    state["mode"] = "onboarding"
    step = state.get("onboarding_step") or "intent"

    # Record the user's input for context.
    if msg:
        transcript.append({"role": "user", "content": msg})
    elif sel:
        transcript.append({"role": "user", "content": _selections_to_text(sel)})

    # Entry / re-entry: greet + ask intent.
    if entering or (step == "intent" and not sel.get("intent") and not msg):
        state["onboarding_step"] = "intent"
        return await _ob_reply(
            conversation_id, tenant_id, transcript, state,
            "Welcome — let's get you set up in under a minute. First, what brings you here?",
            cards=[ONBOARDING_INTENT_CARD],
        )

    if step == "intent":
        intent = sel.get("intent") or _guess_intent(msg)
        if not intent:
            return await _ob_reply(conversation_id, tenant_id, transcript, state,
                "No worries — just pick one so I can tailor things:", cards=[ONBOARDING_INTENT_CARD])
        state["intent"] = intent
        # New tenants need a generation key before any Claude step; existing
        # ones (already keyed) skip straight to setup.
        if not await _has_generation_key(tenant_id):
            state["onboarding_step"] = "key"
            lead = ("A storyteller — love it. " if intent == "stories"
                    else "Nice — let's put your channel on autopilot. ")
            return await _ob_reply(conversation_id, tenant_id, transcript, state,
                lead + _KEY_PROMPT)
        if intent == "stories":
            state["onboarding_step"] = "channel"
            return await _ob_reply(conversation_id, tenant_id, transcript, state,
                "A storyteller — love it. If you have a channel, paste its URL so I can match its vibe "
                "(or say “skip” and we'll start fresh).")
        state["onboarding_step"] = "goals"
        return await _ob_reply(conversation_id, tenant_id, transcript, state,
            "Nice — let's put your channel on autopilot. What should I handle for you?",
            cards=[ONBOARDING_GOALS_CARD])

    if step == "key":
        raw = (body.message or "").strip()
        if not raw:
            # They tapped the link but haven't pasted yet — re-show the ask.
            return await _ob_reply(conversation_id, tenant_id, transcript, state, _KEY_PROMPT)
        slot, val = _pick_key(raw)
        if not slot:
            return await _ob_reply(conversation_id, tenant_id, transcript, state,
                (val or "Paste the whole key — it's a long string with no spaces.") + "\n\n" + _KEY_PROMPT)
        from vault import set_secret, test_api_key
        await set_secret(slot, val, tenant_id=tenant_id, description="Onboarding generation key")
        result = await test_api_key(slot, tenant_id)
        if not result.get("success"):
            return await _ob_reply(conversation_id, tenant_id, transcript, state,
                f"That key didn't go through — {result.get('message') or 'please double-check it'}. "
                "Copy the whole key and paste it again 👇")
        state["key_provider"] = "claude" if slot == "anthropic_api_key" else "kie"
        ack = f"✅ You're powered up — {result.get('message')}. "
        if state.get("intent") == "stories":
            state["onboarding_step"] = "channel"
            return await _ob_reply(conversation_id, tenant_id, transcript, state,
                ack + "If you have a channel, paste its URL so I can match its vibe (or say “skip”).")
        state["onboarding_step"] = "goals"
        return await _ob_reply(conversation_id, tenant_id, transcript, state,
            ack + "Now — what should I handle for you?", cards=[ONBOARDING_GOALS_CARD])

    if step == "goals":
        goals = sel.get("goals")
        if isinstance(goals, str):
            goals = [goals]
        state["goals"] = goals or ["all"]
        state["onboarding_step"] = "channel"
        return await _ob_reply(conversation_id, tenant_id, transcript, state,
            "Got it. Now connect your channel — paste your YouTube channel URL so I can learn what "
            "works for your audience (or say “skip”).")

    if step == "channel":
        if msg and msg.lower() not in _SKIP_WORDS:
            try:
                from routes.onboarding import YouTubeConnect, connect_youtube
                res = await connect_youtube(YouTubeConnect(channel_url=msg), background_tasks, tenant_id=tenant_id)
                state["channel"] = (res or {}).get("channel_name") or msg
                ack = f"Connected **{state['channel']}** — I'll study it in the background. "
            except Exception as e:  # noqa: BLE001
                logger.warning("onboarding: connect_youtube failed: %s", e)
                ack = "I couldn't read that channel just now, but no worries — we can add it later. "
        else:
            ack = "No problem, skipping that. "
        state["onboarding_step"] = "competitors"
        return await _ob_reply(conversation_id, tenant_id, transcript, state,
            ack + "Now paste 1-3 channels you compete with or admire (URLs or @handles) — I'll pull "
            "winning ideas from them. Or say “skip”.")

    if step == "competitors":
        urls = _parse_urls(msg) if msg.lower() not in _SKIP_WORDS else []
        if urls:
            state["competitors"] = urls[:3]
            try:
                from routes.onboarding import CompetitorAnalyze, analyze_competitors
                res = await analyze_competitors(CompetitorAnalyze(channel_urls=urls[:3]), background_tasks, tenant_id=tenant_id)
                state["competitor_job"] = (res or {}).get("job_id")
                ack = f"On it — analyzing {len(urls[:3])} channel(s) in the background. "
            except Exception as e:  # noqa: BLE001
                logger.warning("onboarding: analyze_competitors failed: %s", e)
                ack = "I'll line those up. "
        else:
            ack = "No competitors for now — you can add them anytime. "
        state["onboarding_step"] = "connect_yt"
        return await _ob_reply(conversation_id, tenant_id, transcript, state,
            ack + "\n\n" + _CONNECT_YT_TEXT, cards=[ONBOARDING_CONNECT_YT_CARD])

    if step == "connect_yt":
        # Either choice advances — analytics is optional and the OAuth callback
        # already stored the tokens if they connected. "connected" arrives via the
        # resume turn ChatHome sends after Google returns to /?connected=yt.
        state["youtube_oauth"] = sel.get("connect_yt") or "skip"
        state["onboarding_step"] = "connect_drive"
        return await _ob_reply(conversation_id, tenant_id, transcript, state,
            _CONNECT_DRIVE_TEXT, cards=[ONBOARDING_CONNECT_DRIVE_CARD])

    if step == "connect_drive":
        state["drive_oauth"] = sel.get("connect_drive") or "skip"
        state["onboarding_step"] = "upsell"
        return await _ob_reply(conversation_id, tenant_id, transcript, state,
            _UPSELL_TEXT, cards=[ONBOARDING_UPSELL_CARD])

    if step == "upsell":
        choice = sel.get("upsell") or ("tell_more" if "more" in msg.lower() else "carry_on")
        if choice == "tell_more" and not state.get("upsell_expanded"):
            state["upsell_expanded"] = True
            return await _ob_reply(conversation_id, tenant_id, transcript, state, _UPSELL_DETAIL,
                cards=[{"id": "upsell", "label": "", "type": "single",
                        "options": [{"value": "carry_on", "label": "Got it — let's create"}]}])
        return await _finish_onboarding(conversation_id, tenant_id, transcript, state, background_tasks)

    if step == "modeling":
        angles = (state.get("modeling") or {}).get("angles") or []
        choice = sel.get("modeling_angle")
        niche = None
        if choice is not None and angles:
            try:
                a = angles[int(choice)]
                niche = a.get("label") or ""
                if a.get("description"):
                    niche = f"{a.get('label')} — {a.get('description')}"
            except (ValueError, IndexError, TypeError):
                niche = None
        elif msg:
            niche = msg  # they typed their own niche
        if not niche:
            return await _ob_reply(conversation_id, tenant_id, transcript, state,
                "Pick a direction above, or just type the niche you want to own.")
        state["niche_angle"] = niche
        await _save_creator_brief(tenant_id, state)  # persist niche before any producer handoff
        ideas = await _generate_competitor_ideas(tenant_id, state, niche=niche)
        if ideas:
            return await _present_ideas_turn(conversation_id, tenant_id, transcript, state, ideas)
        state["mode"] = "producer"
        state["onboarding_step"] = "done"
        text = (
            f"Love it — {niche}. I couldn't pull enough recent competitor data to pitch exact ideas right now, "
            "but tell me a rough topic and I'll build it in that lane."
        )
        fresh = [_assistant_turn({"assistant_text": text, "phase": "asking"})]
        await _persist(conversation_id, tenant_id, fresh, state, "asking")
        return ChatTurnResponse(conversation_id=conversation_id, assistant_text=text, phase="asking")

    if step == "ideas":
        ideas = state.get("pitched_ideas") or []
        choice = sel.get("idea_choice")
        if choice is not None and ideas:
            try:
                idea = ideas[int(choice)]
            except (ValueError, IndexError, TypeError):
                idea = None
            if idea:
                seed = (
                    f"Make this video: \"{idea.get('title')}\". "
                    f"Angle: {(idea.get('reasoning') or '').strip()} "
                    f"Suggested structure: {(idea.get('script_structure') or '').strip()}"
                ).strip()
                return await _seed_producer(conversation_id, tenant_id, state, seed)
        if msg:  # typed their own idea instead of picking one
            return await _seed_producer(conversation_id, tenant_id, state, msg)
        return await _ob_reply(conversation_id, tenant_id, transcript, state,
            "Tap one of the ideas above, or just type your own idea and I'll build it.")

    # Unknown step — recover by handing off to the producer.
    state["mode"] = "producer"
    return await _ob_reply(conversation_id, tenant_id, transcript, state,
        "All set — what should we make first?", phase="asking")


# --- the endpoint ------------------------------------------------------------

@router.post("", response_model=ChatTurnResponse)
async def chat_turn(
    body: ChatTurnRequest,
    background_tasks: BackgroundTasks,
    tenant_id=Depends(get_tenant_id),
):
    # 1. Load or create the conversation (tenant-scoped). The dock sends video_id
    #    with no conversation_id on first open -> find-or-create the ONE conversation
    #    bound to that video so it resumes the whole backstory (Decision A).
    if body.conversation_id:
        conv = await _load_conversation(body.conversation_id, tenant_id)
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
    elif body.video_id:
        conv = await _conversation_for_video(tenant_id, body.video_id)
        if not conv:
            raise HTTPException(status_code=404, detail="Video not found")
    else:
        conv = await _create_conversation(tenant_id)

    conversation_id = str(conv["id"])
    transcript = _as_list(conv.get("transcript"))
    state = _as_dict(conv.get("state"))
    video_id = str(conv["video_id"]) if conv.get("video_id") else None

    # Hydrate durable creator facts (intent/goals/niche/channel/competitors) from a
    # past onboarding so a fresh conversation's producer stays channel-aware. Skip
    # during onboarding — it's actively (re)building the brief.
    if not (body.start_onboarding or state.get("mode") == "onboarding"):
        await _hydrate_creator_brief(tenant_id, state)

    # 1.5 Onboarding ("Start Here") — runs before producer intake. Triggered by the
    # explicit launch button or once a conversation is already in onboarding mode.
    if not video_id and (body.start_onboarding or state.get("mode") == "onboarding"):
        return await _handle_onboarding(
            body, conversation_id, tenant_id, transcript, state, background_tasks
        )

    # 2. Video already exists -> co-pilot turn (read or run a pipeline action).
    #    Supersedes _handle_followup; the dock (request carries video_id) gates paid
    #    actions behind a confirm card, the home CreatedCard keeps immediate runs.
    if video_id:
        return await _handle_copilot(
            body, conversation_id, tenant_id, transcript, state, video_id, background_tasks
        )

    # 3. Approval -> create the video + kick off the pipeline.
    if body.approve and state.get("last_spec"):
        return await _handle_approve(
            state["last_spec"], conversation_id, tenant_id, transcript, state, background_tasks
        )

    # 4. Normal intake turn. Append the user's message and/or card selections.
    user_parts: list[str] = []
    if body.message and body.message.strip():
        user_parts.append(body.message.strip())
    if body.selections:
        user_parts.append(_selections_to_text(body.selections))
        state.setdefault("selections", {}).update(body.selections)

    if not user_parts:
        # Nothing said yet — greet (no Claude call needed).
        if not transcript:
            transcript.append(_assistant_turn({"assistant_text": _GREETING, "phase": "asking"}))
            await _persist(conversation_id, tenant_id, transcript, state, "asking")
        return ChatTurnResponse(
            conversation_id=conversation_id, assistant_text=_GREETING, phase="asking"
        )

    transcript.append({"role": "user", "content": "\n".join(user_parts)})

    # The producer uses the tenant's DIRECT Anthropic key (from Vault). Without
    # one, tell the creator how to add it rather than failing a model call.
    api_key = await get_secret("anthropic_api_key", tenant_id)
    if not api_key:
        msg = (
            "I just need an Anthropic API key to get started. Add one under "
            "Profile → API Keys and tell me your idea again — I'll take it from there."
        )
        transcript.append(_assistant_turn({"assistant_text": msg, "phase": "asking"}))
        await _persist(conversation_id, tenant_id, transcript, state, "asking")
        return ChatTurnResponse(conversation_id=conversation_id, assistant_text=msg, phase="asking")

    # Channel intelligence brief is injected in Phase 4; empty for now.
    system_prompt = build_system_prompt(_creator_brief(state) + await _modeled_runtime_hint(tenant_id))
    data = call_producer(transcript, system_prompt, api_key=api_key)
    _stamp_length_default(data)
    transcript.append(_assistant_turn(data))

    plan = data.get("plan") if isinstance(data.get("plan"), dict) else None
    if plan and isinstance(plan.get("spec"), dict):
        state["last_spec"] = plan["spec"]
    phase = "plan" if plan else "asking"
    await _persist(conversation_id, tenant_id, transcript, state, phase)

    return ChatTurnResponse(
        conversation_id=conversation_id,
        assistant_text=data.get("assistant_text", ""),
        cards=data.get("cards") if isinstance(data.get("cards"), list) else None,
        plan=plan,
        ready_to_create=bool(plan),
        phase=phase,
    )


# --- "Worth modeling" suggestions (home page) ------------------------------
#
# Surface the real top videos from the channel the creator is modeling
# (competitor_videos), ranked by views-per-hour (what's breaking out now), each
# with its metrics + an AI "why model this" analysis cached on the row so the home
# page stays fast. Only appears when the creator actually has competitor data.

def _ago(hours_old) -> str:
    h = float(hours_old or 0)
    if h <= 0:
        return "recently"
    if h < 24:
        return f"{int(round(h))}h ago"
    d = h / 24
    return f"{int(round(d))}d ago" if d < 14 else f"{int(round(d / 7))}w ago"


def _metric_why(r: dict) -> str:
    """Fallback 'why' from the numbers alone, if the AI analysis isn't ready."""
    vph = float(r.get("vph") or 0)
    views = int(r.get("views") or 0)
    fresh = float(r.get("hours_old") or 0) < 72
    lead = "Breaking out" if vph >= 500 else "Strong performer"
    fresh_bit = " and still fresh" if fresh else ""
    return f"{lead}: {views:,} views at ~{vph:.0f}/hr{fresh_bit} — a proven format to model."


async def _model_rationales(tenant_id, rows: list) -> dict:
    """One batched AI call: a punchy 'why model this' per video. Returns
    {video_id: why}. Falls back to the metric line on any failure."""
    fallback = {r["video_id"]: _metric_why(r) for r in rows}
    try:
        from kie_unified import get_text_client_for_tenant
        client = await get_text_client_for_tenant(tenant_id)
    except Exception:  # noqa: BLE001 — no key; metric line is fine
        return fallback
    niche = ""
    try:
        cb = await fetch_one("SELECT creator_brief FROM channel_profiles WHERE tenant_id = $1", tenant_id)
        brief = _as_dict((cb or {}).get("creator_brief"))
        niche = (brief.get("niche") or brief.get("modeling_niche") or brief.get("channel") or "").strip()
    except Exception:  # noqa: BLE001
        pass
    lines = [
        f'{i + 1}. "{r["title"]}" — {int(r["views"] or 0):,} views, {float(r["vph"] or 0):.0f} views/hr, '
        f'{_ago(r.get("hours_old"))}'
        for i, r in enumerate(rows)
    ]
    prompt = (
        "These are the current top videos on a YouTube channel a creator is modeling"
        + (f" (the creator's niche: {niche})" if niche else "") + ":\n"
        + "\n".join(lines)
        + "\n\nFor EACH video, write ONE punchy sentence on why it's worth modeling — cite the concrete "
        "signal (breakout views/hour, freshness, or view count) AND the format/hook pattern that's working, "
        "and how the creator could make it their own. Plain, no hype words.\n"
        'Return ONE JSON object: {"whys": ["...", ...]} with exactly one string per video, in the SAME order.'
    )
    try:
        from producer_prompt import _extract_json
        model = "claude-sonnet-4-6" if type(client).__name__ == "AnthropicDirectClient" else None
        kw: dict[str, Any] = {"prompt": prompt, "max_tokens": 700, "temperature": 0.4}
        if model:
            kw["model"] = model
        data = json.loads(_extract_json((await client.generate(**kw)) or ""))
        whys = data.get("whys") if isinstance(data, dict) else None
        if isinstance(whys, list) and whys:
            return {r["video_id"]: (str(whys[i]).strip() if i < len(whys) and whys[i] else _metric_why(r))
                    for i, r in enumerate(rows)}
    except Exception as e:  # noqa: BLE001
        logger.warning("suggested-models: rationale gen failed: %s", e)
    return fallback


@router.get("/suggested-models")
async def suggested_models(tenant_id=Depends(get_tenant_id)):
    """Top videos worth modeling from the creator's modeled channel, with metrics +
    a cached AI 'why'. Empty when they have no competitor data (the home page then
    falls back to the generic example prompts)."""
    rows = await fetch_all(
        "SELECT video_id, title, url, channel, views, vph, hours_old, model_rationale "
        "FROM competitor_videos WHERE tenant_id = $1 AND views > 0 "
        "ORDER BY vph DESC NULLS LAST LIMIT 5",
        tenant_id,
    )
    if not rows:
        return {"channel": None, "videos": []}
    rows = [dict(r) for r in rows]
    # Generate + cache a rationale for any row that doesn't have one yet.
    missing = [r for r in rows if not (r.get("model_rationale") or "").strip()]
    if missing:
        whys = await _model_rationales(tenant_id, missing)
        for r in missing:
            why = whys.get(r["video_id"])
            r["model_rationale"] = why
            if why:
                await execute(
                    "UPDATE competitor_videos SET model_rationale = $1, model_rationale_at = now() "
                    "WHERE tenant_id = $2 AND video_id = $3",
                    why, tenant_id, r["video_id"],
                )
    videos = [{
        "video_id": r["video_id"],
        "title": r["title"],
        "url": r.get("url"),
        "channel": r.get("channel"),
        "views": int(r.get("views") or 0),
        "vph": round(float(r.get("vph") or 0)),
        "posted": _ago(r.get("hours_old")),
        "thumbnail": f"https://i.ytimg.com/vi/{r['video_id']}/hqdefault.jpg",
        "why": (r.get("model_rationale") or _metric_why(r)),
    } for r in rows]
    return {"channel": rows[0].get("channel"), "videos": videos}


@router.get("/conversation")
async def get_conversation_for_video(video_id: str, tenant_id=Depends(get_tenant_id)):
    """Hydrate the dock on open: the prior messages of this video's conversation,
    flattened to the shape ChatCore renders. Empty when none exists yet — the dock
    then starts a fresh thread (the next turn find-or-creates the row)."""
    conv = await fetch_one(
        """SELECT id, transcript, phase FROM chat_conversations
            WHERE tenant_id = $1 AND video_id = $2
            ORDER BY updated_at DESC LIMIT 1""",
        tenant_id, video_id,
    )
    if not conv:
        return {"conversation_id": None, "messages": [], "phase": "created"}
    messages: list[dict[str, Any]] = []
    for t in _as_list(conv.get("transcript")):
        if t.get("role") == "user":
            messages.append({"role": "user", "text": t.get("content") or ""})
        elif t.get("role") == "assistant":
            d = _as_dict(t.get("content"))  # assistant turns store JSON (see _assistant_turn)
            messages.append({
                "role": "assistant",
                "text": d.get("assistant_text") or "",
                "cards": d.get("cards"),
                "plan": d.get("plan"),
            })
    return {"conversation_id": str(conv["id"]), "messages": messages, "phase": conv.get("phase") or "created"}
