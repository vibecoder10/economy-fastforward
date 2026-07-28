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
import copy
import json
import logging
import os
import re
from typing import Any, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from pydantic import BaseModel

from auth import get_tenant_id
from database import execute, fetch_all, fetch_one
from models import CreateVideoRequest
from producer_prompt import build_system_prompt, call_producer
from vault import get_secret
import generation_claims

# C16a (S7-1 CRITICAL): every chat-driven paid dispatch replies with this
# exact line when its generation_claims.acquire() is denied — the video's
# claimed lane is already in flight (another chat turn, or a manual
# routes/pipeline.py click) — instead of scheduling a second concurrent run.
_ALREADY_WORKING_REPLY = (
    "I'm already working on that — I'll let you know when it's done."
)

from actions import (
    ACTIONS as COPILOT_ACTIONS,
    RUNNERS as _ACTION_RUNNERS,
    BUILD_TO_PICTURES as _BUILD_TO_PICTURES,
    CLIP_COST as _CLIP_COST,
    PICTURE_COST as _PICTURE_COST,
    already_uploaded_reply as _already_uploaded_reply,
    apply_followup_edit as _apply_followup_edit,
    blocked_reason as _action_blocked,
    budget_check as _budget_check,
    cost_breakdown as _cost_breakdown,
    estimate_cost as _estimate_cost,
    estimate_custom_film_plan as _estimate_custom_film_plan,
    estimate_plan_cost as _estimate_plan_cost,
    guardrail_note as _guardrail_note,
    make_action_step as _make_copilot_step,
    make_autobuild_step as _make_autobuild_step,
    video_summary as _copilot_summary,
    # Single Claude tier source (checklist §3.4 / C35) — see shared.channel_profile.
    claude_model_for_direct_client as _claude_model_for_direct_client,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])
_QUEUE_CONTEXT_UNSET = object()

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
    # What the creator is looking at, so "this image" / "image 1" / "him" resolves
    # without naming it. Started as the dock's {"scene": int, "index": int, "tab":
    # str}; widened (DIRECTOR-CHAT-PLAN.md Task 5.4a) for the Director surface,
    # which additionally sends {"altitude": str, "focusedAssetId": str, "railTab":
    # str, "selectedEntityId": str, "selectedEntityType": "character"|"environment"}.
    # Every field optional — an older/other caller sending only a subset (or the
    # old {"tab"}/{"tab","scene"} shape) is still a fully valid value of this same
    # dict. `focusedAssetId`/`selectedEntityId` are read DETERMINISTICALLY by
    # `_resolve_prompt_target`/`_resolve_character_target`/
    # `_resolve_environment_target` below — an id, never re-derived from a guess.
    ui_context: Optional[dict[str, Any]] = None
    # Files dropped into the chat this turn: chat_assets ids from POST /api/chat/upload.
    attachments: Optional[list[str]] = None
    # C-frontdoor (2026-07-27): a caller that already KNOWS what it wants done —
    # today, only DirectorHome's "create a new video" front door — states the
    # verb outright instead of letting the co-pilot's classifier guess it from
    # free text. Must be a real ACTIONS verb (validated in _handle_copilot,
    # where anything else is ignored and falls through to the classifier as
    # before) — this is a declaration, not a bypass of the paid-confirm-card
    # or legality-gate checks every classified verb still goes through.
    explicit_verb: Optional[str] = None


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
            "SELECT id FROM videos WHERE id = $1 AND tenant_id = $2",
            video_id,
            tenant_id,
        )
        if owns:
            checked_video_id = video_id
        else:
            logger.warning(
                "chat: upload video_id %s not owned by tenant %s — uploading unscoped",
                video_id,
                tenant_id,
            )

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
            content,
            f"chat-assets/{asset_id}.{ext}",
            file.content_type or "application/octet-stream",
            str(tenant_id),
        )
    except Exception as e:  # noqa: BLE001 — the parsed content is in the row either way
        logger.warning("chat: asset storage upload failed (%s): %s", file.filename, e)

    await execute(
        "INSERT INTO chat_assets (id, tenant_id, conversation_id, video_id, kind, filename, "
        "content_type, storage_url, parsed, parsed_text, summary) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10, $11)",
        asset_id,
        tenant_id,
        conversation_id or None,
        checked_video_id,
        kind,
        (file.filename or "")[:255] or None,
        file.content_type,
        storage_url,
        json.dumps(parsed) if parsed is not None else None,
        parsed_text,
        summary,
    )

    if kind == "csv" and parsed:
        preview: Any = parsed.get("rows", [])[:5]
    elif kind == "image":
        preview = storage_url
    else:
        preview = (parsed_text or "")[:400] or None
    return {
        "asset": {
            "id": asset_id,
            "kind": kind,
            "filename": file.filename,
            "summary": summary,
            "preview": preview,
        }
    }


async def _attach_assets(
    tenant_id, conversation_id, asset_ids, state, user_parts
) -> None:
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
            tenant_id,
            ids,
        )
        if not rows:
            return
        await execute(
            "UPDATE chat_assets SET conversation_id = $1 "
            "WHERE tenant_id = $2 AND id = ANY($3::uuid[])",
            conversation_id,
            tenant_id,
            [str(r["id"]) for r in rows],
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
            return (
                f"\n\nCHANNEL FORMAT (locked by the creator): {bits}. Every video is made "
                "in this format — don't propose formats that contradict it."
            )
        return (
            f"\n\nCHANNEL FORMAT (detected, not locked): {bits}. If the creator confirms "
            "this is how their channel works, emit set_channel_format to lock it."
        )
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
            f'("{row["name"]}") — every generated script automatically follows it. '
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
            tenant_id,
            ids,
        )
        if not rows:
            return ""
        lines = [
            "\n\nFILES THE CREATOR DROPPED INTO THIS CONVERSATION (use the id in filing ops like queue_titles):"
        ]
        for r in rows:
            where = (
                f" (already filed: {r['filed_as']})"
                if r.get("filed_as")
                else " (not filed anywhere yet)"
            )
            lines.append(f"- [{r['kind']}] id={r['id']} {r['summary']}{where}")
        return "\n".join(lines)
    except Exception as e:  # noqa: BLE001
        logger.warning("chat: assets brief failed: %s", e)
        return ""


def _selections_to_text(selections: dict[str, Any]) -> str:
    parts = []
    for k, v in selections.items():
        if (
            k == "length"
        ):  # the slider sends seconds — show it as a runtime so the producer reasons in real time
            try:
                parts.append(
                    f"length: ~{_format_runtime(max(LENGTH_MIN_SECONDS, int(float(v))))}"
                )
                continue
            except (TypeError, ValueError):
                pass
        parts.append(f"{k}: {v}")
    return "My choices — " + ", ".join(parts)


# P5 fix: spec.length_user_set is an LLM self-report ("did the creator name a
# length?"), not ground truth — a producer pass can mis-set it. Longest
# alternatives first so alternation short-circuits on the fullest match
# (belt-and-suspenders; the trailing \b already forces a full-unit match).
_LENGTH_EXPR_RE = re.compile(
    r"\b\d+\s*-?\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?|s|m|h)\b",
    re.IGNORECASE,
)
# How many of the creator's OWN most-recent turns we'll scan for a plausible
# length expression before distrusting length_user_set — bounded so this
# stays cheap on a long-running conversation.
_LENGTH_USER_SET_LOOKBACK_TURNS = 3


def _user_length_expression_present(transcript: Any) -> bool:
    """True only when one of the creator's last few turns actually contains
    something that reads like a length ('90 seconds', '3 minutes',
    '3-minute', '1 hour', '45s', ...). Used to sanity-check
    spec.length_user_set before trusting it — see _stamp_length_default."""
    if not isinstance(transcript, list):
        return False
    user_texts = [
        t.get("content")
        for t in transcript
        if isinstance(t, dict)
        and t.get("role") == "user"
        and isinstance(t.get("content"), str)
    ]
    for text in user_texts[-_LENGTH_USER_SET_LOOKBACK_TURNS:]:
        if _LENGTH_EXPR_RE.search(text):
            return True
    return False


async def _stamp_length_default(
    data: dict[str, Any], tenant_id=None, transcript: Any = None
) -> None:
    """Pre-set the length slider so it opens on a sensible default, not the generic
    1-minute floor. Source order: the producer's recommended_minutes (asking phase),
    else the plan spec's video_length_minutes.

    Deterministic length backstop (GOAL v2 Phase 4; rewired chat channel-identity
    rebuild checklist P3): a real channel runtime should anchor the default —
    OUR OWN channel's runtime, not a competitor's. Source order:
      1. This tenant's OWN median runtime (channel_identity_context.
         own_median_minutes — real channel_videos import data, or this
         tenant's own pipeline-produced videos when that's empty).
      2. Competitor median (_competitor_median_seconds) ONLY when the tenant
         has no own-catalog history yet — the old sole source, now a fallback.
    If we know the channel runtime and the producer picked a NORMAL-form length
    below it, open the slider on the channel runtime instead — the creator can
    still drag it down. Intentional short-form (< 2 min) is left alone so 'make
    a 30s short' stays short.

    USER-OVERRIDE GATE (P3): this is a DEFAULT-FILLING backstop, never a
    silent override of a length the creator actually asked for. spec.
    length_user_set (set by the producer prompt when the creator named a
    specific length, in either direction) turns the whole bump off — a
    user-specified length rides through untouched, shorter OR longer than
    the channel median.

    P5 fix: length_user_set is the LLM's own self-report, not ground truth —
    a deterministic guard (_user_length_expression_present) only honors it
    when a plausible length expression ('90 seconds', '3-minute', '1 hour',
    ...) actually appears in one of the creator's own last few transcript
    turns (`transcript`). Otherwise it's logged and ignored, and the channel
    runtime backstop applies exactly as if the creator never named a length."""
    cards = data.get("cards")
    if not isinstance(cards, list):
        return
    plan = data.get("plan")
    spec = plan.get("spec") if isinstance(plan, dict) else None
    spec_min = None
    user_set = False
    if isinstance(spec, dict):
        try:
            spec_min = float(spec.get("video_length_minutes") or 0) or None
        except (TypeError, ValueError):
            spec_min = None
        user_set = bool(spec.get("length_user_set"))
        if user_set and not _user_length_expression_present(transcript):
            logger.warning(
                "chat length_user_set=true but no plausible length expression found "
                "in the last %d user turn(s) — distrusting the self-report and "
                "applying the channel-runtime backstop normally",
                _LENGTH_USER_SET_LOOKBACK_TURNS,
            )
            user_set = False
    channel_min = None
    if tenant_id is not None:
        from channel_identity_context import own_median_minutes

        own_min = await own_median_minutes(tenant_id)
        if own_min and own_min >= 1:
            channel_min = round(
                own_min
            )  # whole minutes, matches the slider's granularity
        else:
            med_s = await _competitor_median_seconds(tenant_id)
            if med_s >= 60:
                channel_min = round(med_s / 60)
    for c in cards:
        if not (
            isinstance(c, dict)
            and (c.get("id") == "length" or c.get("type") == "slider")
        ):
            continue
        mins = None
        try:
            mins = (
                float(c.get("recommended_minutes"))
                if c.get("recommended_minutes") is not None
                else None
            )
        except (TypeError, ValueError):
            mins = None
        mins = mins or spec_min
        # Backstop: anchor a normal-form default up to the channel's real runtime —
        # but NEVER touch a length the creator explicitly asked for.
        if channel_min and not user_set:
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
        conversation_id,
        tenant_id,
    )


async def _create_conversation(tenant_id) -> dict:
    return await fetch_one(
        """INSERT INTO chat_conversations (tenant_id)
           VALUES ($1)
           RETURNING id, project_id, video_id, transcript, state, phase""",
        tenant_id,
    )


async def _persist(
    conversation_id, tenant_id, transcript, state, phase, video_id=None
) -> None:
    await execute(
        """UPDATE chat_conversations
              SET transcript = $1, state = $2, phase = $3,
                  video_id = COALESCE($4, video_id), updated_at = now()
            WHERE id = $5 AND tenant_id = $6""",
        json.dumps(transcript),
        json.dumps(state),
        phase,
        video_id,
        conversation_id,
        tenant_id,
    )


_DEFAULT_PERSIST = _persist


def _custom_film_start_ready_response(
    conversation_id: str,
    state: dict[str, Any],
    video_id: str,
) -> ChatTurnResponse:
    """Reconstruct the one durable M2-3 result after a race or reload."""
    pending = state.get("pending_custom_film_plan")
    quote = pending.get("quote_inputs") if isinstance(pending, dict) else None
    total = (
        float(quote["totals"]["estimated_cost"])
        if isinstance(quote, dict)
        and isinstance(quote.get("totals"), dict)
        and quote["totals"].get("estimated_cost") is not None
        else None
    )
    amount = f"~${total:.2f} " if total is not None else ""
    scheduled = bool(isinstance(pending, dict) and pending.get("runtime_job_id"))
    message = (
        f"Approved — this exact {amount}BYOK plan is scheduled for section-aware "
        "production. No provider charge has happened yet."
        if scheduled
        else f"Approved — this exact {amount}BYOK plan is safely reserved, but "
        "runtime scheduling has not completed. Try again; the same video and "
        "approval will be reused without a duplicate charge."
    )
    return ChatTurnResponse(
        conversation_id=conversation_id,
        assistant_text=message,
        video_id=video_id,
        phase="created",
    )


def _custom_film_director_stage_response(
    conversation_id: str,
    state: dict[str, Any],
    video_id: str,
) -> ChatTurnResponse:
    """Reconstruct an approved Stage 1 schedule without dispatching it."""
    pending = state.get("pending_custom_film_plan")
    activation = (
        pending.get("director_activation") if isinstance(pending, dict) else None
    )
    quote = activation.get("stage_quote") if isinstance(activation, dict) else None
    cumulative = (
        int(quote["approved_cumulative_cents"])
        if isinstance(quote, dict)
        and type(quote.get("approved_cumulative_cents")) is int
        else None
    )
    amount = (
        f"${cumulative / 100:.2f}" if cumulative is not None else "the approved amount"
    )
    status = pending.get("status") if isinstance(pending, dict) else None
    completed = status == "director_stage_completed"
    return ChatTurnResponse(
        conversation_id=conversation_id,
        assistant_text=(
            (
                f"The screenplay/director stage is complete under the {amount} "
                "cumulative ceiling. Its film bible, locked cast and environments, "
                "dialogue, and progressive shot plan are now durable. No imagery, "
                "animation, voice, render, or upload was authorized."
            )
            if completed
            else (
                f"The screenplay/director stage is authorized at {amount} cumulative "
                "and its immutable multipass schedule is queued. No imagery, animation, "
                "voice, render, or upload is authorized."
            )
        ),
        video_id=video_id,
        phase="created",
    )


async def _schedule_reserved_custom_film_director(
    pending: Mapping[str, Any],
    *,
    tenant_id: str,
    video_id: str,
    arq_pool: Any,
) -> dict[str, Any]:
    """Enqueue the exact durable director job; replay converges on one arq key."""
    from custom_film_contract import CustomFilmContractError
    from job_queue import enqueue_stage

    schedule_id = str(pending.get("director_schedule_id") or "")
    director_job_id = str(pending.get("director_job_id") or "")
    if not schedule_id or not director_job_id:
        raise CustomFilmContractError(
            "The approved screenplay/director schedule is incomplete."
        )
    if arq_pool is None:
        raise CustomFilmContractError(
            "The approved screenplay/director schedule is safely saved, but the "
            "worker queue is unavailable. Retry later; StoryEngine will reuse the "
            "same exact job without another charge."
        )
    queued = await enqueue_stage(
        arq_pool,
        "custom_film_director",
        video_id,
        tenant_id,
        1,
        schedule_id=schedule_id,
        director_job_id=director_job_id,
    )
    return {
        "queue_enqueued": queued is not None,
        "queue_job_id": (queued or f"custom-film-worker:{director_job_id}:1"),
    }


async def _schedule_reserved_custom_film_runtime(
    conversation_id: str,
    tenant_id: str,
    state: dict[str, Any],
    video_id: str,
    *,
    arq_pool: Any = _QUEUE_CONTEXT_UNSET,
) -> dict[str, Any]:
    """Resume-safe scheduling for one already-reserved Custom Film video."""
    from custom_film_contract import CustomFilmContractError

    pending = state.get("pending_custom_film_plan")
    if not isinstance(pending, dict):
        raise CustomFilmContractError("Reserved Custom Film state is missing")
    expected = str(
        pending.get("start_intent_hash") or pending.get("approval_hash") or ""
    )
    quote_inputs = pending.get("quote_inputs")
    if not expected or not isinstance(quote_inputs, dict):
        raise CustomFilmContractError("Reserved Custom Film approval is incomplete")

    from custom_film_runtime import (
        consume_approval_and_schedule,
        load_exact_runtime_schedule,
    )

    try:
        scheduled = await load_exact_runtime_schedule(tenant_id, video_id, expected)
    except CustomFilmContractError:
        raise
    except Exception as exc:
        raise CustomFilmContractError(
            f"Runtime scheduling is temporarily unavailable: {exc}"
        ) from exc
    if scheduled is None:
        try:
            from vault import get_required_tenant_secret

            await get_required_tenant_secret(
                "kie_ai_api_key", tenant_id, provider_label="Kie.ai"
            )
            runtime_claimed = await generation_claims.acquire(
                tenant_id,
                video_id,
                "main",
                claimed_by=f"chat:custom-film-runtime:{conversation_id}",
            )
        except Exception as exc:
            raise CustomFilmContractError(
                getattr(exc, "message", None) or str(exc)
            ) from exc
        if not runtime_claimed:
            raise CustomFilmContractError(
                "This Custom Film runtime is already being scheduled. Try again shortly."
            )
        try:
            from routes.billing import check_plan_limits, enforce_video_length_cap

            await check_plan_limits(tenant_id, "video")
            await enforce_video_length_cap(
                tenant_id,
                float(quote_inputs["requested_duration_seconds"]) / 60,
            )
            scheduled = await consume_approval_and_schedule(
                tenant_id, video_id, expected
            )
        finally:
            await generation_claims.release(tenant_id, video_id, "main")

    pending["status"] = "start_ready"
    pending["video_id"] = video_id
    pending["start_intent_hash"] = expected
    pending["runtime_job_id"] = scheduled["job_id"]
    try:
        await execute(
            """UPDATE chat_conversations
               SET state = $3::jsonb, updated_at = now()
               WHERE id = $1 AND tenant_id = $2 AND video_id = $4""",
            conversation_id,
            tenant_id,
            json.dumps(state),
            video_id,
        )
    except Exception:
        # The durable exact task is authoritative. A conversation-state cache
        # miss is safe: the next reload finds the job by approval identity and
        # retries only this metadata write, never the video or schedule.
        logger.warning(
            "custom film runtime scheduled but conversation cache update failed",
            exc_info=True,
        )
    if arq_pool is not _QUEUE_CONTEXT_UNSET:
        if arq_pool is None:
            raise CustomFilmContractError(
                "The approved Custom Film schedule is safely saved, but the "
                "worker queue is unavailable. Retry later; StoryEngine will "
                "reuse this same exact job without another charge."
            )
        try:
            from job_queue import enqueue_stage

            queued_job_id = await enqueue_stage(
                arq_pool,
                "custom_film_runtime",
                video_id,
                tenant_id,
                1,
                runtime_job_id=str(scheduled["job_id"]),
            )
            # None means arq already owns this exact deterministic worker key.
            # That is successful convergence, not a reason to mint a retry key.
            scheduled["queue_enqueued"] = queued_job_id is not None
            scheduled["queue_job_id"] = (
                queued_job_id or f"custom-film-worker:{scheduled['job_id']}:1"
            )
        except Exception as exc:
            raise CustomFilmContractError(
                "The approved Custom Film schedule is safely saved, but its "
                "worker could not be queued. Retry to enqueue the same exact job."
            ) from exc
    return scheduled


def _custom_film_converged_response(
    conversation_id: str,
    conversation: dict[str, Any],
) -> ChatTurnResponse:
    """Return database truth when a Custom Film CAS loses."""
    state = _as_dict(conversation.get("state"))
    pending = state.get("pending_custom_film_plan")
    video_id = str(conversation["video_id"]) if conversation.get("video_id") else None
    if (
        video_id
        and isinstance(pending, dict)
        and pending.get("status") == "start_ready"
        and str(pending.get("video_id") or "") == video_id
    ):
        return _custom_film_start_ready_response(conversation_id, state, video_id)
    return ChatTurnResponse(
        conversation_id=conversation_id,
        assistant_text=(
            "This Custom Film conversation changed while that request was being "
            "handled, so I kept the newer saved state. Nothing was generated or "
            "charged by this request; please review the current plan."
        ),
        ready_to_create=False,
        phase=str(conversation.get("phase") or "plan"),
    )


async def _persist_custom_film_cas(
    conversation_id: str,
    tenant_id: str,
    transcript: list[dict[str, Any]],
    state: dict[str, Any],
    phase: str,
    expected_state: dict[str, Any] | None,
) -> ChatTurnResponse | None:
    """Persist a Custom Film turn only if its loaded state is still current.

    Direct helper tests written before the CAS contract omit ``expected_state``;
    retain their persistence seam without changing legacy production writes.
    Every endpoint Custom Film path supplies the raw loaded state.
    """
    if expected_state is None or _persist is not _DEFAULT_PERSIST:
        await _persist(conversation_id, tenant_id, transcript, state, phase)
        return None
    updated = await fetch_one(
        """UPDATE chat_conversations
              SET transcript = $1::jsonb, state = $2::jsonb, phase = $3,
                  updated_at = now()
            WHERE id = $4 AND tenant_id = $5
              AND video_id IS NULL
              AND state = $6::jsonb
            RETURNING id""",
        json.dumps(transcript),
        json.dumps(state),
        phase,
        conversation_id,
        tenant_id,
        json.dumps(expected_state),
    )
    if updated:
        return None
    current = await _load_conversation(conversation_id, tenant_id)
    if not current:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return _custom_film_converged_response(conversation_id, current)


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

    # Resolve the chosen style DESCRIPTION (id -> the canonical LOOK sentence
    # the generator front-loads) — the free-text aesthetic-overlay axis.
    # Falls back to a free-text look if the creator described their own style
    # instead of picking a preset. channel_format.STYLE_DESCRIPTIONS is the
    # single source (checklist §C21b — was producer_prompt.VISUAL_PRESETS).
    from channel_format import STYLE_DESCRIPTIONS

    preset_id = (spec.get("visual_style") or "").strip()
    preset = STYLE_DESCRIPTIONS.get(preset_id)
    if preset:
        visual_style = preset_id
        visual_style_label = preset["label"]
        image_style_override = preset["look"]
    else:
        visual_style = None
        visual_style_label = spec.get("visual_style_label")
        image_style_override = spec.get("image_style_override")

    # The LOOK ENGINE pick (a style_presets.id, e.g. "holographic_hud") — a
    # SEPARATE, additive axis from the style description above (checklist
    # §C21b). Validated downstream by routes.videos._resolve_style_preset_id
    # (create_video), same as the New Video gallery's style_preset_id — no
    # duplicate validation here.
    style_preset_id = (spec.get("style_preset_id") or "").strip() or None

    return CreateVideoRequest(
        title=(spec.get("title") or "Untitled video").strip(),
        framework_angle=spec.get("framework_angle"),
        writer_guidance=spec.get("writer_guidance"),
        video_length_minutes=length,
        visual_style=visual_style,
        image_style_override=image_style_override,
        visual_style_label=visual_style_label,
        style_preset_id=style_preset_id,
        production_style_id=(spec.get("production_style_id") or None),
        lock_in_identity=bool(spec.get("lock_in_identity", False)),
        aspect_ratio=aspect,
        pipeline_stages=stages,
        reference_url=(spec.get("reference_url") or None),
    )


# --- branches ----------------------------------------------------------------


async def _handle_approve(
    spec, conversation_id, tenant_id, transcript, state, background_tasks
):
    from routes.videos import create_video

    # The creator's actual card picks are authoritative over the LLM's spec.
    selections = state.get("selections") or {}
    if selections.get("style"):
        spec = {**spec, "visual_style": selections["style"]}
    # LOOK ENGINE pick (checklist §C21b) — a SEPARATE additive axis from
    # "style" above; same authoritative-over-the-LLM's-spec treatment.
    if selections.get("look_engine"):
        spec = {**spec, "style_preset_id": selections["look_engine"]}
    if selections.get("production_style"):
        spec = {**spec, "production_style_id": selections["production_style"]}
    if not spec.get("production_style_id"):
        msg = (
            "Choose one of the four video styles in the production plan first. "
            "That required choice controls the script, pictures, voices, and motion."
        )
        transcript.append(_assistant_turn({"assistant_text": msg, "phase": "plan"}))
        await _persist(conversation_id, tenant_id, transcript, state, "plan")
        return ChatTurnResponse(
            conversation_id=conversation_id,
            assistant_text=msg,
            plan={"spec": spec},
            ready_to_create=True,
            phase="plan",
        )
    # Length slider sends SECONDS (5s..1800s). The pipeline length is int minutes,
    # so round (min 1) and keep the exact target in writer_guidance so short
    # videos aren't silently treated as a full minute.
    if selections.get("length"):
        try:
            secs = max(LENGTH_MIN_SECONDS, int(float(selections["length"])))
            spec = {**spec, "video_length_minutes": max(1, round(secs / 60))}
            wg = (spec.get("writer_guidance") or "").strip()
            spec["writer_guidance"] = (
                f"{wg}\nTarget runtime: ~{_format_runtime(secs)} ({secs}s total).".strip()
            )
        except (TypeError, ValueError):
            pass

    req = _spec_to_create_request(spec)
    try:
        summary = await create_video(
            body=req, background_tasks=background_tasks, tenant_id=tenant_id
        )
    except HTTPException as e:
        # Plan limit (402) or bad input — return a friendly turn, never a raw error.
        msg = (
            "Looks like you're out of video credits on your plan. Upgrade and I'll get right on it."
            if e.status_code == 402
            else (
                e.detail
                if isinstance(e.detail, str)
                else "I couldn't start that one — mind trying again?"
            )
        )
        transcript.append(_assistant_turn({"assistant_text": msg, "phase": "plan"}))
        await _persist(conversation_id, tenant_id, transcript, state, "plan")
        return ChatTurnResponse(
            conversation_id=conversation_id,
            assistant_text=msg,
            ready_to_create=True,
            phase="plan",
        )

    video_id = summary.id
    # Static-documentary channels (exact-figures format) always research first;
    # every other video's autobuild skips the research pass and writes the
    # script straight from the topic (actions.make_autobuild_step). Check the
    # actual mode instead of assuming, so this message never claims a research
    # pass that isn't going to happen (P0.5 — it used to say "I'll research
    # it" unconditionally, which was simply false for the common case).
    video_row = await fetch_one(
        "SELECT render_mode FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id,
        tenant_id,
    )
    will_research = (video_row or {}).get("render_mode") == "static_docu"
    build_desc = (
        "research, script, then the pictures"
        if will_research
        else "the script, then the pictures"
    )
    # C16a (S7-1): claim the "main" lane BEFORE scheduling the autobuild chain
    # — this video was just created above so a same-turn conflict is not the
    # realistic case, but a retried/duplicated turn reaching this same
    # video_id (or a manual main-lane click racing it) must still be refused
    # rather than double-dispatch. Do NOT schedule on denial.
    title = spec.get("title") or "your video"
    if not await generation_claims.acquire(
        tenant_id, video_id, "main", claimed_by="chat:approve"
    ):
        transcript.append(
            _assistant_turn(
                {"assistant_text": _ALREADY_WORKING_REPLY, "phase": "created"}
            )
        )
        await _persist(
            conversation_id, tenant_id, transcript, state, "created", video_id=video_id
        )
        return ChatTurnResponse(
            conversation_id=conversation_id,
            assistant_text=_ALREADY_WORKING_REPLY,
            video_id=video_id,
            phase="created",
        )
    # Auto-build the whole thing up to the pictures (research -> script -> pictures
    # when applicable), then it pauses for review — not a single step.
    background_tasks.add_task(
        _make_autobuild_step(
            tenant_id,
            video_id,
            target="pictures",
            start_msg=f"Building “{spec.get('title') or 'your video'}” — {build_desc}…",
        )
    )
    if will_research:
        assistant_text = (
            f"Love it. I'm building “{title}” now — I'll research it, write the script, and generate the "
            "pictures, then pause so you can review them. Follow along right here."
        )
    else:
        assistant_text = (
            f"Love it. I'm building “{title}” now — I'll write the script straight from the topic "
            "(skipping a separate research pass so it moves faster; say the word any time and I'll "
            "run one) and generate the pictures, then pause so you can review them. Follow along right here."
        )
    transcript.append(
        _assistant_turn({"assistant_text": assistant_text, "phase": "created"})
    )
    await _persist(
        conversation_id, tenant_id, transcript, state, "created", video_id=video_id
    )
    return ChatTurnResponse(
        conversation_id=conversation_id,
        assistant_text=assistant_text,
        video_id=video_id,
        phase="created",
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
    r"confirm|proceed|make it|write( it)?|yes please|please do|let'?s (do it|go)|send it)[.!\s]*$",
    re.I,
)
_DENY_RE = re.compile(
    r"^\s*(n+o+|nope|cancel|stop|never ?mind|nevermind|don'?t|leave it|not now|hold off)[.!\s]*$",
    re.I,
)


async def _log_classification_confidence(
    tenant_id,
    video_id: Optional[str],
    *,
    kind: str,
    verb: str,
    confidence: float,
    source: str,
    gated: bool,
) -> None:
    """C36 (checklist §3.3 item 4): the copilot's confidence gate
    (``COPILOT_CONFIDENCE`` above) had no telemetry — a misfire (wrong verb,
    or a legitimate request stuck in the clarify-loop because it scored just
    under threshold) was invisible; there was no way to tell whether 0.55 was
    even the right number without guessing. This writes ONE row per
    classified turn: a log line (immediate, greppable) plus a row in
    ``bot_activity`` — the existing generic activity-log table every other
    bot already writes to (``pipeline_executor``, autopilot, etc.) — so a
    later tuning pass has real numbers to look at instead of a guess. No new
    table: `message` is a compact key=value line, `bot_name` is a new
    constant value ("copilot_classifier") on the SAME column every other
    activity row already keys on, so this can be filtered exactly like any
    other bot's rows in `/api/activity` or a direct query. Deliberately NOT a
    dashboard (out of scope this chunk, per the checklist) and deliberately
    fail-soft — a broken telemetry write must never break a chat turn."""
    try:
        logger.info(
            "copilot classify: kind=%s verb=%s confidence=%.3f source=%s gated=%s",
            kind,
            verb,
            confidence,
            source,
            gated,
        )
        message = f"kind={kind} verb={verb} confidence={confidence:.3f} source={source} gated={gated}"
        await execute(
            "INSERT INTO bot_activity (tenant_id, video_id, bot_name, status, message, cost) "
            "VALUES ($1, $2, 'copilot_classifier', 'completed', $3, 0)",
            tenant_id,
            video_id,
            message,
        )
    except Exception as e:  # noqa: BLE001 — telemetry must never break the copilot turn
        logger.warning("copilot: confidence telemetry write failed: %s", e)


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
        tenant_id,
        video_id,
    )
    if row:
        return row
    return await fetch_one(
        """INSERT INTO chat_conversations (tenant_id, video_id, phase)
           VALUES ($1, $2, 'created')
           RETURNING id, project_id, video_id, transcript, state, phase""",
        tenant_id,
        video_id,
    )


def _summary_line(s: dict[str, Any]) -> str:
    line = (
        f'Video: "{s["title"]}" — status {s["status"]}, target length {s.get("length_min") or "?"} min, '
        f"animation model {s['model']}.\n"
        f"Progress: {s['scenes']} scenes written ({s.get('voiced', 0)} voiced), {s['boards']} storyboards, "
        f"{s['pics']} pictures made, {s['clips']} clips animated. Spent so far ~${s['spent']:.2f}."
    )
    val = (s.get("validation") or "").strip()
    if val:
        # The creator can see these on the page; the co-pilot must not contradict them.
        line += (
            "\nScript-check results (these are REAL and visible to the creator — quote them "
            "accurately; if a [FAIL] line is present, never claim nothing failed):\n"
            + val
        )
    return line


