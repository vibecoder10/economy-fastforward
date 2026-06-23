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


def _make_stage_step(tenant_id, video_id: str, methods: list[str], *,
                     start_msg: str = "On it…"):
    """Like _make_run_step, but re-runs SPECIFIC executor stage methods in order
    (e.g. ['run_prompts','run_images']) instead of the status-driven next step —
    used by follow-up edits, which target a chosen stage. Reports via the same
    task-status channel so the chat's live tracker updates. Stops on first error."""
    from pipeline_executor import PipelineExecutor
    from routes.pipeline import _clear_task_status, _set_task_status

    async def _run():
        _set_task_status(video_id, "running", start_msg, tenant_id=tenant_id)
        try:
            executor = PipelineExecutor(tenant_id)
            result: dict = {}
            for name in methods:
                method = getattr(executor, name, None)
                if method is None:
                    result = {"status": "failed", "error": f"Unknown stage '{name}'"}
                    break
                result = await method(video_id) or {}
                if result.get("error"):
                    break
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
FOLLOWUP_CONFIDENCE = 0.55  # below this, ask the creator to clarify instead of guessing


def _classify_followup(api_key: str, message: str, video: dict) -> dict:
    """One direct-Anthropic call mapping a free-text edit request onto a target stage +
    the concrete change to apply. Sync — call via asyncio.to_thread."""
    try:
        minutes = int(float(video.get("video_length_minutes") or 0)) or "unknown"
    except (TypeError, ValueError):
        minutes = "unknown"
    prompt = (
        "A creator is iterating on an existing video through chat. Decide how to honor their request.\n\n"
        f"Video title: {video.get('video_title') or 'Untitled'}\n"
        f"Current stage/status: {video.get('status') or 'unknown'}\n"
        f"Current length: {minutes} min\n\n"
        f'The creator said: "{message}"\n\n'
        "Pick the ONE production stage to re-run, and the change to apply:\n"
        "- script: rewrite/restructure the script, or change LENGTH, tone, pacing, or content.\n"
        "- images: change the visual look/style of the scene images.\n"
        "- thumbnail: change the thumbnail (bolder, more aggressive, different text/expression).\n"
        "- render: just re-stitch the final video, no content change.\n"
        "- advance: they're happy and want to keep moving to the next step.\n"
        "- none: unclear, off-topic, or not an edit — ask them to clarify.\n\n"
        "Return ONE JSON object and nothing else:\n"
        '{"stage":"script|images|thumbnail|render|advance|none",'
        '"intent_summary":"<short>",'
        '"video_length_minutes":<int if they changed length else null>,'
        '"guidance_append":"<a concrete instruction to append to that stage\'s guidance so the re-run honors '
        'the request; empty for render/advance/none>",'
        '"confidence":<0.0-1.0>,'
        '"reply":"<one friendly sentence telling them what you\'re doing now, or your clarifying question>"}'
    )
    try:
        return _claude_json(api_key, prompt, 700)
    except Exception as e:  # noqa: BLE001
        logger.warning("followup: classify failed: %s", e)
        return {}


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


async def _handle_followup(body, conversation_id, tenant_id, transcript, state, video_id, background_tasks):
    """A message after the video exists -> a conversational edit. Classify the request,
    apply the change to the right stage, re-run just that stage, and report in plain
    English. Unclear requests get a clarifying ask, not a blind pipeline advance."""
    msg = (body.message or "").strip()
    if msg:
        transcript.append({"role": "user", "content": msg})

    async def _reply(text):
        transcript.append(_assistant_turn({"assistant_text": text, "phase": "created"}))
        await _persist(conversation_id, tenant_id, transcript, state, "created", video_id=video_id)
        return ChatTurnResponse(conversation_id=conversation_id, assistant_text=text,
                                video_id=video_id, phase="created")

    if not msg:
        return await _reply("Tell me what to change — e.g. “make it shorter”, “redo the thumbnail”, or “keep going”.")

    api_key = await get_secret("anthropic_api_key", tenant_id)
    video = await fetch_one(
        "SELECT video_title, status, video_length_minutes FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not api_key or not video:
        # No key (or the video vanished) — fall back to the old blind advance so a
        # "keep going" still moves the pipeline.
        background_tasks.add_task(_make_run_step(tenant_id, video_id, user_intent=msg, start_msg="On it…"))
        return await _reply("On it — I'll take care of that and update you here.")

    edit = await asyncio.to_thread(_classify_followup, api_key, msg, dict(video))
    stage = (edit.get("stage") or "none").strip()
    reply = (edit.get("reply") or "").strip()

    # "keep going" -> advance the pipeline one step.
    if stage == "advance":
        background_tasks.add_task(_make_run_step(tenant_id, video_id, start_msg="Moving to the next step…"))
        return await _reply(reply or "Great — moving on to the next step. I'll keep you posted here.")

    # Unclear / not an edit / low confidence -> ask, don't guess.
    if stage not in FOLLOWUP_STAGES or float(edit.get("confidence") or 0) < FOLLOWUP_CONFIDENCE:
        return await _reply(reply or "Happy to tweak it — want a different script, visuals, thumbnail, or a re-render?")

    await _apply_followup_edit(tenant_id, video_id, stage, edit)
    cfg = FOLLOWUP_STAGES[stage]
    background_tasks.add_task(_make_stage_step(tenant_id, video_id, cfg["methods"], start_msg=f"On it — {cfg['doing']}…"))
    return await _reply(reply or f"On it — {cfg['doing']} now. I'll update you right here.")


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
    data = call_producer(transcript, build_system_prompt(_creator_brief(state)), api_key=api_key)
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
    system_prompt = build_system_prompt(_creator_brief(state))
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
