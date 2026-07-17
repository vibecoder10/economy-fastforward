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
import os
import re
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from auth import get_tenant_id
from database import execute, fetch_all, fetch_one
from models import CreateVideoRequest
from producer_prompt import build_system_prompt, call_producer
from vault import get_secret

from actions import (
    ACTIONS as COPILOT_ACTIONS,
    RUNNERS as _ACTION_RUNNERS,
    BUILD_TO_PICTURES as _BUILD_TO_PICTURES,
    CLIP_COST as _CLIP_COST,
    PICTURE_COST as _PICTURE_COST,
    apply_followup_edit as _apply_followup_edit,
    blocked_reason as _action_blocked,
    estimate_cost as _estimate_cost,
    make_action_step as _make_copilot_step,
    make_autobuild_step as _make_autobuild_step,
    video_summary as _copilot_summary,
)

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
YOUTUBE_URL_RE = re.compile(
    r"https?://(?:www\.)?(?:youtube\.com/watch\?v=[^\s&]+|youtu\.be/[^\s?&]+|youtube\.com/shorts/[^\s?&]+)[^\s]*",
    re.I,
)


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
    # Files dropped into the chat this turn: chat_assets ids from POST /api/chat/upload.
    attachments: Optional[list[str]] = None


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


# --- chat asset uploads ("drop it in the chat") -----------------------------
#
# A dropped file becomes a chat_assets row: raw bytes to storage (Drive), the
# parsed content + a one-line summary in the row so the producer can read it
# on every turn without re-fetching. Filing the asset somewhere real (queue /
# script / cast / template) happens via producer ops in later phases.

@router.post("/upload")
async def upload_chat_asset(
    file: UploadFile = File(...),
    conversation_id: Optional[str] = Form(None),
    # Optional: set when the drop happened in a video's docked co-pilot, so the
    # asset is associated with that video from the moment it lands. The home
    # chat sends no video_id — that path is unchanged.
    video_id: Optional[str] = Form(None),
    tenant_id=Depends(get_tenant_id),
):
    import uuid as _uuid

    import asset_intake

    content = await file.read()
    if len(content) > 15 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 15 MB).")
    if not content:
        raise HTTPException(status_code=400, detail="That file is empty.")

    # Verify the video belongs to this tenant before stamping it on — a foreign
    # or stale id must not leak cross-tenant association; fail-soft to unscoped
    # (still uploads fine, just not tied to a video) rather than erroring the drop.
    checked_video_id: Optional[str] = None
    if video_id:
        owns = await fetch_one(
            "SELECT id FROM videos WHERE id = $1 AND tenant_id = $2", video_id, tenant_id
        )
        if owns:
            checked_video_id = video_id
        else:
            logger.warning("chat: upload video_id %s not owned by tenant %s — uploading unscoped", video_id, tenant_id)

    kind = asset_intake.detect_kind(file.filename, file.content_type)
    parsed, parsed_text = None, None
    try:
        if kind == "csv":
            parsed = asset_intake.parse_csv(content)
        elif kind == "pdf":
            parsed_text = asset_intake.parse_pdf(content)
        elif kind == "text":
            parsed_text = asset_intake.parse_text(content)
    except Exception as e:  # noqa: BLE001 — an unreadable file is still an asset
        logger.warning("chat: asset parse failed (%s): %s", file.filename, e)
    summary = asset_intake.summarize_asset(kind, file.filename, parsed, parsed_text)

    asset_id = str(_uuid.uuid4())
    storage_url = None
    try:
        from storage import upload_bytes

        ext = (file.filename or "file.bin").rsplit(".", 1)[-1].lower()[:8] or "bin"
        storage_url = await upload_bytes(
            content, f"chat-assets/{asset_id}.{ext}",
            file.content_type or "application/octet-stream", str(tenant_id),
        )
    except Exception as e:  # noqa: BLE001 — the parsed content is in the row either way
        logger.warning("chat: asset storage upload failed (%s): %s", file.filename, e)

    await execute(
        "INSERT INTO chat_assets (id, tenant_id, conversation_id, video_id, kind, filename, "
        "content_type, storage_url, parsed, parsed_text, summary) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10, $11)",
        asset_id, tenant_id, conversation_id or None, checked_video_id, kind,
        (file.filename or "")[:255] or None, file.content_type,
        storage_url, json.dumps(parsed) if parsed is not None else None,
        parsed_text, summary,
    )

    if kind == "csv" and parsed:
        preview: Any = parsed.get("rows", [])[:5]
    elif kind == "image":
        preview = storage_url
    else:
        preview = (parsed_text or "")[:400] or None
    return {"asset": {"id": asset_id, "kind": kind, "filename": file.filename,
                      "summary": summary, "preview": preview}}


async def _attach_assets(tenant_id, conversation_id, asset_ids, state, user_parts) -> None:
    """Fold this turn's uploaded files into the conversation: bind them to the
    conversation row, describe each in the user turn (so the producer sees what
    arrived), and remember them in state for the assets brief. Fail-soft."""
    try:
        ids = [str(a) for a in (asset_ids or []) if a][:5]
        if not ids:
            return
        rows = await fetch_all(
            "SELECT id, summary FROM chat_assets "
            "WHERE tenant_id = $1 AND id = ANY($2::uuid[]) ORDER BY created_at",
            tenant_id, ids,
        )
        if not rows:
            return
        await execute(
            "UPDATE chat_assets SET conversation_id = $1 "
            "WHERE tenant_id = $2 AND id = ANY($3::uuid[])",
            conversation_id, tenant_id, [str(r["id"]) for r in rows],
        )
        for r in rows:
            user_parts.append(f"[Attached file: {r['summary']}]")
        pending = [str(x) for x in (state.get("pending_assets") or [])]
        pending += [str(r["id"]) for r in rows if str(r["id"]) not in pending]
        state["pending_assets"] = pending[-5:]  # the last few are plenty of context
    except Exception as e:  # noqa: BLE001 — a bad attachment must not kill the turn
        logger.warning("chat: attach assets failed: %s", e)


async def _format_brief(tenant_id) -> str:
    """The channel's kind of video (visual_format), locked or detected.
    Fail-soft: empty when unknown."""
    try:
        from channel_format import get_channel_format
        fmt, locked = await get_channel_format(tenant_id)
        if not fmt:
            return ""
        bits = "; ".join(f"{k}: {v}" for k, v in fmt.items() if v)
        if locked:
            return (f"\n\nCHANNEL FORMAT (locked by the creator): {bits}. Every video is made "
                    "in this format — don't propose formats that contradict it.")
        return (f"\n\nCHANNEL FORMAT (detected, not locked): {bits}. If the creator confirms "
                "this is how their channel works, emit set_channel_format to lock it.")
    except Exception:  # noqa: BLE001
        return ""


async def _script_template_brief(tenant_id) -> str:
    """One line telling the producer the channel's saved house script format.
    Fail-soft: empty string when none."""
    try:
        row = await fetch_one(
            "SELECT name, created_at FROM script_templates WHERE tenant_id = $1 "
            "ORDER BY created_at DESC LIMIT 1",
            tenant_id,
        )
        if not row:
            return ""
        return (
            f"\n\nHOUSE SCRIPT FORMAT: the creator saved a script format template "
            f"(\"{row['name']}\") — every generated script automatically follows it. "
            "If they upload a new example and ask you to remember it, save_script_template replaces the old one."
        )
    except Exception:  # noqa: BLE001
        return ""


async def _assets_brief(tenant_id, state) -> str:
    """What the creator has dropped into this conversation, for the producer.
    Fail-soft: no assets (or any error) -> empty string."""
    try:
        ids = [str(a) for a in (state.get("pending_assets") or [])]
        if not ids:
            return ""
        rows = await fetch_all(
            "SELECT id, kind, filename, summary, status, filed_as FROM chat_assets "
            "WHERE tenant_id = $1 AND id = ANY($2::uuid[]) ORDER BY created_at",
            tenant_id, ids,
        )
        if not rows:
            return ""
        lines = ["\n\nFILES THE CREATOR DROPPED INTO THIS CONVERSATION (use the id in filing ops like queue_titles):"]
        for r in rows:
            where = f" (already filed: {r['filed_as']})" if r.get("filed_as") else " (not filed anywhere yet)"
            lines.append(f"- [{r['kind']}] id={r['id']} {r['summary']}{where}")
        return "\n".join(lines)
    except Exception as e:  # noqa: BLE001
        logger.warning("chat: assets brief failed: %s", e)
        return ""


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


async def _stamp_length_default(data: dict[str, Any], tenant_id=None) -> None:
    """Pre-set the length slider so it opens on a sensible default, not the generic
    1-minute floor. Source order: the producer's recommended_minutes (asking phase),
    else the plan spec's video_length_minutes.

    Deterministic length backstop (GOAL v2 Phase 4): a real channel runtime should
    anchor the default. If we know the typical runtime of the videos this creator
    models and the producer picked a NORMAL-form length below it, open the slider on
    the channel runtime instead — the creator can still drag it down. Intentional
    short-form (< 2 min) is left alone so 'make a 30s short' stays short."""
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
    channel_min = None
    if tenant_id is not None:
        med_s = await _competitor_median_seconds(tenant_id)
        if med_s >= 60:
            channel_min = round(med_s / 60)  # whole minutes, matches the slider's granularity
    for c in cards:
        if not (isinstance(c, dict) and (c.get("id") == "length" or c.get("type") == "slider")):
            continue
        mins = None
        try:
            mins = float(c.get("recommended_minutes")) if c.get("recommended_minutes") is not None else None
        except (TypeError, ValueError):
            mins = None
        mins = mins or spec_min
        # Backstop: anchor a normal-form default up to the channel's real runtime.
        if channel_min:
            if not mins:
                mins = channel_min
            elif 2 <= mins < channel_min:
                mins = channel_min
        if not mins:
            continue
        secs = max(LENGTH_MIN_SECONDS, int(round(mins * 60)))
        if secs > 0:
            c["recommended_seconds"] = secs


def _extract_youtube_url(text: str | None) -> Optional[str]:
    """Return the first YouTube URL from a chat turn, cleaned of trailing prose punctuation."""
    if not text:
        return None
    m = YOUTUBE_URL_RE.search(text)
    if not m:
        return None
    return m.group(0).rstrip("),.]}'\"")


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


# --- pipeline kickoff -------------------------------------------------------
# The autobuild chainer + its checkpoint sets moved to actions.py (PARITY-PLAN
# Phase 1) so chat and the HTTP build route share one implementation.


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
        reference_url=(spec.get("reference_url") or None),
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

# FOLLOWUP_STAGES + the guidance-append writer moved to actions.py
# (apply_followup_edit) — imported above under the old name.


# --- co-pilot (the in-pipeline chat dock) -----------------------------------
#
# A conversation bound to a video can RUN the pipeline by voice. One classifier
# call maps the message + a compact state summary onto a READ (answer a question,
# free) or an ACTION (one pipeline verb, optional scene). Anything that spends
# money or overwrites work is held behind a one-tap confirm card (pending_action
# in the conversation state); reads run immediately. Reuses PipelineExecutor + the
# task-status channel so the pipeline page's existing live trackers reflect work.
# Supersedes _handle_followup (it folds in FOLLOWUP_STAGES via _apply_followup_edit
# for the edit-style verbs). Paid actions ALWAYS confirm first — dock and home
# alike (Phase 2 closed the CreatedCard immediate-run hole).