def _pending_gate_kind_for(verb: str, summary: dict[str, Any]) -> Optional[str]:
    """Which review gate (if any) belongs in front of this verb's spend, given
    where this video already is. Reusable-mechanism seam (feat/approval-gates,
    DIRECTOR-CHAT-PLAN.md Task 5.2): the two checkpoints Ryan asked for —
    "review the script before spending on cast/locations", "review the cast
    + locations together before spending on storyboards/pictures" — read
    ONLY from durable video state (never a conversation-only flag), so a
    reload or a second conversation for the same video sees the same
    decision.

    - "script": verb == "characters" is the very next paid step after the
      script — designing the cast — and no character rows exist yet
      (`summary["cast"] == 0`). Once ANY character exists (drafted, whether
      approved or not), the gate has already been shown once; a later
      "redo the characters" confirms normally, it doesn't re-litigate the
      script.
    - "anchors": verb is "storyboards" or "images" (the two paid steps that
      spend on drawing pictures) and the cast+locations gate hasn't cleared
      (`chars_approved` / `envs_approved` — set together, see the
      approval_gate handshake above and the pre-existing approve_cast/
      approve_environments runners). Once BOTH are approved, this is a no-op
      forever for this video, matching "approved together in one gate, not
      two" from the design brief.

    Returns None for every other verb — this never touches build/voice/
    animate/render/upload/etc., and NEITHER new gate applies to a video that
    already has real progress past that checkpoint (an old video reusing
    these verbs behaves exactly as it did before this feature existed).
    """
    if verb == "characters" and int(summary.get("cast") or 0) == 0:
        return "script"
    # Guarded on `cast > 0` (not just the approval flags): a video that jumps
    # straight to "make the pictures" without ever designing a cast has
    # nothing to show in an anchors review — showing the card anyway would
    # display "Characters x 0" and let the tap fast-track past a gate with
    # nothing behind it. That video confirms exactly as it did before this
    # feature (the plain confirm_action card), same as any verb this function
    # returns None for.
    if (
        verb in ("storyboards", "images")
        and int(summary.get("cast") or 0) > 0
        and not (summary.get("chars_approved") and summary.get("envs_approved"))
    ):
        return "anchors"
    return None


async def _approval_gate_card(
    gate_kind: str,
    tenant_id,
    video_id: str,
    summary: dict[str, Any],
    cost_text: str,
    breakdown: Optional[dict[str, Any]],
) -> dict[str, Any]:
    """Build the compact `approval_gate` card (id="approval_gate"). Deliberately
    thin: counts + the cost quote for what happens on approval, nothing more —
    the frontend's side panel re-fetches the real script/cast/locations via the
    SAME endpoints ScriptResultCard/CastLocationsCard already use
    (frontend/src/components/chat/ChatResultCards.tsx), rather than this card
    duplicating that data. Every field is additive on top of the existing
    ChatCard shape (frontend/src/lib/api.ts) — an older frontend build that
    doesn't know "approval_gate" simply doesn't render this card kind at all,
    same as any other unrecognized card.id.
    """
    card: dict[str, Any] = {
        "id": "approval_gate",
        "gate_kind": gate_kind,
        "type": "single",
        "options": [
            {"value": "yes", "label": "Looks good!"},
            {"value": "no", "label": "Not yet"},
        ],
        "cost_text": cost_text,
    }
    if breakdown and breakdown.get("lines"):
        card["breakdown"] = breakdown
    if gate_kind == "script":
        card["label"] = summary.get("title") or "Untitled"
        card["scene_count"] = int(summary.get("scenes") or 0)
        length_min = summary.get("length_min")
        card["duration_seconds"] = int(round(length_min * 60)) if length_min else None
    else:
        card["label"] = "Review Anchors"
        card["character_count"] = int(summary.get("cast") or 0)
        card["location_count"] = int(summary.get("envs") or 0)
    return card


async def _post_approval_gate_for_autobuild(
    tenant_id, video_id: str, gate_kind: str, resume: dict[str, Any],
) -> None:
    """Called by actions.make_autobuild_step (lazy import from there — chat.py
    already imports actions.py at module level, so the reverse import must
    stay inside the function it's used from) when the auto-build chain
    ("Make it ✨", or the front door's declared explicit_verb="build" turn)
    reaches one of the two review checkpoints instead of the conversational
    verb-classification path in _handle_copilot.

    Posts the EXACT SAME approval_gate card a conversational "design the
    characters"/"make the pictures" turn would show, as a normal PERSISTED
    assistant turn in whichever conversation is bound to this video
    (_conversation_for_video — find-or-create, same lookup the dock's first
    open already uses). This is deliberately not a new, transient
    "the build is paused" flag: persisting it as an ordinary turn means a
    page reload re-hydrates the gate the exact same way it already
    reconstructs every other pending action card (ChatCore's
    `actionCard = lastCards?.find(...)` over the loaded transcript) — no
    new frontend reload-handling needed for this to survive a refresh.

    Money-wise this function only DISPLAYS the gate; it never runs
    generation itself (the caller already did whatever cheap design work
    happens before this checkpoint) and "Looks good!" resumes via the SAME
    untouched approval_gate handshake + `_run_pending_action("build", ...)`
    path every other gate approval already goes through.
    """
    conv = await _conversation_for_video(tenant_id, video_id)
    if not conv:
        return
    summary = await _copilot_summary(tenant_id, video_id)
    if not summary:
        return
    transcript = _as_list(conv.get("transcript"))
    state = _as_dict(conv.get("state"))
    # The cost quote shown on the card: the script gate's "next step" is
    # designing the cast (verb "characters"); the anchors gate's "next
    # step" is the REST of the autobuild chain (a "build" quote), since
    # approving it resumes the whole chain, not one single verb.
    quote_verb = "characters" if gate_kind == "script" else "build"
    _cost, cost_text = await _estimate_cost(tenant_id, video_id, quote_verb, None, summary)
    breakdown = await _cost_breakdown(tenant_id, video_id, quote_verb, None, summary)
    card = await _approval_gate_card(gate_kind, tenant_id, video_id, summary, cost_text, breakdown)
    state["pending_approval_gate"] = {"gate_kind": gate_kind, "resume": resume}
    state["pending_action"] = None
    text = (
        "Script's ready — take a look, then say the word and I'll design the cast and locations."
        if gate_kind == "script"
        else "Anchors are ready — the cast and locations. Take a look, then say the word and "
        f"I'll keep building ({cost_text})."
    )
    transcript.append(_assistant_turn({"assistant_text": text, "cards": [card], "phase": "created"}))
    await _persist(str(conv["id"]), tenant_id, transcript, state, "created", video_id=video_id)


