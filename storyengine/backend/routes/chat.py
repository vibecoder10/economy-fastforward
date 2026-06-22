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
from database import execute, fetch_one
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
    parts = [f"{k}: {v}" for k, v in selections.items()]
    return "My choices — " + ", ".join(parts)


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


# --- pipeline kickoff (mirrors routes/pipeline.run_next_step's _run) --------

def _make_run_step(tenant_id, video_id: str, *, user_intent: Optional[str] = None,
                   start_msg: str = "Getting started…"):
    """Return a coroutine that runs the next pipeline step in the background and
    reports status the same way routes/pipeline.py does (so the existing SSE
    stream + task polling pick it up)."""
    from pipeline_executor import PipelineExecutor
    from routes.pipeline import _clear_task_status, _set_task_status

    async def _run():
        _set_task_status(video_id, "running", start_msg, tenant_id=tenant_id)
        try:
            executor = PipelineExecutor(tenant_id)
            result = await executor.run_next_step(video_id, user_intent=user_intent)
            _set_task_status(
                video_id, result.get("status", "completed"),
                result.get("error") or result.get("message"), tenant_id=tenant_id,
            )
        except Exception as e:  # noqa: BLE001 — surface as a failed task, not a 500
            _set_task_status(video_id, "failed", str(e), tenant_id=tenant_id)
        finally:
            await asyncio.sleep(30)
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
    background_tasks.add_task(_make_run_step(tenant_id, video_id))
    title = spec.get("title") or "your video"
    assistant_text = (
        f"Love it. I'm making “{title}” now — I'll keep you posted right "
        "here as it comes together."
    )
    transcript.append(_assistant_turn({"assistant_text": assistant_text, "phase": "created"}))
    await _persist(conversation_id, tenant_id, transcript, state, "created", video_id=video_id)
    return ChatTurnResponse(
        conversation_id=conversation_id, assistant_text=assistant_text,
        video_id=video_id, phase="created",
    )


async def _handle_followup(body, conversation_id, tenant_id, transcript, state, video_id, background_tasks):
    """A message after the video exists -> drive the pipeline (Phase 5 makes this
    smarter via the orchestrator; for now it advances/re-runs with the user's
    intent)."""
    msg = (body.message or "").strip()
    if msg:
        transcript.append({"role": "user", "content": msg})
    background_tasks.add_task(_make_run_step(tenant_id, video_id, user_intent=msg or None, start_msg="On it…"))
    assistant_text = "On it — I'll take care of that and update you here."
    transcript.append(_assistant_turn({"assistant_text": assistant_text, "phase": "created"}))
    await _persist(conversation_id, tenant_id, transcript, state, "created", video_id=video_id)
    return ChatTurnResponse(
        conversation_id=conversation_id, assistant_text=assistant_text,
        video_id=video_id, phase="created",
    )


# --- the endpoint ------------------------------------------------------------

@router.post("", response_model=ChatTurnResponse)
async def chat_turn(
    body: ChatTurnRequest,
    background_tasks: BackgroundTasks,
    tenant_id=Depends(get_tenant_id),
):
    # 1. Load or create the conversation (tenant-scoped).
    if body.conversation_id:
        conv = await _load_conversation(body.conversation_id, tenant_id)
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
    else:
        conv = await _create_conversation(tenant_id)

    conversation_id = str(conv["id"])
    transcript = _as_list(conv.get("transcript"))
    state = _as_dict(conv.get("state"))
    video_id = str(conv["video_id"]) if conv.get("video_id") else None

    # 2. Video already exists -> follow-up edit.
    if video_id:
        return await _handle_followup(
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
    system_prompt = build_system_prompt("")
    data = call_producer(transcript, system_prompt, api_key=api_key)
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