# The verb registry, prices, prerequisite gates, and cost estimator live in
# actions.py — one source of truth for every door (chat, buttons, agent).
COPILOT_CONFIDENCE = 0.55

# Typed consent for a waiting confirm card: the card is a convenience, not a
# hostage. "yes" / "run it" / "do it" / "write" runs the pending action;
# "no" / "cancel" clears it. (Bug: creators typed 'write' and just got the
# same proposal again.)
_AFFIRM_RE = re.compile(
    r"^\s*(y+e+s+|yep|yeah|ya|ok(ay)?|sure|do it|run( it)?|go( ahead)?|start|"
    r"confirm|proceed|make it|write( it)?|yes please|please do|let'?s (do it|go)|send it)[.!\s]*$", re.I)
_DENY_RE = re.compile(
    r"^\s*(n+o+|nope|cancel|stop|never ?mind|nevermind|don'?t|leave it|not now|hold off)[.!\s]*$", re.I)


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
    # Runner verbs (approvals, lock, Drive sync, SEO…) reuse the same route
    # handlers the UI buttons call and speak the result back directly.
    if cfg.get("runner"):
        return await _ACTION_RUNNERS[cfg["runner"]](tenant_id, video_id, background_tasks, pending)
    background_tasks.add_task(
        _make_copilot_step(tenant_id, video_id, cfg["calls"], scene=scene, start_msg=f"On it — {doing}…")
    )
    return f"On it — {doing} now. I'll update you right here."