def _confirm_card(
    verb: str,
    scene: Optional[int],
    cost_text: str,
    breakdown: Optional[dict[str, Any]] = None,
    budget_warning: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Smallest-change confirm: a single-select card the frontend already renders;
    the dock reads the pick back as selections.confirm_action = yes|no.

    C15: an optional itemized ``breakdown`` (per-model/tier lines +
    ``all_premium_total``, from ``actions.cost_breakdown``) rides along when
    the quote has one to show. Additive only — the key is omitted entirely
    when there's nothing to itemize, so an old frontend build (or a payload
    from a verb with no routing to break down) sees the EXACT same card
    shape as before C15.

    C36 (checklist §3.3 item 3): ``budget_warning`` (``actions.budget_check``'s
    return) rides along the same additive way when this quote would breach
    the video's optional cap — the "yes" option's label changes from "Do it"
    to "Do it anyway" so the tap itself reads as the explicit override the
    design calls for, and a ``budget`` key carries the numbers for a frontend
    that wants to render them distinctly. Omitted entirely when there's no
    cap or the quote fits under it — an old frontend, or a video with no cap
    set, sees the exact same card as before this chunk."""
    cfg = COPILOT_ACTIONS[verb]
    what = cfg["label"] + (f" — scene {scene}" if scene is not None else "")
    yes_label = (
        f"Do it anyway · {cost_text}" if budget_warning else f"Do it · {cost_text}"
    )
    card: dict[str, Any] = {
        "id": "confirm_action",
        "label": what,
        "type": "single",
        "options": [
            {"value": "yes", "label": yes_label},
            {"value": "no", "label": "Cancel"},
        ],
    }
    if breakdown and breakdown.get("lines"):
        card["breakdown"] = breakdown
    if budget_warning:
        card["budget"] = budget_warning
    return card


async def _run_pending_action(
    tenant_id, video_id, pending: dict, background_tasks, caller: str = "chat"
) -> str:
    """Kick off a confirmed action and return the 'on it' line.

    ``caller`` (C27, checklist P2.4b) is the claimed_by prefix used for every
    generation_claims acquire this dispatch makes — "chat" by default
    (unchanged behavior, every existing chat.py call site omits it), or
    "agent:<token name>" when routes/mcp.py calls this SAME dispatcher for a
    confirmed MCP tool call. This is the attribution seam C28's "via agent"
    chip reads (generation_claims.claimed_by LIKE 'agent:%' while a claim is
    live) — deliberately not a new column/migration, per docs/reports/2026-
    07-17-storyengine-agent-audit-findings.md §S5-2's "smallest correct v1"
    framing."""
    verb = pending["verb"]
    scene = pending.get("scene")
    cfg = COPILOT_ACTIONS[verb]
    # Edit-style verbs apply the creator's change to the stage guidance first.
    if cfg.get("edit") and pending.get("change"):
        await _apply_followup_edit(
            tenant_id,
            video_id,
            verb,
            {
                "guidance_append": pending["change"],
                "video_length_minutes": pending.get("length_min"),
            },
        )
    doing = cfg["doing"] + (f" for scene {scene}" if scene is not None else "")
    if verb == "build":
        target = pending.get("target") or "pictures"
        if target == "pictures":
            # Static-documentary channels always research first; everyone
            # else's autobuild skips research and writes from the topic
            # (actions.make_autobuild_step) — say so instead of claiming a
            # research pass that won't run (P0.5, same fix as _handle_approve).
            vrow = await fetch_one(
                "SELECT render_mode FROM videos WHERE id = $1 AND tenant_id = $2",
                video_id,
                tenant_id,
            )
            will_research = (vrow or {}).get("render_mode") == "static_docu"
            msg = (
                "On it — building your video. I'll run research, script and the pictures, then stop so "
                "you can review them."
                if will_research
                else "On it — building your video. I'll write the script straight from the topic (skipping "
                "research so it's faster — say the word and I'll run one) then make the pictures, then "
                "stop so you can review them."
            )
        else:
            msg = "On it — finishing your video (animating the clips and rendering). I'll update you here."
        # C16a (S7-1 CRITICAL): claim the "main" lane before scheduling — a
        # double-tap of the confirm card (or a retried turn) must not start
        # a second concurrent autobuild chain on the same video. Refuse and
        # DO NOT schedule when the lane is already claimed.
        if not await generation_claims.acquire(
            tenant_id, video_id, "main", claimed_by=f"{caller}:build:{target}"
        ):
            return _ALREADY_WORKING_REPLY
        background_tasks.add_task(
            _make_autobuild_step(tenant_id, video_id, target=target, start_msg=msg)
        )
        return msg
    # Runner verbs (approvals, lock, Drive sync, SEO…) reuse the same route
    # handlers the UI buttons call and speak the result back directly.
    # `caller` rides along in `pending` so the two runners that themselves
    # claim generation_claims (draft_pass/finalize) can attribute their own
    # acquire() the same way — see actions._runner_draft_pass/_runner_finalize.
    if cfg.get("runner"):
        return await _ACTION_RUNNERS[cfg["runner"]](
            tenant_id, video_id, background_tasks, {**pending, "caller": caller}
        )
    # C16e (S7-9 follow-up): "upload it"/"publish" on a video that's already
    # uploaded is far more likely a double-tap (a repeated turn, or the
    # autobuild finish chain having just uploaded it) than genuine intent to
    # mint a SECOND YouTube draft — it consumes another one of the shared
    # project's 100 daily upload calls. Check + reply BEFORE claiming a lane, so
    # a double-tap never even starts a background task. Design choice
    # (deliberately unlike C16d's thumbnail verb, which ALWAYS forces): see
    # actions.already_uploaded_reply's docstring for the full rationale.
    # PipelineExecutor.run_upload's own force= guard (checked independently
    # on every call) is the real money-safety backstop — this only keeps the
    # chat reply honest instead of scheduling a task that will silently skip.
    if verb == "upload":
        already = await _already_uploaded_reply(tenant_id, video_id)
        if already:
            return already
    # C16a (S7-1 CRITICAL): same claim/refuse discipline for single-stage
    # copilot verbs. Granularity: a verb with its own independent lane in the
    # existing in-process system (voice/characters/thumbnail) claims that
    # lane's name; every other verb claims "main" — see
    # generation_claims.stage_for_verb for the full rationale (it mirrors
    # routes/pipeline.py's existing lane vocabulary exactly, so a manual
    # click and a chat verb on the same lane genuinely conflict).
    claim_stage = generation_claims.stage_for_verb(verb)
    if not await generation_claims.acquire(
        tenant_id, video_id, claim_stage, claimed_by=f"{caller}:{verb}"
    ):
        return _ALREADY_WORKING_REPLY
    background_tasks.add_task(
        _make_copilot_step(
            tenant_id,
            video_id,
            cfg["calls"],
            scene=scene,
            start_msg=f"On it — {doing}…",
            stage=claim_stage,
        )
    )
    return f"On it — {doing} now. I'll update you right here."


# --- C15b: inline storyboards/keyframes in chat --------------------------------
#
# "Show me scene 2's boards" -> a card carrying tenant-authorized media-proxy
# URLs (never a raw Drive/external link) for that scene's shots, capped so one
# turn can't dump a wall of images. This is the missing half of revise-by-
# description (prompt studio -> redraw_asset_image already exists) — the other
# half was ChatCore never rendering any image at all.

_MAX_SHOW_IMAGES = 6


def _media_proxy_url(url: Optional[str]) -> Optional[str]:
    """Convert a stored Drive link into the backend's authorized proxy URL —
    same conversion pipeline_executor.py's per-clip `_proxy_url` and
    routes/characters.py's `_fetch_image_bytes` already do (Drive's public
    links unpredictably degrade into HTML interstitials; the proxy streams
    via the authorized Drive API instead). Anything that ISN'T a recognizable
    Drive link (e.g. the Supabase storage backend's own public URL) passes
    through unchanged — it was never a Drive link to begin with, matching
    the existing precedent exactly. Never returns a raw Drive URL."""
    if not url:
        return None
    m = re.search(r"[?&]id=([\w-]+)", url) or re.search(r"/d/([\w-]+)", url)
    if not m:
        return url
    base = os.getenv("PUBLIC_MEDIA_BASE", "https://storyengine.dev").rstrip("/")
    return f"{base}/api/media/drive/{m.group(1)}"


async def _handle_show_op(tenant_id, video_id, summary, data, ui_context, _reply):
    """kind=show: surface a scene's actual pictures/storyboards inline, capped
    at _MAX_SHOW_IMAGES, tenant+video+scene scoped (never another tenant's or
    another scene's assets). No pictures yet for that scene -> a friendly
    offer to generate them (with a real quote), not an empty/broken card."""
    scene = data.get("scene")
    if scene is None:
        scene = (ui_context or {}).get("scene")
    if scene is None:
        return await _reply(
            "Which scene's pictures would you like to see? e.g. \"show me scene 2's boards\"."
        )
    scene = int(scene)

    rows = await fetch_all(
        "SELECT id, image_index, image_url, drive_image_url FROM assets "
        "WHERE video_id=$1 AND tenant_id=$2 AND scene=$3 "
        "AND (image_url IS NOT NULL OR drive_image_url IS NOT NULL) "
        "ORDER BY image_index LIMIT $4",
        video_id,
        tenant_id,
        scene,
        _MAX_SHOW_IMAGES,
    )
    if not rows:
        _cost, cost_text = await _estimate_cost(
            tenant_id, video_id, "images", scene, summary
        )
        return await _reply(
            f"Scene {scene} doesn't have any pictures yet — want me to generate them? ({cost_text})."
        )

    images = []
    # Defense-in-depth: cap client-side too, not just via the SQL LIMIT — a
    # turn can never dump more than _MAX_SHOW_IMAGES regardless of what the
    # query returns.
    for r in rows[:_MAX_SHOW_IMAGES]:
        proxied = _media_proxy_url(r.get("image_url") or r.get("drive_image_url"))
        if not proxied:
            continue
        images.append(
            {
                "url": proxied,
                "label": f"Scene {scene} · shot {r.get('image_index')}",
                "asset_id": str(r["id"]),
                "scene": scene,
                "index": r.get("image_index"),
            }
        )
    if not images:
        return await _reply(
            f"Scene {scene}'s pictures aren't ready to view yet — try again in a moment."
        )

    card = {
        "id": "scene_boards",
        "label": f"Scene {scene} storyboards",
        "type": "single",
        "options": [],
        "images": images,
    }
    n = len(images)
    return await _reply(
        f"Here's scene {scene} — {n} shot{'s' if n != 1 else ''}. Tell me what to change, or "
        f'"approve scene {scene}" if these are good.',
        cards=[card],
    )


def _selection_context_note(ui_context: dict[str, Any]) -> str:
    """DIRECTOR-CHAT-PLAN.md Task 5.4a/b: tell the classifier what's ALREADY
    selected on the Director canvas/rail, so it only has to pick the right
    SURFACE (image/motion/character/environment) — never an id. The actual id
    resolution is 100% code, off `ui_context` directly (routes/chat.py
    `_resolve_prompt_target`/`_resolve_character_target`/
    `_resolve_environment_target`), so a misread here can misclassify the
    KIND of edit but can never point a correctly-classified one at the wrong
    shot/character/environment — that's the deterministic half the plan asks
    for. Duplicated (not shared) in agent_brain.py's system prompt, matching
    this file's existing precedent for the scene/index injection right above
    every call site — chat.py imports agent_brain lazily, inside a function
    body, specifically to avoid a circular import back here."""
    lines = []
    if ui_context.get("focusedAssetId"):
        lines.append(
            f"A shot is currently focused on the canvas (asset id {ui_context['focusedAssetId']}). If "
            "they describe a PICTURE or its MOTION with no scene/shot number named ('this shot', 'this "
            "one', 'make him older', 'zoom in more') — set kind=prompt, surface=image (or motion for a "
            "motion/camera direction), and leave scene/index null; I resolve the exact shot from the "
            "selection myself, never guess a number.\n"
        )
    entity_type = ui_context.get("selectedEntityType")
    if entity_type in ("character", "environment"):
        noun = "person" if entity_type == "character" else "place"
        lines.append(
            f"A {entity_type} is currently selected in the right rail. If they describe that {noun} with "
            "no name given ('make him older', 'she should look tougher', 'add rain to this place') — set "
            f"kind=prompt, surface={entity_type}, and leave scene/index null; I resolve the exact "
            f"{entity_type} from the selection myself, never guess which one.\n"
        )
    return "".join(lines)


async def _handle_copilot(
    body, conversation_id, tenant_id, transcript, state, video_id, background_tasks
):
    """The video-scoped co-pilot turn. Classify -> read (answer) or action (run).
    Paid actions ALWAYS confirm first — dock and home alike (Phase 2 closed the
    home CreatedCard hole where money moved without a tap)."""
    msg = (body.message or "").strip()
    sel = body.selections or {}
    ui_context = getattr(body, "ui_context", None) or {}

    async def _reply(text, cards=None):
        transcript.append(
            _assistant_turn(
                {"assistant_text": text, "cards": cards, "phase": "created"}
            )
        )
        await _persist(
            conversation_id, tenant_id, transcript, state, "created", video_id=video_id
        )
        return ChatTurnResponse(
            conversation_id=conversation_id,
            assistant_text=text,
            cards=cards,
            video_id=video_id,
            phase="created",
        )

    # --- confirm handshake: turn 2 of a paid/destructive action ---
    if "confirm_action" in sel:
        pending = state.get("pending_action")
        state["pending_action"] = None
        if sel["confirm_action"] == "yes" and pending:
            line = await _run_pending_action(
                tenant_id, video_id, pending, background_tasks
            )
            return await _reply(line)
        return await _reply(
            "No problem — left it as it is. Tell me what you'd like instead."
        )

    # --- approval gate handshake (feat/approval-gates): turn 2 of the script
    # or anchors (characters + locations) review card. Deliberately its OWN
    # state slot (`pending_approval_gate`), not a reuse of `pending_action` —
    # a gate carries a `gate_kind` the frontend needs to pick the right card
    # body, and approving it can also stamp durable approval columns (below)
    # before resuming. Resuming reuses the EXACT same `_run_pending_action`
    # dispatcher every confirm_action tap already goes through, so a gate's
    # "Looks good!" is not a new way to spend money — it's the same one-tap
    # confirm, wrapped in a richer preview.
    if "approval_gate" in sel:
        pending_gate = state.get("pending_approval_gate")
        state["pending_approval_gate"] = None
        if sel["approval_gate"] == "yes" and pending_gate and (pending_gate.get("resume") or {}).get("verb"):
            resume = pending_gate["resume"]
            if pending_gate.get("gate_kind") == "anchors":
                # Mirrors the ad hoc UPDATE the autobuild image-phase already
                # runs (actions.make_autobuild_step) when it silently
                # auto-passes this same gate — doing it explicitly here means
                # an anchors gate, once approved, is never re-offered on a
                # later "make the pictures"/"generate storyboards" turn.
                await execute(
                    "UPDATE videos SET characters_approved_at = COALESCE(characters_approved_at, now()), "
                    "environments_approved_at = COALESCE(environments_approved_at, now()), "
                    "updated_at = now() WHERE id = $1 AND tenant_id = $2",
                    video_id, tenant_id,
                )
            state["pending_action"] = None
            line = await _run_pending_action(tenant_id, video_id, resume, background_tasks)
            return await _reply(line)
        return await _reply(
            "No problem — take your time. Tell me if you'd like any changes, or say "
            "the word when you're ready to continue."
        )

    # --- prompt studio: apply (or cancel) a proposed prompt rewrite ---
    if "prompt_apply" in sel:
        draft = state.get("prompt_draft")
        state["prompt_draft"] = None
        if sel["prompt_apply"] == "yes" and draft:
            # The dock sends the (possibly hand-edited) prompt text — full edit access.
            edited = (sel.get("prompt_text") or "").strip()
            if edited:
                draft = {**draft, "draft": edited}
            line = await _apply_prompt_draft(
                tenant_id, video_id, draft, background_tasks
            )
            return await _reply(line)
        return await _reply(
            "No problem — kept the original prompt. Tell me what else you'd like."
        )

    # Files dropped into the docked co-pilot: bind them to this conversation
    # (they're already stamped with video_id at upload time — see /api/chat/upload)
    # and fold a description into the transcript so the copilot sees what arrived.
    # Reuses the same _attach_assets the home chat uses — no separate path.
    if body.attachments:
        attach_lines: list[str] = []
        await _attach_assets(
            tenant_id, conversation_id, body.attachments, state, attach_lines
        )
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
        return await _reply(
            "Ask me anything about this video, or tell me what to do next — e.g. "
            "“animate scene 2”, “redo the thumbnail”, or “how much has this cost?”"
        )

    # --- typed consent: a pending confirm answered in words runs (or clears) it ---
    pending = state.get("pending_action")
    if pending and _AFFIRM_RE.match(msg):
        state["pending_action"] = None
        line = await _run_pending_action(tenant_id, video_id, pending, background_tasks)
        return await _reply(line)
    if pending and _DENY_RE.match(msg):
        state["pending_action"] = None
        return await _reply(
            "No problem — left it as it is. Tell me what you'd like instead."
        )

    summary = await _copilot_summary(tenant_id, video_id)
    if not summary:
        return await _reply(
            "I can't find that video anymore — it may have been deleted."
        )

    # --- explicit entry intent: state it, don't guess it -----------------------
    # The single most important action in the product — "build the whole video" —
    # must never depend on an LLM classifier's guess. DirectorHome's front-door
    # box (the ONE box that creates a brand-new video) sends its opening chat
    # turn with `explicit_verb="build"` set (ChatCore's initialMessage mount
    # effect, gated on `initialIntent === "build"` — see DirectorContext.tsx /
    # DirectorHome.tsx PromptEntrySection.send()). When that's present, skip
    # classification (and the API-key requirement it carries) entirely and go
    # straight to the SAME legality-gate + paid-confirm-card path every
    # classified verb already goes through below — so a declared "build" still
    # quotes real cost and still waits for an explicit tap, it just never
    # risked being misread as some other verb.
    #
    # Root-cause context (verified 2026-07-27, video d218b352-8894-45d1-af0a-
    # fb8847d39e55): "make a 1 minute video about a dystopian world where the
    # elites watch the citizens through bubbles" — a plain topic pitch with no
    # explicit "build"-trigger phrase in it — classified as verb=script
    # (confidence 0.930), which is a single $0.02 stage with no continuation,
    # not the whole-pipeline build the creator actually asked for by using
    # this box. That silent misfire is why this deterministic path exists.
    #
    # Anything that isn't a real COPILOT_ACTIONS verb is ignored (defends
    # against a stale or tampered client) and falls through to the classifier
    # exactly as before.
    explicit_verb = (getattr(body, "explicit_verb", None) or "").strip()
    if explicit_verb and explicit_verb not in COPILOT_ACTIONS:
        explicit_verb = ""

    if explicit_verb:
        kind, verb, reply, conf = "action", explicit_verb, "", 1.0
        # Downstream reads data.get("scene"/"change"/"length_min") — none of
        # which apply to a declared "build" on a just-created video, so an
        # empty dict is the correct (not a stand-in) value, same as a
        # classified turn that named no scene/change/length.
        data: dict[str, Any] = {}
        await _log_classification_confidence(
            tenant_id,
            video_id,
            kind=kind,
            verb=verb,
            confidence=conf,
            source="explicit_entry",
            gated=False,
        )
    else:
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
        copilot_model = _claude_model_for_direct_client(client)

        # While a proposed prompt is open, plain text REFINES it (no spend). Bail words
        # drop the draft; otherwise feed the words back as more direction and redraft.
        draft = state.get("prompt_draft")
        if draft and msg and not sel:
            low = msg.lower()
            if any(
                w in low
                for w in (
                    "cancel",
                    "never mind",
                    "nevermind",
                    "forget it",
                    "leave it",
                    "no thanks",
                )
            ):
                state["prompt_draft"] = None
                return await _reply("No problem — kept the original. What else can I do?")
            new = await _rewrite_prompt(
                client,
                copilot_model,
                draft["surface"],
                draft["draft"],
                msg,
                summary["model"],
            )
            if new:
                draft["draft"] = new
                state["prompt_draft"] = draft
                return await _reply(
                    f"Updated the prompt for {draft['label']} — review and tweak it below, then apply "
                    "(or keep adjusting in words).",
                    cards=[_prompt_apply_card(draft, new)],
                )
            return await _reply("I couldn't adjust that — try wording it a different way?")

        # Files the creator has dropped into this video's co-pilot (chat_assets rows
        # bound to this conversation) — folded into the summary so the copilot can
        # reference them ("use the reference I dropped", "that image I attached").
        # THE channel-identity pool brief (checklist P2) goes FIRST, ahead of the
        # video summary — same position/rationale as the home producer assembly
        # in chat_turn: its hard precedence law must be the first thing the
        # co-pilot reads.
        summary_with_assets = (
            await _identity_pool_brief(tenant_id)
            + _summary_line(summary)
            + await _assets_brief(tenant_id, state)
            + await _preferences_brief(tenant_id, video_id)
        )

        prompt = (
            "You are the in-app co-pilot for ONE video. The creator can (a) ASK a question, (b) tell you to RUN a "
            "production step, (c) work on a generation PROMPT (view it, get suggestions, or rewrite/enhance it "
            "for a specific shot), or (d) ask to SEE the actual pictures/storyboards for a scene. Decide which.\n\n"
            + summary_with_assets
            + "\n"
            + (
                f"They are currently viewing scene {ui_context.get('scene')}"
                + (f", image {ui_context.get('index')}" if ui_context.get("index") else "")
                + ".\n"
                if ui_context.get("scene")
                else ""
            )
            + _selection_context_note(ui_context)
            + f'\nThe creator said: "{msg}"\n\n'
            "ACTIONS (kind=action, exact verb): script, characters, storyboards, images, voice, animate, "
            "draft_pass, finalize, sound, thumbnail, render, research, seo, upload, approve_cast, "
            "approve_environments, skip_environments, approve_scene, camera_preset, script_profile, lock, unlock, "
            "drive_push, drive_sync, advance — for RUNNING/redoing a SINGLE step. "
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
            "'approve_scene' = approve/lock in ONE scene's pictures ('approve scene 2', 'scene 3 looks good, lock "
            "it in', 'these are good, approve them' while viewing a scene) — give the scene number (use the "
            "'currently viewing' scene if they say 'this scene'/'these' and name none). Different from approve_cast/"
            "approve_environments, which gate the whole video's cast/locations, not one scene. "
            "'camera_preset' = set or clear the CAMERA MOVE for a scene's shots ('use a crash zoom on scene 12', "
            "'give the opening a slow push-in', 'put scene 4's camera back to auto') — give the scene number "
            "(use 'currently viewing' for 'this scene') and put the move description ('crash zoom', 'push in', "
            "'auto', etc.) VERBATIM in change. Free and reversible, no confirm needed. "
            "'script_profile' = set or clear the SCRIPT VOICE for future script writes ('write it in the "
            "investigative style', 'use the framework explainer voice', 'put the script voice back to neutral') — "
            "put the voice description ('investigative reveal', 'framework explainer', 'neutral', etc.) VERBATIM "
            "in change. Free and reversible, no confirm needed. Does NOT itself rewrite an existing script — that's "
            "the 'script' verb. "
            "'budget_cap' = set or clear a SPENDING CAP for this video ('cap this video at $15', 'set a $20 "
            "budget limit', 'remove the budget cap', 'no spending limit') — put the amount VERBATIM in change "
            "(e.g. '$15', 'remove the cap'). Free and reversible, no confirm needed — it only changes what future "
            "paid actions check against, it never spends anything itself. "
            "'lock' / 'unlock' = freeze or unfreeze the story(boards) before image spend. "
            "'drive_push' = send the script to Google Drive as an editable Doc; 'drive_sync' = pull the creator's "
            "Doc edits back into the app ('pull my script from Drive', 'sync my Doc changes'). "
            "Use 'build' when they want the whole video built or moved forward, OR when they are simply "
            "PITCHING/DESCRIBING a video idea with no prior script or research on this video yet — 'build it', "
            "'make the video', 'do it', 'run it all', 'keep going', 'generate it', 'finish it', 'animate "
            "everything', 'make a video about X', 'make me a N minute video about X', 'create a video about X'. "
            "This matters most on a FRESH video (no script yet, no research yet): a plain topic description "
            "there ('a dystopian world where...', 'a boy who finds a dragon') is the creator saying what the "
            "WHOLE video should be about, not a request to write just one stage — classify that as build, "
            "never as 'script'. Only classify as 'script' when they clearly want JUST the writing step touched "
            "on a video that already has some history (e.g. 'rewrite the script', 'make the opening punchier', "
            "'redo scene 3's script'). build runs the pipeline automatically to the next checkpoint, NOT one "
            "step. "
            "'draft_pass' = animate EVERY scene on the CHEAP draft-tier model in one pass, before spending real "
            "money — 'draft the whole video', 'rough cut', 'let me see it first', 'draft it cheap'. Different "
            "from 'animate everything'/build, which animates at REAL (routed/premium) quality — draft_pass is "
            "explicitly the cheap-preview pass. 'finalize' = regenerate ONLY the scenes already approved "
            "(approve_scene) at their real routed/premium quality — 'finalize the approved scenes', 'finish "
            "scenes 3 and 7' (no scene number needed — it always means whichever scenes are currently approved). "
            "If nothing is approved yet, finalize still classifies as the verb — the runner itself explains "
            "there's nothing approved yet.\n"
            "PROMPT work (kind=prompt) when they talk about the generation PROMPT TEXT itself — 'rewrite/enhance "
            "the prompt', 'show me the prompt', 'suggest improvements', 'make a better prompt', 'image 1 looks "
            "off, rewrite its prompt to…' — OR when they describe a CHARACTER's or LOCATION's DESCRIPTION with "
            "one selected ('make him older', 'she should look tougher', 'add rain to this place' — see the "
            "'currently focused/selected' note below if present). Then set surface (image=a picture | "
            "motion=a clip's motion | thumbnail | script | character=a character's description | "
            "environment=a location's description), op (view=show current | suggest=ideas only, no change | "
            "rewrite=write a new one to apply), the scene/index of the shot (use the 'currently viewing' one if "
            "they say 'this' and name no shot; leave both null for character/environment, or when a shot is "
            "already focused — see below), and the direction.\n"
            "SHOW work (kind=show) when they want to SEE the actual pictures/storyboards/keyframes for a scene — "
            "'show me scene 2's boards', 'let me see scene 3's pictures', 'what does scene 1 look like' — NOT the "
            "prompt text (that's kind=prompt above). Give the scene (use the 'currently viewing' one for 'this "
            "scene'/'these' with no number named).\n"
            "REMEMBER work (kind=remember) when they give a STANDING instruction meant to stick across future "
            "conversations and videos, not just this one ask — 'always...', 'never...', 'remember that...', 'from "
            "now on...'. Put their instruction VERBATIM in change (do not paraphrase). Set scope='video' only when "
            "it's clearly specific to THIS video; default scope='channel' (e.g. they said always/never/from now "
            "on, or it's a general fact about them/their channel).\n"
            "FORGET work (kind=forget) when they say 'forget that', 'forget #N', 'forget the one about...', or ask "
            "'what do you remember (about me/this channel)?'. For an ask-to-list, answer directly from the STANDING "
            "PREFERENCES list above (if present) as kind=read instead. For an actual forget, put their reference "
            "(a number, 'that'/'last', or the closest matching text) in change.\n"
            "If they're ASKING about state (cost/status/what's left/why), kind=read and answer from the numbers.\n\n"
            "Return ONE JSON object and nothing else:\n"
            '{"kind":"read|action|prompt|show|remember|forget",'
            '"verb":"script|characters|storyboards|images|voice|animate|draft_pass|finalize|sound|thumbnail|'
            "render|research|seo|upload|approve_cast|approve_environments|skip_environments|approve_scene|"
            'camera_preset|script_profile|budget_cap|lock|unlock|drive_push|drive_sync|advance|build|none",'
            '"surface":"image|motion|thumbnail|script|character|environment|null",'
            '"op":"view|suggest|rewrite|null",'
            '"scene":<int or null>,"index":<int picture/shot number or null>,'
            '"change":"<for action edits: a concrete instruction; for remember: the instruction VERBATIM; for '
            'forget: their reference to which one; else empty>",'
            '"direction":"<for prompt rewrite: the enhancement instruction; else empty>",'
            '"length_min":<int or null>,'
            '"scope":"channel|video (only meaningful for kind=remember; default channel)",'
            '"answer":"<for read: a friendly, specific 1-2 sentence answer using the numbers>",'
            '"reply":"<for action: one friendly sentence; for none: a clarifying question>",'
            '"confidence":<0.0-1.0>}'
        )
        # THE AGENT BRAIN (Phase 6): a tool-using loop that READS the video (state,
        # script, shots, prompts, history) before deciding, then returns the same
        # decision shape as the one-shot classifier. Any failure -> None -> the
        # legacy classifier below runs instead, so the brain can only add smarts.
        data = None
        used_brain = False
        try:
            from agent_brain import run_copilot_brain

            data = await run_copilot_brain(
                client,
                copilot_model,
                tenant_id,
                video_id,
                summary,
                msg,
                ui_context,
                summary_with_assets,
            )
            used_brain = data is not None
        except Exception as e:  # noqa: BLE001
            logger.warning("copilot: agent brain failed, falling back: %s", e)
        if data is None:
            try:
                from producer_prompt import _extract_json

                gen_kwargs: dict[str, Any] = {
                    "prompt": prompt,
                    "max_tokens": 700,
                    "temperature": 0.2,
                }
                if copilot_model:
                    gen_kwargs["model"] = copilot_model
                raw = await client.generate(**gen_kwargs)
                data = json.loads(_extract_json(raw))
            except Exception as e:  # noqa: BLE001
                logger.warning("copilot: classify failed: %s", e)
                return await _reply(
                    "I didn't quite catch that — want me to change the script, the pictures, the "
                    "thumbnail, animate a scene, or render it?"
                )

        kind = (data.get("kind") or "").strip()
        verb = (data.get("verb") or "none").strip()
        reply = (data.get("reply") or "").strip()
        conf = float(data.get("confidence") or 0)
        await _log_classification_confidence(
            tenant_id,
            video_id,
            kind=kind,
            verb=verb,
            confidence=conf,
            source="brain" if used_brain else "legacy",
            gated=(verb not in COPILOT_ACTIONS or conf < COPILOT_CONFIDENCE),
        )

    # --- prompt studio: view / suggest / rewrite a generation prompt ---
    if kind == "prompt":
        return await _handle_prompt_op(
            client,
            copilot_model,
            tenant_id,
            video_id,
            summary,
            data,
            ui_context,
            state,
            _reply,
        )

    # --- C15b: show the actual storyboards/keyframes for a scene, inline ---
    if kind == "show":
        return await _handle_show_op(
            tenant_id, video_id, summary, data, ui_context, _reply
        )

    # --- C15c: director memory — a standing instruction becomes a durable
    # preference; "forget" deactivates one. Free, no confirm needed. ---
    if kind == "remember":
        return await _handle_remember_op(tenant_id, video_id, data, _reply)
    if kind == "forget":
        return await _handle_forget_op(tenant_id, video_id, data, _reply)

    # --- read: answer immediately, no spend ---
    if kind == "read" or verb == "none":
        answer = (data.get("answer") or reply or "").strip()
        if not answer:
            answer = (
                f"“{summary['title']}” is at {summary['status']}: {summary['scenes']} scenes, "
                f"{summary['pics']} pictures, {summary['clips']} clips. Spent so far ~${summary['spent']:.2f}."
            )
        return await _reply(answer)

    if verb not in COPILOT_ACTIONS or conf < COPILOT_CONFIDENCE:
        return await _reply(
            reply
            or "Happy to help — want me to change the script, the pictures, the "
            "thumbnail, the voice, animate a scene, add sound, or render it?"
        )

    # --- legality gate: refuse politely if the prerequisite isn't there ---
    blocked = _action_blocked(verb, summary)
    if blocked:
        return await _reply(
            f"I can't {COPILOT_ACTIONS[verb]['label'].lower()} yet — {blocked}. "
            "Want me to do that first?"
        )

    scene = data.get("scene")
    scene = int(scene) if isinstance(scene, (int, float)) else None
    cfg = COPILOT_ACTIONS[verb]

    # --- free vs paid ---
    if not cfg["paid"]:
        line = await _run_pending_action(
            tenant_id,
            video_id,
            {
                "verb": verb,
                "scene": scene,
                "change": data.get("change"),
                "length_min": data.get("length_min"),
            },
            background_tasks,
        )
        return await _reply(line)

    # Paid: ALWAYS held behind a one-tap confirm card — dock and home alike.
    # (Phase 2 closed the hole where the home CreatedCard follow-up spent money
    # with no tap; the home chat renders the same confirm card.)
    pending = {
        "verb": verb,
        "scene": scene,
        "change": (data.get("change") or "").strip(),
        "length_min": data.get("length_min"),
    }
    if verb == "build":
        # To pictures if we're before them, else finish the rest.
        pending["target"] = (
            "pictures" if summary["status"] in _BUILD_TO_PICTURES else "finish"
        )

    _cost, cost_text = await _estimate_cost(tenant_id, video_id, verb, scene, summary)
    # C36 (checklist §3.3 item 3): would this quote push the video over its
    # optional per-video cap? None on any video without one set — same
    # module-wide "quote honestly, never silent-block" philosophy as the rest
    # of this money gate. Folded into the SAME one-tap confirm card below —
    # tapping "yes" after reading this warning IS the explicit override.
    budget_warning = _budget_check(summary, _cost)
    # C15: itemize the SAME quote by model/tier — one resolver
    # (actions.cost_breakdown groups the exact per-row prices _estimate_cost
    # already summed), never a second cost path. None for verbs/states with
    # nothing routed to itemize (e.g. a build quote before any pictures
    # exist) — cost_text alone carries the confirm text in that case,
    # unchanged from pre-C15 behavior.
    breakdown = await _cost_breakdown(tenant_id, video_id, verb, scene, summary)

    # --- approval gate (feat/approval-gates): the SAME cost quote computed
    # above, shown as the rich script/anchors review card instead of the
    # plain confirm_action card — the whole feature's job is to make these
    # two moments a genuine review, not a smaller change in disguise. Only
    # fires the FIRST time each checkpoint is reached (see
    # _pending_gate_kind_for); once past it, this verb confirms exactly as
    # it always has. Never a SECOND, more expensive quote than the one that
    # was about to show — this literally IS that quote, just in a richer card.
    gate_kind = _pending_gate_kind_for(verb, summary)
    if gate_kind:
        state["pending_approval_gate"] = {"gate_kind": gate_kind, "resume": pending}
        state["pending_action"] = None
        gate_card = await _approval_gate_card(
            gate_kind, tenant_id, video_id, summary, cost_text, breakdown
        )
        gate_intro = (
            "Here's the script — take a look, then say the word and I'll design the cast and locations."
            if gate_kind == "script"
            else "Here are the anchors — the cast and locations. Take a look, then say the word and I'll "
            f"draw the storyboards ({cost_text})."
        )
        return await _reply(gate_intro, cards=[gate_card])

    state["pending_action"] = pending
    # Deterministic, confirmation-clear message — NOT the model's free-text reply, which
    # tended to say "Generating now…" even though this is gated behind a tap (the money
    # gate). State what will run + the cost + that a tap is needed; no contradiction.
    where = f" for scene {scene}" if scene is not None else ""
    detail = ""
    if breakdown and breakdown["lines"]:
        parts = [
            f"{ln['count']} × {ln['display_name']} (${ln['subtotal']:.2f})"
            for ln in breakdown["lines"]
        ]
        detail = " — " + "; ".join(parts)
        if (
            breakdown.get("all_premium_total")
            and breakdown["all_premium_total"] > breakdown["total"]
        ):
            detail += f" vs ${breakdown['all_premium_total']:.2f} all-premium"
        # Only call out hero scenes by name when the plan is actually mixed
        # (more than one model in play) — a uniform plan has nothing to
        # single out. routing_reason rides straight from the asset row —
        # never re-derived here.
        hero = breakdown.get("hero_scenes") or []
        if hero and len(breakdown["lines"]) > 1:
            names = "; ".join(
                f"scene {h['scene']} ({h['reason']})"
                for h in hero[:3]
                if h.get("scene") is not None
            )
            if names:
                detail += f". {names}"
    guard = (
        f" {_guardrail_note(summary.get('render_style'))}"
        if breakdown and breakdown["lines"]
        else ""
    )
    budget_note = f" ⚠️ {budget_warning['message']}" if budget_warning else ""
    intro = (
        f"Ready when you are — I'll {cfg['label'].lower()}{where} ({cost_text}{detail}). "
        f"Tap to run it, or tell me to change anything first.{guard}{budget_note}"
    )
    return await _reply(
        intro, cards=[_confirm_card(verb, scene, cost_text, breakdown, budget_warning)]
    )


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

_PROMPT_SURFACES = {"image", "motion", "thumbnail", "script", "character", "environment"}
_IMAGE_GUIDE = (
    "Target: GPT Image 2 drawing ONE cinematic 16:9 frame. Keep the locked characters' exact looks. "
    "Be concrete and visual — subject, action, composition, lighting, lens, mood. One flowing prompt, no lists."
)
_THUMB_GUIDE = (
    "Target: a high-CTR YouTube thumbnail. Bold focal subject, strong emotion/expression, high contrast, "
    "readable at small size, minimal text. One flowing image prompt."
)
_SCRIPT_GUIDE = (
    "Target: the spoken script for this scene. Keep the story beats and characters; sharpen the hook, "
    "clarity, pacing and voice. Return the rewritten scene text only."
)
# DIRECTOR-CHAT-PLAN.md Task 5.4b: "an indian boy", "a mexican grandma", "make him
# older" — free text against a CHARACTER's/ENVIRONMENT's description field, the
# same one-tap propose-then-apply shape as image/motion/thumbnail/script above.
# Free (apply_cost=0.0, see _resolve_character_target/_resolve_environment_target)
# — this only rewrites the description text (routes.characters.update_character /
# routes.environments.update_environment); it does NOT redraw the portrait/
# reference image (that's the separate, paid redo_character_sheet/redo_environment
# MCP tools — out of scope here, same distinction the MCP tool docstrings draw).
_CHARACTER_GUIDE = (
    "Target: a character's DESCRIPTION text (what future artwork of them is drawn from), not the portrait "
    "image itself. Keep their name and any locked visual traits the creator didn't ask to change. Return the "
    "FULL updated description (not just the changed clause)."
)
_ENVIRONMENT_GUIDE = (
    "Target: a location's DESCRIPTION text (what future artwork of this place is drawn from), not the "
    "reference image itself. Keep anything the creator didn't ask to change. Return the FULL updated "
    "description (not just the changed clause)."
)
# Motion guidance keyed by the chosen video model (self-contained — no import risk).
_MOTION_MODEL_GUIDE = {
    "grok-imagine": "Target: Grok Imagine motion (~6-10s). You MAY name one simple camera move. Keep motion physical and clear.",
    "seedance-2-fast": "Target: Seedance 2.0 cinematic motion (6-10s). Camera control + first/last frame supported — you may specify a camera move and pacing.",
    "veo-3.1-fast": "Target: Veo 3.1 (8s). NO in-prompt camera control — describe the SUBJECT's motion and the action, not camera operation. Rich cinematic detail works.",
    "veo-3.1-quality": "Target: Veo 3.1 (8s). NO in-prompt camera control — describe the SUBJECT's motion and the action. Rich cinematic detail works.",
}


def _surface_guide(surface: str, video_model: str) -> str:
    if surface == "image":
        return _IMAGE_GUIDE
    if surface == "thumbnail":
        return _THUMB_GUIDE
    if surface == "script":
        return _SCRIPT_GUIDE
    if surface == "character":
        return _CHARACTER_GUIDE
    if surface == "environment":
        return _ENVIRONMENT_GUIDE
    return _MOTION_MODEL_GUIDE.get(
        video_model,
        "Target: a short motion clip from the picture. Describe the motion and action clearly.",
    )


async def _resolve_character_target(tenant_id, video_id, ui: dict[str, Any]) -> dict[str, Any]:
    """DETERMINISTIC id-based resolution — same shape/contract as
    _resolve_prompt_target's image/motion branch, split out because a character
    lives in a different table/id-space than an asset. Never guesses a name from
    the message; `ui_context.selectedEntityId` (DirectorContext.tsx `selectedEntity`,
    set by tapping a Cast tile — RightRail.tsx) is the ONLY source of the id."""
    if (ui.get("selectedEntityType") or "") != "character" or not ui.get("selectedEntityId"):
        return {"error": "Which character do you mean? Select one in the Cast rail, or name them."}
    row = await fetch_one(
        "SELECT id, name, description FROM video_characters WHERE id=$1 AND video_id=$2 AND tenant_id=$3",
        ui["selectedEntityId"],
        video_id,
        tenant_id,
    )
    if not row:
        return {"error": "That character isn't there anymore — pick another one?"}
    return {
        "surface": "character",
        "entity_id": str(row["id"]),
        "label": f"the character {row['name']}",
        "current": (row.get("description") or "").strip(),
        "apply_cost": 0.0,
    }


async def _resolve_environment_target(tenant_id, video_id, ui: dict[str, Any]) -> dict[str, Any]:
    """Environment counterpart to _resolve_character_target — same contract,
    `video_environments` table, sourced from `ui_context.selectedEntityId` with
    `selectedEntityType == "environment"`."""
    if (ui.get("selectedEntityType") or "") != "environment" or not ui.get("selectedEntityId"):
        return {"error": "Which location do you mean? Select one in the Environments rail, or name it."}
    row = await fetch_one(
        "SELECT id, name, description FROM video_environments WHERE id=$1 AND video_id=$2 AND tenant_id=$3",
        ui["selectedEntityId"],
        video_id,
        tenant_id,
    )
    if not row:
        return {"error": "That location isn't there anymore — pick another one?"}
    return {
        "surface": "environment",
        "entity_id": str(row["id"]),
        "label": f"the location {row['name']}",
        "current": (row.get("description") or "").strip(),
        "apply_cost": 0.0,
    }


async def _resolve_prompt_target(
    tenant_id, video_id, surface, scene, index, ui_context, summary
) -> dict[str, Any]:
    """Point a prompt op at a concrete thing + read its current prompt. Falls back to
    the scene/image the creator is viewing; returns {"error": <ask>} when ambiguous.

    Resolution order for image/motion, most specific first — DETERMINISTIC, never a
    guess handed to the LLM: (1) a scene/index the classifier read straight out of
    the creator's own words ("redo scene 5 image 2") always wins, since they named a
    different target on purpose; (2) failing that, `ui_context.focusedAssetId` — the
    EXACT `assets.id` of whatever shot is tapped/focused on the Director canvas right
    now (DirectorContext.tsx `focusedShotId`) — resolves straight to that one row, no
    scene/index list-and-guess involved, so "make him older" with shot 3.2 focused
    can never land on shot 3.1 in the same multi-shot scene; (3) failing that, the
    older `ui_context.scene`/`.index` ambient hint (pre-Task-5.4a producers: the old
    pipeline dock, ImagesStagePanel — unchanged). Character/environment surfaces
    resolve the same way off `ui_context.selectedEntityId`/`.selectedEntityType` —
    see _resolve_character_target/_resolve_environment_target above."""
    ui = ui_context or {}
    if surface == "character":
        return await _resolve_character_target(tenant_id, video_id, ui)
    if surface == "environment":
        return await _resolve_environment_target(tenant_id, video_id, ui)
    if surface in ("image", "motion"):
        if scene is None and index is None and ui.get("focusedAssetId"):
            row = await fetch_one(
                "SELECT id, scene, image_index, image_prompt, video_prompt, image_url "
                "FROM assets WHERE id=$1 AND video_id=$2 AND tenant_id=$3",
                ui["focusedAssetId"],
                video_id,
                tenant_id,
            )
            if not row:
                return {"error": "That shot isn't there anymore — pick another one?"}
            if surface == "motion" and not row.get("image_url"):
                return {
                    "error": f"Scene {row.get('scene')} image {row.get('image_index')} hasn't been drawn yet — make the picture first."
                }
            cur = (row.get("image_prompt" if surface == "image" else "video_prompt") or "").strip()
            cost = _PICTURE_COST if surface == "image" else _CLIP_COST.get(summary["model"], 0.10)
            noun = "picture" if surface == "image" else "clip"
            return {
                "surface": surface,
                "asset_id": str(row["id"]),
                "scene": int(row["scene"]) if row.get("scene") is not None else None,
                "index": int(row["image_index"]) if row.get("image_index") is not None else None,
                "label": f"scene {row.get('scene')} {noun} {row.get('image_index')}",
                "current": cur,
                "apply_cost": cost,
            }
        sc = scene if scene is not None else ui.get("scene")
        if sc is None:
            return {
                "error": "Which scene's shot do you mean? e.g. “image 1 in scene 2”."
            }
        rows = await fetch_all(
            "SELECT id, image_index, image_prompt, video_prompt, image_url "
            "FROM assets WHERE video_id=$1 AND tenant_id=$2 AND scene=$3 ORDER BY image_index",
            video_id,
            tenant_id,
            int(sc),
        )
        if not rows:
            return {
                "error": f"Scene {sc} doesn't have pictures yet — want me to make them first?"
            }
        idx = index if index is not None else ui.get("index")
        if idx is None:
            if len(rows) == 1:
                row, idx = rows[0], 1
            else:
                return {
                    "error": f"Scene {sc} has {len(rows)} pictures — which one? (e.g. “image 1”)."
                }
        else:
            n = int(idx)
            if n < 1 or n > len(rows):
                return {
                    "error": f"Scene {sc} has {len(rows)} pictures — pick 1 to {len(rows)}."
                }
            row, idx = rows[n - 1], n
        if surface == "motion" and not row.get("image_url"):
            return {
                "error": f"Scene {sc} image {idx} hasn't been drawn yet — make the picture first."
            }
        cur = (
            row.get("image_prompt" if surface == "image" else "video_prompt") or ""
        ).strip()
        cost = (
            _PICTURE_COST
            if surface == "image"
            else _CLIP_COST.get(summary["model"], 0.10)
        )
        noun = "picture" if surface == "image" else "clip"
        return {
            "surface": surface,
            "asset_id": str(row["id"]),
            "scene": int(sc),
            "index": int(idx),
            "label": f"scene {sc} {noun} {idx}",
            "current": cur,
            "apply_cost": cost,
        }
    if surface == "thumbnail":
        v = await fetch_one(
            "SELECT thumbnail_prompt FROM videos WHERE id=$1 AND tenant_id=$2",
            video_id,
            tenant_id,
        )
        return {
            "surface": "thumbnail",
            "label": "the thumbnail",
            "current": ((v or {}).get("thumbnail_prompt") or "").strip(),
            "apply_cost": 0.10,
        }
    if surface == "script":
        sc = scene if scene is not None else ui.get("scene")
        if sc is None:
            return {
                "error": "Which scene's script do you mean? e.g. “the script for scene 2”."
            }
        r = await fetch_one(
            "SELECT scene_text FROM scripts WHERE video_id=$1 AND tenant_id=$2 AND scene=$3",
            video_id,
            tenant_id,
            int(sc),
        )
        if not r or not (r.get("scene_text") or "").strip():
            return {"error": f"Scene {sc} doesn't have written text yet."}
        return {
            "surface": "script",
            "scene": int(sc),
            "label": f"scene {sc}'s script",
            "current": r["scene_text"].strip(),
            "apply_cost": 0.0,
        }
    return {
        "error": "I can work on the picture, motion, thumbnail, or script prompt — which one?"
    }


async def _rewrite_prompt(
    client, model_for_call, surface, current, direction, video_model
) -> str:
    guide = _surface_guide(surface, video_model)
    p = (
        "You are refining a generation prompt. Rewrite it to honor the creator's direction and optimize it for "
        "the target. PRESERVE the original intent and any specific characters/objects — never invent new ones.\n\n"
        f"{guide}\n\nCURRENT PROMPT:\n{current or '(empty — write a strong one from the direction)'}\n\n"
        f"CREATOR'S DIRECTION: {direction or '(no specific direction — just make it noticeably stronger)'}\n\n"
        "Return ONLY the rewritten prompt text, nothing else."
    )
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
    p = (
        "Give the creator 3-5 short, concrete suggestions to improve this generation prompt for the target. "
        "Don't rewrite it — just the bullet suggestions.\n\n"
        f"{guide}\n\nCURRENT PROMPT:\n{current or '(empty)'}\n\nReturn a short friendly message with the bullets."
    )
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
    verb = {
        "image": "redraw",
        "motion": "re-animate",
        "thumbnail": "redo",
        "script": "save",
        "character": "save",
        "environment": "save",
    }[target["surface"]]
    # character/environment are a free text-only save (Task 5.4b) — same "no
    # regenerate" contract as script, not a redraw/re-animate.
    do = (
        "Save it"
        if target["surface"] in ("script", "character", "environment")
        else f"Apply & {verb} · {'no extra cost' if cost <= 0 else f'~${cost:.2f}'}"
    )
    return {
        "id": "prompt_apply",
        "label": f"Apply to {target['label']}?",
        "type": "single",
        "body": draft_text,
        "options": [{"value": "yes", "label": do}, {"value": "no", "label": "Cancel"}],
    }


def _make_prompt_regen(
    tenant_id,
    video_id: str,
    surface: str,
    *,
    asset_id: Optional[str] = None,
    start_msg: str = "Applying your prompt…",
):
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
                result = (
                    await PipelineExecutor(tenant_id).run_clip_generation(
                        video_id, asset_id=asset_id, force=True
                    )
                    or {}
                )
            elif surface == "thumbnail":
                # C16d (S7-3): applying an edited thumbnail prompt is always an
                # explicit "redo it" — bypass the skip-if-done guard, same as
                # the ACTIONS["thumbnail"] verb.
                result = (
                    await PipelineExecutor(tenant_id).run_thumbnail(
                        video_id, force=True
                    )
                    or {}
                )
            else:
                result = {"status": "completed"}
            _set_task_status(
                video_id,
                result.get("status", "completed"),
                result.get("error") or result.get("message"),
                tenant_id=tenant_id,
            )
        except Exception as e:  # noqa: BLE001
            _set_task_status(video_id, "failed", str(e), tenant_id=tenant_id)
        finally:
            await asyncio.sleep(20)
            _clear_task_status(video_id, tenant_id)

    return _run


async def _apply_prompt_draft(
    tenant_id, video_id, draft: dict[str, Any], background_tasks
) -> str:
    """Save the approved prompt to the right column, then regenerate that one shot."""
    surface, text, label = draft["surface"], draft["draft"], draft["label"]
    if surface == "image":
        await execute(
            "UPDATE assets SET image_prompt=$1, updated_at=now() WHERE id=$2 AND tenant_id=$3",
            text,
            draft["asset_id"],
            tenant_id,
        )
        background_tasks.add_task(
            _make_prompt_regen(
                tenant_id,
                video_id,
                "image",
                asset_id=draft["asset_id"],
                start_msg=f"Redrawing {label}…",
            )
        )
        return f"Saved and redrawing {label} now — I'll update you here."
    if surface == "motion":
        await execute(
            "UPDATE assets SET video_prompt=$1, updated_at=now() WHERE id=$2 AND tenant_id=$3",
            text,
            draft["asset_id"],
            tenant_id,
        )
        background_tasks.add_task(
            _make_prompt_regen(
                tenant_id,
                video_id,
                "motion",
                asset_id=draft["asset_id"],
                start_msg=f"Re-animating {label}…",
            )
        )
        return f"Saved and re-animating {label} now — I'll update you here."
    if surface == "thumbnail":
        await execute(
            "UPDATE videos SET thumbnail_prompt=$1, updated_at=now() WHERE id=$2 AND tenant_id=$3",
            text,
            video_id,
            tenant_id,
        )
        background_tasks.add_task(
            _make_prompt_regen(
                tenant_id, video_id, "thumbnail", start_msg="Redoing the thumbnail…"
            )
        )
        return "Saved and redoing the thumbnail now — I'll update you here."
    if surface == "character":
        # Free text-only save (Task 5.4b) — reuses the SAME route function the
        # edit_character MCP tool wraps (routes/mcp.py `_call_edit_character`),
        # so this goes through the one real write path, not a second one.
        # Deliberately does NOT queue redo_character_sheet (the paid portrait
        # redraw) — that stays an explicit separate ask, same distinction the
        # MCP tool docstrings draw ("edit_character... Free, no cost" vs
        # "redo_character_sheet... PAID").
        from routes.characters import CharacterUpdate, update_character

        await update_character(
            video_id, draft["entity_id"], CharacterUpdate(description=text), tenant_id=tenant_id
        )
        return (
            f"Done — I've updated {label}. If they already have a portrait, you may want to redo their "
            "character sheet so it matches (that one does cost a redraw)."
        )
    if surface == "environment":
        from routes.environments import EnvironmentUpdate, update_environment

        await update_environment(
            video_id, draft["entity_id"], EnvironmentUpdate(description=text), tenant_id=tenant_id
        )
        return (
            f"Done — I've updated {label}. If it already has a reference image, you may want to redo "
            "the environment so it matches (that one does cost a redraw)."
        )
    # script: just save the new scene text; downstream art is regenerated separately.
    await execute(
        "UPDATE scripts SET scene_text=$1, updated_at=now() WHERE video_id=$2 AND scene=$3 AND tenant_id=$4",
        text,
        video_id,
        draft["scene"],
        tenant_id,
    )
    return (
        f"Done — I've updated {label}. If you've already storyboarded this scene, you may want to "
        "redo its pictures so they match."
    )


async def _handle_prompt_op(
    client,
    model_for_call,
    tenant_id,
    video_id,
    summary,
    data,
    ui_context,
    state,
    _reply,
):
    """view / suggest / rewrite a generation prompt. Rewrite proposes a draft + a
    one-tap apply card; refinement happens via free text on the next turns."""
    surface = (data.get("surface") or "").strip()
    op = (data.get("op") or "rewrite").strip()
    scene = data.get("scene")
    scene = int(scene) if isinstance(scene, (int, float)) else None
    index = data.get("index")
    index = int(index) if isinstance(index, (int, float)) else None
    direction = (data.get("direction") or data.get("change") or "").strip()
    if surface not in _PROMPT_SURFACES:
        return await _reply(
            "I can rewrite the picture, motion, thumbnail, or script prompt — or update a character's "
            "or location's description — which one, and for which shot?"
        )
    target = await _resolve_prompt_target(
        tenant_id, video_id, surface, scene, index, ui_context, summary
    )
    if target.get("error"):
        return await _reply(target["error"])

    if op == "view":
        cur = target["current"] or "(no prompt saved for this one yet)"
        return await _reply(
            f"Here's the current prompt for {target['label']}:\n\n{cur}"
        )
    if op == "suggest":
        s = await _suggest_prompt(
            client, model_for_call, surface, target["current"], summary["model"]
        )
        return await _reply(s or "I couldn't read that one — try again?")

    # rewrite -> propose a draft, hold it for one-tap apply.
    new = await _rewrite_prompt(
        client, model_for_call, surface, target["current"], direction, summary["model"]
    )
    if not new:
        return await _reply(
            "I couldn't draft that — want to try again with a little more direction?"
        )
    state["prompt_draft"] = {
        "surface": surface,
        "asset_id": target.get("asset_id"),
        "entity_id": target.get("entity_id"),
        "scene": target.get("scene"),
        "index": target.get("index"),
        "label": target["label"],
        "draft": new,
        "apply_cost": target.get("apply_cost", 0.0),
    }
    return await _reply(
        f"Here's a stronger prompt for {target['label']} — tweak it below if you like, then apply "
        "(or just tell me how to adjust it in words).",
        cards=[_prompt_apply_card(target, new)],
    )


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
    "id": "intent",
    "label": "What brings you here?",
    "type": "single",
    "options": [
        {
            "value": "automate",
            "label": "Automate my channel",
            "hint": "Ideas, scripts, voiceovers, thumbnails, whole videos",
        },
        {
            "value": "stories",
            "label": "Tell stories",
            "hint": "Narrative videos, shorts, films",
        },
    ],
}
ONBOARDING_GOALS_CARD = {
    "id": "goals",
    "label": "What should I handle for you?",
    "type": "multi",
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
    "id": "upsell",
    "label": "",
    "type": "single",
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


def _add_competitors_card() -> dict[str, Any]:
    """C36 (checklist §3.3 item 2): the cold-start fix — a fresh conversation
    with zero competitor data used to fall straight to the generic dragon-
    video greeting with no way out. This one-tap card (same single-select
    shape as `_confirm_card`/`_secure_key_card`) is attached alongside that
    greeting instead, so the creator can fix the ROOT cause (no competitor
    data) in one turn rather than getting stuck with generic examples every
    time. Handled by `chat_turn`'s "awaiting_competitor_paste" branch, which
    reuses the SAME `analyze_competitors`/`_parse_urls` call the onboarding
    "competitors" step already uses — not a second implementation."""
    return {
        "id": "add_competitors",
        "label": "No competitor data yet",
        "type": "single",
        "options": [
            {"value": "add", "label": "Add 3 competitors now"},
            {"value": "skip", "label": "Not now — give me examples"},
        ],
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
        return None, (
            "That looks like an OpenAI key. I need your **Kie.ai** key, or an "
            "Anthropic key that starts with `sk-ant-`."
        )
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
        return await _ob_reply(
            conversation_id,
            tenant_id,
            transcript,
            state,
            ack
            + "If you have a channel, paste its URL so I can match its vibe (or say “skip”).",
        )
    state["onboarding_step"] = "goals"
    return await _ob_reply(
        conversation_id,
        tenant_id,
        transcript,
        state,
        ack + "Now — what should I handle for you?",
        cards=[ONBOARDING_GOALS_CARD],
    )


# --- account-connect steps (YouTube analytics + Google Drive) ---------------
# Two optional, skippable OAuth steps. The frontend renders a "Connect" button
# (it owns the per-tenant auth_url via getYouTube/DriveConnectUrl), sends the
# user same-tab to Google, and the existing callbacks return to "/?connected=…"
# so ChatHome resumes onboarding. The OAuth callback persists the tokens, so the
# chat step just records intent and advances — either choice moves on.
ONBOARDING_CONNECT_YT_CARD = {
    "id": "connect_yt",
    "label": "",
    "type": "single",
    "options": [
        {"value": "connected", "label": "I've connected it"},
        {"value": "skip", "label": "Skip for now"},
    ],
}
ONBOARDING_CONNECT_DRIVE_CARD = {
    "id": "connect_drive",
    "label": "",
    "type": "single",
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
        if (
            "youtube.com" in t
            or "youtu.be" in t
            or t.startswith("@")
            or t.startswith("http")
        ):
            out.append(t)
    return out


async def _ob_reply(
    conversation_id,
    tenant_id,
    transcript,
    state,
    text,
    *,
    cards=None,
    phase="onboarding",
    video_id=None,
):
    transcript.append(
        _assistant_turn({"assistant_text": text, "phase": phase, "cards": cards})
    )
    await _save_creator_brief(
        tenant_id, state
    )  # mirror durable facts as they're collected
    await _persist(
        conversation_id, tenant_id, transcript, state, phase, video_id=video_id
    )
    return ChatTurnResponse(
        conversation_id=conversation_id,
        assistant_text=text,
        cards=cards,
        phase=phase,
        video_id=video_id,
    )


_GOAL_LABELS = {
    "ideas": "video ideas",
    "scripts": "scripts",
    "voiceover": "voiceovers",
    "thumbnails": "thumbnails",
    "full_video": "whole videos",
}


async def _identity_pool_brief(tenant_id) -> str:
    """THE canonical channel-identity block (chat channel-identity rebuild,
    checklist P2) — injected FIRST into both chat system prompts (producer +
    in-video co-pilot), ahead of every other brief, so its hard precedence
    law (our locked identity leads; a modeled reference contributes topic
    only, never format/runtime/titling) is the first thing the model reads.
    Every other brief that touches a reference video (_reference_brief,
    producer_prompt's LENGTH/MODELING-A-REFERENCE guidance) is written to
    point back at this block rather than re-deriving its own anchor.

    Built fresh every turn — no cross-turn state caching (unlike
    _reference_brief's per-URL cache), so a just-locked format/cast/DNA
    change lands on the very next turn. Fail-soft: any error here still
    yields "" rather than breaking prompt assembly; render_identity_brief
    itself already renders a minimal, honest block for a pool with nothing
    learned yet, so there is no separate "empty tenant" special case.

    P5 fix: passes include_script_profiles=False — render_identity_brief
    never reads pool["script_profiles"], so building that section (a sys.path
    import + a load per registered profile) on every single chat turn was
    pure dead work. The MCP verb still asks for the full pool (default True)."""
    try:
        from channel_identity_context import build_identity_pool, render_identity_brief

        pool = await build_identity_pool(tenant_id, include_script_profiles=False)
        brief = render_identity_brief(pool)
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "chat: identity pool brief failed for tenant=%s: %s", tenant_id, e
        )
        return ""
    return f"\n{brief}\n" if brief else ""


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
        bits.append(
            "They want help with: "
            + ", ".join(_GOAL_LABELS.get(g, g) for g in goals)
            + "."
        )
    if state.get("channel"):
        bits.append(f"Their channel: {state['channel']}.")
    comps = state.get("competitors") or []
    if comps:
        bits.append(
            "Channels they model: " + ", ".join(str(c) for c in comps[:3]) + "."
        )
    if state.get("niche_angle"):
        bits.append(f"Their chosen niche/angle: {state['niche_angle']}.")
    if not bits:
        return ""
    tailor = ""
    if goals == ["thumbnails"]:
        tailor = " They mainly want THUMBNAILS — default to the thumbnail-only workflow and keep questions minimal."
    elif goals and "full_video" not in goals and "all" not in goals:
        tailor = f" Default the workflow to match what they asked for ({', '.join(goals)}), not a full video, unless they say otherwise."
    return (
        "WHO YOU'RE TALKING TO (from their setup — remember this): "
        + " ".join(bits)
        + tailor
    )


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
    return (
        f"\nLENGTH ANCHOR: the videos this creator models typically run ~{_format_runtime(med)}. "
        "Lean toward that as your recommended length unless the specific story clearly needs "
        "shorter or longer — and say so."
    )


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
                "OUR CHANNEL IDENTITY LEADS (see the identity block above): this reference contributes "
                "its TOPIC and subject lane ONLY — never its title structure, pacing, or runtime. "
                "Propose a concrete new TITLE that carries this reference's topic hook and actual "
                "subject/genre, but written in OUR channel's own title convention (from the identity "
                "block's TITLE PATTERN/VOICE lines when present). Do NOT snap back to an unrelated "
                "topic from the creator's past videos, and do NOT copy this reference's title formula "
                "wholesale. Recommend length from OUR channel identity's own LENGTH line, not from this "
                f"reference's runtime (~{runtime}) — that runtime is context only, never the anchor."
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
    r"why (does|do) (this|it|that) work|what makes (this|it|that) work)",
    re.I,
)


def _analyze_intent(text: str | None) -> bool:
    return bool(text and _ANALYZE_RE.search(text))


def _dna_brief(state: dict) -> str:
    """The distilled DNA of the video being modeled, for the producer. Set by
    _handle_analyze; cleared naturally when a new conversation starts."""
    dna = state.get("video_dna")
    if not dna:
        return ""
    return (
        "\n--- FULL DNA OF THE REFERENCE VIDEO (distilled from its ACTUAL content — ground "
        "any recreation in THIS: same hook shape, same structure, same pacing, our subject "
        "and identity) ---\n" + json.dumps(dna)[:2400] + "\n"
    )


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
            distill_from_url(DistillURLRequest(url=url), tenant_id=tenant_id),
            timeout=90,
        )
        res = res or {}
        dna_summary = res.get("summary")
        dna_meta = res.get("dna") if isinstance(res.get("dna"), dict) else None
        if not (dna_summary or dna_meta) and res.get("status") != "distilled":
            dna_err = "the deep pass couldn't read its content"
    except HTTPException as e:
        dna_err = (
            e.detail if isinstance(e.detail, str) else "couldn't pull the video content"
        )
    except asyncio.TimeoutError:
        dna_err = "the deep analysis timed out"
    except Exception as e:  # noqa: BLE001
        logger.warning("chat: analyze distill failed: %s", e)
        dna_err = "couldn't pull the video content"

    if not meta_lines and not dna_summary and not dna_meta:
        text = (
            "I couldn't read that video at all — it may be private, removed, or the link is off. "
            "Try another link?"
        )
        transcript.append(_assistant_turn({"assistant_text": text, "phase": "asking"}))
        await _persist(conversation_id, tenant_id, transcript, state, "asking")
        return ChatTurnResponse(
            conversation_id=conversation_id, assistant_text=text, phase="asking"
        )

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
    if dna_summary or dna_meta:
        # Trim before persisting: conversation state rides along on every turn.
        slim = {}
        for k, v in (dna_meta or {}).items():
            if v in (None, "", [], {}):
                continue
            slim[str(k)[:60]] = (
                ", ".join(str(x) for x in v) if isinstance(v, list) else str(v)
            )[:400]
            if len(slim) >= 12:
                break
        state["video_dna"] = {"summary": str(dna_summary or "")[:1200], "dna": slim}
    elif dna_err:
        parts += [
            "",
            f"(I could only read the public data — {dna_err}. The read above is from "
            "metadata; I can still model the format.)",
        ]

    state["pending_reference_url"] = url
    parts += [
        "",
        "Want it as YOURS? Say “make it” and I'll recreate this structure on your "
        "channel — or tell me what to change first.",
    ]
    text = "\n".join(parts)
    transcript.append(_assistant_turn({"assistant_text": text, "phase": "asking"}))
    await _persist(conversation_id, tenant_id, transcript, state, "asking")
    return ChatTurnResponse(
        conversation_id=conversation_id, assistant_text=text, phase="asking"
    )


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
        comps = (
            await fetch_all(
                "SELECT channel_name, channel_url FROM competitor_channels "
                "WHERE tenant_id = $1 AND active = true ORDER BY channel_name",
                tenant_id,
            )
            or []
        )
        if comps:
            names = ", ".join(
                (c.get("channel_name") or c.get("channel_url") or "?")
                for c in comps[:12]
            )
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
    return (
        "\n--- THIS CREATOR'S CURRENT SETUP (you can change any of this when they ask) ---\n"
        + "\n".join(lines)
        + "\n"
    )


_STYLE_PRESETS_BRIEF_FALLBACK = [
    '- "neutral_v1": Neutral — a clean, versatile default look.'
]


async def _style_presets_brief(tenant_id) -> str:
    """The 5 structural "Look Engine" presets (style_presets table, checklist
    §C20/§C21b) — read live so the optional LOOK ENGINE card the producer may
    offer always carries REAL, currently-active ids (a hardcoded list would
    drift from the table and 400 downstream at routes.videos.
    _resolve_style_preset_id, same as reference_url's "use these EXACT
    values" precedent). Fail-soft: any DB error or an empty catalog falls
    back to a frozen minimal default — NOT a maintained parallel catalog,
    just enough for the card to keep degrading gracefully instead of
    crashing the turn. Always returns a non-empty block (unlike most _brief
    helpers here) since the LOOK ENGINE card is meaningless without it."""
    try:
        rows = await fetch_all(
            "SELECT id, display_name, description FROM style_presets "
            "WHERE active = true ORDER BY sort, id"
        )
        if not rows:
            raise ValueError("style_presets table returned no active rows")
        lines = [
            f'- "{r["id"]}": {r["display_name"]}'
            + (f" — {r['description']}" if r.get("description") else "")
            for r in rows
        ]
    except Exception as e:  # noqa: BLE001
        logger.warning("chat: style_presets brief failed, using fallback: %s", e)
        lines = list(_STYLE_PRESETS_BRIEF_FALLBACK)
    return (
        "\n--- LOOK ENGINE PRESETS (structural visual engines — an ADVANCED, "
        "optional card; use these EXACT ids as option values if you offer it) ---\n"
        + "\n".join(lines)
        + "\n"
    )


async def _visual_styles_brief(tenant_id) -> str:
    """This tenant's own saved-style library (checklist §C22 — the `visual_styles`
    CRUD table, the SAME rows the profile page's "Visual Styles" manager reads/
    writes). Distinct from both the 6 LOOK descriptions and the 5 LOOK ENGINE
    presets above — this is a project-scoped, user-EXTENSIBLE list (each row
    created by draft_style or the profile page's AI generator). Lets the
    producer resolve "use my <name> style" against a REAL saved look instead
    of inventing a new description, for both a one-off plan pick
    (spec.image_style_override) and a channel-wide switch (the use_style op).
    Fail-soft: any DB error or an empty library returns "" — unlike
    `_style_presets_brief`, an empty section here is fine (there's nothing to
    offer when the creator hasn't saved any styles yet)."""
    try:
        from routes.visual_styles import _get_project_id
        from identity import _style_profile_to_look

        project_id = await _get_project_id(tenant_id)
        rows = await fetch_all(
            "SELECT name, style_profile, is_active FROM visual_styles "
            "WHERE project_id = $1 ORDER BY is_active DESC, created_at DESC",
            project_id,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("chat: visual_styles brief failed: %s", e)
        return ""
    if not rows:
        return ""
    lines = []
    for r in rows:
        look = _style_profile_to_look(r.get("style_profile")) or ""
        tag = " (their current default)" if r.get("is_active") else ""
        lines.append(
            f'- "{r["name"]}"{tag}: {look}' if look else f'- "{r["name"]}"{tag}'
        )
    return (
        "\n--- YOUR SAVED STYLES (this creator's own style library — use these "
        "EXACT names when they ask to use or switch to one) ---\n"
        + "\n".join(lines)
        + "\n"
    )


async def _delete_competitor(tenant_id, channel_id) -> None:
    """Remove a competitor channel and cascade-delete its scraped videos, matching
    the niche.remove_channel route's cascade so analytics don't orphan."""
    ch = await fetch_one(
        "SELECT channel_url, channel_name FROM competitor_channels WHERE id = $1 AND tenant_id = $2",
        channel_id,
        tenant_id,
    )
    if ch:
        url = ch.get("channel_url") or ""
        name = ch.get("channel_name") or ""
        key_col, key_val = (
            ("channel_url", url)
            if url
            else (("channel", name) if name else (None, None))
        )
        if key_col:
            await execute(
                f"UPDATE discovery_ideas SET competitor_video_id = NULL WHERE tenant_id = $1 "
                f"AND competitor_video_id IN (SELECT id FROM competitor_videos "
                f"WHERE tenant_id = $1 AND {key_col} = $2)",
                tenant_id,
                key_val,
            )
            await execute(
                f"DELETE FROM competitor_videos WHERE tenant_id = $1 AND {key_col} = $2",
                tenant_id,
                key_val,
            )
    await execute(
        "DELETE FROM competitor_channels WHERE id = $1 AND tenant_id = $2",
        channel_id,
        tenant_id,
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
                    results.append(
                        f'To add a competitor I need its YouTube channel link, and "{val}" isn\'t one.'
                    )
                    continue
                if background_tasks is None:
                    results.append(
                        f"Add {url} from the Competitors page, I can't pull it in from here right now."
                    )
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
                background_tasks.add_task(
                    _run_competitor_analysis, job_id, tenant_id, [url]
                )
                results.append(
                    f"Added {url} to your competitors, pulling its top videos now."
                )
            elif kind == "remove_competitor":
                row = await fetch_one(
                    "SELECT id, channel_name FROM competitor_channels "
                    "WHERE tenant_id = $1 AND (lower(channel_name) = lower($2) OR channel_url = $2) LIMIT 1",
                    tenant_id,
                    val,
                )
                if not row:
                    results.append(
                        f'Couldn\'t find a competitor matching "{val}" to remove.'
                    )
                    continue
                await _delete_competitor(tenant_id, row["id"])
                results.append(
                    f"Removed {row.get('channel_name') or val} from your competitors."
                )
            elif kind == "queue_titles":
                # value: {"asset_id": "<chat_assets id>", "column": "<optional>"}
                # or {"titles": ["...", ...]} for titles given in conversation.
                raw = op.get("value") if isinstance(op.get("value"), dict) else {}
                from routes.queue import add_queue_items, queue_titles_from_asset

                titles = [
                    str(t).strip() for t in (raw.get("titles") or []) if str(t).strip()
                ]
                asset_id = str(raw.get("asset_id") or "").strip()
                if asset_id and not titles:
                    n, err = await queue_titles_from_asset(
                        tenant_id, asset_id, raw.get("column")
                    )
                    if err:
                        results.append(err)
                        continue
                elif titles:
                    n = await add_queue_items(tenant_id, [{"title": t} for t in titles])
                else:
                    results.append(
                        "I need the uploaded file (or the titles themselves) to queue anything."
                    )
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
                    results.append(
                        "I need the uploaded script file to do that — drop it in again?"
                    )
                    continue
                arow = await fetch_one(
                    "SELECT id, filename, parsed_text FROM chat_assets WHERE id = $1 AND tenant_id = $2",
                    asset_id,
                    tenant_id,
                )
                text_body = ((arow or {}).get("parsed_text") or "").strip()
                if not text_body:
                    results.append(
                        "I couldn't read any text out of that file, so I can't use it as a "
                        "script — paste the script here instead?"
                    )
                    continue
                if not title:
                    title = (
                        await _derive_script_title(tenant_id, text_body)
                        or (
                            (arow.get("filename") or "Untitled script").rsplit(".", 1)[
                                0
                            ]
                        )
                    )
                from models import CreateVideoRequest as _CVR
                from routes.videos import create_video as _create_video

                words = len(text_body.split())
                req = _CVR(
                    title=title[:200], video_length_minutes=max(1, round(words / 150))
                )
                try:
                    summary = await _create_video(
                        body=req, background_tasks=background_tasks, tenant_id=tenant_id
                    )
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
                    asset_id,
                    tenant_id,
                )
                results.append(
                    f'Created "{title}" using your script word for word — {sres["scenes"]} '
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
                        asset_id,
                        tenant_id,
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
                        asset_id,
                        tenant_id,
                    )
                results.append(
                    f'Learned your script format ("{tpl["name"]}") — every script I write '
                    "from now on follows it. Drop in a new example any time to replace it."
                )
            elif kind == "lock_cast":
                # value: {"asset_ids": ["<chat_assets image ids>"]}
                raw = op.get("value") if isinstance(op.get("value"), dict) else {}
                ids = [
                    str(a).strip()
                    for a in (raw.get("asset_ids") or [])
                    if str(a).strip()
                ]
                if not ids:
                    results.append(
                        "I need the character-sheet images to lock in — drop them into the chat."
                    )
                    continue
                arows = await fetch_all(
                    "SELECT id, filename, storage_url FROM chat_assets "
                    "WHERE tenant_id = $1 AND id = ANY($2::uuid[]) AND kind = 'image' "
                    "AND storage_url IS NOT NULL ORDER BY created_at",
                    tenant_id,
                    ids,
                )
                if not arows:
                    results.append(
                        "I couldn't find those images — drop the character sheets in again?"
                    )
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
                    tenant_id,
                    [str(r["id"]) for r in arows],
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
                from channel_format import (
                    FORMAT_FIELDS,
                    set_channel_format,
                    style_preset_for_format,
                )

                fields = {k: raw.get(k) for k in FORMAT_FIELDS if raw.get(k)}
                if not fields:
                    results.append(
                        'Tell me the format in a sentence and I\'ll lock it in — e.g. "animated 2D dialogue scenes, no one on camera".'
                    )
                    continue
                fmt = await set_channel_format(tenant_id, fields)
                preset = style_preset_for_format(fmt)
                bits = "; ".join(f"{k}: {v}" for k, v in fmt.items() if v)
                extra = f" New videos default to the {preset} look." if preset else ""
                results.append(
                    f"Locked your channel format ({bits}).{extra} Every build shapes itself to it."
                )
            elif kind == "remember":
                # value: the standing instruction, verbatim. Home chat has no
                # single "current video" in scope, so every remember here is
                # channel-wide (video scoping only happens in the in-video
                # co-pilot — see _handle_copilot's kind=="remember" branch).
                if not val:
                    results.append("What would you like me to remember?")
                    continue
                await _save_preference(tenant_id, val, scope=_PREF_SCOPE_CHANNEL)
                results.append(
                    f'Got it — I\'ll remember: {val}. Say "forget that" any time to undo it.'
                )
            elif kind == "forget":
                ok, matched = await _deactivate_preference(
                    tenant_id, val, video_id=None
                )
                if ok:
                    results.append(f"Forgot it — I'll no longer remember: {matched}.")
                else:
                    results.append(
                        "I couldn't find a matching preference to forget — which one did you mean?"
                    )
            elif kind == "draft_style":
                # value: {"name": "<short name>", "look": "<one-sentence description>"}.
                # NEVER writes a row — only stashes the draft for the creator's own
                # confirm tap (checklist §C22). See _handle_style_draft_confirm for
                # the ONLY place a visual_styles row actually gets created from chat.
                raw = op.get("value") if isinstance(op.get("value"), dict) else {}
                name = str(raw.get("name") or "").strip()[:80] or "Custom style"
                look = str(raw.get("look") or "").strip()
                if not look:
                    results.append(
                        "Describe the look a little more and I'll draft it — the medium, colors, "
                        "lighting, or mood you're picturing."
                    )
                    continue
                state["pending_style_draft"] = {"name": name, "look": look}
                results.append(f"Here's the style I've drafted — \"{name}\": {look}")
            elif kind == "draft_quality_rules":
                # value: {"asset_id": "<chat_assets id>"} | {"text": "..."}.
                # NEVER writes a row — parses candidate rules and stashes the
                # draft for the creator's own confirm tap (checklist §C46b,
                # same "no rows until confirmed" pattern draft_style uses
                # above). See _handle_quality_rules_draft_confirm for the
                # ONLY place quality_rules rows actually get created from chat.
                raw = op.get("value") if isinstance(op.get("value"), dict) else {}
                text_body = str(raw.get("text") or "").strip()
                asset_id = str(raw.get("asset_id") or "").strip() or None
                if not text_body and asset_id:
                    arow = await fetch_one(
                        "SELECT parsed_text FROM chat_assets WHERE id = $1 AND tenant_id = $2",
                        asset_id,
                        tenant_id,
                    )
                    text_body = ((arow or {}).get("parsed_text") or "").strip()
                if not text_body:
                    results.append(
                        "I couldn't read any quality-rules text — paste them here, or "
                        "drop in the document again?"
                    )
                    continue
                import quality_rules as _quality_rules

                parse_client = None
                try:
                    parse_client = await _resolve_producer_client(tenant_id)
                except Exception:
                    parse_client = None
                rows = await _quality_rules.parse_rules_document(
                    text_body, client=parse_client
                )
                if not rows:
                    results.append(
                        "I couldn't find any testable rules in that — a numbered/bulleted list of "
                        '"always/never" style rules works best, or the table format from a doc '
                        "like dvsu-quality-law.md."
                    )
                    continue
                state["pending_quality_rules_draft"] = {
                    "rows": rows,
                    "asset_id": asset_id,
                }
                hard = sum(1 for r in rows if r.get("severity") == "hard_gate")
                warn = sum(1 for r in rows if r.get("severity") == "warn")
                guidance = sum(1 for r in rows if r.get("severity") == "guidance")
                results.append(
                    f"Found {len(rows)} rule{'s' if len(rows) != 1 else ''} "
                    f"({hard} hard-gate, {warn} warn, {guidance} guidance) — "
                    "tap to save them to your channel's quality rules."
                )
            elif kind == "clear_reference":
                # No value needed — the creator wants OFF the reference video
                # entirely (P3, the length-backstop/reference-steering fix).
                # Clears BOTH state keys _reference_brief/_dna_brief read so
                # next turn's system prompt renders neither block, and drops
                # the per-URL _reference_brief cache so a stale cached string
                # can't leak back in if the same URL is set again later.
                ref_url = state.get("pending_reference_url")
                had_ref = bool(ref_url or state.get("video_dna"))
                state.pop("pending_reference_url", None)
                state.pop("video_dna", None)
                state.pop("_ref_brief_for", None)
                state.pop("_ref_brief", None)
                if had_ref:
                    # Durable steering lesson — reuses the SAME director_preferences
                    # channel-wide store the "remember" op already writes to (no new
                    # table/infra), so this steering survives into future
                    # conversations too, not just the rest of this one.
                    lesson = (
                        (
                            f"Stopped modeling {ref_url} — "
                            if ref_url
                            else "Stopped modeling that reference video — "
                        )
                        + "build from OUR channel's own identity, not a reference video, unless I ask to model one again."
                    )
                    await _save_preference(tenant_id, lesson, scope=_PREF_SCOPE_CHANNEL)
                    results.append(
                        "Dropped that reference — I'll build from our own channel identity from here."
                    )
                else:
                    results.append(
                        "There wasn't a reference video active, but I'll keep it that way."
                    )
            elif kind == "use_style":
                # value: the saved style's name (or a close match to it). Switches
                # the tenant's ACTIVE visual_styles row — same activate semantics
                # the profile page's CRUD already uses (identity.py's
                # channel_visual_style feeds every non-cloned video from then on).
                if not val:
                    results.append("Which saved style would you like to use?")
                    continue
                from routes.visual_styles import _get_project_id, activate_visual_style

                project_id = await _get_project_id(tenant_id)
                row = await fetch_one(
                    "SELECT id, name FROM visual_styles WHERE project_id = $1 "
                    "AND lower(name) = lower($2) LIMIT 1",
                    project_id,
                    val,
                )
                if not row:
                    row = await fetch_one(
                        "SELECT id, name FROM visual_styles WHERE project_id = $1 "
                        "AND name ILIKE $2 LIMIT 1",
                        project_id,
                        f"%{val}%",
                    )
                if not row:
                    results.append(
                        f'I couldn\'t find a saved style called "{val}" — check Profile → '
                        "Visual Styles for the exact name, or ask me to draft one first."
                    )
                    continue
                await activate_visual_style(str(row["id"]), tenant_id=tenant_id)
                results.append(
                    f'Switched your active look to "{row["name"]}" — every new video (and any '
                    "video that doesn't set its own custom look) uses it from here on."
                )
            elif kind in _PROFILE_FIELD_COLS:
                if not val:
                    continue
                col = _PROFILE_FIELD_COLS[kind]
                await execute(
                    f"INSERT INTO channel_profiles (tenant_id, {col}) VALUES ($1, $2) "
                    f"ON CONFLICT (tenant_id) DO UPDATE SET {col} = $2, updated_at = now()",
                    tenant_id,
                    val,
                )
                if kind == "set_niche":
                    state["niche_angle"] = val
                elif kind == "set_channel_name":
                    state["channel"] = val
                results.append(
                    f'Updated your {_PROFILE_FIELD_LABELS[kind]} to "{val}".'
                )
        except Exception as e:  # noqa: BLE001
            logger.warning("chat: profile op %s failed: %s", kind, e)
            results.append(
                "I hit a snag saving one of those changes, mind trying again?"
            )
    return results


async def _derive_script_title(tenant_id, text: str) -> str:
    """One cheap model call: name the video from the creator's script opening.
    Empty string on any failure (caller falls back to the filename)."""
    try:
        from kie_unified import get_text_client_for_tenant

        client = await get_text_client_for_tenant(tenant_id)
        model = _claude_model_for_direct_client(client)
        kwargs = {"model": model} if model else {}
        raw = await client.generate(
            prompt=(
                "Here is the opening of a video script:\n\n"
                + text[:2000]
                + "\n\nWrite ONE YouTube-ready title for this video. Reply with the title only, no quotes."
            ),
            max_tokens=60,
            temperature=0.7,
            **kwargs,
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


def _style_draft_card(draft: dict) -> dict[str, Any]:
    """The style-draft preview/confirm card (checklist §C22): the draft's name
    as the card label, the look sentence as its body (reuses the SAME `body`
    field prompt_apply already carries a draft in — no new ChatCard field),
    yes/no options read back exactly like confirm_action's."""
    return {
        "id": "style_draft",
        "label": draft.get("name") or "New style",
        "type": "single",
        "body": draft.get("look") or "",
        "options": [
            {"value": "yes", "label": "Save this style"},
            {"value": "no", "label": "Not quite — let's tweak it"},
        ],
    }


def _maybe_attach_style_draft_card(data: dict, state: dict) -> None:
    """After a turn where the producer drafted a style (a "draft_style" profile_op,
    checklist §C22), attach the preview card the creator taps to actually save it.
    This is the deterministic half of the confirm gate: a card only ever appears
    when THIS turn's ops genuinely included draft_style, so the LLM's own words
    can never manufacture a save-ready card without the backend having stashed a
    real draft in `state["pending_style_draft"]` first."""
    ops = data.get("profile_ops") if isinstance(data.get("profile_ops"), list) else []
    for alt_key in ("queue_ops", "file_ops", "asset_ops"):
        alt = data.get(alt_key)
        if isinstance(alt, list):
            ops = ops + alt
    if not any(isinstance(o, dict) and o.get("op") == "draft_style" for o in ops):
        return
    draft = state.get("pending_style_draft")
    if not draft:
        return
    cards = data.get("cards")
    if not isinstance(cards, list):
        cards = []
    cards.append(_style_draft_card(draft))
    data["cards"] = cards


async def _handle_style_draft_confirm(
    selections, conversation_id, tenant_id, transcript, state
) -> ChatTurnResponse:
    """Turn 2 of the conversational style-creation door (checklist §C22): the
    creator's tap on the style_draft preview card. Deterministic and NOT routed
    back through the producer LLM — a visual_styles row can ONLY be created here,
    and ONLY on an explicit "yes", so "confirm-before-save" is a backend
    guarantee, not a hope that the model behaves.

    Saves through the EXACT SAME create path the profile-page CRUD uses
    (routes.visual_styles.create_visual_style) — one implementation, matching
    the "reuse its route handler" requirement; this never forks the write."""
    draft = state.pop("pending_style_draft", None)

    async def _reply(text: str) -> ChatTurnResponse:
        transcript.append(_assistant_turn({"assistant_text": text, "phase": "asking"}))
        await _persist(conversation_id, tenant_id, transcript, state, "asking")
        return ChatTurnResponse(
            conversation_id=conversation_id, assistant_text=text, phase="asking"
        )

    if not draft:
        return await _reply(
            "I don't have a style draft waiting — describe the look you want and I'll draft one."
        )
    if selections.get("style_draft") != "yes":
        return await _reply(
            "No problem — didn't save that one. Describe the look again (or what you'd change) and I'll draft another."
        )

    from routes.visual_styles import create_visual_style, CreateStyleRequest

    try:
        style = await create_visual_style(
            CreateStyleRequest(
                name=draft["name"], style_profile={"prompt_prefix": draft["look"]}
            ),
            tenant_id=tenant_id,
        )
    except Exception as e:  # noqa: BLE001 — HTTPException or anything else, never crash the turn
        logger.warning("chat: style_draft confirm failed to save: %s", e)
        return await _reply("I hit a snag saving that style — mind trying again?")

    return await _reply(
        f'Saved — "{style.name}" is in your styles now. Find it on the Profile page under Visual '
        f'Styles, or just say "use {style.name}" any time to build with it or make it your default look.'
    )


def _quality_rules_draft_card(draft: dict) -> dict[str, Any]:
    """The quality-rules draft preview/confirm card (checklist §C46b) — same
    yes/no confirm shape as _style_draft_card, never a route that writes
    without this explicit tap."""
    rows = draft.get("rows") or []
    hard = sum(1 for r in rows if r.get("severity") == "hard_gate")
    warn = sum(1 for r in rows if r.get("severity") == "warn")
    guidance = sum(1 for r in rows if r.get("severity") == "guidance")
    preview = "; ".join(f"{r.get('rule_id')}: {r.get('law')}" for r in rows[:3])
    if len(rows) > 3:
        preview += f"; +{len(rows) - 3} more"
    return {
        "id": "quality_rules_draft",
        "label": f"{len(rows)} quality rule{'s' if len(rows) != 1 else ''} found",
        "type": "single",
        "body": f"{hard} hard-gate, {warn} warn, {guidance} guidance. {preview}",
        "options": [
            {"value": "yes", "label": "Save these rules"},
            {"value": "no", "label": "Not quite — let's tweak it"},
        ],
    }


def _maybe_attach_quality_rules_draft_card(data: dict, state: dict) -> None:
    """After a turn whose ops included draft_quality_rules, attach the
    preview card the creator taps to actually save the parsed rules —
    deterministic mirror of _maybe_attach_style_draft_card: a card only ever
    appears when THIS turn's ops genuinely included the op AND a real draft
    was stashed, never manufactured from the LLM's own words alone."""
    ops = data.get("profile_ops") if isinstance(data.get("profile_ops"), list) else []
    for alt_key in ("queue_ops", "file_ops", "asset_ops"):
        alt = data.get(alt_key)
        if isinstance(alt, list):
            ops = ops + alt
    if not any(
        isinstance(o, dict) and o.get("op") == "draft_quality_rules" for o in ops
    ):
        return
    draft = state.get("pending_quality_rules_draft")
    if not draft or not draft.get("rows"):
        return
    cards = data.get("cards")
    if not isinstance(cards, list):
        cards = []
    cards.append(_quality_rules_draft_card(draft))
    data["cards"] = cards


async def _handle_quality_rules_draft_confirm(
    selections, conversation_id, tenant_id, transcript, state
) -> ChatTurnResponse:
    """Turn 2 of the quality-rules ingestion door (checklist §C46b): the
    creator's tap on the quality_rules_draft preview card. Deterministic,
    NOT routed back through the producer LLM — rows can ONLY be created
    here (or via the CRUD route, routes/quality_rules.py), and ONLY on an
    explicit "yes"."""
    draft = state.pop("pending_quality_rules_draft", None)

    async def _reply(text: str) -> ChatTurnResponse:
        transcript.append(_assistant_turn({"assistant_text": text, "phase": "asking"}))
        await _persist(conversation_id, tenant_id, transcript, state, "asking")
        return ChatTurnResponse(
            conversation_id=conversation_id, assistant_text=text, phase="asking"
        )

    if not draft or not draft.get("rows"):
        return await _reply(
            "I don't have a quality-rules draft waiting — paste or upload the rules again and I'll parse them."
        )
    if selections.get("quality_rules_draft") != "yes":
        return await _reply(
            "No problem — didn't save those. Paste the rules again (or say what to change) and I'll re-parse them."
        )

    import quality_rules as _quality_rules

    try:
        saved = await _quality_rules.bulk_create_rules(
            tenant_id, draft["rows"], source="doc_upload"
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("chat: quality_rules_draft confirm failed to save: %s", e)
        return await _reply("I hit a snag saving those rules — mind trying again?")

    asset_id = draft.get("asset_id")
    if asset_id:
        try:
            await execute(
                "UPDATE chat_assets SET status = 'filed', filed_as = 'quality_rules' "
                "WHERE id = $1 AND tenant_id = $2",
                asset_id,
                tenant_id,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("chat: failed to mark quality-rules asset filed: %s", e)

    return await _reply(
        f"Saved — {len(saved)} quality rule{'s' if len(saved) != 1 else ''} are locked into your "
        "channel now. Every script I grade from here on checks against them. Drop in an updated "
        "doc any time to edit or add more."
    )


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
            tenant_id,
            json.dumps(brief),
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


# --- Director memory: durable preference store (C15c) -----------------------
#
# A correction said once ("the kitten is gray", "never use premium models on
# Poco") becomes a STANDING preference remembered across FUTURE conversations
# and videos, instead of forcing the creator to re-say it every time. Explicit
# instructions ONLY — written when the producer/copilot detects a standing
# instruction ("always...", "never...", "remember that...", "from now on...")
# and emits a remember/forget op; no auto-learning beyond that. See
# migrations/091_director_preferences.sql. Mirrors the _save_creator_brief /
# _hydrate_creator_brief pattern above: fail-soft everywhere, never breaks a
# chat turn on a DB error.

_PREF_SCOPE_CHANNEL = "channel"
_PREF_CAP = 20  # most-recent preferences hydrated into the prompt
_PREF_BLOCK_MAX_CHARS = 3000  # hard cap so the prompt can't bloat unboundedly
_PREF_GENERIC_REFS = {
    "",
    "that",
    "it",
    "last",
    "this",
    "the last one",
    "the last thing",
    "that one",
}


async def _save_preference(
    tenant_id, text: str, scope: str = _PREF_SCOPE_CHANNEL
) -> None:
    """Persist a standing preference VERBATIM (never paraphrased/summarized —
    the creator's exact words are the instruction). Fail-soft."""
    text = (text or "").strip()
    if not text:
        return
    try:
        await execute(
            "INSERT INTO director_preferences (tenant_id, scope, text, source) "
            "VALUES ($1, $2, $3, 'user')",
            tenant_id,
            (scope or _PREF_SCOPE_CHANNEL),
            text,
        )
    except Exception as e:  # noqa: BLE001 — memory is best-effort, never block a turn
        logger.warning("chat: save preference failed: %s", e)


async def _list_preferences(tenant_id, video_id=None) -> list[dict]:
    """Active preferences for this tenant: channel-wide always, plus this
    video's own when video_id is given (never another tenant's, never
    another video's). Newest first, capped at _PREF_CAP. Fail-soft -> []."""
    scopes = [_PREF_SCOPE_CHANNEL]
    if video_id:
        scopes.append(str(video_id))
    try:
        rows = await fetch_all(
            "SELECT id, scope, text, created_at FROM director_preferences "
            "WHERE tenant_id = $1 AND active = true AND scope = ANY($2::text[]) "
            "ORDER BY created_at DESC LIMIT $3",
            tenant_id,
            scopes,
            _PREF_CAP,
        )
        return rows or []
    except Exception as e:  # noqa: BLE001
        logger.warning("chat: list preferences failed: %s", e)
        return []


async def _preferences_brief(tenant_id, video_id=None) -> str:
    """The additive system-prompt block BOTH chats hydrate every turn (the
    home producer gets the channel-wide list; the in-video co-pilot gets
    channel-wide + this video's own). Capped + length-limited so it can't
    bloat the prompt unboundedly. Fail-soft -> '' (never breaks a chat turn)."""
    rows = await _list_preferences(tenant_id, video_id)
    if not rows:
        return ""
    lines = []
    for i, r in enumerate(rows, 1):
        tag = (
            " (this video only)" if video_id and r.get("scope") == str(video_id) else ""
        )
        lines.append(f"{i}. {r['text']}{tag}")
    block = "\n".join(lines)
    if len(block) > _PREF_BLOCK_MAX_CHARS:
        block = block[:_PREF_BLOCK_MAX_CHARS].rsplit("\n", 1)[0]
    return (
        "\n\nSTANDING PREFERENCES (obey unless the creator overrides this turn; "
        "these came from explicit corrections/instructions, not a guess):\n" + block
    )


async def _deactivate_preference(
    tenant_id, ref: str, video_id=None
) -> tuple[bool, str]:
    """'forget that' / 'forget #N' / 'forget <text>' -> deactivate ONE matching
    active preference (soft-delete: active=false, never a hard DELETE). Scoped
    to the same channel+video group hydration uses. Matching, in order:
      1. "#N" / a bare number -> position N in the same newest-first order
         hydration numbers them in (matches what the creator was just shown).
      2. exact case-insensitive text match.
      3. case-insensitive substring match (either direction).
      4. empty or a generic reference ("that"/"it"/"last"/...) -> the single
         most-recently-created active preference.
    Returns (True, the deactivated text) or (False, "") if nothing matched."""
    rows = await _list_preferences(tenant_id, video_id)
    if not rows:
        return False, ""
    ref_norm = (ref or "").strip().lower()
    ref_num = ref_norm.lstrip("#").strip()
    match = None
    if ref_num.isdigit():
        idx = int(ref_num) - 1
        if 0 <= idx < len(rows):
            match = rows[idx]
    if match is None and ref_norm and ref_norm not in _PREF_GENERIC_REFS:
        for r in rows:
            if r["text"].strip().lower() == ref_norm:
                match = r
                break
        if match is None:
            for r in rows:
                low = r["text"].strip().lower()
                if ref_norm in low or low in ref_norm:
                    match = r
                    break
    if match is None and (not ref_norm or ref_norm in _PREF_GENERIC_REFS):
        match = rows[0]  # newest first
    if match is None:
        return False, ""
    try:
        await execute(
            "UPDATE director_preferences SET active = false, updated_at = now() "
            "WHERE id = $1 AND tenant_id = $2",
            match["id"],
            tenant_id,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("chat: forget preference failed: %s", e)
        return False, ""
    return True, match["text"]


async def _handle_remember_op(tenant_id, video_id, data, _reply):
    """The in-video co-pilot's kind=="remember" branch: save the creator's
    standing instruction verbatim, scoped channel-wide unless they clearly
    meant just this video."""
    text = (data.get("change") or "").strip()
    if not text:
        return await _reply("What would you like me to remember?")
    scope_choice = (data.get("scope") or "channel").strip().lower()
    scope = str(video_id) if scope_choice == "video" else _PREF_SCOPE_CHANNEL
    await _save_preference(tenant_id, text, scope=scope)
    where = "for this video" if scope != _PREF_SCOPE_CHANNEL else "channel-wide"
    return await _reply(
        f'Got it — I\'ll remember ({where}): {text}. Say "forget that" any time to undo it.'
    )


async def _handle_forget_op(tenant_id, video_id, data, _reply):
    """The in-video co-pilot's kind=="forget" branch: deactivate one matching
    preference (channel-wide or this video's own), soft-delete only."""
    ref = (data.get("change") or "").strip()
    ok, matched = await _deactivate_preference(tenant_id, ref, video_id=video_id)
    if ok:
        return await _reply(f"Forgot it — I'll no longer remember: {matched}.")
    return await _reply(
        "I couldn't find a matching preference to forget — which one did you mean?"
    )


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
                prompt += "\n\nTHUMBNAIL STYLE NOTES:\n" + "\n".join(
                    f"- {s}" for s in thumb_snippets
                )
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
                    thumbnail_motifs = [
                        str(m).strip() for m in motifs if str(m).strip()
                    ][:4]
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
    if (
        intel
        and (time.time() - float(intel.get("computed_at") or 0)) < _CHANNEL_INTEL_TTL_S
    ):
        return intel
    api_key = await get_secret("anthropic_api_key", tenant_id)
    fresh = await _compute_channel_intel(tenant_id, api_key)
    if not fresh:
        return intel  # keep the last good cache if we couldn't refresh
    try:
        await execute(
            "UPDATE channel_profiles SET channel_intel = $2::jsonb, updated_at = now() "
            "WHERE tenant_id = $1",
            tenant_id,
            json.dumps(fresh),
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
        bits.append(
            "Their channel's top-performing titles: "
            + "; ".join(f'"{t}"' for t in titles[:6])
            + "."
        )
    if intel.get("hook_pattern"):
        bits.append(
            "The title/hook pattern that wins for them: " + intel["hook_pattern"]
        )
    motifs = intel.get("thumbnail_motifs") or []
    if motifs:
        bits.append("Recurring thumbnail motifs: " + ", ".join(motifs) + ".")
    cadence = int(intel.get("cadence_days") or 0)
    if cadence > 0:
        bits.append(f"They publish about every {cadence} day(s).")
    if not bits:
        return ""
    return (
        "\nCHANNEL INTELLIGENCE (real data from the videos this creator models — model your "
        "ideas, titles, hooks and thumbnail concepts on these, don't be generic):\n- "
        + "\n- ".join(bits)
    )


async def _competitor_winners_brief(tenant_id) -> str:
    """Top competitor videos RIGHT NOW with real numbers (views, views/hour, age)
    so the producer can answer 'what's working on my competitors?' with specifics
    and ground title/thumbnail ideas in actual winners. Compact top 8 by vph.
    Mirrors the /suggested-models query. Fail-soft -> ''."""
    try:
        rows = (
            await fetch_all(
                "SELECT title, channel, views, vph, hours_old FROM competitor_videos "
                "WHERE tenant_id = $1 AND views > 0 AND removed_at IS NULL "
                "ORDER BY vph DESC NULLS LAST LIMIT 8",
                tenant_id,
            )
            or []
        )
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
    return (
        "\nTOP COMPETITOR VIDEOS RIGHT NOW (real numbers from the channels they model - when they ask "
        "what's working or how a competitor is doing, cite these specifics; and model title/thumbnail "
        "ideas on these proven winners):\n- " + "\n- ".join(lines)
    )


# _next_to_make_brief / _own_performance_brief / _learnings_brief moved to
# channel_briefs.py (C15d) so agent_brain.py's in-video copilot can import
# the SAME implementation the home producer's _loop_brief below uses — one
# data source, two chat surfaces, instead of the copilot having no reach
# into competitor/performance/learnings data at all.
from channel_briefs import (  # noqa: E402
    _next_to_make_brief,
    _own_performance_brief,
    _learnings_brief,
    _style_performance_brief,
)


async def _own_catalog_brief(tenant_id) -> str:
    """The creator's OWN existing catalog (scraped from their channel via channel_videos),
    ranked by real view count. Lets the chat pitch ideas modeled on their PROVEN top
    performers even without synced YouTube analytics (which need the OAuth connection).
    Top 8 by views. Fail-soft -> ''."""
    try:
        rows = (
            await fetch_all(
                "SELECT title, view_count FROM channel_videos "
                "WHERE tenant_id = $1 AND title IS NOT NULL "
                "ORDER BY view_count DESC NULLS LAST LIMIT 8",
                tenant_id,
            )
            or []
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("chat: own catalog brief failed: %s", e)
        return ""
    rows = [r for r in rows if (r.get("view_count") or 0) > 0]
    if not rows:
        return ""
    lines = [
        f'"{(r.get("title") or "").strip()}" - {int(r.get("view_count") or 0):,} views'
        for r in rows
    ]
    return (
        "\nYOUR OWN TOP-PERFORMING VIDEOS (from this channel, ranked by real views — these ARE the "
        "creator's top performers; model new ideas on what already works here):\n- "
        + "\n- ".join(lines)
    )


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
        await _style_performance_brief(tenant_id),
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
        out.append(
            f'- "{r.get("title")}" ({r.get("channel") or "competitor"}) — {v:,} views{when}'
        )
    return out


def _claude_json(api_key: str, prompt: str, max_tokens: int = 1400) -> dict:
    """One direct-Anthropic JSON call (sync; invoke via asyncio.to_thread)."""
    import anthropic
    from producer_prompt import ANTHROPIC_DIRECT_BASE_URL, MODEL, _extract_json

    client = anthropic.Anthropic(api_key=api_key, base_url=ANTHROPIC_DIRECT_BASE_URL)
    resp = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(
        getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text"
    )
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
        if (
            isinstance(data, dict)
            and isinstance(data.get("angles"), list)
            and data["angles"]
        ):
            return {
                "format_summary": data.get("format_summary", ""),
                "angles": data["angles"][:4],
            }
        return None
    except Exception as e:  # noqa: BLE001
        logger.warning("onboarding: modeling angles failed: %s", e)
        return None


async def _generate_competitor_ideas(
    tenant_id, state, niche: Optional[str] = None
) -> Optional[list[dict[str, Any]]]:
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
        + "\n\n"
        + ask
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
            f"{idea.get('script_structure') or ''} | rationale: {idea.get('reasoning') or ''}"
            for i, idea in enumerate(ideas)
        )
        prompt = (
            "You are a ruthless YouTube head of programming. Score these video IDEAS for a "
            f"{niche or 'this creator'} channel against what actually wins on YouTube. The idea "
            "sets the ceiling, so be strict.\n\n"
            "Proven competitor winners (real recent data):\n"
            + "\n".join(_video_lines(rows))
            + "\n\n"
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
            int(s["index"]): s
            for s in (raw or [])
            if isinstance(s, dict) and isinstance(s.get("index"), int)
        }
        if not by_index:
            return ideas
        ranked = [
            {
                **idea,
                "_score": int(by_index.get(i, {}).get("score") or 0),
                "_verdict": str(by_index.get(i, {}).get("verdict") or "ok").lower(),
            }
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
    """Cheap, cached vision classification of the reference video's in-video
    ANIMATION MEDIUM (pixar_3d/flat_2d/realistic/anime/watercolor/comic — the
    style-DESCRIPTION axis, channel_format.STYLE_DESCRIPTIONS) into one of
    those ids, so the chat can RECOMMEND it on the "style" card (the creator
    can still pick another). This is a DIFFERENT question than "which
    style_presets ENGINE renders the scenes" — no mapping exists between the
    two axes (checklist §C21b). Cached in state per reference. Fail-soft ->
    None."""
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
            out = await vision_call(
                prompt, frames, anthropic_key=api_key, tier="fast", max_tokens=12
            )
            cand = (out or "").strip().lower()
            from channel_format import STYLE_DESCRIPTIONS

            for pid in STYLE_DESCRIPTIONS:
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
    ref = state.get("pending_reference_url") or (
        spec.get("reference_url") if spec else None
    )
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
    from channel_format import STYLE_DESCRIPTIONS

    label = STYLE_DESCRIPTIONS.get(preset, {}).get("label") or preset
    cards = data.get("cards")
    if isinstance(cards, list):
        for c in cards:
            if isinstance(c, dict) and c.get("id") == "style":
                c["recommended_value"] = preset
                c["recommended_hint"] = (
                    f"Closest to the video you're modeling ({label})"
                )
    if spec:
        spec["detected_style_label"] = label


async def _stamp_plan_estimate(data) -> None:
    """C15a — MONEY GAP CLOSED: the home Producer's "Make it" tap used to fire
    ``_handle_approve`` -> ``create_video`` -> a paid autobuild straight to real
    pictures with no cost shown or confirmed anywhere (every other paid verb in
    this file quote-gates via ``_confirm_card``; this was the one hole). Stamp
    the plan with a REAL, honest estimate BEFORE it ever reaches the creator, so
    "Make it" is informed consent (shape (a) — the plan card itself carries the
    quote, not a second confirm round-trip: C15's itemized ``cost_breakdown``
    needs a shot plan that doesn't exist before the script is written, so there
    is nothing to itemize yet — same as this estimate being a rough guess, not
    a precise one).

    Sourced ENTIRELY from ``actions.estimate_plan_cost`` (itself a thin
    synthetic-summary wrapper around ``estimate_cost``'s own pre-pictures
    "build" guess) — no new math, no hardcoded price lives here. Threads the
    plan's OWN ``spec.video_length_minutes`` through so the estimate scales
    with the requested length (orchestrator review, 2026-07-18: a flat guess
    ignoring length was a predictable-direction shown-price-vs-real-spend
    mismatch on long plans) — ``estimate_plan_cost`` derives the real scene
    count from that length via the SAME formula the live script generator
    already targets (``VideoConfig.act_count``, see its docstring), so this
    file still does zero scene-count math of its own. Additive only: an
    older frontend build simply never reads ``estimated_cost_text``, so it
    renders the exact same card it always has."""
    plan = data.get("plan") if isinstance(data.get("plan"), dict) else None
    if not plan:
        return
    spec = plan.get("spec") if isinstance(plan.get("spec"), dict) else None
    minutes = spec.get("video_length_minutes") if spec else None
    try:
        cost, _cost_text, scenes = await _estimate_plan_cost(minutes)
    except Exception:  # noqa: BLE001 — never block the plan turn over a display quote
        return
    plan["estimated_cost"] = cost
    plan["estimated_cost_text"] = (
        f"Making this ≈ ${cost:.2f} — pictures for ~{scenes} scenes "
        "(rough estimate; refined once the script's written)."
    )


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
    if type(client).__name__ != "AnthropicDirectClient" and not state.get(
        "kie_hint_shown"
    ):
        state["kie_hint_shown"] = True
        return assistant_text + _KIE_PRODUCER_HINT
    return assistant_text


def _custom_film_plan_text(display_plan: dict[str, Any]) -> str:
    """Render only the compiler's creator-safe view, never its private contract."""
    lines = [str(display_plan["summary"])]
    for section in display_plan["sections"]:
        lines.append(
            f"\n{section['order']}. **{section['role']}** "
            f"({section['share_percent']:g}% of the film)\n"
            f"{section['purpose']}. {section['feel']} "
            f"{section['expected_media']}\n"
            f"Why: {section['why']}"
        )
    lines.extend(
        [
            f"\n{display_plan['byok_notice']}",
            display_plan["status"],
        ]
    )
    return "\n".join(lines)


def _custom_film_duration_seconds(
    message: str,
    prior_pending: Optional[dict[str, Any]] = None,
) -> int:
    """Resolve an explicit runtime edit; otherwise retain it or use five minutes."""
    match = re.search(
        r"\b(\d+(?:\.\d+)?)\s*(seconds?|secs?|minutes?|mins?)\b",
        message or "",
        re.I,
    )
    if match:
        value = float(match.group(1))
        seconds = value if match.group(2).lower().startswith(("s",)) else value * 60
        return max(5, min(24 * 60 * 60, int(round(seconds))))
    if prior_pending:
        quote = prior_pending.get("quote_inputs")
        if isinstance(quote, dict) and quote.get("requested_duration_seconds"):
            return int(quote["requested_duration_seconds"])
    return 5 * 60


def _custom_film_requested_budget_cap(
    message: str,
    prior_pending: Optional[dict[str, Any]] = None,
) -> Optional[float]:
    patterns = (
        r"\b(?:budget|cap|limit)\b[^\d$]{0,20}\$?\s*(\d+(?:\.\d{1,2})?)",
        r"\$\s*(\d+(?:\.\d{1,2})?)\s*(?:budget|cap|limit)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, message or "", re.I)
        if match:
            return round(max(0.01, float(match.group(1))), 2)
    if (
        prior_pending
        and prior_pending.get("budget_cap_source") == "user"
        and isinstance(prior_pending.get("quote_inputs"), dict)
        and prior_pending["quote_inputs"].get("max_spend") is not None
    ):
        return round(float(prior_pending["quote_inputs"]["max_spend"]), 2)
    return None


def _custom_film_approval_card(
    quote: dict[str, Any],
    display_plan: dict[str, Any],
) -> dict[str, Any]:
    total = float(quote["totals"]["estimated_cost"])
    max_spend = float(quote["max_spend"])
    quote_rows = {int(row["order_index"]): row for row in quote["sections"]}
    sections = []
    for display_section in display_plan["sections"]:
        row = quote_rows[int(display_section["order"]) - 1]
        sections.append(
            {
                "order": int(display_section["order"]),
                "role": str(display_section["role"]),
                "purpose": str(display_section["purpose"]),
                "feel": str(display_section["feel"]),
                "share_percent": float(display_section["share_percent"]),
                "duration_seconds": int(row["duration_seconds"]),
                "still_images": int(row["still_images"]),
                "animation_clips": int(row["animation_clips"]),
                "voice_tracks": int(row["voice_tracks"]),
                "estimated_cost": float(row["estimated_cost"]),
            }
        )
    remotion_finishing = _custom_film_remotion_finishing_eligible(
        quote,
        display_plan,
    )
    orchestration_beats = []
    orchestration = quote.get("orchestration")
    if isinstance(orchestration, dict):
        resolved_plan = orchestration.get("resolved_plan")
        recipes = (
            resolved_plan.get("recipes") if isinstance(resolved_plan, dict) else None
        )
        if isinstance(recipes, list):
            beat_counts: dict[int, int] = {}
            for recipe in recipes:
                if not isinstance(recipe, dict):
                    continue
                section_index = int(recipe.get("sectionIndex", -1))
                beat_counts[section_index] = beat_counts.get(section_index, 0) + 1
                layers = recipe.get("motionLayers")
                capability_labels = (
                    [
                        re.sub(r"(?<=[a-z])(?=[A-Z])", " ", str(layer["primitive"]))
                        for layer in layers
                        if isinstance(layer, dict) and layer.get("primitive")
                    ]
                    if isinstance(layers, list)
                    else []
                )
                signals = (
                    recipe.get("signals")
                    if isinstance(recipe.get("signals"), dict)
                    else {}
                )
                camera = (
                    recipe.get("camera")
                    if isinstance(recipe.get("camera"), dict)
                    else {}
                )
                caption = (
                    recipe.get("caption")
                    if isinstance(recipe.get("caption"), dict)
                    else {}
                )
                audio = (
                    recipe.get("audio") if isinstance(recipe.get("audio"), dict) else {}
                )
                orchestration_beats.append(
                    {
                        "section_order": section_index + 1,
                        "beat_order": beat_counts[section_index],
                        "narrative_label": str(
                            recipe.get("narrativeFunction")
                            or " + ".join(signals.get("intents") or [])
                            or "Layered scene"
                        )
                        .replace("_", " ")
                        .title(),
                        "start_seconds": round(float(recipe.get("from", 0)) / 24, 3),
                        "duration_seconds": round(
                            float(recipe.get("durationInFrames", 0)) / 24, 3
                        ),
                        "media_kind": str(signals.get("media_kind") or "adaptive"),
                        "capability_labels": capability_labels,
                        "transformation_summary": str(
                            signals.get("handoff") or "continuous"
                        ).replace("_", " → "),
                        "camera_summary": str(camera.get("mode") or "locked").replace(
                            "-", " "
                        ),
                        "captions_summary": str(caption.get("mode") or "none").replace(
                            "-", " "
                        ),
                        "audio_summary": (
                            "dialogue duck + motion audio"
                            if audio.get("dialogueDuck") == 0.24
                            else "motion audio"
                        ),
                    }
                )
    return {
        "id": "custom_film_approval",
        "label": "Your Custom Film production blueprint",
        "type": "single",
        "header": "Custom Film plan review",
        "custom_film_sections": sections,
        "custom_film_orchestration_beats": orchestration_beats,
        "custom_film_totals": {
            "duration_seconds": int(quote["totals"]["duration_seconds"]),
            "still_images": int(quote["totals"]["still_images"]),
            "animation_clips": int(quote["totals"]["animation_clips"]),
            "voice_tracks": int(quote["totals"]["voice_tracks"]),
            "estimated_cost": total,
            "max_spend": max_spend,
            "headroom": round(max(0.0, max_spend - total), 2),
        },
        "approval_notice": (
            "This is a paid BYOK production start. Approval binds to this exact "
            f"{len(sections)}-section plan, timing, media bill, and spending cap; "
            "any edit clears approval and creates a new quote."
        ),
        "finishing_engine": "remotion" if remotion_finishing else "ffmpeg",
        "finishing_notice": (
            (
                "Layered Remotion orchestration is locked to this exact approved "
                "scene recipe. StoryEngine will combine the approved media, motion, "
                "caption, camera, transition, and audio capabilities selected for "
                "each creator-visible beat with $0 additional provider spend."
            )
            if remotion_finishing
            else (
                "This plan uses StoryEngine's verified FFmpeg finishing fallback. "
                "Approve a plan whose creator-visible beat recipes explicitly "
                "combine supported media, motion, caption, and audio capabilities "
                "to activate layered Remotion finishing."
            )
        ),
        "options": [
            {
                "value": "yes",
                "label": f"Approve paid production · up to ${max_spend:.2f}",
            },
            {"value": "no", "label": "Keep editing"},
        ],
    }


_CUSTOM_FILM_REMOTION_FINISHING_CANVAS = {
    "engine": "remotion",
    "orchestration_contract_version": "storyengine-layered-orchestration-v1",
    "decision_rules_version": "storyengine-layered-recipe-rules-v1",
    "aspect_ratio": "16:9",
    "width": 1920,
    "height": 1080,
    "fps": 24,
}


def _custom_film_showcase_treatment_match(
    quote: dict[str, Any],
    display_plan: dict[str, Any],
) -> bool:
    """Match the exact four-act treatment before binding its finishing canvas."""
    orchestration = quote.get("orchestration")
    if (
        not isinstance(orchestration, dict)
        or orchestration.get("reference_compatible") is not True
    ):
        return False
    expected = (
        ("opening", 45),
        ("evidence", 105),
        ("case_study", 90),
        ("explanation", 60),
    )
    display_sections = display_plan.get("sections")
    quote_sections = quote.get("sections")
    if not isinstance(display_sections, list) or not isinstance(quote_sections, list):
        return False
    if len(display_sections) != len(expected) or len(quote_sections) != len(expected):
        return False
    quote_by_order = {
        int(row.get("order_index", -1)): row
        for row in quote_sections
        if isinstance(row, dict)
    }
    for index, (expected_role, expected_duration) in enumerate(expected):
        section = display_sections[index]
        quote_row = quote_by_order.get(index)
        if not isinstance(section, dict) or quote_row is None:
            return False
        role = str(section.get("role", "")).strip().lower().replace(" ", "_")
        if (
            int(section.get("order", -1)) != index + 1
            or role != expected_role
            or int(quote_row.get("duration_seconds", -1)) != expected_duration
        ):
            return False
    totals = quote.get("totals")
    return isinstance(totals, dict) and int(totals.get("duration_seconds", -1)) == 300


def _custom_film_remotion_finishing_eligible(
    quote: dict[str, Any],
    display_plan: dict[str, Any],
) -> bool:
    """Return true only when resolved beats and approved canvas are both exact."""
    orchestration = quote.get("orchestration")
    canvas = quote.get("finishing_canvas")
    resolved = (
        orchestration.get("resolved_plan") if isinstance(orchestration, dict) else None
    )
    executable = False
    if isinstance(orchestration, dict) and isinstance(resolved, dict):
        try:
            from custom_film_contract import CustomFilmContractError
            from custom_film_orchestration import (
                validate_executable_orchestration,
            )

            validate_executable_orchestration(
                orchestration,
                total_duration_seconds=int(quote["totals"]["duration_seconds"]),
                section_duration_seconds=[
                    int(section["duration_seconds"]) for section in quote["sections"]
                ],
                fps=int(_CUSTOM_FILM_REMOTION_FINISHING_CANVAS["fps"]),
            )
            executable = True
        except (CustomFilmContractError, KeyError, TypeError, ValueError):
            executable = False
    return (
        executable
        and isinstance(orchestration, dict)
        and isinstance(resolved, dict)
        and bool(resolved.get("recipes"))
        and resolved.get("fps") == _CUSTOM_FILM_REMOTION_FINISHING_CANVAS["fps"]
        and resolved.get("total_frames")
        == int(quote["totals"]["duration_seconds"]) * int(resolved["fps"])
        and isinstance(orchestration.get("recipe_hash"), str)
        and isinstance(canvas, dict)
        and canvas
        == {
            **_CUSTOM_FILM_REMOTION_FINISHING_CANVAS,
            "orchestration_contract_hash": orchestration.get("contract_hash"),
            "story_identity": orchestration.get("story_identity"),
            "recipe_hash": orchestration.get("recipe_hash"),
        }
    )


def _custom_film_approval_cards(
    quote: dict[str, Any],
    display_plan: dict[str, Any],
) -> list[dict[str, Any]] | None:
    """Expose paid approval only when the creator's cap covers the estimate."""
    estimate = float(quote["totals"]["estimated_cost"])
    max_spend = float(quote["max_spend"])
    if max_spend + 1e-9 < estimate:
        return None
    return [_custom_film_approval_card(quote, display_plan)]


def _custom_film_estimate_text(quote: dict[str, Any]) -> str:
    total = quote["totals"]
    rows = [
        (
            f"Section {row['order_index'] + 1}: {row['still_images']} stills, "
            f"{row['animation_clips']} clips, {row['voice_tracks']} voice "
            f"track{'s' if row['voice_tracks'] != 1 else ''} — "
            f"~${row['estimated_cost']:.2f}"
        )
        for row in quote["sections"]
    ]
    return "\n".join(
        [
            *rows,
            (
                f"\nTotal: {total['still_images']} stills, "
                f"{total['animation_clips']} clips, {total['voice_tracks']} voice "
                f"tracks — ~${total['estimated_cost']:.2f}."
            ),
            (
                "This is a BYOK estimate: production uses only your connected AI "
                "accounts. Approving binds to this exact plan and estimate; any edit "
                "clears it and produces a new approval."
            ),
            f"Spending cap for this film: ${float(quote['max_spend']):.2f}.",
        ]
    )


def _custom_film_recipe_command(
    message: str,
    *,
    has_save_candidate: bool = False,
) -> tuple[str, tuple[str, ...]] | None:
    """Parse the small, deterministic public chat vocabulary for saved recipes."""
    text = re.sub(r"\s+", " ", str(message or "").strip())
    if not text:
        return None
    quoted = tuple(re.findall(r'["“]([^"”]+)["”]', text))
    if re.fullmatch(
        r"(?:please )?(?:list|show)(?: me)? (?:my )?(?:active )?"
        r"(?:saved )?custom film recipes?[.!]?",
        text,
        re.I,
    ):
        return ("list", ())
    rename_match = re.fullmatch(
        r"(?:please )?rename (?:the )?(?:saved )?(?:custom film )?recipe "
        r"(.+?) to (.+?)[.!]?",
        text,
        re.I,
    )
    if rename_match:
        return (
            ("rename", quoted)
            if len(quoted) == 2
            else ("rename", (rename_match.group(1), rename_match.group(2)))
        )
    if re.fullmatch(r"(?:please )?rename(?: the)? recipe[.!]?", text, re.I):
        return ("rename", ())
    archive_match = re.fullmatch(
        r"(?:please )?archive (?:the )?(?:saved )?(?:custom film )?recipe "
        r'(?:(?:["“]([^"”]+)["”])|(.+?))[.!]?',
        text,
        re.I,
    )
    if archive_match:
        return ("archive", (archive_match.group(1) or archive_match.group(2),))
    if re.fullmatch(r"(?:please )?archive(?: the)? recipe[.!]?", text, re.I):
        return ("archive", ())
    if has_save_candidate and re.fullmatch(
        r"(?:please )?save (?:this custom film recipe|this recipe)[.!]?",
        text,
        re.I,
    ):
        return ("save", ())
    save_match = re.fullmatch(
        r"(?:please )?save (this custom film recipe|this recipe) as "
        r'(?:(?:["“]([^"”]+)["”])|(.+?))[.!]?',
        text,
        re.I,
    )
    if save_match and (
        "custom film" in save_match.group(1).lower() or has_save_candidate
    ):
        return ("save", (save_match.group(2) or save_match.group(3),))
    reuse_match = re.fullmatch(
        r"(?:please )?reuse (?:the )?saved (?:custom film )?recipe "
        r'(?:(?:["“]([^"”]+)["”])|(.+?)) (?:for|about) (.+?)[.!]?',
        text,
        re.I,
    )
    if reuse_match:
        return (
            "reuse",
            (reuse_match.group(1) or reuse_match.group(2), reuse_match.group(3)),
        )
    if re.fullmatch(
        r"(?:please )?reuse (?:the )?saved (?:custom film )?recipe"
        r'(?: ["“][^"”]+["”])?[.!]?',
        text,
        re.I,
    ):
        return ("reuse", quoted[:1])
    return None


async def _append_custom_film_recipe_turn(
    conversation_id: str,
    tenant_id: str,
    user_message: str,
    message: str,
    *,
    video_id: str | None = None,
    phase: str = "asking",
) -> ChatTurnResponse:
    turns = [
        {"role": "user", "content": user_message},
        _assistant_turn({"assistant_text": message, "phase": phase}),
    ]
    await execute(
        """UPDATE chat_conversations
           SET transcript = COALESCE(transcript, '[]'::jsonb) || $3::jsonb,
               state = jsonb_set(
                 COALESCE(state, '{}'::jsonb),
                 '{recipe_command_revision}',
                 to_jsonb(
                   COALESCE((state->>'recipe_command_revision')::bigint, 0) + 1
                 )
               ),
               updated_at = now()
           WHERE id = $1 AND tenant_id = $2""",
        conversation_id,
        tenant_id,
        json.dumps(turns),
    )
    return ChatTurnResponse(
        conversation_id=conversation_id,
        assistant_text=message,
        video_id=video_id,
        phase=phase,
    )


async def _handle_custom_film_recipe_command(
    command: tuple[str, tuple[str, ...]],
    *,
    conversation_id: str,
    tenant_id: str,
    state: dict[str, Any],
    video_id: str | None,
    user_message: str,
    transcript: list[dict[str, Any]],
    expected_state: dict[str, Any],
) -> ChatTurnResponse:
    """Execute recipe metadata actions without touching production runtime."""
    from custom_film_contract import (
        CustomFilmContractError,
        DuplicateRecipeError,
        archive_active_recipe,
        list_active_recipes_for_chat,
        load_active_recipe_for_chat,
        rename_active_recipe,
        save_approved_recipe,
    )
    from custom_film_planner import load_capability_manifest

    action, args = command
    mutation_audited = False
    if action == "list":
        _recipes, message = await list_active_recipes_for_chat(
            tenant_id,
            conversation_id,
            user_message,
            phase="created" if video_id else "asking",
        )
        return ChatTurnResponse(
            conversation_id=conversation_id,
            assistant_text=message,
            video_id=video_id,
            phase="created" if video_id else "asking",
        )
    if action == "save":
        if len(args) != 1:
            return await _append_custom_film_recipe_turn(
                conversation_id,
                tenant_id,
                user_message,
                "What name should I use? Say “Save this Custom Film recipe as My Recipe.”",
                video_id=video_id,
                phase="created" if video_id else "asking",
            )
        try:
            manifest = await load_capability_manifest()
            recipe = await save_approved_recipe(
                tenant_id,
                conversation_id,
                args[0],
                manifest,
                user_message=user_message,
                audit_phase="created" if video_id else "asking",
            )
            message = recipe["_assistant_text"]
            mutation_audited = True
        except DuplicateRecipeError:
            message = (
                "That production recipe already exists as an active saved or public "
                "recipe, so I did not create a duplicate."
            )
        except CustomFilmContractError as exc:
            message = str(exc)
        if mutation_audited:
            return ChatTurnResponse(
                conversation_id=conversation_id,
                assistant_text=message,
                video_id=video_id,
                phase="created" if video_id else "asking",
            )
        return await _append_custom_film_recipe_turn(
            conversation_id,
            tenant_id,
            user_message,
            message,
            video_id=video_id,
            phase="created" if video_id else "asking",
        )
    if action == "rename":
        if len(args) != 2:
            message = (
                "Name both recipes, for example: "
                "Rename recipe “Old Name” to “New Name”."
            )
        else:
            try:
                recipe = await rename_active_recipe(
                    tenant_id,
                    args[0],
                    args[1],
                    conversation_id=conversation_id,
                    user_message=user_message,
                    audit_phase="created" if video_id else "asking",
                )
                message = recipe["_assistant_text"]
                mutation_audited = True
            except CustomFilmContractError as exc:
                message = str(exc)
        if mutation_audited:
            return ChatTurnResponse(
                conversation_id=conversation_id,
                assistant_text=message,
                video_id=video_id,
                phase="created" if video_id else "asking",
            )
        return await _append_custom_film_recipe_turn(
            conversation_id,
            tenant_id,
            user_message,
            message,
            video_id=video_id,
            phase="created" if video_id else "asking",
        )
    if action == "archive":
        if len(args) != 1:
            message = "Which recipe should I archive? Put its exact name in quotes."
        else:
            try:
                recipe = await archive_active_recipe(
                    tenant_id,
                    args[0],
                    conversation_id=conversation_id,
                    user_message=user_message,
                    audit_phase="created" if video_id else "asking",
                )
                message = recipe["_assistant_text"]
                mutation_audited = True
            except CustomFilmContractError as exc:
                message = str(exc)
        if mutation_audited:
            return ChatTurnResponse(
                conversation_id=conversation_id,
                assistant_text=message,
                video_id=video_id,
                phase="created" if video_id else "asking",
            )
        return await _append_custom_film_recipe_turn(
            conversation_id,
            tenant_id,
            user_message,
            message,
            video_id=video_id,
            phase="created" if video_id else "asking",
        )
    # reuse
    if video_id:
        return await _append_custom_film_recipe_turn(
            conversation_id,
            tenant_id,
            user_message,
            "Start a fresh chat to reuse a saved recipe for a new film; this chat "
            "is already attached to the approved film.",
            video_id=video_id,
            phase="created",
        )
    if len(args) < 2 or not args[1].strip():
        return await _append_custom_film_recipe_turn(
            conversation_id,
            tenant_id,
            user_message,
            "Name the recipe and fresh topic, for example: Reuse saved recipe "
            "“My Recipe” for a film about coastal restoration.",
        )
    try:
        manifest = await load_capability_manifest()
        recipe, transcript, state = await load_active_recipe_for_chat(
            tenant_id,
            conversation_id,
            args[0],
            manifest,
        )
        expected_state = copy.deepcopy(state)
    except CustomFilmContractError as exc:
        return await _append_custom_film_recipe_turn(
            conversation_id, tenant_id, user_message, str(exc)
        )
    return await _handle_custom_film_plan(
        conversation_id,
        tenant_id,
        transcript,
        state,
        args[1].strip(),
        expected_state,
        saved_recipe=recipe,
        audit_user_message=user_message,
    )


_CUSTOM_FILM_STALE_STATE_KEYS = (
    "last_spec",
    "pending_action",
    "pending_style_draft",
    "pending_quality_rules_draft",
    "pending_dna_digest",
    "pending_reference_url",
    "pending_assets",
    "selections",
)


def _quarantine_custom_film_state(
    state: dict[str, Any],
    *,
    clear_custom_plan: bool = False,
) -> None:
    for key in _CUSTOM_FILM_STALE_STATE_KEYS:
        state.pop(key, None)
    if clear_custom_plan:
        state.pop("pending_custom_film_plan", None)


async def _handle_custom_film_control_turn(
    conversation_id: str,
    tenant_id: str,
    transcript: list[dict[str, Any]],
    state: dict[str, Any],
    expected_state: dict[str, Any] | None = None,
) -> ChatTurnResponse:
    """Hold approve/selection-only taps inside the planning-only M2-2 boundary."""
    _quarantine_custom_film_state(state)
    message = (
        "This Custom Film is an unapproved plan with no current approval. Tell me what to revise "
        "in words and I'll show the refreshed section-aware BYOK estimate for an "
        "explicit approval. Nothing was generated or charged."
    )
    data = {
        "assistant_text": message,
        "ready_to_create": False,
        "phase": "plan",
    }
    transcript.append(_assistant_turn(data))
    converged = await _persist_custom_film_cas(
        conversation_id, tenant_id, transcript, state, "plan", expected_state
    )
    if converged:
        return converged
    return ChatTurnResponse(
        conversation_id=conversation_id,
        assistant_text=message,
        plan=None,
        ready_to_create=False,
        phase="plan",
    )


async def _handle_custom_film_cancel_turn(
    conversation_id: str,
    tenant_id: str,
    transcript: list[dict[str, Any]],
    state: dict[str, Any],
    expected_state: dict[str, Any] | None = None,
) -> ChatTurnResponse:
    """Leave Custom Film without resolving a key or invoking either planner."""
    state["mode"] = "producer"
    _quarantine_custom_film_state(state, clear_custom_plan=True)
    message = (
        "Custom Film planning is cancelled. Nothing was generated or charged. "
        "Tell me whenever you want to plan a regular video."
    )
    transcript.append(_assistant_turn({"assistant_text": message, "phase": "asking"}))
    converged = await _persist_custom_film_cas(
        conversation_id, tenant_id, transcript, state, "asking", expected_state
    )
    if converged:
        return converged
    return ChatTurnResponse(
        conversation_id=conversation_id,
        assistant_text=message,
        plan=None,
        ready_to_create=False,
        phase="asking",
    )


async def _handle_custom_film_approval_turn(
    selection: str,
    conversation_id: str,
    tenant_id: str,
    transcript: list[dict[str, Any]],
    state: dict[str, Any],
    background_tasks: BackgroundTasks,
    expected_state: dict[str, Any] | None = None,
    *,
    arq_pool: Any = _QUEUE_CONTEXT_UNSET,
) -> ChatTurnResponse:
    """Confirm one exact quote into a durable no-provider start intention."""
    pending = state.get("pending_custom_film_plan")
    if (
        isinstance(pending, dict)
        and pending.get("execution_model") == "storyboard_director_v1"
    ):
        pending["status"] = "stale"
        pending.pop("approval_hash", None)
        message = (
            "That held screenplay/director quote used the retired v1 contract, "
            "so it cannot authorize the new multipass worker. Nothing was "
            "started or charged. Send the film request again to receive the "
            "current exact v2 approval card."
        )
        transcript.append(_assistant_turn({"assistant_text": message, "phase": "plan"}))
        converged = await _persist_custom_film_cas(
            conversation_id,
            tenant_id,
            transcript,
            state,
            "plan",
            expected_state,
        )
        if converged:
            return converged
        return ChatTurnResponse(
            conversation_id=conversation_id,
            assistant_text=message,
            phase="plan",
        )
    if isinstance(pending, dict) and pending.get("execution_model") in {
        "storyboard_director_v1",
        "storyboard_director_multipass_v2",
    }:
        return await _handle_custom_film_director_approval_turn(
            selection,
            conversation_id,
            tenant_id,
            transcript,
            state,
            expected_state,
            arq_pool=arq_pool,
        )
    if selection != "yes":
        message = "No problem — the current Custom Film plan remains unapproved. Tell me what to edit."
        transcript.append(_assistant_turn({"assistant_text": message, "phase": "plan"}))
        converged = await _persist_custom_film_cas(
            conversation_id, tenant_id, transcript, state, "plan", expected_state
        )
        if converged:
            return converged
        return ChatTurnResponse(
            conversation_id=conversation_id,
            assistant_text=message,
            ready_to_create=False,
            phase="plan",
        )
    if not isinstance(pending, dict) or pending.get("status") != "awaiting_approval":
        return await _handle_custom_film_control_turn(
            conversation_id, tenant_id, transcript, state, expected_state
        )

    from custom_film_contract import (
        CustomFilmContractError,
        approval_binding_hash,
        plan_hash,
        reserve_approved_start_intent,
    )

    internal_plan = pending.get("internal_plan")
    quote_inputs = pending.get("quote_inputs")
    expected = str(pending.get("approval_hash") or "")
    if not isinstance(internal_plan, dict) or not isinstance(quote_inputs, dict):
        message = "That estimate is incomplete. Please revise the plan so I can quote it again."
        state.pop("pending_custom_film_plan", None)
        transcript.append(
            _assistant_turn({"assistant_text": message, "phase": "asking"})
        )
        converged = await _persist_custom_film_cas(
            conversation_id, tenant_id, transcript, state, "asking", expected_state
        )
        if converged:
            return converged
        return ChatTurnResponse(
            conversation_id=conversation_id, assistant_text=message, phase="asking"
        )
    current = approval_binding_hash(plan_hash(internal_plan), quote_inputs)
    if not expected or current != expected:
        pending["status"] = "stale"
        pending.pop("approval_hash", None)
        message = (
            "That plan or estimate changed, so the old approval is no longer valid. "
            "Please review the refreshed plan and approve again."
        )
        return ChatTurnResponse(
            conversation_id=conversation_id, assistant_text=message, phase="plan"
        )

    # BYOK first: never let a process environment/operator key satisfy this gate.
    try:
        from vault import get_required_tenant_secret

        await get_required_tenant_secret(
            "kie_ai_api_key", tenant_id, provider_label="Kie.ai"
        )
    except Exception as exc:  # noqa: BLE001 - helper text is creator-safe
        message = str(exc)
        return ChatTurnResponse(
            conversation_id=conversation_id, assistant_text=message, phase="plan"
        )

    # Tenant-scoped pre-create claim is both the drain gate and the retry /
    # double-tap idempotency gate before a video id exists.
    try:
        claimed = await generation_claims.acquire_channel(
            tenant_id,
            "custom_film_start",
            claimed_by=f"chat:custom-film:{conversation_id}",
        )
    except Exception as exc:  # drain mode carries a useful retryable response
        message = getattr(exc, "message", None) or str(exc)
        return ChatTurnResponse(
            conversation_id=conversation_id, assistant_text=message, phase="plan"
        )
    if not claimed:
        message = "This Custom Film start is already being handled. I did not reserve it twice."
        return ChatTurnResponse(
            conversation_id=conversation_id, assistant_text=message, phase="plan"
        )

    try:
        # Read-only account gates precede the durable intent transaction.
        from routes.billing import check_plan_limits, enforce_video_length_cap

        await check_plan_limits(tenant_id, "video")
        await enforce_video_length_cap(
            tenant_id,
            float(quote_inputs["requested_duration_seconds"]) / 60,
        )
        from custom_film_planner import load_capability_manifest

        manifest = await load_capability_manifest()
        quote_total = float(quote_inputs["totals"]["estimated_cost"])
        save_offer = (
            " If you want to reuse this section treatment later, send a separate "
            "message such as “Save this Custom Film recipe as My Recipe.”"
        )
        message = (
            f"Approved — this exact ~${quote_total:.2f} BYOK plan is safely held "
            "and ready for section-aware production. No generation has started "
            "or been charged yet."
        )
        result = await reserve_approved_start_intent(
            tenant_id,
            conversation_id,
            expected,
            manifest,
            confirmation_turn=_assistant_turn(
                {"assistant_text": message, "phase": "created"}
            ),
            save_offer_suffix=save_offer,
        )
        video_id = result["video_id"]
        accepted_turn = result.get("confirmation_turn")
        if isinstance(accepted_turn, dict) and accepted_turn.get("content"):
            message = str(accepted_turn["content"])
        reserved_pending = result.get("pending_custom_film_plan")
        if isinstance(reserved_pending, dict):
            # Schedule from the transaction's authoritative accepted state.
            # Using the pre-lock caller snapshot here would overwrite the
            # post-approval save candidate during the runtime metadata update.
            state["pending_custom_film_plan"] = copy.deepcopy(reserved_pending)
        schedule_kwargs = (
            {"arq_pool": arq_pool} if arq_pool is not _QUEUE_CONTEXT_UNSET else {}
        )
        await _schedule_reserved_custom_film_runtime(
            conversation_id,
            tenant_id,
            state,
            video_id,
            **schedule_kwargs,
        )
        return ChatTurnResponse(
            conversation_id=conversation_id,
            assistant_text=message,
            video_id=video_id,
            phase="created",
        )
    except (HTTPException, CustomFilmContractError) as exc:
        message = (
            exc.detail
            if isinstance(exc, HTTPException) and isinstance(exc.detail, str)
            else str(exc)
        )
        if "video_id" in locals() and video_id:
            return ChatTurnResponse(
                conversation_id=conversation_id,
                assistant_text=(
                    f"{message} The approved film is still safely reserved; retry "
                    "and StoryEngine will reuse this same video."
                ),
                video_id=video_id,
                phase="created",
            )
        return ChatTurnResponse(
            conversation_id=conversation_id, assistant_text=message, phase="plan"
        )
    finally:
        await generation_claims.release_channel(tenant_id, "custom_film_start")


async def _handle_custom_film_director_approval_turn(
    selection: str,
    conversation_id: str,
    tenant_id: str,
    transcript: list[dict[str, Any]],
    state: dict[str, Any],
    expected_state: dict[str, Any] | None = None,
    *,
    arq_pool: Any = _QUEUE_CONTEXT_UNSET,
) -> ChatTurnResponse:
    """Persist and enqueue one explicitly approved Stage 1 authority."""
    from custom_film_contract import CustomFilmContractError
    from custom_film_director_activation import (
        DIRECTOR_EXECUTION_MODEL,
        reserve_director_stage_intent,
        validate_director_intake,
    )

    pending = state.get("pending_custom_film_plan")
    if selection != "yes":
        message = (
            "No problem — the screenplay/director stage remains unapproved. "
            "Nothing was started or charged; tell me what to change."
        )
        transcript.append(_assistant_turn({"assistant_text": message, "phase": "plan"}))
        converged = await _persist_custom_film_cas(
            conversation_id,
            tenant_id,
            transcript,
            state,
            "plan",
            expected_state,
        )
        if converged:
            return converged
        return ChatTurnResponse(
            conversation_id=conversation_id,
            assistant_text=message,
            phase="plan",
        )
    if (
        not isinstance(pending, dict)
        or pending.get("execution_model") != DIRECTOR_EXECUTION_MODEL
        or pending.get("status") != "awaiting_director_approval"
    ):
        return await _handle_custom_film_control_turn(
            conversation_id,
            tenant_id,
            transcript,
            state,
            expected_state,
        )
    expected = str(pending.get("approval_hash") or "")
    try:
        activation = validate_director_intake(pending.get("director_activation"))
    except CustomFilmContractError as exc:
        pending["status"] = "stale"
        pending.pop("approval_hash", None)
        message = str(exc)
        transcript.append(_assistant_turn({"assistant_text": message, "phase": "plan"}))
        converged = await _persist_custom_film_cas(
            conversation_id,
            tenant_id,
            transcript,
            state,
            "plan",
            expected_state,
        )
        if converged:
            return converged
        return ChatTurnResponse(
            conversation_id=conversation_id,
            assistant_text=message,
            phase="plan",
        )
    if (
        not expected
        or activation["approval_hash"] != expected
        or activation["prospective_plan_id"] != pending.get("prospective_plan_id")
    ):
        pending["status"] = "stale"
        pending.pop("approval_hash", None)
        message = (
            "That screenplay/director quote changed, so its approval is no "
            "longer valid. Nothing was started or charged."
        )
        transcript.append(_assistant_turn({"assistant_text": message, "phase": "plan"}))
        converged = await _persist_custom_film_cas(
            conversation_id,
            tenant_id,
            transcript,
            state,
            "plan",
            expected_state,
        )
        if converged:
            return converged
        return ChatTurnResponse(
            conversation_id=conversation_id,
            assistant_text=message,
            phase="plan",
        )

    # Resolve only the existence of a tenant-owned text client. This does not
    # invoke it; the durable schedule remains provider_calls_started=false.
    client = await _resolve_producer_client(tenant_id)
    if client is None:
        return ChatTurnResponse(
            conversation_id=conversation_id,
            assistant_text=(
                "Add your Kie.ai or Anthropic key under Profile → API Keys before "
                "approving the screenplay/director stage. Nothing was started."
            ),
            phase="plan",
        )
    try:
        claimed = await generation_claims.acquire_channel(
            tenant_id,
            "custom_film_director_start",
            claimed_by=f"chat:custom-film-director:{conversation_id}",
        )
    except Exception as exc:  # noqa: BLE001 - drain text is creator-safe
        return ChatTurnResponse(
            conversation_id=conversation_id,
            assistant_text=getattr(exc, "message", None) or str(exc),
            phase="plan",
        )
    if not claimed:
        return ChatTurnResponse(
            conversation_id=conversation_id,
            assistant_text=(
                "This screenplay/director approval is already being handled. "
                "I did not reserve it twice."
            ),
            phase="plan",
        )

    try:
        from custom_film_planner import load_capability_manifest
        from routes.billing import check_plan_limits, enforce_video_length_cap

        await check_plan_limits(tenant_id, "video")
        await enforce_video_length_cap(
            tenant_id,
            float(activation["quote_inputs"]["requested_duration_seconds"]) / 60,
        )
        manifest = await load_capability_manifest()
        cumulative = int(activation["stage_quote"]["approved_cumulative_cents"])
        message = (
            "Stage 1 is safely authorized at an exact cumulative ceiling of "
            f"${cumulative / 100:.2f}. Its immutable multipass director schedule "
            "is queued. No imagery, animation, voice, render, upload, or later-stage "
            "provider work is authorized."
        )
        result = await reserve_director_stage_intent(
            tenant_id,
            conversation_id,
            expected,
            manifest,
            confirmation_turn=_assistant_turn(
                {"assistant_text": message, "phase": "created"}
            ),
        )
        video_id = result["video_id"]
        durable_pending = result.get("pending_custom_film_plan")
        if isinstance(durable_pending, dict):
            state["pending_custom_film_plan"] = copy.deepcopy(durable_pending)
            if arq_pool is not _QUEUE_CONTEXT_UNSET:
                await _schedule_reserved_custom_film_director(
                    durable_pending,
                    tenant_id=tenant_id,
                    video_id=video_id,
                    arq_pool=arq_pool,
                )
        return ChatTurnResponse(
            conversation_id=conversation_id,
            assistant_text=message,
            video_id=video_id,
            phase="created",
        )
    except (HTTPException, CustomFilmContractError) as exc:
        message = (
            exc.detail
            if isinstance(exc, HTTPException) and isinstance(exc.detail, str)
            else str(exc)
        )
        if "video_id" in locals() and video_id:
            return ChatTurnResponse(
                conversation_id=conversation_id,
                assistant_text=(
                    f"{message} The approved director schedule is still safely "
                    "reserved; retry and StoryEngine will enqueue the same exact job."
                ),
                video_id=video_id,
                phase="created",
            )
        return ChatTurnResponse(
            conversation_id=conversation_id,
            assistant_text=message,
            phase="plan",
        )
    finally:
        await generation_claims.release_channel(
            tenant_id,
            "custom_film_director_start",
        )


async def _handle_custom_film_director_intake_plan(
    conversation_id: str,
    tenant_id: str,
    transcript: list[dict[str, Any]],
    state: dict[str, Any],
    user_message: str,
    expected_state: dict[str, Any] | None = None,
    *,
    audit_user_message: str | None = None,
) -> ChatTurnResponse:
    """Build a deterministic Stage 1 quote before any planner inference."""
    from custom_film_contract import CustomFilmContractError
    from custom_film_director_activation import (
        DIRECTOR_EXECUTION_MODEL,
        build_director_intake,
        configured_director_price_book,
        director_approval_card,
        director_intake_text,
    )
    from custom_film_planner import load_capability_manifest

    transcript.append({"role": "user", "content": audit_user_message or user_message})
    existing = state.get("pending_custom_film_plan")
    prior_cumulative_cents = state.get(
        "custom_film_completed_spend_cents",
        0,
    )
    if (
        isinstance(existing, dict)
        and existing.get("execution_model") == DIRECTOR_EXECUTION_MODEL
        and isinstance(existing.get("director_activation"), dict)
    ):
        stage_quote = existing["director_activation"].get("stage_quote")
        if isinstance(stage_quote, dict):
            prior_cumulative_cents = stage_quote.get(
                "prior_cumulative_cents",
                prior_cumulative_cents,
            )
    if type(prior_cumulative_cents) is not int or prior_cumulative_cents < 0:
        prior_cumulative_cents = 0

    _quarantine_custom_film_state(state)
    state.pop("pending_custom_film_plan", None)
    total_duration_seconds = _custom_film_duration_seconds(
        user_message,
        None,
    )
    try:
        manifest = await load_capability_manifest()
        activation = build_director_intake(
            user_message,
            manifest,
            total_duration_seconds=total_duration_seconds,
            prior_cumulative_cents=prior_cumulative_cents,
            price_book=configured_director_price_book(),
        )
    except CustomFilmContractError as exc:
        state["mode"] = "custom_film"
        state["pending_custom_film_plan"] = {
            "execution_model": DIRECTOR_EXECUTION_MODEL,
            "status": "director_pricing_blocked",
            "user_request": user_message.strip(),
        }
        message = str(exc)
        transcript.append(_assistant_turn({"assistant_text": message, "phase": "plan"}))
        converged = await _persist_custom_film_cas(
            conversation_id,
            tenant_id,
            transcript,
            state,
            "plan",
            expected_state,
        )
        if converged:
            return converged
        return ChatTurnResponse(
            conversation_id=conversation_id,
            assistant_text=message,
            phase="plan",
        )
    except Exception as exc:  # noqa: BLE001 - DB detail is not creator-safe
        logger.warning("custom-film director intake setup failed: %s", exc)
        state["mode"] = "custom_film"
        state["pending_custom_film_plan"] = {
            "execution_model": DIRECTOR_EXECUTION_MODEL,
            "status": "director_intake_blocked",
            "user_request": user_message.strip(),
        }
        message = (
            "I couldn't safely prepare the screenplay/director approval. "
            "Nothing was approved, started, or charged."
        )
        transcript.append(_assistant_turn({"assistant_text": message, "phase": "plan"}))
        converged = await _persist_custom_film_cas(
            conversation_id,
            tenant_id,
            transcript,
            state,
            "plan",
            expected_state,
        )
        if converged:
            return converged
        return ChatTurnResponse(
            conversation_id=conversation_id,
            assistant_text=message,
            phase="plan",
        )

    state["mode"] = "custom_film"
    state["pending_custom_film_plan"] = {
        "execution_model": DIRECTOR_EXECUTION_MODEL,
        "status": "awaiting_director_approval",
        "user_request": activation["user_request"],
        "prospective_plan_id": activation["prospective_plan_id"],
        "approval_hash": activation["approval_hash"],
        "director_activation": activation,
    }
    assistant_text = director_intake_text(activation)
    cards = [director_approval_card(activation)]
    transcript.append(
        _assistant_turn(
            {
                "assistant_text": assistant_text,
                "cards": cards,
                "ready_to_create": False,
                "phase": "plan",
            }
        )
    )
    converged = await _persist_custom_film_cas(
        conversation_id,
        tenant_id,
        transcript,
        state,
        "plan",
        expected_state,
    )
    if converged:
        return converged
    return ChatTurnResponse(
        conversation_id=conversation_id,
        assistant_text=assistant_text,
        cards=cards,
        ready_to_create=False,
        phase="plan",
    )


async def _handle_custom_film_plan(
    conversation_id: str,
    tenant_id: str,
    transcript: list[dict[str, Any]],
    state: dict[str, Any],
    user_message: str,
    expected_state: dict[str, Any] | None = None,
    *,
    saved_recipe: dict[str, Any] | None = None,
    audit_user_message: str | None = None,
) -> ChatTurnResponse:
    """Plan only: no video creation, estimate, approval, or background dispatch."""
    from custom_film_director_activation import director_activation_enabled

    if saved_recipe is None and director_activation_enabled():
        return await _handle_custom_film_director_intake_plan(
            conversation_id,
            tenant_id,
            transcript,
            state,
            user_message,
            expected_state,
            audit_user_message=audit_user_message,
        )
    from custom_film_planner import (
        CustomFilmPlannerError,
        NO_KEY_MESSAGE,
        PLANNER_FAILURE_MESSAGE,
        SECTION_COUNT_CHANGE_MESSAGE,
        classify_plan_novelty,
        is_section_count_change_request,
        load_capability_manifest,
        plan_custom_film,
        plan_custom_film_from_recipe,
    )

    transcript.append({"role": "user", "content": audit_user_message or user_message})
    existing_pending = state.get("pending_custom_film_plan")
    prior_pending = (
        existing_pending
        if (
            state.get("mode") == "custom_film"
            and isinstance(existing_pending, dict)
            and existing_pending.get("status")
            in {
                "planned_unapproved",
                "awaiting_approval",
            }
            and isinstance(existing_pending.get("planner_proposal"), dict)
            and isinstance(existing_pending.get("internal_plan"), dict)
            and isinstance(existing_pending["internal_plan"].get("sections"), list)
        )
        else None
    )
    prior_section_ids = (
        [
            section.get("section_id")
            for section in prior_pending["internal_plan"]["sections"]
            if isinstance(section, dict)
        ]
        if prior_pending is not None
        else None
    )
    # Any textual edit is estimate-affecting until the deterministic compiler
    # proves otherwise.  Clear consent before inference/key/validation so even
    # a failed revision can never leave an old spend approval live.
    if prior_pending is not None:
        prior_pending["status"] = "planned_unapproved"
        prior_pending.pop("approval_hash", None)
    # Entering the Custom Film composer quarantines any old generic create or
    # co-pilot confirmation. Even a key/planner failure must not leave a stale
    # approval payload that a later approve=True/yes tap could consume.
    _quarantine_custom_film_state(state)
    if prior_pending is None:
        state.pop("pending_custom_film_plan", None)
    if prior_pending is not None and is_section_count_change_request(user_message):
        data = {
            "assistant_text": SECTION_COUNT_CHANGE_MESSAGE,
            "ready_to_create": False,
            "phase": "plan",
        }
        transcript.append(_assistant_turn(data))
        converged = await _persist_custom_film_cas(
            conversation_id, tenant_id, transcript, state, "plan", expected_state
        )
        if converged:
            return converged
        return ChatTurnResponse(
            conversation_id=conversation_id,
            assistant_text=SECTION_COUNT_CHANGE_MESSAGE,
            plan=None,
            ready_to_create=False,
            phase="plan",
        )
    client = await _resolve_producer_client(tenant_id)
    if client is None:
        message = NO_KEY_MESSAGE
        phase = "asking"
        if prior_pending is not None:
            message += " Your previous unapproved plan is unchanged."
            phase = "plan"
        data = {"assistant_text": message, "phase": phase}
        transcript.append(_assistant_turn(data))
        converged = await _persist_custom_film_cas(
            conversation_id, tenant_id, transcript, state, phase, expected_state
        )
        if converged:
            return converged
        return ChatTurnResponse(
            conversation_id=conversation_id,
            assistant_text=message,
            ready_to_create=False,
            phase=phase,
        )

    try:
        manifest = await load_capability_manifest()
        total_duration_seconds = _custom_film_duration_seconds(
            user_message,
            prior_pending,
        )
        requested_budget_cap = _custom_film_requested_budget_cap(
            user_message,
            prior_pending,
        )
        if saved_recipe is not None:
            compiled = await plan_custom_film_from_recipe(
                user_message,
                saved_recipe["recipe"],
                manifest,
                client,
                total_duration_seconds=total_duration_seconds,
            )
        else:
            compiled = await plan_custom_film(
                user_message,
                manifest,
                client,
                total_duration_seconds=total_duration_seconds,
                prior_proposal=(
                    prior_pending.get("planner_proposal")
                    if prior_pending is not None
                    else None
                ),
                prior_section_ids=prior_section_ids,
            )
    except CustomFilmPlannerError as exc:
        message = str(exc) or PLANNER_FAILURE_MESSAGE
        phase = "asking"
        if prior_pending is not None:
            message += " Your previous unapproved plan is unchanged."
            phase = "plan"
        data = {"assistant_text": message, "phase": phase}
        transcript.append(_assistant_turn(data))
        converged = await _persist_custom_film_cas(
            conversation_id, tenant_id, transcript, state, phase, expected_state
        )
        if converged:
            return converged
        return ChatTurnResponse(
            conversation_id=conversation_id,
            assistant_text=message,
            ready_to_create=False,
            phase=phase,
        )
    except Exception as exc:  # noqa: BLE001 - DB/manifest detail is not creator-safe
        logger.warning("custom-film planner setup failed: %s", exc)
        message = PLANNER_FAILURE_MESSAGE
        phase = "asking"
        if prior_pending is not None:
            message += " Your previous unapproved plan is unchanged."
            phase = "plan"
        data = {"assistant_text": message, "phase": phase}
        transcript.append(_assistant_turn(data))
        converged = await _persist_custom_film_cas(
            conversation_id, tenant_id, transcript, state, phase, expected_state
        )
        if converged:
            return converged
        return ChatTurnResponse(
            conversation_id=conversation_id,
            assistant_text=message,
            ready_to_create=False,
            phase=phase,
        )

    try:
        quote_inputs = await _estimate_custom_film_plan(
            compiled.internal_plan,
            total_duration_seconds=total_duration_seconds,
        )
        quote_inputs["max_spend"] = round(
            requested_budget_cap
            if requested_budget_cap is not None
            else float(quote_inputs["totals"]["estimated_cost"]),
            2,
        )
        quote_rows = {row["section_id"]: row for row in quote_inputs["sections"]}
        for section in compiled.internal_plan["sections"]:
            row = quote_rows[section["section_id"]]
            section["estimated_media"] = {
                "still_images": row["still_images"],
                "animation_clips": row["animation_clips"],
                "voice_tracks": row["voice_tracks"],
                # EstimatedMedia's canonical JSON contract serializes Decimal
                # durations as strings; preserve that shape so the persisted
                # normalized revision hashes identically to the approved plan.
                "duration_seconds": str(row["duration_seconds"]),
            }
        for display_section in compiled.display_plan["sections"]:
            row = quote_inputs["sections"][display_section["order"] - 1]
            display_section["expected_media"] = (
                f"{row['still_images']} stills, {row['animation_clips']} animated "
                f"clips, and {row['voice_tracks']} voice "
                f"track{'s' if row['voice_tracks'] != 1 else ''}."
            )
        compiled.display_plan["byok_notice"] = (
            "Any production uses only your connected AI accounts."
        )
        compiled.display_plan["status"] = (
            "Planning is complete; generation has not started. Review the one "
            "itemized estimate below and explicitly approve this exact version."
        )
        from custom_film_orchestration import compile_approved_orchestration

        orchestration = compile_approved_orchestration(
            compiled.internal_plan,
            quote_inputs,
            compiled.planner_proposal,
        )
        quote_inputs["orchestration"] = orchestration
        if isinstance(orchestration.get("resolved_plan"), dict):
            # The provider generation tier remains independently quoted. This
            # immutable approval field owns only the deterministic delivery
            # canvas and is hashed with the rest of the quote.
            quote_inputs["finishing_canvas"] = {
                **copy.deepcopy(_CUSTOM_FILM_REMOTION_FINISHING_CANVAS),
                "orchestration_contract_hash": orchestration["contract_hash"],
                "story_identity": orchestration["story_identity"],
                "recipe_hash": orchestration["recipe_hash"],
            }
        from custom_film_contract import (
            approval_binding_hash,
            canonical_hash,
            plan_hash,
        )

        current_plan_hash = plan_hash(compiled.internal_plan)
        current_approval_hash = approval_binding_hash(
            current_plan_hash,
            quote_inputs,
        )
    except Exception as exc:  # noqa: BLE001 - estimation must fail before approval
        logger.warning("custom-film estimate failed: %s", exc)
        message = (
            "I couldn't produce a safe estimate for that plan. Nothing was "
            "approved, generated, or charged; please try the edit again."
        )
        data = {"assistant_text": message, "phase": "plan"}
        transcript.append(_assistant_turn(data))
        converged = await _persist_custom_film_cas(
            conversation_id, tenant_id, transcript, state, "plan", expected_state
        )
        if converged:
            return converged
        return ChatTurnResponse(
            conversation_id=conversation_id,
            assistant_text=message,
            ready_to_create=False,
            phase="plan",
        )

    # Novelty is classified now for later save eligibility, but M2-2 does not
    # expose or persist a recipe and never shows a save action. A lookup failure
    # fails closed to "unverified" instead of masquerading as novel.
    novelty_payload: dict[str, Any]
    try:
        novelty = await classify_plan_novelty(tenant_id, compiled, manifest)
        novelty_payload = {
            "is_novel": novelty.is_novel,
            **(
                {
                    "duplicate_kind": novelty.duplicate_kind,
                    "duplicate_id": novelty.duplicate_id,
                }
                if not novelty.is_novel
                else {}
            ),
        }
    except Exception as exc:  # noqa: BLE001 - no Save offer is safer than guessing
        logger.warning("custom-film novelty lookup failed: %s", exc)
        novelty_payload = {"is_novel": None, "status": "unverified"}

    state["mode"] = "custom_film"
    approval_cards = _custom_film_approval_cards(
        quote_inputs,
        compiled.display_plan,
    )
    budget_blocked = approval_cards is None
    state["pending_custom_film_plan"] = {
        "internal_plan": compiled.internal_plan,
        "display_plan": compiled.display_plan,
        "planner_proposal": compiled.planner_proposal,
        "plan_hash": current_plan_hash,
        "quote_inputs": quote_inputs,
        "budget_cap_source": ("user" if requested_budget_cap is not None else "quote"),
        "recipe_signature": compiled.recipe_signature,
        "recipe_hash": canonical_hash(compiled.normalized_recipe),
        "novelty": novelty_payload,
        "status": "budget_blocked" if budget_blocked else "awaiting_approval",
    }
    if not budget_blocked:
        state["pending_custom_film_plan"]["approval_hash"] = current_approval_hash
    assistant_text = (
        _custom_film_plan_text(compiled.display_plan)
        + "\n\n"
        + _custom_film_estimate_text(quote_inputs)
    )
    if budget_blocked:
        assistant_text += (
            "\n\nThis plan is estimated at "
            f"${float(quote_inputs['totals']['estimated_cost']):.2f}, which is "
            f"above your ${float(quote_inputs['max_spend']):.2f} cap. Nothing "
            "is approved or generated. Raise the cap to at least the estimate, "
            "or ask me to reduce the media plan; I will issue a new exact quote."
        )
    data = {
        "assistant_text": assistant_text,
        "ready_to_create": False,
        "phase": "plan",
    }
    if approval_cards is not None:
        data["cards"] = approval_cards
    transcript.append(_assistant_turn(data))
    converged = await _persist_custom_film_cas(
        conversation_id, tenant_id, transcript, state, "plan", expected_state
    )
    if converged:
        return converged
    return ChatTurnResponse(
        conversation_id=conversation_id,
        assistant_text=assistant_text,
        cards=approval_cards,
        plan=None,
        ready_to_create=False,
        phase="plan",
    )


async def _seed_producer(conversation_id, tenant_id, state, seed_text):
    """Hand off into the producer seeded with a chosen/typed idea: start a fresh
    producer transcript and run one intake turn."""
    state["mode"] = "producer"
    state["onboarding_step"] = "done"
    client = await _resolve_producer_client(tenant_id)
    transcript = [{"role": "user", "content": seed_text}]
    if client is None:
        transcript.append(
            _assistant_turn({"assistant_text": _NO_KEY_PRODUCER_MSG, "phase": "asking"})
        )
        await _persist(conversation_id, tenant_id, transcript, state, "asking")
        return ChatTurnResponse(
            conversation_id=conversation_id,
            assistant_text=_NO_KEY_PRODUCER_MSG,
            phase="asking",
        )
    # THE channel-identity pool brief (checklist P2) goes FIRST here too —
    # this is the onboarding hand-off into the SAME producer chat_turn drives,
    # so it must open with the same precedence law from turn one.
    brief = (
        await _identity_pool_brief(tenant_id)
        + _creator_brief(state)
        + await _modeled_runtime_hint(tenant_id)
        + await _channel_intel_brief(tenant_id)
        + await _competitor_winners_brief(tenant_id)
        + await _loop_brief(tenant_id)
        + await _reference_brief(state, state.get("pending_reference_url"))
        + _dna_brief(state)
        + await _profile_state_brief(tenant_id)
        + await _style_presets_brief(tenant_id)
        + await _visual_styles_brief(tenant_id)
        + await _assets_brief(tenant_id, state)
    )
    data = call_producer(transcript, build_system_prompt(brief), client=client)
    await _stamp_length_default(data, tenant_id, transcript)
    await _annotate_style_recommendation(data, tenant_id, state)
    await _stamp_plan_estimate(data)
    assistant_text = await _apply_and_merge_profile_ops(data, tenant_id, state, None)
    _maybe_attach_style_draft_card(data, state)
    _maybe_attach_quality_rules_draft_card(data, state)
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
        lines.append(
            f"**{i + 1}. {badge}{idea.get('title')}**\n{why}{(chr(10) + srcline) if srcline else ''}"
        )
        opts.append(
            {
                "value": str(i),
                "label": (idea.get("title") or "Idea")[:70],
                "hint": why[:140],
            }
        )
    niche = state.get("niche_angle")
    n = len(ideas)
    intro = (
        f"Here are **{n} ideas for “{niche}”**, modeled on what's winning:\n\n"
        if niche
        else f"Here are **{n} ideas I'd model**, and why:\n\n"
    )
    text = (
        intro
        + "\n\n".join(lines)
        + "\n\nTap one and I'll start building it — or just type your own idea below."
    )
    card = {
        "id": "idea_choice",
        "label": "Pick one to build",
        "type": "single",
        "options": opts,
    }
    return await _ob_reply(
        conversation_id, tenant_id, transcript, state, text, cards=[card]
    )


async def _finish_onboarding_dna_note(tenant_id) -> tuple[str, Optional[dict]]:
    """C45 (P4.1f): surface the Channel-DNA learn pass the "channel" step
    kicked off, right at this natural end-of-flow moment — the same spot
    competitor results already get folded in just above. Reuses C42's exact
    `_build_dna_digest_card` builder so onboarding and the "show the channel
    digest" chat intent render the IDENTICAL card — one digest, both
    surfaces, no second renderer to keep in sync.

    Returns (note_text, card_or_None). Both empty when no channel was ever
    connected (channel step was skipped, or connect_youtube failed) — there's
    nothing to report. `note_text` is a suffix to append to whichever
    message this turn already shows; `card` (when not None) is meant to be
    appended to that same turn's `cards` list."""
    row = await fetch_one(
        "SELECT channel_identity FROM channel_profiles WHERE tenant_id=$1",
        str(tenant_id),
    )
    ident = _as_dict((row or {}).get("channel_identity"))
    run = ident.get("_last_run") if isinstance(ident.get("_last_run"), dict) else None
    if not run:
        return "", None

    from channel_dna import is_learning as _dna_is_learning

    if await _dna_is_learning(str(tenant_id)):
        return (
            "\n\n🧬 Still learning your channel's voice, hooks, and structure in the background — "
            'say **"show the channel digest"** in a bit and I\'ll lay out everything.',
            None,
        )

    preferences = await _list_preferences(tenant_id, video_id=None)
    proposed_patterns = await _proposed_channel_patterns(tenant_id)
    card = _build_dna_digest_card(ident, run, preferences, proposed_patterns)
    return (
        "\n\n🧬 I also learned your channel's voice, hooks, and structure — see below.",
        card,
    )


async def _finish_onboarding(
    conversation_id, tenant_id, transcript, state, background_tasks
):
    """Mark onboarding done, then help the creator MODEL their competitors: summarize
    the winning format and propose concrete ways to make it their OWN niche. They
    pick a direction (the 'modeling' step) -> we pitch 3 ideas in that niche. Falls
    back gracefully if there's no recent competitor data yet."""
    try:
        from routes.onboarding import complete_onboarding

        await complete_onboarding(tenant_id=tenant_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("onboarding: complete failed: %s", e)

    dna_note, dna_card = await _finish_onboarding_dna_note(tenant_id)

    angles = await _propose_modeling_angles(tenant_id, state)
    if angles and angles.get("angles"):
        state["modeling"] = angles
        state["mode"] = "onboarding"
        state["onboarding_step"] = "modeling"
        a = angles["angles"]
        lines = [
            f"**{i + 1}. {x.get('label')}** — {x.get('description', '')}"
            for i, x in enumerate(a)
        ]
        text = (
            "You're all set! 🎉 Here's what's working on your competitors: "
            + (angles.get("format_summary") or "strong, repeatable hooks")
            + "\n\nThere are a few ways to make this **your own** — pick a direction (or just type the niche "
            "you want to own):\n\n" + "\n".join(lines) + dna_note
        )
        opts = [
            {
                "value": str(i),
                "label": (x.get("label") or "Angle")[:60],
                "hint": (x.get("description") or "")[:140],
            }
            for i, x in enumerate(a)
        ]
        card = {
            "id": "modeling_angle",
            "label": "How do you want to model it?",
            "type": "single",
            "options": opts,
        }
        cards = [card, dna_card] if dna_card else [card]
        return await _ob_reply(
            conversation_id, tenant_id, transcript, state, text, cards=cards
        )

    # No recent competitor data yet — hand off honestly (never "ask me").
    state["mode"] = "producer"
    state["onboarding_step"] = "done"
    text = (
        "You're all set! 🎉 I pulled your competitor channel(s), but couldn't find enough of their "
        "recent videos to model from yet — they may still be importing. Paste another channel under "
        "Competitors, or just tell me what you'd like to make and I'll run with it."
        + dna_note
    )
    cards = [dna_card] if dna_card else None
    fresh = [
        _assistant_turn({"assistant_text": text, "phase": "asking", "cards": cards})
    ]
    await _persist(conversation_id, tenant_id, fresh, state, "asking")
    return ChatTurnResponse(
        conversation_id=conversation_id,
        assistant_text=text,
        phase="asking",
        cards=cards,
    )


async def _handle_onboarding(
    body, conversation_id, tenant_id, transcript, state, background_tasks
):
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
            conversation_id,
            tenant_id,
            transcript,
            state,
            "Welcome — let's get you set up in under a minute. First, what brings you here?",
            cards=[ONBOARDING_INTENT_CARD],
        )

    if step == "intent":
        intent = sel.get("intent") or _guess_intent(msg)
        if not intent:
            return await _ob_reply(
                conversation_id,
                tenant_id,
                transcript,
                state,
                "No worries — just pick one so I can tailor things:",
                cards=[ONBOARDING_INTENT_CARD],
            )
        state["intent"] = intent
        # New tenants need a generation key before any Claude step; existing
        # ones (already keyed) skip straight to setup.
        if not await _has_generation_key(tenant_id):
            state["onboarding_step"] = "key"
            lead = (
                "A storyteller — love it. "
                if intent == "stories"
                else "Nice — let's put your channel on autopilot. "
            )
            return await _ob_reply(
                conversation_id,
                tenant_id,
                transcript,
                state,
                lead + _KEY_PROMPT,
                cards=[_secure_key_card(optional=False)],
            )
        if intent == "stories":
            state["onboarding_step"] = "channel"
            return await _ob_reply(
                conversation_id,
                tenant_id,
                transcript,
                state,
                "A storyteller — love it. If you have a channel, paste its URL so I can match its vibe "
                "(or say “skip” and we'll start fresh).",
            )
        state["onboarding_step"] = "goals"
        return await _ob_reply(
            conversation_id,
            tenant_id,
            transcript,
            state,
            "Nice — let's put your channel on autopilot. What should I handle for you?",
            cards=[ONBOARDING_GOALS_CARD],
        )

    if step == "key":
        # Preferred path: the secure box already saved + validated the key via
        # /api/chat/onboarding-key, so the raw key never entered this turn. We get
        # a benign selection {secure_key: "saved", key_provider: ...} instead.
        if sel.get("secure_key") == "saved" or (
            not msg and await _has_generation_key(tenant_id)
        ):
            provider = sel.get("key_provider") or state.get("key_provider") or "kie"
            state["key_provider"] = provider
            ack = "✅ You're powered up. "
            # If they led with a Claude key, the fast text path is already on —
            # no point offering it again. Kie keys get the optional Claude upgrade.
            if provider == "claude":
                return await _after_key_setup(
                    conversation_id, tenant_id, transcript, state, ack
                )
            state["onboarding_step"] = "key_claude"
            return await _ob_reply(
                conversation_id,
                tenant_id,
                transcript,
                state,
                ack + _CLAUDE_OFFER,
                cards=[_secure_key_card(optional=True)],
            )
        # Fallback: a key arrived as composer text (legacy paste-in-chat). Still
        # works, but route it through the same save + validate so nothing changes.
        raw = (body.message or "").strip()
        if not raw:
            # They tapped the link but haven't pasted yet — re-show the ask + box.
            return await _ob_reply(
                conversation_id,
                tenant_id,
                transcript,
                state,
                _KEY_PROMPT,
                cards=[_secure_key_card(optional=False)],
            )
        slot, val = _pick_key(raw)
        if not slot:
            return await _ob_reply(
                conversation_id,
                tenant_id,
                transcript,
                state,
                (val or "Paste the whole key — it's a long string with no spaces.")
                + "\n\n"
                + _KEY_PROMPT,
                cards=[_secure_key_card(optional=False)],
            )
        from vault import set_secret, test_api_key

        await set_secret(
            slot, val, tenant_id=tenant_id, description="Onboarding generation key"
        )
        result = await test_api_key(slot, tenant_id)
        if not result.get("success"):
            return await _ob_reply(
                conversation_id,
                tenant_id,
                transcript,
                state,
                f"That key didn't go through — {result.get('message') or 'please double-check it'}. "
                "Copy the whole key and paste it again 👇",
                cards=[_secure_key_card(optional=False)],
            )
        state["key_provider"] = "claude" if slot == "anthropic_api_key" else "kie"
        ack = f"✅ You're powered up — {result.get('message')}. "
        if state["key_provider"] == "claude":
            return await _after_key_setup(
                conversation_id, tenant_id, transcript, state, ack
            )
        state["onboarding_step"] = "key_claude"
        return await _ob_reply(
            conversation_id,
            tenant_id,
            transcript,
            state,
            ack + _CLAUDE_OFFER,
            cards=[_secure_key_card(optional=True)],
        )

    if step == "key_claude":
        # Optional Claude upgrade. Secure box → {secure_key: "saved"}; Skip →
        # {secure_key: "skip"}. A pasted Claude key (fallback) is saved here too.
        if sel.get("secure_key") == "saved":
            return await _after_key_setup(
                conversation_id,
                tenant_id,
                transcript,
                state,
                "✅ Claude connected — your text will fly now. ",
            )
        if sel.get("secure_key") == "skip" or (msg and msg.lower() in _SKIP_WORDS):
            return await _after_key_setup(
                conversation_id,
                tenant_id,
                transcript,
                state,
                "No problem — Kie's got you covered. ",
            )
        raw = (body.message or "").strip()
        if raw:
            slot, val = _pick_key(raw)
            if slot == "anthropic_api_key":
                from vault import set_secret, test_api_key

                await set_secret(
                    slot, val, tenant_id=tenant_id, description="Onboarding Claude key"
                )
                result = await test_api_key(slot, tenant_id)
                if result.get("success"):
                    state["key_provider"] = "claude"
                    return await _after_key_setup(
                        conversation_id,
                        tenant_id,
                        transcript,
                        state,
                        "✅ Claude connected — your text will fly now. ",
                    )
            return await _ob_reply(
                conversation_id,
                tenant_id,
                transcript,
                state,
                "That didn't look like a Claude key (they start with `sk-ant-`). Paste it in the "
                "secure box below, or skip — Kie already does everything.",
                cards=[_secure_key_card(optional=True)],
            )
        return await _ob_reply(
            conversation_id,
            tenant_id,
            transcript,
            state,
            _CLAUDE_OFFER,
            cards=[_secure_key_card(optional=True)],
        )

    if step == "goals":
        goals = sel.get("goals")
        if isinstance(goals, str):
            goals = [goals]
        state["goals"] = goals or ["all"]
        state["onboarding_step"] = "channel"
        return await _ob_reply(
            conversation_id,
            tenant_id,
            transcript,
            state,
            "Got it. Now connect your channel — paste your YouTube channel URL so I can learn what "
            "works for your audience (or say “skip”).",
        )

    if step == "channel":
        if msg and msg.lower() not in _SKIP_WORDS:
            try:
                from routes.onboarding import YouTubeConnect, connect_youtube

                res = await connect_youtube(
                    YouTubeConnect(channel_url=msg),
                    background_tasks,
                    tenant_id=tenant_id,
                )
                state["channel"] = (res or {}).get("channel_name") or msg
                ack = f"Connected **{state['channel']}** — I'll study it in the background. "
                # C45: connect_youtube schedules the C41 Channel-DNA learn pass
                # right after the import (own-channel mode) and tells us via
                # `dna_learning` whether it actually fired — money-honest ack
                # when it did, a non-blocking "add a key" hint when it didn't
                # (C04 precedent: never block onboarding on a missing key).
                dna_status = (res or {}).get("dna_learning")
                if dna_status == "started":
                    ack += (
                        "I'll also learn its voice, hooks, and structure (~$0.10-0.30 of your API "
                        "budget) — say “show the channel digest” once it's done. "
                    )
                elif dna_status == "needs_key":
                    ack += (
                        "Add a generation key (Settings → Keys) and I can also learn its voice "
                        "and structure automatically. "
                    )
            except Exception as e:  # noqa: BLE001
                logger.warning("onboarding: connect_youtube failed: %s", e)
                ack = "I couldn't read that channel just now, but no worries — we can add it later. "
        else:
            ack = "No problem, skipping that. "
        state["onboarding_step"] = "competitors"
        return await _ob_reply(
            conversation_id,
            tenant_id,
            transcript,
            state,
            ack
            + "Now paste 1-3 channels you compete with or admire (URLs or @handles) — I'll pull "
            "winning ideas from them. Or say “skip”.",
        )

    if step == "competitors":
        urls = _parse_urls(msg) if msg.lower() not in _SKIP_WORDS else []
        if urls:
            state["competitors"] = urls[:3]
            try:
                from routes.onboarding import CompetitorAnalyze, analyze_competitors

                res = await analyze_competitors(
                    CompetitorAnalyze(channel_urls=urls[:3]),
                    background_tasks,
                    tenant_id=tenant_id,
                )
                state["competitor_job"] = (res or {}).get("job_id")
                ack = (
                    f"On it — analyzing {len(urls[:3])} channel(s) in the background. "
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("onboarding: analyze_competitors failed: %s", e)
                ack = "I'll line those up. "
        else:
            ack = "No competitors for now — you can add them anytime. "
        state["onboarding_step"] = "connect_yt"
        return await _ob_reply(
            conversation_id,
            tenant_id,
            transcript,
            state,
            ack + "\n\n" + _CONNECT_YT_TEXT,
            cards=[ONBOARDING_CONNECT_YT_CARD],
        )

    if step == "connect_yt":
        # Either choice advances — analytics is optional and the OAuth callback
        # already stored the tokens if they connected. "connected" arrives via the
        # resume turn ChatHome sends after Google returns to /?connected=yt.
        state["youtube_oauth"] = sel.get("connect_yt") or "skip"
        state["onboarding_step"] = "connect_drive"
        return await _ob_reply(
            conversation_id,
            tenant_id,
            transcript,
            state,
            _CONNECT_DRIVE_TEXT,
            cards=[ONBOARDING_CONNECT_DRIVE_CARD],
        )

    if step == "connect_drive":
        state["drive_oauth"] = sel.get("connect_drive") or "skip"
        state["onboarding_step"] = "upsell"
        return await _ob_reply(
            conversation_id,
            tenant_id,
            transcript,
            state,
            _UPSELL_TEXT,
            cards=[ONBOARDING_UPSELL_CARD],
        )

    if step == "upsell":
        choice = sel.get("upsell") or (
            "tell_more" if "more" in msg.lower() else "carry_on"
        )
        if choice == "tell_more" and not state.get("upsell_expanded"):
            state["upsell_expanded"] = True
            return await _ob_reply(
                conversation_id,
                tenant_id,
                transcript,
                state,
                _UPSELL_DETAIL,
                cards=[
                    {
                        "id": "upsell",
                        "label": "",
                        "type": "single",
                        "options": [
                            {"value": "carry_on", "label": "Got it — let's create"}
                        ],
                    }
                ],
            )
        return await _finish_onboarding(
            conversation_id, tenant_id, transcript, state, background_tasks
        )

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
            return await _ob_reply(
                conversation_id,
                tenant_id,
                transcript,
                state,
                "Pick a direction above, or just type the niche you want to own.",
            )
        state["niche_angle"] = niche
        await _save_creator_brief(
            tenant_id, state
        )  # persist niche before any producer handoff
        ideas = await _generate_competitor_ideas(tenant_id, state, niche=niche)
        if ideas:
            return await _present_ideas_turn(
                conversation_id, tenant_id, transcript, state, ideas
            )
        state["mode"] = "producer"
        state["onboarding_step"] = "done"
        text = (
            f"Love it — {niche}. I couldn't pull enough recent competitor data to pitch exact ideas right now, "
            "but tell me a rough topic and I'll build it in that lane."
        )
        fresh = [_assistant_turn({"assistant_text": text, "phase": "asking"})]
        await _persist(conversation_id, tenant_id, fresh, state, "asking")
        return ChatTurnResponse(
            conversation_id=conversation_id, assistant_text=text, phase="asking"
        )

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
                    f'Make this video: "{idea.get("title")}". '
                    f"Angle: {(idea.get('reasoning') or '').strip()} "
                    f"Suggested structure: {(idea.get('script_structure') or '').strip()}"
                ).strip()
                return await _seed_producer(conversation_id, tenant_id, state, seed)
        if msg:  # typed their own idea instead of picking one
            return await _seed_producer(conversation_id, tenant_id, state, msg)
        return await _ob_reply(
            conversation_id,
            tenant_id,
            transcript,
            state,
            "Tap one of the ideas above, or just type your own idea and I'll build it.",
        )

    # Unknown step — recover by handing off to the producer.
    state["mode"] = "producer"
    return await _ob_reply(
        conversation_id,
        tenant_id,
        transcript,
        state,
        "All set — what should we make first?",
        phase="asking",
    )


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
    if any(
        v in m
        for v in ("build", "rebuild", "analyze", "analyse", "learn", "study", "extract")
    ):
        return "build"
    if any(
        v in m for v in ("what", "whats", "what's", "show", "tell", "who", "describe")
    ):
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

    extra = {
        "research_approach": ident.get("research_depth"),
        "visual_format": ident.get("inferred_format"),
    }
    for emoji, label, key in (
        ("🔍", "Research", "research_approach"),
        ("📼", "Video visuals", "visual_format"),
        ("🖼️", "Thumbnail style", "thumbnail_style"),
    ):
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
        section(
            "💬 **More real lines from his videos:**\n"
            + "\n".join(f"> {q}" for q in rq[:6])
        )

    return "\n".join(out)


async def _plain_reply(conversation_id, tenant_id, transcript, state, user_msg, text):
    if user_msg:
        transcript.append({"role": "user", "content": user_msg})
    transcript.append(_assistant_turn({"assistant_text": text, "phase": "asking"}))
    await _persist(conversation_id, tenant_id, transcript, state, "asking")
    return ChatTurnResponse(
        conversation_id=conversation_id, assistant_text=text, phase="asking"
    )


async def _handle_build_identity(
    conversation_id, tenant_id, transcript, state, user_msg, background_tasks
):
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
    text = (
        "🔍 On it — analyzing his **top 3 videos** for voice, research style, real quotes, and "
        "thumbnail format. This takes about a minute. Say **“show his identity”** in a moment and "
        "I'll lay out the full locked profile."
    )
    return await _plain_reply(
        conversation_id, tenant_id, transcript, state, user_msg, text
    )


async def _handle_show_identity(
    conversation_id, tenant_id, transcript, state, user_msg
):
    row = await fetch_one(
        "SELECT channel_identity, youtube_channel_name FROM channel_profiles WHERE tenant_id=$1",
        str(tenant_id),
    )
    ident = _as_dict((row or {}).get("channel_identity"))
    if not ident or not ident.get("voice_tone"):
        text = (
            "I haven't learned this channel yet. Say “build his identity” and I'll analyze "
            "the channel's top videos to work out his voice, format, and style."
        )
        return await _plain_reply(
            conversation_id, tenant_id, transcript, state, user_msg, text
        )
    name = (row or {}).get("youtube_channel_name") or "this channel"
    body = _format_identity(
        ident, f"Here's what I've learned about **{name}** (from his own top videos):"
    )
    body += "\n\nWant me to refresh it from his latest top videos? Say “rebuild his identity.”"
    return await _plain_reply(
        conversation_id, tenant_id, transcript, state, user_msg, body
    )


# --- C42 (P4.1c): "learn this channel" chat front door + confirmable digest -
#
# Broader than `_identity_intent`/`_handle_build_identity` above, which only
# ever run identity_builder (one learner). This runs the FULL C41 orchestrator
# (channel_dna.learn_channel: optional import -> identity_builder -> optional
# script template -> confidence-gated format lock -> optional reference video)
# and, once it lands, surfaces a confirmable digest card the creator can act
# on: keep (default — the values are already saved, C41's write-then-review
# design), revert a field (channel_dna.revert_field, C40's history undo), or
# correct one in free text (becomes a standing director preference, same
# `_save_preference` C15c's remember op writes through — C44 will teach the
# full LLM-classified remember/forget routing onto this specific ask; today
# it's the deterministic form-post version of the same write).

_LEARN_CHANNEL_VERBS = ("learn", "study", "analyze", "analyse", "manage", "managing")


def _learn_channel_intent(msg: str) -> bool:
    """Detect the C42 'learn this channel' ask: 'learn this channel: <url>',
    'learn my channel', 'here's a channel I'm managing <url>', and close
    variants — always mentions "channel" plus a learn/study/manage verb.
    Deliberately a SIBLING of `_identity_intent`, not a rewrite of it:
    `_identity_intent`'s "voice/style" wording keeps meaning "just show/rebuild
    the identity_builder view"; this one means "run every learner and show me
    the full digest," so a message matching both (e.g. "learn my channel's
    voice") should get the broader treatment — callers check this FIRST."""
    m = (msg or "").lower()
    if "channel" not in m:
        return False
    return any(v in m for v in _LEARN_CHANNEL_VERBS)


def _extract_channel_url(msg: str) -> Optional[str]:
    """Pull a YouTube channel URL/handle out of a learn-channel ask, reusing
    onboarding's own identifier parser as the validity check so this and
    channel_dna._run_import (which calls the same parser) always agree on
    what counts as a channel reference. None means "no URL in this message"
    -> learn_channel learns from whatever's already imported."""
    from routes.onboarding import _extract_channel_id_from_url

    for token in re.findall(r"\S+", msg or ""):
        cleaned = token.strip("():,.\"'")
        if _extract_channel_id_from_url(cleaned):
            return cleaned
    return None


async def _handle_learn_channel(
    conversation_id, tenant_id, transcript, state, user_msg, background_tasks
):
    """Ack now, run channel_dna.learn_channel in the background — mirrors
    `_handle_build_identity`'s exact ack-now pattern (Firecrawl scrapes plus
    several Claude calls can exceed a chat turn's gateway window). Money
    honesty (checklist's explicit requirement): this spends the tenant's own
    Claude/Firecrawl credits, so the ack STATES the cost even though — per
    the existing research/SEO-verb precedent this mirrors — it doesn't gate
    behind a confirm card."""
    channel_url = _extract_channel_url(user_msg)

    async def _job():
        try:
            from channel_dna import learn_channel

            await learn_channel(str(tenant_id), channel_url=channel_url)
        except Exception as e:  # noqa: BLE001
            logger.warning("chat: background learn_channel failed: %s", e)

    background_tasks.add_task(_job)
    text = (
        "🧬 On it — analyzing the channel, this takes a couple of minutes; ~$0.10-0.30 of your "
        "API budget. Say **“show the channel digest”** in a bit and I'll lay out everything I "
        "learned, with a Revert on anything that doesn't look right."
    )
    return await _plain_reply(
        conversation_id, tenant_id, transcript, state, user_msg, text
    )


_DNA_DIGEST_INTENT_PHRASES = (
    "what did you learn",
    "what you learned",
    "show me what you learned",
    "show the digest",
    "show channel digest",
)


def _dna_digest_intent(msg: str) -> bool:
    m = (msg or "").lower()
    if any(p in m for p in _DNA_DIGEST_INTENT_PHRASES):
        return True
    return "digest" in m and any(t in m for t in ("channel", "dna", "learn"))


_DNA_DIGEST_FIELDS: list[tuple[str, str]] = [
    ("voice_tone", "Voice"),
    ("cadence", "Cadence"),
    ("hook_style", "Hook"),
    ("structure", "Structure"),
    ("research_approach", "Research"),
    ("visual_format", "Visual format"),
    ("thumbnail_style", "Thumbnail style"),
    ("reference_video_style", "Reference video style"),
]

_DNA_LEARNER_LABELS: dict[str, str] = {
    "import_channel_videos": "Importing channel videos",
    "identity_builder": "Voice, hooks & structure",
    "script_template": "Example script format",
    "channel_format": "Visual format lock",
    "reference_video": "Reference video style",
    "pattern_analysis": "Analytics patterns",
}

# C44 (P4.1e corrections loop): cheap keyword match between a learned identity
# field and the tenant's active channel-scope standing preferences, so the
# digest can flag "this learned value has a standing correction on file"
# instead of showing a field as if nothing had overridden it. Deliberately NOT
# NLP (checklist's own explicit hedge: "keyword/field-tag match is fine; don't
# build NLP") — a correction that doesn't happen to use one of these words
# (e.g. "no stock-footage b-roll" for visual_format, which DOES match here via
# "b-roll"/"footage", but plenty of real phrasing won't) will miss the
# per-field flag. That's why `standing_directions` (the full active list,
# unconditional) is ALSO always attached to the card below — nothing is ever
# silently hidden just because the keyword match missed it.
_FIELD_OVERRIDE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "voice_tone": ("voice", "tone"),
    "cadence": ("cadence", "pace", "pacing", "rhythm"),
    "hook_style": ("hook",),
    "structure": ("structure",),
    "research_approach": ("research",),
    "visual_format": ("visual", "b-roll", "broll", "footage", "animation"),
    "thumbnail_style": ("thumbnail",),
    "reference_video_style": ("reference video", "reference"),
}


def _match_preference_override(field_key: str, pref_texts: list[str]) -> Optional[str]:
    """The most recent (pref_texts is already newest-first) active standing
    preference whose text mentions this field's keyword(s), or None. See
    `_FIELD_OVERRIDE_KEYWORDS`'s docstring for why this is intentionally a
    cheap substring match, not semantic matching."""
    keywords = _FIELD_OVERRIDE_KEYWORDS.get(field_key)
    if not keywords:
        return None
    for text in pref_texts:
        low = text.lower()
        if any(kw in low for kw in keywords):
            return text
    return None


async def _proposed_channel_patterns(tenant_id) -> list[dict]:
    """Shared fetch for both digest-card call sites (C42's onboarding-finish
    note and the "show the channel digest" intent) — one implementation,
    fail-soft (an empty list on any DB hiccup never blocks the digest itself
    from rendering)."""
    import channel_patterns

    try:
        return await channel_patterns.list_patterns(str(tenant_id), status="proposed")
    except Exception as e:  # noqa: BLE001
        logger.warning("chat: fetching proposed channel_patterns failed: %s", e)
        return []


def _pattern_evidence_summary(evidence: dict) -> str:
    """One short line rendering a channel_patterns row's evidence — the
    "why" a proposed pattern exists, so a creator can confirm/retire from
    an informed read instead of a bare claim sentence. Additive/best-effort:
    an evidence shape from a future source (launch_analysis, manual) that
    doesn't carry these exact keys just renders "" rather than raising."""
    metric = evidence.get("metric")
    delta = evidence.get("delta_pct")
    cohort = evidence.get("cohort_size")
    if metric is None or delta is None:
        return ""
    return (
        f"{metric}: {delta:+.1f}% vs. channel median (n={cohort})"
        if cohort
        else f"{metric}: {delta:+.1f}% vs. channel median"
    )


def _build_dna_digest_card(
    identity: dict,
    run: Optional[dict],
    preferences: Optional[list[dict]] = None,
    patterns: Optional[list[dict]] = None,
) -> dict[str, Any]:
    """The digest card checklist C42 asks for: per-learner sections (from
    the persisted `_last_run` report) plus the key identity fields with
    their provenance (C40's `_sources`) and a Revert affordance wherever
    C40's `_history` has something to revert TO. No string-match branches —
    the frontend keys off `cardKind()`'s "channel_dna_digest" entry, same
    lookup-table pattern S9-3 established for every other card kind.

    C46e adds `patterns`: this tenant's still-`proposed` channel_patterns
    rows (from the import-time analytics learner, or a future launch-time
    one) rendered with Confirm/Retire actions — nothing in that list has
    taken effect yet; confirming is the ONLY thing that does (OR-6 expanded)."""
    from channel_dna_meta import field_provenance, latest_history_index_for_field

    learners_raw = (run or {}).get("learners") or {}
    learners = [
        {
            "name": name,
            "label": _DNA_LEARNER_LABELS.get(name, name.replace("_", " ").title()),
            "status": (info or {}).get("status") or "skipped",
            "summary": (info or {}).get("summary") or "",
        }
        for name, info in learners_raw.items()
    ]
    any_failed = any(l["status"] == "failed" for l in learners)
    header = (
        "Here's what I could learn about your channel — a step or two hit a snag, so this is a "
        "partial picture (see below); ask me to try again any time."
        if any_failed
        else "Here's what I learned about your channel:"
    )

    # C44: channel-scope standing preferences (director_preferences, C15c) —
    # the SAME rows now feeding every generation prompt via
    # identity._standing_preferences_block — so the digest can show a
    # creator's corrections aren't just sitting in a table somewhere but are
    # actually in effect. Newest-first, same order the preferences chat
    # surfaces already number them in.
    pref_texts = [p["text"] for p in (preferences or []) if p.get("text")]

    fields = []
    for key, label in _DNA_DIGEST_FIELDS:
        val = identity.get(key)
        if not val:
            continue
        prov = field_provenance(identity, key) or {}
        revertable = latest_history_index_for_field(identity, key) is not None
        overridden_by = _match_preference_override(key, pref_texts)
        fields.append(
            {
                "field": key,
                "label": label,
                "value": _fmt_field(val),
                "learner": prov.get("learner"),
                "at": prov.get("at"),
                "revertable": revertable,
                # C44: "" absent by default (additive key — an older frontend
                # simply never reads it); set only when a standing preference's
                # text keyword-matched this field, per the hedge above.
                "overridden_by": overridden_by,
            }
        )

    pattern_rows = [
        {
            "id": str(p.get("id") or ""),
            "pattern": p.get("pattern") or "",
            "polarity": p.get("polarity") or "anti",
            "source": p.get("source") or "",
            "evidence_summary": _pattern_evidence_summary(p.get("evidence") or {}),
        }
        for p in (patterns or [])
        if p.get("id")
    ]

    return {
        "id": "channel_dna_digest",
        "label": "Channel DNA digest",
        "type": "single",
        "options": [],
        "header": header,
        "learners": learners,
        "fields": fields,
        "any_failed": any_failed,
        # C44: every active channel-scope standing preference, regardless of
        # whether it keyword-matched a field above — the footer section a
        # cheap match can't fully cover (see _FIELD_OVERRIDE_KEYWORDS docstring).
        "standing_directions": pref_texts,
        # C46e: proposed (not-yet-confirmed) channel_patterns rows. Optional/
        # additive — an older frontend build simply never reads this key.
        "patterns": pattern_rows,
    }


async def _handle_show_channel_digest(
    conversation_id, tenant_id, transcript, state, user_msg
):
    row = await fetch_one(
        "SELECT channel_identity FROM channel_profiles WHERE tenant_id=$1",
        str(tenant_id),
    )
    ident = _as_dict((row or {}).get("channel_identity"))
    run = ident.get("_last_run") if isinstance(ident.get("_last_run"), dict) else None
    if not ident or not (ident.get("voice_tone") or run):
        text = (
            "I haven't learned this channel yet — say **“learn this channel”** or "
            "**“learn my channel”** and I'll analyze it (~$0.10-0.30 of your API budget)."
        )
        return await _plain_reply(
            conversation_id, tenant_id, transcript, state, user_msg, text
        )

    # C44: channel-scope standing preferences, reusing the EXACT same
    # `_list_preferences` read the chat hydration path uses (video_id=None ->
    # channel scope only) — one query, two consumers, never a second
    # parallel implementation. Fail-soft already inside _list_preferences.
    preferences = await _list_preferences(tenant_id, video_id=None)
    proposed_patterns = await _proposed_channel_patterns(tenant_id)
    card = _build_dna_digest_card(ident, run, preferences, proposed_patterns)
    state["pending_dna_digest"] = True
    if user_msg:
        transcript.append({"role": "user", "content": user_msg})
    transcript.append(
        _assistant_turn(
            {"assistant_text": card["header"], "phase": "asking", "cards": [card]}
        )
    )
    await _persist(conversation_id, tenant_id, transcript, state, "asking")
    return ChatTurnResponse(
        conversation_id=conversation_id,
        assistant_text=card["header"],
        phase="asking",
        cards=[card],
    )


async def _handle_dna_digest_action(
    selections, conversation_id, tenant_id, transcript, state
) -> ChatTurnResponse:
    """Turn 2 of the digest card (checklist C42): deterministic, NOT routed
    through the producer LLM — same "backend guarantee, not a hope the model
    behaves" discipline `_handle_style_draft_confirm` established. One-shot:
    the pending marker is popped regardless of which action was tapped."""
    state.pop("pending_dna_digest", None)
    action = (selections.get("channel_dna_digest") or "").strip().lower()

    async def _reply(text: str) -> ChatTurnResponse:
        transcript.append(_assistant_turn({"assistant_text": text, "phase": "asking"}))
        await _persist(conversation_id, tenant_id, transcript, state, "asking")
        return ChatTurnResponse(
            conversation_id=conversation_id, assistant_text=text, phase="asking"
        )

    if action == "revert":
        field = (selections.get("field") or "").strip()
        if not field:
            return await _reply("Which field would you like me to revert?")
        from channel_dna import revert_field

        try:
            ok, msg = await revert_field(str(tenant_id), field)
        except Exception as e:  # noqa: BLE001
            logger.warning("chat: dna digest revert failed: %s", e)
            return await _reply("I hit a snag reverting that — mind trying again?")
        return await _reply(msg)

    if action == "correct":
        text = (selections.get("correction_text") or "").strip()
        if not text:
            return await _reply("What would you like me to fix?")
        await _save_preference(tenant_id, text, scope=_PREF_SCOPE_CHANNEL)
        return await _reply(
            f'Got it — I\'ll remember (channel-wide): {text}. Say "forget that" any time to undo it.'
        )

    if action in ("confirm_pattern", "retire_pattern"):
        # C46e (OR-6 expanded): the ONLY thing that makes a proposed pattern
        # take effect (confirm) or reverses one (retire) — same deterministic,
        # not-LLM-routed discipline every other digest action here uses.
        pattern_id = (selections.get("pattern_id") or "").strip()
        if not pattern_id:
            return await _reply("Which pattern do you mean?")
        import channel_patterns

        try:
            if action == "confirm_pattern":
                row = await channel_patterns.confirm_pattern(
                    str(tenant_id), pattern_id, confirmed_by="chat"
                )
            else:
                row = await channel_patterns.retire_pattern(
                    str(tenant_id), pattern_id, confirmed_by="chat"
                )
        except Exception as e:  # noqa: BLE001
            logger.warning("chat: dna digest %s failed: %s", action, e)
            return await _reply("I hit a snag with that — mind trying again?")
        if not row:
            return await _reply(
                "Couldn't find that pattern — it may have already been handled."
            )
        if action == "confirm_pattern":
            note = (
                " It'll now be kept out of future style-seed/few-shot picks."
                if row.get("polarity") == "anti"
                else ""
            )
            return await _reply(f"Confirmed: {row.get('pattern')}{note}")
        return await _reply(f"Retired: {row.get('pattern')}")

    # "keep" (the default — no action needed) or anything else -> acknowledge.
    return await _reply("Sounds good — keeping everything as learned.")


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
            ok=False,
            message=val or "Paste the whole key — it's a long string with no spaces.",
        )
    from vault import set_secret, test_api_key

    await set_secret(
        slot, val, tenant_id=tenant_id, description="Onboarding generation key"
    )
    result = await test_api_key(slot, tenant_id)
    if not result.get("success"):
        return OnboardingKeyResponse(
            ok=False,
            message=f"That key didn't go through — {result.get('message') or 'please double-check it'}.",
        )
    return OnboardingKeyResponse(
        ok=True,
        provider="claude" if slot == "anthropic_api_key" else "kie",
        message=result.get("message") or "Key verified",
    )


async def _handle_cold_start_competitor_followup(
    body,
    conversation_id,
    tenant_id,
    transcript,
    state,
    background_tasks,
) -> Optional[ChatTurnResponse]:
    """C36 (checklist §3.3 item 2): continues the one-tap "add competitors
    now" card attached by the fresh-conversation branch below (section 4)
    when a tenant has zero competitor data — the fix for the cold-start
    finding ("no competitors -> producer gives generic examples... add an
    inline card instead of degrading silently").

    Two turns can land here: the card tap itself (add/skip), or — after
    tapping "add" — the follow-up message pasting the actual URLs. Handled
    OUTSIDE the onboarding step machine (``state["onboarding_step"]``) on
    purpose: this fires for an ALREADY-onboarded creator who simply never
    added competitors, so routing back through connect_yt/connect_drive/
    upsell would be a regression, not a fix — it reuses the SAME
    analyze_competitors/_parse_urls calls the onboarding "competitors" step
    already uses, just without the rest of that step machine attached.

    Returns None (meaning "not my turn — fall through to normal intake")
    when ``state["awaiting_competitor_paste"]`` isn't set, or is a stale/
    unrecognized value — the caller must not get stuck."""
    awaiting = state.get("awaiting_competitor_paste")
    if not awaiting:
        return None
    choice = (body.selections or {}).get("add_competitors")
    if awaiting == "prompt" and choice == "skip":
        state["awaiting_competitor_paste"] = None
        return await _ob_reply(
            conversation_id, tenant_id, transcript, state, _GREETING, phase="asking"
        )
    if awaiting == "prompt" and choice == "add":
        state["awaiting_competitor_paste"] = "collecting"
        return await _ob_reply(
            conversation_id,
            tenant_id,
            transcript,
            state,
            "Paste 1-3 competitor channel URLs or @handles (space or comma separated).",
            phase="asking",
        )
    if awaiting == "collecting":
        urls = _parse_urls(body.message or "")
        if not urls:
            return await _ob_reply(
                conversation_id,
                tenant_id,
                transcript,
                state,
                "I didn't catch a channel URL or @handle there — paste one to three, "
                'or say "skip" to move on.',
                phase="asking",
            )
        state["awaiting_competitor_paste"] = None
        try:
            from routes.onboarding import CompetitorAnalyze, analyze_competitors

            await analyze_competitors(
                CompetitorAnalyze(channel_urls=urls[:3]),
                background_tasks,
                tenant_id=tenant_id,
            )
            text = (
                f"On it — analyzing {len(urls[:3])} channel(s) in the background. I'll have "
                "data-backed ideas once that's done. In the meantime, tell me a topic and I'll "
                "get started."
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("chat: cold-start competitor add failed: %s", e)
            text = "I'll line those up. In the meantime, tell me a topic and I'll get started."
        return await _ob_reply(
            conversation_id, tenant_id, transcript, state, text, phase="asking"
        )
    # Stale/unrecognized value (e.g. they typed over the card) — clear it
    # and fall through to the ordinary intake turn rather than getting stuck.
    state["awaiting_competitor_paste"] = None
    return None


# --- the endpoint ------------------------------------------------------------


@router.post("", response_model=ChatTurnResponse)
async def chat_turn(
    body: ChatTurnRequest,
    background_tasks: BackgroundTasks,
    request: Request = None,
    tenant_id=Depends(get_tenant_id),
):
    arq_pool = getattr(request.app.state, "arq", None) if request is not None else None
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
    custom_film_expected_state = copy.deepcopy(state)
    video_id = str(conv["video_id"]) if conv.get("video_id") else None

    # Saved-recipe commands are deterministic chat control turns. They run
    # before runtime resume/co-pilot routing so save/list/rename/archive never
    # schedule, generate, render, or inherit a production approval.
    pending_recipe_plan = state.get("pending_custom_film_plan")
    has_save_candidate = bool(
        state.get("mode") == "custom_film"
        and isinstance(pending_recipe_plan, dict)
        and pending_recipe_plan.get("status") == "start_ready"
        and isinstance(pending_recipe_plan.get("save_candidate"), dict)
    )
    recipe_command = (
        _custom_film_recipe_command(
            body.message,
            has_save_candidate=has_save_candidate,
        )
        if body.message and body.message.strip()
        else None
    )
    if recipe_command is not None:
        return await _handle_custom_film_recipe_command(
            recipe_command,
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            state=state,
            video_id=video_id,
            user_message=body.message.strip(),
            transcript=transcript,
            expected_state=custom_film_expected_state,
        )

    # M2-3 owns a held pre-runtime video, not a generic co-pilot video. A retry
    # or reload must reconstruct that durable result before legacy video routing.
    pending_custom_film = state.get("pending_custom_film_plan")
    if (
        video_id
        and state.get("mode") == "custom_film"
        and isinstance(pending_custom_film, dict)
        and pending_custom_film.get("execution_model")
        in {"storyboard_director_v1", "storyboard_director_multipass_v2"}
        and pending_custom_film.get("status")
        in {"director_stage_scheduled", "director_stage_completed"}
        and str(pending_custom_film.get("video_id") or "") == video_id
    ):
        if (
            pending_custom_film.get("execution_model")
            == "storyboard_director_multipass_v2"
            and pending_custom_film.get("status") == "director_stage_scheduled"
            and request is not None
        ):
            try:
                await _schedule_reserved_custom_film_director(
                    pending_custom_film,
                    tenant_id=tenant_id,
                    video_id=video_id,
                    arq_pool=arq_pool,
                )
            except Exception:
                logger.warning(
                    "custom film director reload enqueue failed",
                    exc_info=True,
                )
        return _custom_film_director_stage_response(
            conversation_id,
            state,
            video_id,
        )
    if (
        video_id
        and state.get("mode") == "custom_film"
        and isinstance(pending_custom_film, dict)
        and pending_custom_film.get("status") == "start_ready"
        and str(pending_custom_film.get("video_id") or "") == video_id
    ):
        try:
            schedule_kwargs = {"arq_pool": arq_pool} if request is not None else {}
            await _schedule_reserved_custom_film_runtime(
                conversation_id,
                tenant_id,
                state,
                video_id,
                **schedule_kwargs,
            )
        except Exception as exc:
            message = exc.detail if isinstance(exc, HTTPException) else str(exc)
            return ChatTurnResponse(
                conversation_id=conversation_id,
                assistant_text=(
                    f"{message} The approved film is still safely reserved; retry "
                    "and StoryEngine will reuse this same video."
                ),
                video_id=video_id,
                phase="created",
            )
        return _custom_film_start_ready_response(conversation_id, state, video_id)

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
            body,
            conversation_id,
            tenant_id,
            transcript,
            state,
            video_id,
            background_tasks,
        )

    # 2.5 Custom Film interception must precede legacy approval. A combined
    # approve=True + Custom Film message can otherwise consume an old last_spec
    # before the composer has a chance to quarantine it.
    if (
        state.get("mode") == "custom_film"
        and body.selections
        and "custom_film_approval" in body.selections
        and not (body.message and body.message.strip())
    ):
        approval_kwargs = {"arq_pool": arq_pool} if request is not None else {}
        return await _handle_custom_film_approval_turn(
            str(body.selections["custom_film_approval"]),
            conversation_id,
            tenant_id,
            transcript,
            state,
            background_tasks,
            custom_film_expected_state,
            **approval_kwargs,
        )
    if state.get("mode") == "custom_film" and not (
        body.message and body.message.strip()
    ):
        return await _handle_custom_film_control_turn(
            conversation_id,
            tenant_id,
            transcript,
            state,
            custom_film_expected_state,
        )

    if body.message and body.message.strip():
        from custom_film_planner import (
            is_custom_film_exit_intent,
            is_custom_film_intent,
            is_custom_film_ordinary_video_request,
        )

        if state.get("mode") == "custom_film" and is_custom_film_exit_intent(
            body.message
        ):
            if not is_custom_film_ordinary_video_request(body.message):
                return await _handle_custom_film_cancel_turn(
                    conversation_id,
                    tenant_id,
                    transcript,
                    state,
                    custom_film_expected_state,
                )
            # A normal-video request continues into ordinary Producer below.
            # Clear every Custom Film/legacy approval payload first, so
            # switching modes cannot itself approve or dispatch anything.
            state["mode"] = "producer"
            _quarantine_custom_film_state(state, clear_custom_plan=True)
            converged = await _persist_custom_film_cas(
                conversation_id,
                tenant_id,
                transcript,
                state,
                str(conv.get("phase") or "plan"),
                custom_film_expected_state,
            )
            if converged:
                return converged
        elif state.get("mode") == "custom_film" or is_custom_film_intent(body.message):
            return await _handle_custom_film_plan(
                conversation_id,
                tenant_id,
                transcript,
                state,
                body.message.strip(),
                custom_film_expected_state,
            )

    # 3. Approval -> create the video + kick off the pipeline.
    if body.approve and state.get("last_spec"):
        if body.selections:
            state.setdefault("selections", {}).update(body.selections)
        return await _handle_approve(
            state["last_spec"],
            conversation_id,
            tenant_id,
            transcript,
            state,
            background_tasks,
        )

    # 3.6 Style-draft confirm — turn 2 of "make me a new style…" (checklist §C22).
    #     Deterministic, no LLM call: a saved style can ONLY come from here, and
    #     ONLY on the creator's own "yes" tap. Must run before the normal intake
    #     turn below, which would otherwise just feed the selection to the LLM.
    if (
        body.selections
        and "style_draft" in body.selections
        and state.get("pending_style_draft")
    ):
        return await _handle_style_draft_confirm(
            body.selections, conversation_id, tenant_id, transcript, state
        )

    # 3.6a Quality-rules draft confirm — turn 2 of "here are my quality rules"
    #      (checklist §C46b). Same deterministic, no-LLM-call discipline as 3.6.
    if (
        body.selections
        and "quality_rules_draft" in body.selections
        and state.get("pending_quality_rules_draft")
    ):
        return await _handle_quality_rules_draft_confirm(
            body.selections, conversation_id, tenant_id, transcript, state
        )

    # 3.6b Channel-DNA digest card actions (checklist C42) — keep/revert/correct
    #      taps on the digest card. Same source-lock discipline as 3.6 above:
    #      deterministic, runs BEFORE producer intake, only fires when a digest
    #      is actually pending (never manufactured from LLM prose alone).
    if (
        body.selections
        and "channel_dna_digest" in body.selections
        and state.get("pending_dna_digest")
    ):
        return await _handle_dna_digest_action(
            body.selections, conversation_id, tenant_id, transcript, state
        )

    # 3.4 "Learn this channel" chat front door (checklist C42 · P4.1c) + "show
    #     the channel digest" — both run before 3.5's identity-only commands
    #     since "learn my channel's voice" should get the FULL C41 orchestrator,
    #     not just identity_builder alone (see _learn_channel_intent's docstring).
    if body.message and body.message.strip():
        msg_stripped = body.message.strip()
        if _learn_channel_intent(msg_stripped):
            return await _handle_learn_channel(
                conversation_id,
                tenant_id,
                transcript,
                state,
                msg_stripped,
                background_tasks,
            )
        if _dna_digest_intent(msg_stripped):
            return await _handle_show_channel_digest(
                conversation_id, tenant_id, transcript, state, msg_stripped
            )

    # 3.5 Channel-identity commands ("build his identity" / "what's his voice?").
    #     Runs before producer intake so it doesn't get treated as a video request.
    if body.message and body.message.strip():
        _iid = _identity_intent(body.message)
        if _iid == "build":
            return await _handle_build_identity(
                conversation_id,
                tenant_id,
                transcript,
                state,
                body.message.strip(),
                background_tasks,
            )
        if _iid == "show":
            return await _handle_show_identity(
                conversation_id, tenant_id, transcript, state, body.message.strip()
            )

    # 3.7 Cold-start "add competitors now" follow-up (checklist §3.3 item 2, C36).
    cold_start_reply = await _handle_cold_start_competitor_followup(
        body, conversation_id, tenant_id, transcript, state, background_tasks
    )
    if cold_start_reply is not None:
        return cold_start_reply

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
                return await _handle_analyze(
                    conversation_id, tenant_id, transcript, state, ref
                )
    if body.selections:
        user_parts.append(_selections_to_text(body.selections))
        state.setdefault("selections", {}).update(body.selections)
    if body.attachments:
        await _attach_assets(
            tenant_id, conversation_id, body.attachments, state, user_parts
        )

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
            # C36 (checklist §3.3 item 2): distinguish WHY ideas came back None.
            # No competitor rows -> the fixable cold-start case this item
            # targets — offer the one-tap card instead of silently handing
            # over the generic dragon-video example. Any other reason (no
            # Anthropic key, a transient API failure) is a DIFFERENT problem
            # (missing-key friction is P0.4's territory) — the card would be
            # actively misleading there, so it's gated strictly on "genuinely
            # no competitor data", not on ideas-is-None in general.
            has_competitors = True
            try:
                has_competitors = bool(await _recent_competitor_rows(tenant_id))
            except Exception as e:  # noqa: BLE001
                logger.warning("chat: cold-start competitor check failed: %s", e)
                has_competitors = (
                    True  # fail open to the plain greeting, not a misleading card
                )
            if not has_competitors:
                state["awaiting_competitor_paste"] = "prompt"
                text = (
                    _GREETING
                    + "\n\nBy the way — you haven't added any competitor channels yet, so "
                    "I can't pull data-backed ideas for you yet. Want to add a few now?"
                )
                return await _ob_reply(
                    conversation_id,
                    tenant_id,
                    transcript,
                    state,
                    text,
                    phase="asking",
                    cards=[_add_competitors_card()],
                )
            transcript.append(
                _assistant_turn({"assistant_text": _GREETING, "phase": "asking"})
            )
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
        transcript.append(
            _assistant_turn({"assistant_text": _NO_KEY_PRODUCER_MSG, "phase": "asking"})
        )
        await _persist(conversation_id, tenant_id, transcript, state, "asking")
        return ChatTurnResponse(
            conversation_id=conversation_id,
            assistant_text=_NO_KEY_PRODUCER_MSG,
            phase="asking",
        )

    # THE channel-identity pool brief (checklist P2) goes FIRST, ahead of the
    # durable creator brief, the length anchor, channel intelligence,
    # competitor winners, the loop brief, and — most directly —
    # _reference_brief: that function's own modeling instructions point back
    # at "the identity block above", so it must actually render above them.
    # Producer sees the durable creator brief + a real length anchor + the channel
    # intelligence brief (top titles / hook pattern / thumbnail motifs / cadence) +
    # REAL data on any video being modeled (so it grounds the proposal in the
    # reference, not the creator's own channel) + the current channel setup it can
    # edit (competitors, name, niche, look).
    system_prompt = build_system_prompt(
        await _identity_pool_brief(tenant_id)
        + _creator_brief(state)
        + await _modeled_runtime_hint(tenant_id)
        + await _channel_intel_brief(tenant_id)
        + await _competitor_winners_brief(tenant_id)
        + await _loop_brief(tenant_id)
        + await _reference_brief(state, state.get("pending_reference_url"))
        + _dna_brief(state)
        + await _profile_state_brief(tenant_id)
        + await _format_brief(tenant_id)
        + await _script_template_brief(tenant_id)
        + await _style_presets_brief(tenant_id)
        + await _visual_styles_brief(tenant_id)
        + await _assets_brief(tenant_id, state)
        + await _preferences_brief(tenant_id)
    )
    data = call_producer(transcript, system_prompt, client=client)
    await _stamp_length_default(data, tenant_id, transcript)
    await _annotate_style_recommendation(data, tenant_id, state)
    await _stamp_plan_estimate(data)
    assistant_text = await _apply_and_merge_profile_ops(
        data, tenant_id, state, background_tasks
    )
    _maybe_attach_style_draft_card(data, state)
    _maybe_attach_quality_rules_draft_card(data, state)
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
        cb = await fetch_one(
            "SELECT creator_brief FROM channel_profiles WHERE tenant_id = $1", tenant_id
        )
        brief = _as_dict((cb or {}).get("creator_brief"))
        niche = (
            brief.get("niche")
            or brief.get("modeling_niche")
            or brief.get("channel")
            or ""
        ).strip()
    except Exception:  # noqa: BLE001
        pass
    lines = [
        f'{i + 1}. "{r["title"]}" — {int(r["views"] or 0):,} views, {float(r["vph"] or 0):.0f} views/hr, '
        f"{_ago(r.get('hours_old'))}"
        for i, r in enumerate(rows)
    ]
    prompt = (
        "These are the current top videos on a YouTube channel a creator is modeling"
        + (f" (the creator's niche: {niche})" if niche else "")
        + ":\n"
        + "\n".join(lines)
        + "\n\nFor EACH video, write ONE punchy sentence on why it's worth modeling — cite the concrete "
        "signal (breakout views/hour, freshness, or view count) AND the format/hook pattern that's working, "
        "and how the creator could make it their own. Plain, no hype words.\n"
        'Return ONE JSON object: {"whys": ["...", ...]} with exactly one string per video, in the SAME order.'
    )
    try:
        from producer_prompt import _extract_json

        model = _claude_model_for_direct_client(client)
        kw: dict[str, Any] = {"prompt": prompt, "max_tokens": 700, "temperature": 0.4}
        if model:
            kw["model"] = model
        data = json.loads(_extract_json((await client.generate(**kw)) or ""))
        whys = data.get("whys") if isinstance(data, dict) else None
        if isinstance(whys, list) and whys:
            return {
                r["video_id"]: (
                    str(whys[i]).strip()
                    if i < len(whys) and whys[i]
                    else _metric_why(r)
                )
                for i, r in enumerate(rows)
            }
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
                tenant_id,
                dead,
            )
            logger.info(
                "suggested-models: flagged %d removed videos for %s",
                len(dead),
                tenant_id,
            )
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
                    why,
                    tenant_id,
                    r["video_id"],
                )
    videos = [
        {
            "video_id": r["video_id"],
            "title": r["title"],
            "url": r.get("url"),
            "channel": r.get("channel"),
            "views": int(r.get("views") or 0),
            "vph": round(float(r.get("vph") or 0)),
            "posted": _ago(r.get("hours_old")),
            "thumbnail": f"https://i.ytimg.com/vi/{r['video_id']}/hqdefault.jpg",
            "why": (r.get("model_rationale") or _metric_why(r)),
        }
        for r in rows
    ]
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
        tenant_id,
        video_id,
    )
    if not conv:
        return {"conversation_id": None, "messages": [], "phase": "created"}
    messages: list[dict[str, Any]] = []
    for t in _as_list(conv.get("transcript")):
        if t.get("role") == "user":
            messages.append({"role": "user", "text": t.get("content") or ""})
        elif t.get("role") == "assistant":
            d = _as_dict(
                t.get("content")
            )  # assistant turns store JSON (see _assistant_turn)
            messages.append(
                {
                    "role": "assistant",
                    "text": d.get("assistant_text") or "",
                    "cards": d.get("cards"),
                    "plan": d.get("plan"),
                }
            )
    return {
        "conversation_id": str(conv["id"]),
        "messages": messages,
        "phase": conv.get("phase") or "created",
    }


# --- Chat history (sidebar list + resume any past conversation by id) ---


def _flatten_transcript(transcript) -> list:
    """Transcript rows -> the {role, text, cards?, plan?} shape ChatCore renders."""
    out: list = []
    for t in _as_list(transcript):
        if t.get("role") == "user":
            out.append({"role": "user", "text": t.get("content") or ""})
        elif t.get("role") == "assistant":
            d = _as_dict(t.get("content"))
            out.append(
                {
                    "role": "assistant",
                    "text": d.get("assistant_text") or "",
                    "cards": d.get("cards"),
                    "plan": d.get("plan"),
                }
            )
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
        tenant_id,
        limit * 3,
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
        out.append(
            {
                "conversation_id": str(c["id"]),
                "title": title[:80],
                "preview": (last_assistant or "")[:140],
                "phase": c.get("phase") or "asking",
                "video_id": str(c["video_id"]) if c.get("video_id") else None,
                "updated_at": c["updated_at"].isoformat()
                if c.get("updated_at")
                else None,
            }
        )
        if len(out) >= limit:
            break
    return out


@router.get("/conversation/{conversation_id}")
async def get_conversation_by_id(
    conversation_id: str, tenant_id=Depends(get_tenant_id)
):
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