async def _handle_copilot(body, conversation_id, tenant_id, transcript, state, video_id, background_tasks):
    """The video-scoped co-pilot turn. Classify -> read (answer) or action (run).
    Paid actions ALWAYS confirm first — dock and home alike (Phase 2 closed the
    home CreatedCard hole where money moved without a tap)."""
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

    # Files dropped into the docked co-pilot: bind them to this conversation
    # (they're already stamped with video_id at upload time — see /api/chat/upload)
    # and fold a description into the transcript so the copilot sees what arrived.
    # Reuses the same _attach_assets the home chat uses — no separate path.
    if body.attachments:
        attach_lines: list[str] = []
        await _attach_assets(tenant_id, conversation_id, body.attachments, state, attach_lines)
        for line in attach_lines:
            transcript.append({"role": "user", "content": line})

    if msg:
        transcript.append({"role": "user", "content": msg})
    if not msg:
        if body.attachments:
            return await _reply(
                "Got it — that's saved to this video. Tell me what you'd like me to do with it "
                "(e.g. use it as a character reference, or work it into the script)."
            )
        return await _reply("Ask me anything about this video, or tell me what to do next — e.g. "
                            "“animate scene 2”, “redo the thumbnail”, or “how much has this cost?”")

    # --- typed consent: a pending confirm answered in words runs (or clears) it ---
    pending = state.get("pending_action")
    if pending and _AFFIRM_RE.match(msg):
        state["pending_action"] = None
        line = await _run_pending_action(tenant_id, video_id, pending, background_tasks)
        return await _reply(line)
    if pending and _DENY_RE.match(msg):
        state["pending_action"] = None
        return await _reply("No problem — left it as it is. Tell me what you'd like instead.")

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

    # Files the creator has dropped into this video's co-pilot (chat_assets rows
    # bound to this conversation) — folded into the summary so the copilot can
    # reference them ("use the reference I dropped", "that image I attached").
    summary_with_assets = _summary_line(summary) + await _assets_brief(tenant_id, state)

    prompt = (
        "You are the in-app co-pilot for ONE video. The creator can (a) ASK a question, (b) tell you to RUN a "
        "production step, or (c) work on a generation PROMPT (view it, get suggestions, or rewrite/enhance it "
        "for a specific shot). Decide which.\n\n"
        + summary_with_assets + "\n"
        + (f"They are currently viewing scene {ui_context.get('scene')}"
           + (f", image {ui_context.get('index')}" if ui_context.get("index") else "")
           + ".\n" if ui_context.get("scene") else "")
        + f'\nThe creator said: "{msg}"\n\n'
        "ACTIONS (kind=action, exact verb): script, characters, storyboards, images, voice, animate, sound, "
        "thumbnail, render, research, seo, upload, approve_cast, approve_environments, skip_environments, "
        "lock, unlock, drive_push, drive_sync, advance — for RUNNING/redoing a SINGLE step. "
        "'advance' = skip the CURRENT stage/gate and move on ('skip this step', 'move on', 'skip research', "
        "'I don't need this'). Note: asking for the script while research hasn't run maps to 'script' — it "
        "skips research automatically. "
        "'characters' = design or REDESIGN the CAST "
        "(the character reference sheets): 'redesign the cast', 'redo the characters', 'regenerate the cast', "
        "'design the characters', 'change how Tom looks'. NEVER map a cast/character request to 'script'. "
        "'animate' is ONE scene (give the scene). "
        "'research' = fact-find the topic (web research) before scripting. "
        "'seo' = write the YouTube title/description/tags. 'upload' = publish the RENDERED video to YouTube. "
        "'approve_cast' = approve/lock the characters ('approve the cast', 'the characters look good, lock them in'). "
        "'approve_environments' = approve/lock the locations; 'skip_environments' = this video needs no "
        "distinct locations ('skip the locations', 'no locations needed'). "
        "'lock' / 'unlock' = freeze or unfreeze the story(boards) before image spend. "
        "'drive_push' = send the script to Google Drive as an editable Doc; 'drive_sync' = pull the creator's "
        "Doc edits back into the app ('pull my script from Drive', 'sync my Doc changes'). "
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
        '"verb":"script|characters|storyboards|images|voice|animate|sound|thumbnail|render|research|seo|'
        'upload|approve_cast|approve_environments|skip_environments|lock|unlock|drive_push|drive_sync|advance|build|none",'
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
    # THE AGENT BRAIN (Phase 6): a tool-using loop that READS the video (state,
    # script, shots, prompts, history) before deciding, then returns the same
    # decision shape as the one-shot classifier. Any failure -> None -> the
    # legacy classifier below runs instead, so the brain can only add smarts.
    data = None
    try:
        from agent_brain import run_copilot_brain
        data = await run_copilot_brain(client, copilot_model, tenant_id, video_id,
                                       summary, msg, ui_context, summary_with_assets)
    except Exception as e:  # noqa: BLE001
        logger.warning("copilot: agent brain failed, falling back: %s", e)
    if data is None:
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

    # Paid: ALWAYS held behind a one-tap confirm card — dock and home alike.
    # (Phase 2 closed the hole where the home CreatedCard follow-up spent money
    # with no tap; the home chat renders the same confirm card.)
    pending = {"verb": verb, "scene": scene, "change": (data.get("change") or "").strip(),
               "length_min": data.get("length_min")}
    if verb == "build":
        # To pictures if we're before them, else finish the rest.
        pending["target"] = "pictures" if summary["status"] in _BUILD_TO_PICTURES else "finish"

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
_CLAUDE_KEY_URL = "https://console.anthropic.com/settings/keys"
_KEY_PROMPT = (
    "Quick bit of setup: StoryEngine runs on **your own AI key**, so your work stays "
    "private and you only pay for what you make. Start with **Kie.ai** — one key powers "
    "scripts, voices, images, and video.\n\n"
    "**Get your key in about 2 minutes:**\n"
    f"1. [Open kie.ai to create your key →]({_KEY_URL}) — sign up and add a few dollars of credit\n"
    "2. Click **Create API Key**, then copy it\n"
    "3. Paste it into the secure box below 👇\n\n"
    "Already have an Anthropic (Claude) key? Paste that here instead — I'll detect it automatically."
)
# After the required Kie key lands, we offer Claude as an optional speed upgrade.
# Direct-to-Anthropic skips Kie's gateway hop, so text (scripts, ideas, hooks) is
# faster. Kie still does the images, video, and voices — this is additive, not a
# second required step. Skipping is always fine.
_CLAUDE_OFFER = (
    "Want it **faster**? Add a **Claude** key too — totally optional. StoryEngine sends "
    "all the text work (scripts, ideas, hooks) straight to Claude, which is quicker than "
    "routing it through Kie. Kie keeps doing your images, video, and voices.\n\n"
    f"Grab one at [console.anthropic.com →]({_CLAUDE_KEY_URL}) → **API Keys** → **Create Key**, "
    "then paste it into the secure box below. Or skip — Kie already does everything."
)


def _secure_key_card(*, optional: bool) -> dict:
    """The inline secure key box (same masked input the Settings page uses). The
    frontend renders id 'secure_key' as a password field that POSTs straight to
    /api/chat/onboarding-key, so the raw key never rides in as a chat message.
    `optional` adds a Skip button (used for the Claude upgrade step)."""
    if optional:
        return {
            "id": "secure_key",
            "label": "Add your Claude key (optional — faster text)",
            "type": "single",
            "placeholder": "Paste your Claude API key — it stays hidden",
            "options": [{"value": "skip", "label": "Skip for now"}],
        }
    # Required step. Name the key explicitly (Kie.ai) so it's unambiguous which
    # one to paste — though the backend still auto-detects a Claude key if that's
    # what the creator pastes here instead.
    return {
        "id": "secure_key",
        "label": "Paste your Kie.ai key",
        "type": "single",
        "placeholder": "Paste your Kie.ai API key — it stays hidden",
        "options": [],
    }


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


async def _after_key_setup(conversation_id, tenant_id, transcript, state, ack):
    """Key(s) are in the Vault — move on to channel (storytellers) or goals.
    Shared by every path out of the key steps so the next prompt stays identical."""
    if state.get("intent") == "stories":
        state["onboarding_step"] = "channel"
        return await _ob_reply(conversation_id, tenant_id, transcript, state,
            ack + "If you have a channel, paste its URL so I can match its vibe (or say “skip”).")
    state["onboarding_step"] = "goals"
    return await _ob_reply(conversation_id, tenant_id, transcript, state,
        ack + "Now — what should I handle for you?", cards=[ONBOARDING_GOALS_CARD])


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


async def _competitor_median_seconds(tenant_id) -> int:
    """Median runtime (seconds) of the videos this creator models. The shared length
    anchor for both the producer hint and the slider backstop. 0 if unknown. Fail-soft."""
    try:
        row = await fetch_one(
            "SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY duration_seconds) AS med "
            "FROM competitor_videos WHERE tenant_id = $1 AND duration_seconds > 0 AND removed_at IS NULL",
            tenant_id,
        )
        return int((row or {}).get("med") or 0)
    except Exception:  # noqa: BLE001
        return 0


async def _modeled_runtime_hint(tenant_id) -> str:
    """A length anchor for the producer: the typical runtime of the videos this creator
    models (their competitors' winners). Real data — competitor_videos.duration_seconds is
    populated at modeling time. Fail-soft; empty when there's nothing solid to anchor on."""
    med = await _competitor_median_seconds(tenant_id)
    if med < 30:
        return ""
    return (f"\nLENGTH ANCHOR: the videos this creator models typically run ~{_format_runtime(med)}. "
            "Lean toward that as your recommended length unless the specific story clearly needs "
            "shorter or longer — and say so.")


async def _reference_brief(state: dict, reference_url: str | None) -> str:
    """When the creator is modeling a specific YouTube video, fetch its REAL public
    data (title, channel, views, runtime, what it's actually about) and hand it to
    the producer so the proposal is grounded in THE REFERENCE, not invented from the
    creator's own channel persona. Without this the producer hallucinates a title
    from past videos (e.g. an ESL-kids title for a trucking documentary). Uses the
    YouTube Data API (YOUTUBE_API_KEY) which, unlike yt-dlp scraping, is not
    IP-bot-blocked. Cached in state per URL. Fail-soft -> ''."""
    if not reference_url:
        return ""
    if state.get("_ref_brief_for") == reference_url:
        return state.get("_ref_brief") or ""
    brief = ""
    try:
        api_key = os.getenv("YOUTUBE_API_KEY", "").strip()
        from routes.model_video import _parse_youtube_id
        yid = _parse_youtube_id(reference_url) if reference_url else None
        info = None
        if api_key and yid:
            from youtube_data_api import fetch_single_video
            info = await fetch_single_video(yid, api_key)
        if info and info.get("title"):
            dur = int(info.get("duration_seconds") or 0)
            runtime = _format_runtime(dur) if dur else "unknown"
            views = int(info.get("views") or 0)
            desc = " ".join((info.get("description") or "").split())
            if len(desc) > 600:
                desc = desc[:600].rstrip() + "..."
            lines = [
                "\n--- THE REFERENCE VIDEO THIS CREATOR IS MODELING (REAL DATA, GROUND YOUR PROPOSAL IN THIS) ---",
                f"Title: {info['title']}",
                f"Channel: {info.get('channel') or 'unknown'}",
                f"Views: {views:,}   Runtime: ~{runtime}   Published: {info.get('published_at') or 'unknown'}",
            ]
            if desc:
                lines.append(f"What it's actually about: {desc}")
            lines.append(
                "Propose a concrete new TITLE that adapts THIS video's proven formula AND its "
                "actual subject and genre to the creator: keep its hook structure and topic lane. "
                "Do NOT snap back to an unrelated topic from the creator's past videos. Anchor the "
                f"recommended length to this video's runtime (~{runtime})."
            )
            brief = "\n".join(lines) + "\n"
    except Exception as e:  # noqa: BLE001
        logger.warning("chat: reference brief fetch failed: %s", e)
        brief = ""
    state["_ref_brief_for"] = reference_url
    state["_ref_brief"] = brief
    return brief


# --- analyze any video (PARITY-PLAN Phase 7) ---------------------------------

_ANALYZE_RE = re.compile(
    r"\b(analyz|analys|break\s?down|deconstruct|study this|"
    r"why (does|do) (this|it|that) work|what makes (this|it|that) work)", re.I)


def _analyze_intent(text: str | None) -> bool:
    return bool(text and _ANALYZE_RE.search(text))


def _dna_brief(state: dict) -> str:
    """The distilled DNA of the video being modeled, for the producer. Set by
    _handle_analyze; cleared naturally when a new conversation starts."""
    dna = state.get("video_dna")
    if not dna:
        return ""
    return ("\n--- FULL DNA OF THE REFERENCE VIDEO (distilled from its ACTUAL content — ground "
            "any recreation in THIS: same hook shape, same structure, same pacing, our subject "
            "and identity) ---\n" + json.dumps(dna)[:2400] + "\n")


async def _handle_analyze(conversation_id, tenant_id, transcript, state, url: str):
    """'Analyze this video' — the commander move: read ANY YouTube video and
    report why it works, then hold its DNA so 'make it' recreates it as ours.

    Two layers, fail-soft: (1) real public metadata via the YouTube Data API
    (never bot-blocked); (2) full DNA via the intelligence distiller (yt-dlp
    transcript -> Claude -> hook/structure/topics). YouTube sometimes bot-blocks
    yt-dlp from the server IP, so layer 2 failing still yields a useful
    metadata-grounded report instead of an error."""
    info = None
    try:
        api_key = os.getenv("YOUTUBE_API_KEY", "").strip()
        from routes.model_video import _parse_youtube_id
        yid = _parse_youtube_id(url)
        if api_key and yid:
            from youtube_data_api import fetch_single_video
            info = await fetch_single_video(yid, api_key)
    except Exception as e:  # noqa: BLE001
        logger.warning("chat: analyze metadata fetch failed: %s", e)

    meta_lines: list[str] = []
    if info and info.get("title"):
        dur = int(info.get("duration_seconds") or 0)
        views = int(info.get("views") or 0)
        meta_lines = [
            f"“{info['title']}” — {info.get('channel') or 'unknown channel'}",
            f"{views:,} views · ~{_format_runtime(dur) if dur else '?'} · published {str(info.get('published_at') or 'unknown')[:10]}",
        ]

    dna_summary, dna_meta, dna_err = None, None, None
    try:
        from routes.intelligence import DistillURLRequest, distill_from_url
        res = await asyncio.wait_for(
            distill_from_url(DistillURLRequest(url=url), tenant_id=tenant_id), timeout=90)
        res = res or {}
        dna_summary = res.get("summary")
        dna_meta = res.get("dna") if isinstance(res.get("dna"), dict) else None
        if not (dna_summary or dna_meta) and res.get("status") != "distilled":
            dna_err = "the deep pass couldn't read its content"
    except HTTPException as e:
        dna_err = e.detail if isinstance(e.detail, str) else "couldn't pull the video content"
    except asyncio.TimeoutError:
        dna_err = "the deep analysis timed out"
    except Exception as e:  # noqa: BLE001
        logger.warning("chat: analyze distill failed: %s", e)
        dna_err = "couldn't pull the video content"

    if not meta_lines and not dna_summary and not dna_meta:
        text = ("I couldn't read that video at all — it may be private, removed, or the link is off. "
                "Try another link?")
        transcript.append(_assistant_turn({"assistant_text": text, "phase": "asking"}))
        await _persist(conversation_id, tenant_id, transcript, state, "asking")
        return ChatTurnResponse(conversation_id=conversation_id, assistant_text=text, phase="asking")

    parts: list[str] = ["Here's the breakdown:"]
    if meta_lines:
        parts += [""] + meta_lines
    if dna_summary:
        parts += ["", str(dna_summary).strip()[:900]]
    if dna_meta:
        shown = 0
        for k, v in dna_meta.items():
            if v in (None, "", [], {}):
                continue
            val = ", ".join(str(x) for x in v) if isinstance(v, list) else str(v)
            parts.append(f"- {str(k).replace('_', ' ').title()}: {val[:280]}")
            shown += 1
            if shown >= 8:
                break
    if (dna_summary or dna_meta):
        # Trim before persisting: conversation state rides along on every turn.
        slim = {}
        for k, v in (dna_meta or {}).items():
            if v in (None, "", [], {}):
                continue
            slim[str(k)[:60]] = (", ".join(str(x) for x in v) if isinstance(v, list) else str(v))[:400]
            if len(slim) >= 12:
                break
        state["video_dna"] = {"summary": str(dna_summary or "")[:1200], "dna": slim}
    elif dna_err:
        parts += ["", f"(I could only read the public data — {dna_err}. The read above is from "
                      "metadata; I can still model the format.)"]

    state["pending_reference_url"] = url
    parts += ["", "Want it as YOURS? Say “make it” and I'll recreate this structure on your "
                  "channel — or tell me what to change first."]
    text = "\n".join(parts)
    transcript.append(_assistant_turn({"assistant_text": text, "phase": "asking"}))
    await _persist(conversation_id, tenant_id, transcript, state, "asking")
    return ChatTurnResponse(conversation_id=conversation_id, assistant_text=text, phase="asking")


_URL_RE = re.compile(r"https?://[^\s)]+", re.I)


def _first_url(text: str | None) -> Optional[str]:
    """First http(s) URL in a string (any host, not just YouTube watch links)."""
    if not text:
        return None
    m = _URL_RE.search(text)
    return m.group(0).rstrip("),.]}'\"") if m else None


async def _profile_state_brief(tenant_id) -> str:
    """The creator's CURRENT channel setup, so the producer can confirm and edit it
    against real values: the competitor channels on file plus the saved channel
    name / niche / audience / default look. Fail-soft -> ''."""
    lines: list[str] = []
    try:
        comps = await fetch_all(
            "SELECT channel_name, channel_url FROM competitor_channels "
            "WHERE tenant_id = $1 AND active = true ORDER BY channel_name",
            tenant_id,
        ) or []
        if comps:
            names = ", ".join((c.get("channel_name") or c.get("channel_url") or "?") for c in comps[:12])
            lines.append(f"Competitor channels on file ({len(comps)}): {names}")
        else:
            lines.append("Competitor channels on file: none yet.")
    except Exception as e:  # noqa: BLE001
        logger.warning("chat: profile state (competitors) failed: %s", e)
    try:
        row = await fetch_one(
            "SELECT channel_name, niche, target_audience, style_description "
            "FROM channel_profiles WHERE tenant_id = $1",
            tenant_id,
        )
        if row:
            if row.get("channel_name"):
                lines.append(f"Saved channel name: {row['channel_name']}")
            if row.get("niche"):
                lines.append(f"Saved niche: {row['niche']}")
            if row.get("target_audience"):
                lines.append(f"Saved audience: {row['target_audience']}")
            if row.get("style_description"):
                lines.append(f"Saved default look: {row['style_description']}")
    except Exception as e:  # noqa: BLE001
        logger.warning("chat: profile state (profile) failed: %s", e)
    if not lines:
        return ""
    return ("\n--- THIS CREATOR'S CURRENT SETUP (you can change any of this when they ask) ---\n"
            + "\n".join(lines) + "\n")


async def _delete_competitor(tenant_id, channel_id) -> None:
    """Remove a competitor channel and cascade-delete its scraped videos, matching
    the niche.remove_channel route's cascade so analytics don't orphan."""
    ch = await fetch_one(
        "SELECT channel_url, channel_name FROM competitor_channels WHERE id = $1 AND tenant_id = $2",
        channel_id, tenant_id,
    )
    if ch:
        url = ch.get("channel_url") or ""
        name = ch.get("channel_name") or ""
        key_col, key_val = ("channel_url", url) if url else (("channel", name) if name else (None, None))
        if key_col:
            await execute(
                f"UPDATE discovery_ideas SET competitor_video_id = NULL WHERE tenant_id = $1 "
                f"AND competitor_video_id IN (SELECT id FROM competitor_videos "
                f"WHERE tenant_id = $1 AND {key_col} = $2)",
                tenant_id, key_val,
            )
            await execute(
                f"DELETE FROM competitor_videos WHERE tenant_id = $1 AND {key_col} = $2",
                tenant_id, key_val,
            )
    await execute(
        "DELETE FROM competitor_channels WHERE id = $1 AND tenant_id = $2",
        channel_id, tenant_id,
    )


# Profile-edit ops the producer may emit -> channel_profiles columns.
_PROFILE_FIELD_COLS = {
    "set_channel_name": "channel_name",
    "set_niche": "niche",
    "set_audience": "target_audience",
    "set_visual_style": "style_description",
}
_PROFILE_FIELD_LABELS = {
    "set_channel_name": "channel name",
    "set_niche": "niche",
    "set_audience": "audience",
    "set_visual_style": "default look",
}


async def _apply_profile_ops(tenant_id, ops, state, background_tasks) -> list[str]:
    """Execute the producer's requested profile / competitor changes against the real
    tables and return short, TRUTHFUL confirmation lines (so we never claim a change
    the database didn't accept). Adding a competitor runs the existing add+scrape job
    in the background. Fail-soft per op."""
    results: list[str] = []
    if not isinstance(ops, list):
        return results
    for op in ops:
        if not isinstance(op, dict):
            continue
        kind = str(op.get("op") or "").strip()
        val = str(op.get("value") or "").strip()
        if not kind:
            continue
        try:
            if kind == "add_competitor":
                url = _first_url(val) or (val if "youtu" in val.lower() else "")
                if not url or "youtu" not in url.lower():
                    results.append(f"To add a competitor I need its YouTube channel link, and \"{val}\" isn't one.")
                    continue
                if background_tasks is None:
                    results.append(f"Add {url} from the Competitors page, I can't pull it in from here right now.")
                    continue
                import uuid as _uuid
                # _run_competitor_analysis reports progress through onboarding's
                # in-memory _analyze_jobs dict and does `_analyze_jobs[job_id]` up
                # front, so the entry MUST exist before we schedule it (same shape
                # the /competitors/analyze route registers).
                from routes.onboarding import _run_competitor_analysis, _analyze_jobs
                job_id = _uuid.uuid4().hex[:8]
                _analyze_jobs[job_id] = {
                    "tenant_id": tenant_id,
                    "status": "starting",
                    "channels_total": 1,
                    "channels_complete": 0,
                    "current_channel": None,
                    "channel_results": {},
                    "intelligence_ready": False,
                    "error": None,
                }
                background_tasks.add_task(_run_competitor_analysis, job_id, tenant_id, [url])
                results.append(f"Added {url} to your competitors, pulling its top videos now.")
            elif kind == "remove_competitor":
                row = await fetch_one(
                    "SELECT id, channel_name FROM competitor_channels "
                    "WHERE tenant_id = $1 AND (lower(channel_name) = lower($2) OR channel_url = $2) LIMIT 1",
                    tenant_id, val,
                )
                if not row:
                    results.append(f"Couldn't find a competitor matching \"{val}\" to remove.")
                    continue
                await _delete_competitor(tenant_id, row["id"])
                results.append(f"Removed {row.get('channel_name') or val} from your competitors.")
            elif kind == "queue_titles":
                # value: {"asset_id": "<chat_assets id>", "column": "<optional>"}
                # or {"titles": ["...", ...]} for titles given in conversation.
                raw = op.get("value") if isinstance(op.get("value"), dict) else {}
                from routes.queue import add_queue_items, queue_titles_from_asset
                titles = [str(t).strip() for t in (raw.get("titles") or []) if str(t).strip()]
                asset_id = str(raw.get("asset_id") or "").strip()
                if asset_id and not titles:
                    n, err = await queue_titles_from_asset(tenant_id, asset_id, raw.get("column"))
                    if err:
                        results.append(err)
                        continue
                elif titles:
                    n = await add_queue_items(tenant_id, [{"title": t} for t in titles])
                else:
                    results.append("I need the uploaded file (or the titles themselves) to queue anything.")
                    continue
                results.append(
                    f"Queued {n} video{'s' if n != 1 else ''} — they're on your calendar in that "
                    "order, first slots. Autopilot will build them one by one when it's on, or "
                    "hit Build on any of them from the Calendar page."
                )
            elif kind == "use_script_for_video":
                # value: {"asset_id": "<chat_assets id>", "title": "<or null>"}
                raw = op.get("value") if isinstance(op.get("value"), dict) else {}
                asset_id = str(raw.get("asset_id") or "").strip()
                title = str(raw.get("title") or "").strip()
                if not asset_id:
                    results.append("I need the uploaded script file to do that — drop it in again?")
                    continue
                arow = await fetch_one(
                    "SELECT id, filename, parsed_text FROM chat_assets WHERE id = $1 AND tenant_id = $2",
                    asset_id, tenant_id,
                )
                text_body = ((arow or {}).get("parsed_text") or "").strip()
                if not text_body:
                    results.append(
                        "I couldn't read any text out of that file, so I can't use it as a "
                        "script — paste the script here instead?"
                    )
                    continue
                if not title:
                    title = await _derive_script_title(tenant_id, text_body) or (
                        (arow.get("filename") or "Untitled script").rsplit(".", 1)[0]
                    )
                from models import CreateVideoRequest as _CVR
                from routes.videos import create_video as _create_video
                words = len(text_body.split())
                req = _CVR(title=title[:200], video_length_minutes=max(1, round(words / 150)))
                try:
                    summary = await _create_video(body=req, background_tasks=background_tasks, tenant_id=tenant_id)
                except HTTPException as e:
                    results.append(
                        "Looks like you're out of video credits on your plan — upgrade and I'll get right on it."
                        if e.status_code == 402
                        else "I couldn't create that video — mind trying again?"
                    )
                    continue
                from user_script import set_user_script
                sres = await set_user_script(tenant_id, summary.id, text_body)
                await execute(
                    "UPDATE chat_assets SET status = 'filed', filed_as = 'video_script' "
                    "WHERE id = $1 AND tenant_id = $2",
                    asset_id, tenant_id,
                )
                results.append(
                    f"Created \"{title}\" using your script word for word — {sres['scenes']} "
                    "scenes, ready for voice. Say the word when you want production to start "
                    "(that part costs money)."
                )
            elif kind == "save_script_template":
                # value: {"asset_id": "<chat_assets id>" | "text": "...", "name": "<or empty>"}
                raw = op.get("value") if isinstance(op.get("value"), dict) else {}
                text_body = str(raw.get("text") or "").strip()
                asset_id = str(raw.get("asset_id") or "").strip() or None
                if not text_body and asset_id:
                    arow = await fetch_one(
                        "SELECT parsed_text FROM chat_assets WHERE id = $1 AND tenant_id = $2",
                        asset_id, tenant_id,
                    )
                    text_body = ((arow or {}).get("parsed_text") or "").strip()
                if not text_body:
                    results.append(
                        "I couldn't read the example script to learn its format — paste it here instead?"
                    )
                    continue
                from routes.script_templates import analyze_and_save_template
                try:
                    tpl = await analyze_and_save_template(
                        tenant_id, text_body, str(raw.get("name") or ""), asset_id
                    )
                except ValueError as e:
                    results.append(str(e))
                    continue
                if asset_id:
                    await execute(
                        "UPDATE chat_assets SET status = 'filed', filed_as = 'template' "
                        "WHERE id = $1 AND tenant_id = $2",
                        asset_id, tenant_id,
                    )
                results.append(
                    f"Learned your script format (\"{tpl['name']}\") — every script I write "
                    "from now on follows it. Drop in a new example any time to replace it."
                )
            elif kind == "lock_cast":
                # value: {"asset_ids": ["<chat_assets image ids>"]}
                raw = op.get("value") if isinstance(op.get("value"), dict) else {}
                ids = [str(a).strip() for a in (raw.get("asset_ids") or []) if str(a).strip()]
                if not ids:
                    results.append("I need the character-sheet images to lock in — drop them into the chat.")
                    continue
                arows = await fetch_all(
                    "SELECT id, filename, storage_url FROM chat_assets "
                    "WHERE tenant_id = $1 AND id = ANY($2::uuid[]) AND kind = 'image' "
                    "AND storage_url IS NOT NULL ORDER BY created_at",
                    tenant_id, ids,
                )
                if not arows:
                    results.append("I couldn't find those images — drop the character sheets in again?")
                    continue
                from routes.characters import lock_project_cast
                try:
                    merged = await lock_project_cast(
                        tenant_id,
                        [{"url": r["storage_url"]} for r in arows],
                    )
                except ValueError as e:
                    results.append(str(e))
                    continue
                await execute(
                    "UPDATE chat_assets SET status = 'filed', filed_as = 'cast' "
                    "WHERE tenant_id = $1 AND id = ANY($2::uuid[])",
                    tenant_id, [str(r["id"]) for r in arows],
                )
                names = ", ".join(c["name"] for c in merged[:8])
                results.append(
                    f"Locked in your channel cast: {names}. Every new video uses these exact "
                    "character sheets and skips character generation — they're brand assets now. "
                    "Manage them under Profile → Channel cast."
                )
            elif kind == "set_channel_format":
                # value: {"style": ..., "motion": ..., "segmentation": ..., "on_camera": ...}
                raw = op.get("value") if isinstance(op.get("value"), dict) else {}
                from channel_format import FORMAT_FIELDS, set_channel_format, style_preset_for_format
                fields = {k: raw.get(k) for k in FORMAT_FIELDS if raw.get(k)}
                if not fields:
                    results.append("Tell me the format in a sentence and I'll lock it in — e.g. \"animated 2D dialogue scenes, no one on camera\".")
                    continue
                fmt = await set_channel_format(tenant_id, fields)
                preset = style_preset_for_format(fmt)
                bits = "; ".join(f"{k}: {v}" for k, v in fmt.items() if v)
                extra = f" New videos default to the {preset} look." if preset else ""
                results.append(f"Locked your channel format ({bits}).{extra} Every build shapes itself to it.")
            elif kind in _PROFILE_FIELD_COLS:
                if not val:
                    continue
                col = _PROFILE_FIELD_COLS[kind]
                await execute(
                    f"INSERT INTO channel_profiles (tenant_id, {col}) VALUES ($1, $2) "
                    f"ON CONFLICT (tenant_id) DO UPDATE SET {col} = $2, updated_at = now()",
                    tenant_id, val,
                )
                if kind == "set_niche":
                    state["niche_angle"] = val
                elif kind == "set_channel_name":
                    state["channel"] = val
                results.append(f"Updated your {_PROFILE_FIELD_LABELS[kind]} to \"{val}\".")
        except Exception as e:  # noqa: BLE001
            logger.warning("chat: profile op %s failed: %s", kind, e)
            results.append("I hit a snag saving one of those changes, mind trying again?")
    return results


async def _derive_script_title(tenant_id, text: str) -> str:
    """One cheap model call: name the video from the creator's script opening.
    Empty string on any failure (caller falls back to the filename)."""
    try:
        from kie_unified import get_text_client_for_tenant
        client = await get_text_client_for_tenant(tenant_id)
        kwargs = {"model": "claude-sonnet-4-6"} if type(client).__name__ == "AnthropicDirectClient" else {}
        raw = await client.generate(
            prompt=(
                "Here is the opening of a video script:\n\n" + text[:2000] +
                "\n\nWrite ONE YouTube-ready title for this video. Reply with the title only, no quotes."
            ),
            max_tokens=60, temperature=0.7, **kwargs,
        )
        return (raw or "").strip().strip('"').splitlines()[0].strip()[:200]
    except Exception as e:  # noqa: BLE001
        logger.warning("chat: script title derivation failed: %s", e)
        return ""


async def _apply_and_merge_profile_ops(data, tenant_id, state, background_tasks) -> str:
    """Run any profile_ops the producer emitted, fold the TRUTHFUL result lines into
    the turn's assistant_text (so the creator sees exactly what actually changed, not
    just what the model promised), and return the final text. Mutates `data` so the
    saved transcript matches what we show. Returns the (possibly unchanged) text."""
    text = data.get("assistant_text", "") or ""
    ops = data.get("profile_ops")
    # Models sometimes invent a sibling key for filing ops (seen live: "queue_ops")
    # instead of using profile_ops — accept those rather than silently dropping
    # the creator's request on the floor.
    for alt_key in ("queue_ops", "file_ops", "asset_ops"):
        alt = data.get(alt_key)
        if isinstance(alt, list) and alt:
            ops = (ops if isinstance(ops, list) else []) + alt
    if ops:
        results = await _apply_profile_ops(tenant_id, ops, state, background_tasks)
        if results:
            joined = "\n".join(results)
            text = f"{text}\n\n{joined}".strip() if text else joined
            data["assistant_text"] = text
    return text


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


# --- Channel intelligence brief (Phase 2) ----------------------------------
#
# A cached, data-backed picture of the channel the creator models — top winning
# titles, the recurring title/hook pattern, thumbnail motifs, upload cadence —
# mined from competitor_videos and fed into EVERY producer turn so the chat's
# suggestions are genuinely modeled, not generic. Lazy-first: computed on demand,
# cached on channel_profiles.channel_intel, recomputed only when stale. All
# fail-soft — channel intelligence is a bonus, it must never block a turn.

_CHANNEL_INTEL_TTL_S = 12 * 3600  # recompute at most twice a day


async def _compute_channel_intel(tenant_id, api_key) -> dict:
    """Mine competitor_videos for the channel's real winning patterns. Cheap:
    deterministic SQL aggregates over existing columns + ONE small Claude distill
    for the title/hook pattern and thumbnail motifs. Returns {} when there isn't
    enough real data to model (fewer than 3 videos with views)."""
    import asyncio
    import time
    try:
        rows = await fetch_all(
            """SELECT title, views, vph, duration_seconds, thumbnail_style_json, published_date
                 FROM competitor_videos
                WHERE tenant_id = $1 AND views > 0 AND title IS NOT NULL AND removed_at IS NULL
                ORDER BY vph DESC NULLS LAST, views DESC NULLS LAST
                LIMIT 12""",
            tenant_id,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("chat: channel_intel query failed: %s", e)
        return {}
    rows = [dict(r) for r in (rows or [])]
    if len(rows) < 3:
        return {}

    top_titles = [r["title"] for r in rows if r.get("title")][:8]

    durs = sorted(int(r["duration_seconds"]) for r in rows if r.get("duration_seconds"))
    median_runtime_s = durs[len(durs) // 2] if durs else 0

    cadence_days = 0
    dates = sorted(d for d in (r.get("published_date") for r in rows) if d)
    if len(dates) >= 2:
        gaps = sorted((dates[i + 1] - dates[i]).days for i in range(len(dates) - 1))
        cadence_days = gaps[len(gaps) // 2]

    # Raw thumbnail-style snippets we already have (no new vision spend) — fed to
    # the distill so it can name the recurring motifs.
    thumb_snippets: list[str] = []
    for r in rows:
        tj = r.get("thumbnail_style_json")
        if tj and isinstance(tj, str) and tj.strip():
            thumb_snippets.append(tj.strip()[:300])
        if len(thumb_snippets) >= 6:
            break

    hook_pattern = ""
    thumbnail_motifs: list[str] = []
    if api_key and top_titles:
        try:
            prompt = (
                "A YouTube channel's top-performing videos. Find what repeats.\n\n"
                "TOP TITLES:\n" + "\n".join(f"- {t}" for t in top_titles)
            )
            if thumb_snippets:
                prompt += "\n\nTHUMBNAIL STYLE NOTES:\n" + "\n".join(f"- {s}" for s in thumb_snippets)
            prompt += (
                "\n\nIn ONE sentence, describe the recurring TITLE/HOOK pattern that drives the "
                "clicks (structure + emotional trigger + formula). Also list up to 4 recurring "
                "THUMBNAIL MOTIFS (short noun phrases) if the notes show any.\n"
                'Return ONE JSON object and nothing else: {"pattern":"...","thumbnail_motifs":["..."]}.'
            )
            data = await asyncio.to_thread(_claude_json, api_key, prompt, 400)
            if isinstance(data, dict):
                hook_pattern = str(data.get("pattern") or "").strip()
                motifs = data.get("thumbnail_motifs")
                if isinstance(motifs, list):
                    thumbnail_motifs = [str(m).strip() for m in motifs if str(m).strip()][:4]
        except Exception as e:  # noqa: BLE001
            logger.warning("chat: channel_intel distill failed: %s", e)

    return {
        "top_titles": top_titles,
        "hook_pattern": hook_pattern,
        "thumbnail_motifs": thumbnail_motifs,
        "median_runtime_s": median_runtime_s,
        "cadence_days": cadence_days,
        "computed_at": time.time(),
    }


async def _get_channel_intel(tenant_id) -> dict:
    """Return the cached channel-intel dict, recomputing when missing or stale.
    Fail-soft: returns {} (never raises) so a bad turn just loses the bonus."""
    import time
    try:
        row = await fetch_one(
            "SELECT channel_intel FROM channel_profiles WHERE tenant_id = $1", tenant_id
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("chat: channel_intel read failed: %s", e)
        return {}
    intel = _as_dict((row or {}).get("channel_intel"))
    if intel and (time.time() - float(intel.get("computed_at") or 0)) < _CHANNEL_INTEL_TTL_S:
        return intel
    api_key = await get_secret("anthropic_api_key", tenant_id)
    fresh = await _compute_channel_intel(tenant_id, api_key)
    if not fresh:
        return intel  # keep the last good cache if we couldn't refresh
    try:
        await execute(
            "UPDATE channel_profiles SET channel_intel = $2::jsonb, updated_at = now() "
            "WHERE tenant_id = $1",
            tenant_id, json.dumps(fresh),
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("chat: channel_intel write failed: %s", e)
    return fresh


async def _channel_intel_brief(tenant_id) -> str:
    """Format the cached channel intel as a compact block for the producer system
    prompt. Empty string when there's no intel yet (fail-soft)."""
    intel = await _get_channel_intel(tenant_id)
    if not intel:
        return ""
    bits: list[str] = []
    titles = intel.get("top_titles") or []
    if titles:
        bits.append("Their channel's top-performing titles: " + "; ".join(f'"{t}"' for t in titles[:6]) + ".")
    if intel.get("hook_pattern"):
        bits.append("The title/hook pattern that wins for them: " + intel["hook_pattern"])
    motifs = intel.get("thumbnail_motifs") or []
    if motifs:
        bits.append("Recurring thumbnail motifs: " + ", ".join(motifs) + ".")
    cadence = int(intel.get("cadence_days") or 0)
    if cadence > 0:
        bits.append(f"They publish about every {cadence} day(s).")
    if not bits:
        return ""
    return ("\nCHANNEL INTELLIGENCE (real data from the videos this creator models — model your "
            "ideas, titles, hooks and thumbnail concepts on these, don't be generic):\n- "
            + "\n- ".join(bits))


async def _competitor_winners_brief(tenant_id) -> str:
    """Top competitor videos RIGHT NOW with real numbers (views, views/hour, age)
    so the producer can answer 'what's working on my competitors?' with specifics
    and ground title/thumbnail ideas in actual winners. Compact top 8 by vph.
    Mirrors the /suggested-models query. Fail-soft -> ''."""
    try:
        rows = await fetch_all(
            "SELECT title, channel, views, vph, hours_old FROM competitor_videos "
            "WHERE tenant_id = $1 AND views > 0 AND removed_at IS NULL "
            "ORDER BY vph DESC NULLS LAST LIMIT 8",
            tenant_id,
        ) or []
    except Exception as e:  # noqa: BLE001
        logger.warning("chat: competitor winners brief failed: %s", e)
        return ""
    if not rows:
        return ""
    lines: list[str] = []
    for r in rows:
        views = int(r.get("views") or 0)
        vph = r.get("vph")
        vph_s = f"~{int(round(float(vph))):,}/hr" if vph else "?/hr"
        days = round((float(r.get("hours_old") or 0)) / 24)
        age = f"{days}d old" if days > 0 else "new"
        ch = r.get("channel") or "?"
        title = (r.get("title") or "").strip()
        lines.append(f'"{title}" - {ch} - {views:,} views, {vph_s}, {age}')
    return ("\nTOP COMPETITOR VIDEOS RIGHT NOW (real numbers from the channels they model - when they ask "
            "what's working or how a competitor is doing, cite these specifics; and model title/thumbnail "
            "ideas on these proven winners):\n- " + "\n- ".join(lines))


async def _next_to_make_brief(tenant_id) -> str:
    """The strongest UNMODELED competitor winners to make next, scored the same way
    Autopilot scores candidates (view velocity + freshness + a small DNA boost). Lets
    the chat answer 'what should I make next?' with ranked, scored picks the creator
    can build on the spot. Top 5 by score. Fail-soft -> ''."""
    try:
        from routes.autopilot import calculate_confidence_with_breakdown
        rows = await fetch_all(
            "SELECT title, channel, url, vph, hours_old, views, distilled_at "
            "FROM competitor_videos WHERE tenant_id = $1 AND views > 0 AND removed_at IS NULL "
            "AND (modeled = false OR modeled IS NULL) ORDER BY vph DESC NULLS LAST LIMIT 12",
            tenant_id,
        ) or []
    except Exception as e:  # noqa: BLE001
        logger.warning("chat: next-to-make brief failed: %s", e)
        return ""
    if not rows:
        return ""
    scored: list[tuple[float, dict]] = []
    for r in rows:
        vph = float(r.get("vph") or 0)
        h = r.get("hours_old")
        hours = float(h) if h is not None else 9999.0
        try:
            bd = calculate_confidence_with_breakdown(vph, hours, {"has_dna": r.get("distilled_at") is not None})
            score = float(bd.total_score)
        except Exception:  # noqa: BLE001
            score = 0.0
        scored.append((score, r))
    scored.sort(key=lambda x: x[0], reverse=True)
    lines = []
    for score, r in scored[:5]:
        title = (r.get("title") or "").strip()
        ch = r.get("channel") or "?"
        days = round((float(r.get("hours_old")) / 24)) if r.get("hours_old") is not None else None
        age = f"{days}d" if days else "new"
        url = r.get("url") or ""
        lines.append(f'[{score:.0f}/100] "{title}" - {ch} ({int(r.get("views") or 0):,} views, {age}) {url}')
    return ("\nWHAT TO MAKE NEXT (the creator's strongest UNMODELED competitor winners, scored 0-100 on "
            "view velocity + freshness; when they ask what to make or pick one, propose it and set "
            "spec.reference_url to that video's link so it gets modeled on real data):\n- "
            + "\n- ".join(lines))


async def _own_performance_brief(tenant_id) -> str:
    """The creator's OWN recently-published videos with REAL synced YouTube analytics
    (views, CTR, retention). Lets the chat answer 'how did my videos do?' and diagnose
    weak spots. Top 5 most-recently-synced. Fail-soft -> ''."""
    try:
        rows = await fetch_all(
            "SELECT video_title, views, ctr, impressions, avg_retention "
            "FROM videos WHERE tenant_id = $1 AND last_analytics_sync IS NOT NULL "
            "ORDER BY last_analytics_sync DESC LIMIT 5",
            tenant_id,
        ) or []
    except Exception as e:  # noqa: BLE001
        logger.warning("chat: own performance brief failed: %s", e)
        return ""
    if not rows:
        return ""
    lines = []
    for r in rows:
        t = (r.get("video_title") or "Untitled").strip()
        parts = [f"{int(r.get('views') or 0):,} views"]
        ctr = r.get("ctr")
        parts.append(f"{float(ctr):.1f}% CTR" if ctr is not None else "CTR n/a")
        ret = r.get("avg_retention")
        if ret is not None:
            parts.append(f"{float(ret):.0f}% retention")
        imp = r.get("impressions")
        if imp:
            parts.append(f"{int(imp):,} impressions")
        lines.append(f'"{t}" - ' + ", ".join(parts))
    return ("\nYOUR OWN PUBLISHED VIDEOS (real YouTube analytics; use to answer how the channel is doing "
            "and to DIAGNOSE - low impressions = title/SEO/topic, low CTR = title+thumbnail, low "
            "retention = hook/pacing):\n- " + "\n- ".join(lines))


async def _own_catalog_brief(tenant_id) -> str:
    """The creator's OWN existing catalog (scraped from their channel via channel_videos),
    ranked by real view count. Lets the chat pitch ideas modeled on their PROVEN top
    performers even without synced YouTube analytics (which need the OAuth connection).
    Top 8 by views. Fail-soft -> ''."""
    try:
        rows = await fetch_all(
            "SELECT title, view_count FROM channel_videos "
            "WHERE tenant_id = $1 AND title IS NOT NULL "
            "ORDER BY view_count DESC NULLS LAST LIMIT 8",
            tenant_id,
        ) or []
    except Exception as e:  # noqa: BLE001
        logger.warning("chat: own catalog brief failed: %s", e)
        return ""
    rows = [r for r in rows if (r.get("view_count") or 0) > 0]
    if not rows:
        return ""
    lines = [f'"{(r.get("title") or "").strip()}" - {int(r.get("view_count") or 0):,} views' for r in rows]
    return ("\nYOUR OWN TOP-PERFORMING VIDEOS (from this channel, ranked by real views — these ARE the "
            "creator's top performers; model new ideas on what already works here):\n- " + "\n- ".join(lines))


async def _learnings_brief(tenant_id) -> str:
    """Proven patterns this channel has LEARNED (title/hook/script patterns that
    correlate with higher CTR, mined from its own results). Lets the chat cite 'what
    works for you' with evidence. Top 6 by confidence. Fail-soft -> ''."""
    try:
        rows = await fetch_all(
            "SELECT category, pattern, confidence, sample_size, avg_ctr FROM learnings "
            "WHERE tenant_id = $1 AND active = true ORDER BY confidence DESC LIMIT 6",
            tenant_id,
        ) or []
    except Exception as e:  # noqa: BLE001
        logger.warning("chat: learnings brief failed: %s", e)
        return ""
    if not rows:
        return ""
    lines = []
    for r in rows:
        cat = r.get("category") or "general"
        pat = (r.get("pattern") or "").strip()
        ctr = r.get("avg_ctr")
        ctr_s = f", ~{float(ctr):.1f}% CTR" if ctr else ""
        n = int(r.get("sample_size") or 0)
        lines.append(f"[{cat}] {pat}{ctr_s} (n={n})")
    return ("\nWHAT THIS CHANNEL HAS LEARNED (proven patterns from its own results - lean on these and "
            "cite them when advising):\n- " + "\n- ".join(lines))


async def _loop_brief(tenant_id) -> str:
    """Phase A: the full 'loop awareness' block injected into the producer so the chat
    is a master faceless-YouTube copilot that can see the whole machine - what to make
    next (scored), the creator's own real performance, and what the channel has learned.
    Each piece is fail-soft and empty until there's data, so it lights up over time."""
    parts = [
        await _next_to_make_brief(tenant_id),
        await _own_performance_brief(tenant_id),
        await _own_catalog_brief(tenant_id),
        await _learnings_brief(tenant_id),
    ]
    return "".join(p for p in parts if p)


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
            WHERE tenant_id = $1 AND title IS NOT NULL AND removed_at IS NULL
              AND hours_old IS NOT NULL AND hours_old <= 240
            ORDER BY vph DESC NULLS LAST, views DESC NULLS LAST
            LIMIT 12""",
        tenant_id,
    )
    if not rows:
        rows = await fetch_all(
            """SELECT title, channel, views, vph, hours_old
                 FROM competitor_videos
                WHERE tenant_id = $1 AND title IS NOT NULL AND removed_at IS NULL
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


async def _detect_reference_style_preset(tenant_id, reference_url, state):
    """Cheap, cached vision classification of the reference video's in-video style
    into one of the LOOK preset ids, so the chat can RECOMMEND it (the creator can
    still pick another). Cached in state per reference. Fail-soft -> None."""
    if state.get("_ref_style_for") == reference_url:
        return state.get("_ref_style_preset") or None
    preset = None
    try:
        from routes.model_video import _parse_youtube_id, _scene_frame_urls
        yid = _parse_youtube_id(reference_url or "")
        frames = _scene_frame_urls(yid) if yid else None
        api_key = await get_secret("anthropic_api_key", tenant_id) if frames else None
        if frames and api_key:
            from shared.clients.vision_client import vision_call
            prompt = (
                "These are real frames from a video. Classify its visual style as EXACTLY "
                "ONE of these ids and return ONLY the id: pixar_3d (3D Pixar/Disney CG), "
                "flat_2d (2D flat/vector animation), realistic (live-action/photoreal), "
                "anime, watercolor (storybook/painted), comic (graphic-novel/inked)."
            )
            out = await vision_call(prompt, frames, anthropic_key=api_key, tier="fast", max_tokens=12)
            cand = (out or "").strip().lower()
            from producer_prompt import VISUAL_PRESETS
            for pid in VISUAL_PRESETS:
                if pid in cand:
                    preset = pid
                    break
    except Exception as e:  # noqa: BLE001
        logger.warning("chat: reference style detect failed: %s", e)
    state["_ref_style_for"] = reference_url
    state["_ref_style_preset"] = preset or ""
    return preset


async def _annotate_style_recommendation(data, tenant_id, state):
    """When a reference video is in play, detect its style and (1) mark the matching
    LOOK option 'recommended' on the style card so the creator sees the suggestion at
    pick time, and (2) stamp a friendly detected-style label on the plan spec. The
    creator can still pick any look; an explicit pick is left untouched. Fail-soft."""
    plan = data.get("plan") if isinstance(data.get("plan"), dict) else None
    spec = plan.get("spec") if plan and isinstance(plan.get("spec"), dict) else None
    ref = state.get("pending_reference_url") or (spec.get("reference_url") if spec else None)
    if not ref:
        return
    if spec and str(spec.get("visual_style") or "").strip():
        return  # creator already picked a look — don't override the recommendation
    try:
        preset = await _detect_reference_style_preset(tenant_id, ref, state)
    except Exception:  # noqa: BLE001
        preset = None
    if not preset:
        return
    from producer_prompt import VISUAL_PRESETS
    label = VISUAL_PRESETS.get(preset, {}).get("label") or preset
    cards = data.get("cards")
    if isinstance(cards, list):
        for c in cards:
            if isinstance(c, dict) and c.get("id") == "style":
                c["recommended_value"] = preset
                c["recommended_hint"] = f"Closest to the video you're modeling ({label})"
    if spec:
        spec["detected_style_label"] = label


# --- producer text-client resolution (home path) ----------------------------
# The home Producer needs the SAME key fallback the in-video co-pilot already
# has (_handle_copilot above): the tenant's direct Anthropic key if they have
# one, else their Kie.ai key, and only the friendly "add a key" message (never
# a crash) when they have neither. Shared by both home producer entry points
# below (_seed_producer and chat_turn's intake turn) so they can't drift apart.

_NO_KEY_PRODUCER_MSG = (
    "I just need an API key to think this through. Add your Kie.ai or Anthropic key under "
    "Profile → API Keys, then tell me your idea again — I'll take it from there."
)

_KIE_PRODUCER_HINT = (
    "\n\n**Tip:** you're running on your Kie.ai key, which works great — add an "
    f"Anthropic key too ([console.anthropic.com →]({_CLAUDE_KEY_URL}), under Profile → "
    "API Keys) any time you want the sharpest possible plans."
)


async def _resolve_producer_client(tenant_id: str):
    """Resolve the tenant's producer text client. Returns None (never raises)
    when neither an Anthropic nor a Kie.ai key is configured — mirrors the
    try/except around get_text_client_for_tenant in _handle_copilot exactly."""
    try:
        from kie_unified import get_text_client_for_tenant
        return await get_text_client_for_tenant(tenant_id)
    except Exception:  # noqa: BLE001 — no key configured at all
        return None


def _with_kie_hint(assistant_text: str, state: dict, client) -> str:
    """Append a soft, one-time 'add an Anthropic key' tip when this turn ran on
    the Kie fallback client. Never a wall — Kie-only tenants already got their
    full plan; this just nudges once per conversation, unobtrusively."""
    if type(client).__name__ != "AnthropicDirectClient" and not state.get("kie_hint_shown"):
        state["kie_hint_shown"] = True
        return assistant_text + _KIE_PRODUCER_HINT
    return assistant_text


async def _seed_producer(conversation_id, tenant_id, state, seed_text):
    """Hand off into the producer seeded with a chosen/typed idea: start a fresh
    producer transcript and run one intake turn."""
    state["mode"] = "producer"
    state["onboarding_step"] = "done"
    client = await _resolve_producer_client(tenant_id)
    transcript = [{"role": "user", "content": seed_text}]
    if client is None:
        transcript.append(_assistant_turn({"assistant_text": _NO_KEY_PRODUCER_MSG, "phase": "asking"}))
        await _persist(conversation_id, tenant_id, transcript, state, "asking")
        return ChatTurnResponse(
            conversation_id=conversation_id, assistant_text=_NO_KEY_PRODUCER_MSG, phase="asking")
    brief = (
        _creator_brief(state)
        + await _modeled_runtime_hint(tenant_id)
        + await _channel_intel_brief(tenant_id)
        + await _competitor_winners_brief(tenant_id)
        + await _loop_brief(tenant_id)
        + await _reference_brief(state, state.get("pending_reference_url"))
        + _dna_brief(state)
        + await _profile_state_brief(tenant_id)
        + await _assets_brief(tenant_id, state)
    )
    data = call_producer(transcript, build_system_prompt(brief), client=client)
    await _stamp_length_default(data, tenant_id)
    await _annotate_style_recommendation(data, tenant_id, state)
    assistant_text = await _apply_and_merge_profile_ops(data, tenant_id, state, None)
    transcript.append(_assistant_turn(data))
    plan = data.get("plan") if isinstance(data.get("plan"), dict) else None
    if plan and isinstance(plan.get("spec"), dict):
        if state.get("pending_reference_url") and not plan["spec"].get("reference_url"):
            plan["spec"]["reference_url"] = state["pending_reference_url"]
        state["last_spec"] = plan["spec"]
    if plan:
        assistant_text = _with_kie_hint(assistant_text, state, client)
    phase = "plan" if plan else "asking"
    await _persist(conversation_id, tenant_id, transcript, state, phase)
    return ChatTurnResponse(
        conversation_id=conversation_id, assistant_text=assistant_text,
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
                lead + _KEY_PROMPT, cards=[_secure_key_card(optional=False)])
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
        # Preferred path: the secure box already saved + validated the key via
        # /api/chat/onboarding-key, so the raw key never entered this turn. We get
        # a benign selection {secure_key: "saved", key_provider: ...} instead.
        if sel.get("secure_key") == "saved" or (not msg and await _has_generation_key(tenant_id)):
            provider = sel.get("key_provider") or state.get("key_provider") or "kie"
            state["key_provider"] = provider
            ack = "✅ You're powered up. "
            # If they led with a Claude key, the fast text path is already on —
            # no point offering it again. Kie keys get the optional Claude upgrade.
            if provider == "claude":
                return await _after_key_setup(conversation_id, tenant_id, transcript, state, ack)
            state["onboarding_step"] = "key_claude"
            return await _ob_reply(conversation_id, tenant_id, transcript, state,
                ack + _CLAUDE_OFFER, cards=[_secure_key_card(optional=True)])
        # Fallback: a key arrived as composer text (legacy paste-in-chat). Still
        # works, but route it through the same save + validate so nothing changes.
        raw = (body.message or "").strip()
        if not raw:
            # They tapped the link but haven't pasted yet — re-show the ask + box.
            return await _ob_reply(conversation_id, tenant_id, transcript, state,
                _KEY_PROMPT, cards=[_secure_key_card(optional=False)])
        slot, val = _pick_key(raw)
        if not slot:
            return await _ob_reply(conversation_id, tenant_id, transcript, state,
                (val or "Paste the whole key — it's a long string with no spaces.") + "\n\n" + _KEY_PROMPT,
                cards=[_secure_key_card(optional=False)])
        from vault import set_secret, test_api_key
        await set_secret(slot, val, tenant_id=tenant_id, description="Onboarding generation key")
        result = await test_api_key(slot, tenant_id)
        if not result.get("success"):
            return await _ob_reply(conversation_id, tenant_id, transcript, state,
                f"That key didn't go through — {result.get('message') or 'please double-check it'}. "
                "Copy the whole key and paste it again 👇",
                cards=[_secure_key_card(optional=False)])
        state["key_provider"] = "claude" if slot == "anthropic_api_key" else "kie"
        ack = f"✅ You're powered up — {result.get('message')}. "
        if state["key_provider"] == "claude":
            return await _after_key_setup(conversation_id, tenant_id, transcript, state, ack)
        state["onboarding_step"] = "key_claude"
        return await _ob_reply(conversation_id, tenant_id, transcript, state,
            ack + _CLAUDE_OFFER, cards=[_secure_key_card(optional=True)])

    if step == "key_claude":
        # Optional Claude upgrade. Secure box → {secure_key: "saved"}; Skip →
        # {secure_key: "skip"}. A pasted Claude key (fallback) is saved here too.
        if sel.get("secure_key") == "saved":
            return await _after_key_setup(conversation_id, tenant_id, transcript, state,
                "✅ Claude connected — your text will fly now. ")
        if sel.get("secure_key") == "skip" or (msg and msg.lower() in _SKIP_WORDS):
            return await _after_key_setup(conversation_id, tenant_id, transcript, state,
                "No problem — Kie's got you covered. ")
        raw = (body.message or "").strip()
        if raw:
            slot, val = _pick_key(raw)
            if slot == "anthropic_api_key":
                from vault import set_secret, test_api_key
                await set_secret(slot, val, tenant_id=tenant_id, description="Onboarding Claude key")
                result = await test_api_key(slot, tenant_id)
                if result.get("success"):
                    state["key_provider"] = "claude"
                    return await _after_key_setup(conversation_id, tenant_id, transcript, state,
                        "✅ Claude connected — your text will fly now. ")
            return await _ob_reply(conversation_id, tenant_id, transcript, state,
                "That didn't look like a Claude key (they start with `sk-ant-`). Paste it in the "
                "secure box below, or skip — Kie already does everything.",
                cards=[_secure_key_card(optional=True)])
        return await _ob_reply(conversation_id, tenant_id, transcript, state,
            _CLAUDE_OFFER, cards=[_secure_key_card(optional=True)])

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


# --- channel identity commands (home chat) ---------------------------------
# Let the operator build/query a channel's identity conversationally: analyze the
# channel's OWN top videos (Firecrawl transcripts -> LLM) into a voice/format
# profile, or read back what's stored. See identity_builder.build_channel_identity.

def _identity_intent(msg: str) -> Optional[str]:
    """Detect a channel-identity command. The topic word (identity/voice/style)
    must be explicit so ordinary 'make a video' asks fall through to the producer."""
    m = (msg or "").lower()
    if not any(t in m for t in ("identity", "voice", "style")):
        return None
    if any(v in m for v in ("build", "rebuild", "analyze", "analyse", "learn", "study", "extract")):
        return "build"
    if any(v in m for v in ("what", "whats", "what's", "show", "tell", "who", "describe")):
        return "show"
    return None


def _fmt_field(val) -> str:
    """Render an identity field that may be a string, a dict, or a list."""
    if isinstance(val, dict):
        return "; ".join(f"{k.replace('_', ' ')}: {v}" for k, v in val.items() if v)
    if isinstance(val, list):
        return "; ".join(str(x) for x in val)
    return str(val)


def _dict_bullets(val: dict) -> str:
    return "\n".join(f"- **{k.replace('_', ' ')}:** {v}" for k, v in val.items() if v)


def _format_identity(ident: dict, header: str) -> str:
    out: list[str] = [header]

    def section(text: str) -> None:
        out.append("")  # blank line between sections so it's not one wall of text
        out.append(text)

    if ident.get("voice_tone"):
        section(f"🎙️ **Voice** — {_fmt_field(ident['voice_tone'])}")

    if ident.get("cadence"):
        block = f"🎵 **Cadence** — {_fmt_field(ident['cadence'])}"
        if ident.get("cadence_example"):
            block += f"\n> {ident['cadence_example']}"
        section(block)

    if ident.get("hook_style"):
        block = f"🪝 **Hook** — {_fmt_field(ident['hook_style'])}"
        exs = ident.get("hook_examples") or []
        if exs:
            block += "\n\n_How his top videos actually open:_"
            for ex in exs[:3]:
                v = (ex.get("video") or "").strip()
                line = ex.get("line", "")
                block += f"\n> **{v}** — {line}" if v else f"\n> {line}"
        section(block)

    if ident.get("structure"):
        block = f"🧱 **Structure** — {_fmt_field(ident['structure'])}"
        if ident.get("structure_example"):
            block += f"\n> {ident['structure_example']}"
        section(block)

    extra = {"research_approach": ident.get("research_depth"), "visual_format": ident.get("inferred_format")}
    for emoji, label, key in (("🔍", "Research", "research_approach"),
                              ("📼", "Video visuals", "visual_format"),
                              ("🖼️", "Thumbnail style", "thumbnail_style")):
        val = ident.get(key) or extra.get(key)
        if not val:
            continue
        if isinstance(val, dict):
            section(f"{emoji} **{label}**\n{_dict_bullets(val)}")
        else:
            section(f"{emoji} **{label}** — {val}")

    sig = ident.get("signature_phrases") or []
    if sig:
        section("✍️ **Signature patterns**\n" + "\n".join(f"- {s}" for s in sig[:6]))

    rq = ident.get("real_quotes") or []
    if rq:
        section("💬 **More real lines from his videos:**\n" + "\n".join(f"> {q}" for q in rq[:6]))

    return "\n".join(out)


async def _plain_reply(conversation_id, tenant_id, transcript, state, user_msg, text):
    if user_msg:
        transcript.append({"role": "user", "content": user_msg})
    transcript.append(_assistant_turn({"assistant_text": text, "phase": "asking"}))
    await _persist(conversation_id, tenant_id, transcript, state, "asking")
    return ChatTurnResponse(conversation_id=conversation_id, assistant_text=text, phase="asking")


async def _handle_build_identity(conversation_id, tenant_id, transcript, state, user_msg, background_tasks):
    # Run the analysis in the background — Firecrawl (3 sequential scrapes + retries)
    # plus two model calls can exceed a chat turn's gateway window. We ack now and
    # the operator reads it back with "show his identity" once it's stored.
    async def _job():
        try:
            from identity_builder import build_channel_identity
            await build_channel_identity(str(tenant_id))
        except Exception as e:  # noqa: BLE001
            logger.warning("chat: background identity build failed: %s", e)

    background_tasks.add_task(_job)
    text = ("🔍 On it — analyzing his **top 3 videos** for voice, research style, real quotes, and "
            "thumbnail format. This takes about a minute. Say **“show his identity”** in a moment and "
            "I'll lay out the full locked profile.")
    return await _plain_reply(conversation_id, tenant_id, transcript, state, user_msg, text)


async def _handle_show_identity(conversation_id, tenant_id, transcript, state, user_msg):
    row = await fetch_one(
        "SELECT channel_identity, youtube_channel_name FROM channel_profiles WHERE tenant_id=$1",
        str(tenant_id),
    )
    ident = _as_dict((row or {}).get("channel_identity"))
    if not ident or not ident.get("voice_tone"):
        text = ("I haven't learned this channel yet. Say “build his identity” and I'll analyze "
                "the channel's top videos to work out his voice, format, and style.")
        return await _plain_reply(conversation_id, tenant_id, transcript, state, user_msg, text)
    name = (row or {}).get("youtube_channel_name") or "this channel"
    body = _format_identity(ident, f"Here's what I've learned about **{name}** (from his own top videos):")
    body += "\n\nWant me to refresh it from his latest top videos? Say “rebuild his identity.”"
    return await _plain_reply(conversation_id, tenant_id, transcript, state, user_msg, body)


# --- secure onboarding key intake -------------------------------------------
# The chat's secure box POSTs the pasted key here instead of sending it as a
# chat message. We detect, save, and validate it exactly like the in-chat path,
# so the raw key never becomes a transcript entry or reaches the producer model.

class OnboardingKeyRequest(BaseModel):
    value: str


class OnboardingKeyResponse(BaseModel):
    ok: bool
    provider: Optional[str] = None  # "kie" | "claude"
    message: str


@router.post("/onboarding-key", response_model=OnboardingKeyResponse)
async def onboarding_key(body: OnboardingKeyRequest, tenant_id=Depends(get_tenant_id)):
    slot, val = _pick_key((body.value or "").strip())
    if not slot:
        return OnboardingKeyResponse(
            ok=False, message=val or "Paste the whole key — it's a long string with no spaces.")
    from vault import set_secret, test_api_key
    await set_secret(slot, val, tenant_id=tenant_id, description="Onboarding generation key")
    result = await test_api_key(slot, tenant_id)
    if not result.get("success"):
        return OnboardingKeyResponse(
            ok=False,
            message=f"That key didn't go through — {result.get('message') or 'please double-check it'}.")
    return OnboardingKeyResponse(
        ok=True,
        provider="claude" if slot == "anthropic_api_key" else "kie",
        message=result.get("message") or "Key verified",
    )


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
    #    actions behind a confirm card everywhere (home included, Phase 2).
    if video_id:
        return await _handle_copilot(
            body, conversation_id, tenant_id, transcript, state, video_id, background_tasks
        )

    # 3. Approval -> create the video + kick off the pipeline.
    if body.approve and state.get("last_spec"):
        return await _handle_approve(
            state["last_spec"], conversation_id, tenant_id, transcript, state, background_tasks
        )

    # 3.5 Channel-identity commands ("build his identity" / "what's his voice?").
    #     Runs before producer intake so it doesn't get treated as a video request.
    if body.message and body.message.strip():
        _iid = _identity_intent(body.message)
        if _iid == "build":
            return await _handle_build_identity(
                conversation_id, tenant_id, transcript, state, body.message.strip(), background_tasks)
        if _iid == "show":
            return await _handle_show_identity(
                conversation_id, tenant_id, transcript, state, body.message.strip())

    # 4. Normal intake turn. Append the user's message and/or card selections.
    user_parts: list[str] = []
    if body.message and body.message.strip():
        msg_text = body.message.strip()
        user_parts.append(msg_text)
        ref = _extract_youtube_url(msg_text)
        if ref:
            state["pending_reference_url"] = ref
            # "Analyze this" + a link = the commander move (Phase 7): full
            # breakdown now, DNA held for a one-tap recreate.
            if _analyze_intent(msg_text):
                transcript.append({"role": "user", "content": msg_text})
                return await _handle_analyze(conversation_id, tenant_id, transcript, state, ref)
    if body.selections:
        user_parts.append(_selections_to_text(body.selections))
        state.setdefault("selections", {}).update(body.selections)
    if body.attachments:
        await _attach_assets(tenant_id, conversation_id, body.attachments, state, user_parts)

    if not user_parts:
        # Nothing said yet. For a RETURNING, onboarded creator opening a FRESH
        # conversation, proactively pitch a modeled idea (Phase 2) instead of a
        # static greeting. Gated to the first open (empty transcript), so it
        # fires once per conversation, not on every poll. Fail-soft to the greeting.
        if not transcript:
            # Self-gating: _generate_competitor_ideas returns None when there's no
            # competitor data or no API key, so we don't rely on creator_brief being
            # populated (established tenants keep channel data in other tables, not
            # the chat brief — gating on state.channel here silently skipped them).
            ideas = None
            try:
                ideas = await _generate_competitor_ideas(
                    tenant_id, state, niche=state.get("niche_angle")
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("chat: proactive idea pitch failed: %s", e)
                ideas = None
            if ideas:
                return await _present_ideas_turn(
                    conversation_id, tenant_id, transcript, state, ideas
                )
            transcript.append(_assistant_turn({"assistant_text": _GREETING, "phase": "asking"}))
            await _persist(conversation_id, tenant_id, transcript, state, "asking")
        return ChatTurnResponse(
            conversation_id=conversation_id, assistant_text=_GREETING, phase="asking"
        )

    transcript.append({"role": "user", "content": "\n".join(user_parts)})

    # The producer needs a text model. Same fallback the in-video co-pilot uses
    # (_handle_copilot): the tenant's direct Anthropic key if they have one,
    # else their Kie.ai key — never a hard wall, only the friendly key prompt
    # if they have neither configured at all.
    client = await _resolve_producer_client(tenant_id)
    if client is None:
        transcript.append(_assistant_turn({"assistant_text": _NO_KEY_PRODUCER_MSG, "phase": "asking"}))
        await _persist(conversation_id, tenant_id, transcript, state, "asking")
        return ChatTurnResponse(
            conversation_id=conversation_id, assistant_text=_NO_KEY_PRODUCER_MSG, phase="asking")

    # Producer sees the durable creator brief + a real length anchor + the channel
    # intelligence brief (top titles / hook pattern / thumbnail motifs / cadence) +
    # REAL data on any video being modeled (so it grounds the proposal in the
    # reference, not the creator's own channel) + the current channel setup it can
    # edit (competitors, name, niche, look).
    system_prompt = build_system_prompt(
        _creator_brief(state)
        + await _modeled_runtime_hint(tenant_id)
        + await _channel_intel_brief(tenant_id)
        + await _competitor_winners_brief(tenant_id)
        + await _loop_brief(tenant_id)
        + await _reference_brief(state, state.get("pending_reference_url"))
        + _dna_brief(state)
        + await _profile_state_brief(tenant_id)
        + await _format_brief(tenant_id)
        + await _script_template_brief(tenant_id)
        + await _assets_brief(tenant_id, state)
    )
    data = call_producer(transcript, system_prompt, client=client)
    await _stamp_length_default(data, tenant_id)
    await _annotate_style_recommendation(data, tenant_id, state)
    assistant_text = await _apply_and_merge_profile_ops(data, tenant_id, state, background_tasks)
    transcript.append(_assistant_turn(data))

    plan = data.get("plan") if isinstance(data.get("plan"), dict) else None
    if plan and isinstance(plan.get("spec"), dict):
        if state.get("pending_reference_url") and not plan["spec"].get("reference_url"):
            plan["spec"]["reference_url"] = state["pending_reference_url"]
        state["last_spec"] = plan["spec"]
    if plan:
        assistant_text = _with_kie_hint(assistant_text, state, client)
    phase = "plan" if plan else "asking"
    await _persist(conversation_id, tenant_id, transcript, state, phase)

    return ChatTurnResponse(
        conversation_id=conversation_id,
        assistant_text=assistant_text,
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


async def _drop_removed_videos(tenant_id, rows: list[dict]) -> list[dict]:
    """Filter out competitor rows whose YouTube video no longer exists, and soft-flag
    them (removed_at) so they stay pruned. Fail-soft: returns rows unchanged when the
    liveness check can't run (no key / API hiccup) so we never blank the home page."""
    api_key = os.getenv("YOUTUBE_API_KEY", "").strip()
    if not api_key or not rows:
        return rows
    from youtube_data_api import fetch_live_video_ids
    ids = [r["video_id"] for r in rows if r.get("video_id")]
    try:
        live = await fetch_live_video_ids(ids, api_key)
    except Exception as e:  # noqa: BLE001
        logger.warning("suggested-models: liveness check failed: %s", e)
        return rows
    dead = [i for i in ids if i not in live]
    if dead:
        try:
            await execute(
                "UPDATE competitor_videos SET removed_at = now() "
                "WHERE tenant_id = $1 AND video_id = ANY($2::text[])",
                tenant_id, dead,
            )
            logger.info("suggested-models: flagged %d removed videos for %s", len(dead), tenant_id)
        except Exception as e:  # noqa: BLE001
            logger.warning("suggested-models: removed-flag write failed: %s", e)
    return [r for r in rows if r.get("video_id") in live]


@router.get("/suggested-models")
async def suggested_models(tenant_id=Depends(get_tenant_id)):
    """Top videos worth modeling from the creator's modeled channel, with metrics +
    a cached AI 'why'. Empty when they have no competitor data (the home page then
    falls back to the generic example prompts)."""
    # Fetch a WIDER candidate set than we show, then drop any whose YouTube video
    # has been removed/made private (data-freshness: a dead video must never rank as
    # a "worth modeling" top pick). The liveness check + soft-flag prune the dead
    # rows so they stay gone. Fail-soft: if the check can't run, show what we have.
    rows = await fetch_all(
        "SELECT video_id, title, url, channel, views, vph, hours_old, model_rationale "
        "FROM competitor_videos WHERE tenant_id = $1 AND views > 0 AND removed_at IS NULL "
        "ORDER BY vph DESC NULLS LAST LIMIT 15",
        tenant_id,
    )
    if not rows:
        return {"channel": None, "videos": []}
    rows = [dict(r) for r in rows]
    rows = await _drop_removed_videos(tenant_id, rows)
    if not rows:
        return {"channel": None, "videos": []}
    rows = rows[:5]
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


# --- Chat history (sidebar list + resume any past conversation by id) ---

def _flatten_transcript(transcript) -> list:
    """Transcript rows -> the {role, text, cards?, plan?} shape ChatCore renders."""
    out: list = []
    for t in _as_list(transcript):
        if t.get("role") == "user":
            out.append({"role": "user", "text": t.get("content") or ""})
        elif t.get("role") == "assistant":
            d = _as_dict(t.get("content"))
            out.append({
                "role": "assistant",
                "text": d.get("assistant_text") or "",
                "cards": d.get("cards"),
                "plan": d.get("plan"),
            })
    return out


@router.get("/conversations")
async def list_conversations(limit: int = 20, tenant_id=Depends(get_tenant_id)):
    """Recent chat history for the sidebar: id + a title (the first thing the creator
    said) + a short preview (last reply) + when it was last touched. Skips empty
    threads. Tenant-scoped."""
    rows = await fetch_all(
        """SELECT id, transcript, phase, video_id, updated_at
             FROM chat_conversations
            WHERE tenant_id = $1 AND jsonb_array_length(transcript) > 0
            ORDER BY updated_at DESC LIMIT $2""",
        tenant_id, limit * 3,
    )
    out: list = []
    for c in rows or []:
        tr = _as_list(c.get("transcript"))
        title = None
        last_assistant = None
        for t in tr:
            if t.get("role") == "user" and not title:
                title = (t.get("content") or "").strip()
            elif t.get("role") == "assistant":
                d = _as_dict(t.get("content"))
                if d.get("assistant_text"):
                    last_assistant = d["assistant_text"]
        if not title:
            continue
        out.append({
            "conversation_id": str(c["id"]),
            "title": title[:80],
            "preview": (last_assistant or "")[:140],
            "phase": c.get("phase") or "asking",
            "video_id": str(c["video_id"]) if c.get("video_id") else None,
            "updated_at": c["updated_at"].isoformat() if c.get("updated_at") else None,
        })
        if len(out) >= limit:
            break
    return out


@router.get("/conversation/{conversation_id}")
async def get_conversation_by_id(conversation_id: str, tenant_id=Depends(get_tenant_id)):
    """Hydrate any past conversation by id, so the creator can resume from history."""
    conv = await _load_conversation(conversation_id, tenant_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {
        "conversation_id": str(conv["id"]),
        "messages": _flatten_transcript(conv.get("transcript")),
        "phase": conv.get("phase") or "asking",
        "video_id": str(conv["video_id"]) if conv.get("video_id") else None,
    }
