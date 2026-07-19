"""StoryEngine MCP server — the "talk to it from Claude" door (checklist
P2.4a/P2.4b, chunks C26/C27; tasks/storyengine-copilot-ux-map.md §7, "the
Higgsfield-killer door").

DARK BY DEFAULT: this router only registers in main.py when
`MCP_ENABLED=true`. Default/unset -> these routes structurally do not exist
(404, not "exists but blocked") — see main.py's registration comment. Nothing
external may reach this endpoint until the C25a media-proxy tenant-auth fix
(currently held on `claude/c25a-media-auth-hold`, not on this branch) lands
via a coordinated deploy.

Protocol shape (justified): the UX map §7 spec says "streamable-HTTP MCP
endpoint" only parenthetically, as one possible file/route name — it does
not mandate full MCP transport compliance (SSE, `Mcp-Session-Id`
negotiation, server-initiated pushes). v1 here is a single JSON-RPC 2.0 POST
endpoint supporting exactly the three methods a tool-calling MCP client
needs: `initialize`, `tools/list`, `tools/call`. No SSE stream, no session
header. Whether a real external MCP client needs the fuller transport is
C29's live-client loop test (tasks/live-verification-queue.md §C26/§C27) —
deferred, not decided here.

TOOL SURFACE v2 (C27 — checklist P2.4b expands C26's 2 read-only tools with
the money-gated verb registry):

  READS (tenant-scoped, no cost, no media URL in any result — C25a hold):
    list_videos, get_video, get_scenes, get_script, get_ledger,
    list_style_presets, list_models.

  FREE WRITES (execute immediately, no confirm_token — same `paid: False`
  verbs actions.ACTIONS marks free for chat/buttons):
    approve_cast, approve_environments, skip_environments, approve_scene,
    camera_preset, script_profile, budget_cap, lock, unlock, drive_push,
    drive_sync, advance, create_video.
    (create_video is a special case, not an actions.ACTIONS verb — see
    _call_create_video. It's free because creating the row spends nothing;
    the first paid verb run against that video — "script", "build", ... —
    is what actually gates on a quote.)

  PAID (the money gate — see module docstring section below for the exact
  two-step protocol; same `paid: True` verbs actions.ACTIONS marks for
  chat/buttons):
    script, characters, storyboards, images, voice, animate, draft_pass,
    finalize, sound, thumbnail, render, research, seo, upload, build.

TOOL SURFACE v3 (C47 — decisions.md 2026-07-19's "MCP is the setup brain" +
"MCP economics" entries; see the SETUP TOOLS / INGEST TOOLS sections below
for the full per-tool docstrings):

  SETUP (free config reads/writes onto EXISTING functions/routes only, no
  new logic; every write attributed via `caller`, structurally where a real
  attribution column already exists — quality_rules.source='mcp_agent',
  channel_patterns.confirmed_by — else logged):
    get_channel_dna, learn_channel_start (the one tool here with a real,
    stated, non-StoryEngine-billed cost — BYOK ~$0.10-0.30), learn_channel_
    status, list_quality_rules, upsert_quality_rule, deactivate_quality_rule,
    list_channel_patterns, confirm_channel_pattern, retire_channel_pattern,
    get_script_template, set_script_template, list_script_profiles,
    get_system_prompts, set_system_prompt, set_render_style, set_style_preset.
    (script_profile/budget_cap are NOT duplicated here — they already exist
    as free verb tools, generated from actions.ACTIONS above.)

  INGEST (checklist's "MCP economics" play — the connected agent thinks on
  its OWN Claude subscription, submits the result; only the media pipeline
  that follows still spends BYOK keys):
    submit_research (shape-validated against run_research's own payload
    shape + the SAME deterministic roster gate, no confirm_token — see
    research_ingest.py), submit_script (thin wrapper over
    user_script.accept_external_script, source="agent_submitted" — see
    that function's docstring for the accept/reject design, C46d).

TOOL SURFACE v4 (C52 — checklist P4.2-c, the read/decide surface for C51's
propose_only autopilot dry-run loop): list_autopilot_proposals (read),
accept_autopilot_proposal / dismiss_autopilot_proposal (free writes,
attributed decided_by='mcp_agent', calling the SAME routes.autopilot.
accept_proposal/dismiss_proposal functions the HTTP door uses — see the
"AUTOPILOT PROPOSAL TOOLS" section below for the accept-is-free
classification's full reasoning).

TOOL SURFACE v5 (C54 — checklist P4.2-e, weekly budget ceiling + kill
switch): set_autopilot_dial (free write — dial_level and/or
weekly_budget_cap, calling the SAME routes.autopilot.update_config the HTTP
config route uses), reset_autopilot_kill_switch (free write — calls the SAME
routes.autopilot.reset_kill_switch the HTTP door uses). See the "AUTOPILOT
DIAL TOOLS" section below for both tools' free-vs-confirm classification
reasoning (the kill-switch reset in particular was a real judgment call, not
a rubber-stamp of the create_video/accept_autopilot_proposal precedent).

Every verb tool (free or paid) dispatches through actions.ACTIONS/
routes.chat._run_pending_action — the EXACT SAME dispatcher chat.py's
confirmed-action path calls. This module adds ONLY: (1) MCP framing
(JSON-RPC envelope, tool schemas), (2) the confirm_token money gate for paid
verbs, (3) attribution (the `caller` parameter `_run_pending_action` now
accepts, threaded down to every generation_claims acquire). No new pipeline
logic, no forked dispatch, no parallel cost math — actions.estimate_cost/
cost_breakdown/blocked_reason are the SAME calls chat.py's confirm-card path
makes for the SAME verb.

THE MONEY GATE (checklist P2.4b, the heart of this chunk): no paid tool
executes on its first call. Call it once with no `confirm_token` -> you get
back a quote (cost, cost_text, an itemized breakdown when there is one) plus
a single-use `confirm_token`. Call the SAME tool again with the SAME
arguments plus that `confirm_token` -> it actually runs, through
`_run_pending_action`, which still holds every existing money-safety layer
underneath (generation_claims' C16a concurrency lock, C16b's per-stage
skip-if-done, C16c's generation_ledger backstop, C16e's upload skip-if-
already-uploaded) — this chunk adds a gate IN FRONT of that path, it does
not touch what's inside it.

confirm_tokens.py (see that module for the full design rationale) makes the
token single-use, short-lived (10 min), and bound to the EXACT (tenant,
video, verb, params-hash) the quote was computed for — a token minted for
"animate scene 3" cannot be replayed against "animate scene 12", a
different verb, a different video, or a different tenant; and calling
confirm twice with the same token only works once.

Rate limiting (checklist P2.4b, the gap C26 flagged): rate_limit.py's
`_extract_tenant_from_jwt` previously only tried to decode an Authorization
bearer value as a session JWT — an `se_agent_...` agent token always failed
that decode, so `RateLimitMiddleware` treated every MCP request as anonymous
and never metered it. Fixed at the extractor (not here) — see
rate_limit.py's updated `_extract_tenant_from_jwt` for the agent-token
branch. Every request through this router is therefore now rate-limited
under the SAME per-tenant PLAN_LIMITS bucket an ordinary session uses.

Attribution ("via agent" seam for C28): `mcp_rpc` resolves the calling
token's display name (agent_tokens.name_for_token — fail-soft, never blocks
the call) and threads `caller=f"agent:{name}"` down through
`_run_pending_action` into every generation_claims.acquire() this dispatch
makes. C28's chip reads `generation_claims.claimed_by LIKE 'agent:%'`
(live, while a claim is held) — this is intentionally the SAME ephemeral
signal chat's own claimed_by already carries (docs/reports/2026-07-17-
storyengine-agent-audit-findings.md §S5-2's "smallest correct v1" framing),
not a new durable column/migration.

Explicitly EXCLUDED from v1 (docs/reports/2026-07-17-storyengine-agent-
audit-findings.md §S5):
  - Any memory-writing tool (remember/forget) — S5-2 says MCP v1 must
    EXCLUDE memory-writing tools outright. Not in actions.ACTIONS at all,
    so there is nothing to wrap; pinned by a test regardless.
  - Any media/asset URL in any tool result. get_scenes/get_script are
    hand-written queries that never SELECT an *_url column; get_ledger's
    kie_task_id is an opaque provider job id, not a URL;
    list_style_presets' preview_url is explicitly stripped before return
    (belt-and-suspenders — same posture C26 took with get_video).

Auth: get_agent_tenant_id (auth_agent.py) — the DISTINCT agent-token
dependency (S5-4), never auth.verify_token/get_tenant_id.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

import logging

import actions
import agent_tokens
import confirm_tokens
from auth_agent import get_agent_tenant_id
from database import fetch_all, fetch_one

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mcp", tags=["mcp"])

PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "storyengine", "version": "1.0.0"}


def _text_result(payload: Any) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(payload)}], "isError": False}


def _error_result(message: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": message}], "isError": True}


def _coerce_scene(raw: Any) -> Optional[int]:
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


# =============================================================================
# READ TOOLS — tenant-scoped, no cost, no media URLs.
# =============================================================================

_VIDEO_ID_SCHEMA = {
    "type": "object",
    "properties": {"video_id": {"type": "string", "description": "Video UUID."}},
    "required": ["video_id"],
}

_READ_TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_videos",
        "description": "List this tenant's videos (id, title, status). Read-only, no cost.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max rows to return (default 50, max 100).",
                },
            },
        },
    },
    {
        "name": "get_video",
        "description": (
            "Get a compact status summary for one video: title, status, "
            "scene/asset counts, and spend so far. Read-only, no cost."
        ),
        "inputSchema": _VIDEO_ID_SCHEMA,
    },
    {
        "name": "get_scenes",
        "description": (
            "Per-scene state for a video: pictures/clips drawn, whether the scene is "
            "approved, the routed clip model + why (the routing_reason a hero shot got "
            "picked for a premium tier), any manual model override, and the camera "
            "preset set on it. No media URLs — this is the shot map, not the pictures "
            "themselves. Read-only, no cost."
        ),
        "inputSchema": _VIDEO_ID_SCHEMA,
    },
    {
        "name": "get_script",
        "description": (
            "The written script, scene by scene: the narration text, script status, "
            "voice status, and tone. No media URLs. Read-only, no cost."
        ),
        "inputSchema": _VIDEO_ID_SCHEMA,
    },
    {
        "name": "get_ledger",
        "description": (
            "Actual-spend receipts for a video: total spent, a per-stage breakdown, "
            "and every individual generation_ledger row (stage, model, units, cost). "
            "This is REAL spend already incurred, not an estimate. Read-only, no cost."
        ),
        "inputSchema": _VIDEO_ID_SCHEMA,
    },
    {
        "name": "list_style_presets",
        "description": (
            "The visual style catalog (id, display name, tags, best-for, cost tier) "
            "for picking a look with create_video's visual_style/style_preset_id. "
            "Read-only, no cost."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_models",
        "description": (
            "The clip-generation model registry: id, tier, whether it's actually wired "
            "(has a live generation path), and cost per clip. Read-only, no cost."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
]

_CREATE_VIDEO_TOOL: dict[str, Any] = {
    "name": "create_video",
    "description": (
        "Create a new video idea — free (this only writes the row; nothing is "
        "generated or spent until you run a paid verb like \"script\" or \"build\" "
        "and confirm its quote). Mirrors the New Video form."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "The video's working title/topic."},
            "framework_angle": {"type": "string", "description": "The angle/thesis, if you have one."},
            "video_length_minutes": {
                "type": "integer",
                "description": "Target runtime in minutes (default 10).",
            },
            "writer_guidance": {
                "type": "string",
                "description": "Free-text creative direction for the script.",
            },
            "visual_style": {
                "type": "string",
                "description": "Free-text visual style, or an id from list_style_presets.",
            },
            "script_profile": {
                "type": "string",
                "description": "A script-voice id (see the script_profile verb's aliases), or omit for the default.",
            },
        },
        "required": ["title"],
    },
}


async def _call_list_videos(tenant_id, arguments: dict[str, Any]) -> dict[str, Any]:
    raw_limit = arguments.get("limit") or 50
    try:
        limit = max(1, min(int(raw_limit), 100))
    except (TypeError, ValueError):
        limit = 50
    rows = await fetch_all(
        "SELECT id, video_title, status FROM videos WHERE tenant_id = $1 "
        "ORDER BY updated_at DESC LIMIT $2",
        tenant_id, limit,
    )
    videos = [
        {
            "id": str(r["id"]),
            "title": r.get("video_title") or "Untitled",
            "status": r.get("status"),
        }
        for r in (rows or [])
    ]
    return _text_result({"videos": videos})


async def _call_get_video(tenant_id, arguments: dict[str, Any]) -> dict[str, Any]:
    video_id = arguments.get("video_id")
    if not video_id:
        return _error_result("get_video requires a video_id argument")
    summary = await actions.video_summary(tenant_id, str(video_id))
    if summary is None:
        return _error_result(f"No video {video_id} found for this tenant")
    return _text_result(summary)


async def _call_get_scenes(tenant_id, arguments: dict[str, Any]) -> dict[str, Any]:
    video_id = arguments.get("video_id")
    if not video_id:
        return _error_result("get_scenes requires a video_id argument")
    owned = await actions.video_summary(tenant_id, str(video_id))
    if owned is None:
        return _error_result(f"No video {video_id} found for this tenant")
    rows = await fetch_all(
        "SELECT scene, "
        "count(*) FILTER (WHERE image_url IS NOT NULL) AS pics, "
        "count(*) FILTER (WHERE video_clip_url IS NOT NULL) AS clips, "
        "bool_or(status = 'approved') AS approved, "
        "max(routed_model) AS routed_model, max(model_override) AS model_override, "
        "max(routing_reason) AS routing_reason, max(camera_preset_id) AS camera_preset_id "
        "FROM assets WHERE video_id = $1 AND tenant_id = $2 AND scene IS NOT NULL "
        "GROUP BY scene ORDER BY scene",
        video_id, tenant_id,
    )
    scenes = [
        {
            "scene": r.get("scene"),
            "pics": int(r.get("pics") or 0),
            "clips": int(r.get("clips") or 0),
            "approved": bool(r.get("approved")),
            "routed_model": r.get("routed_model"),
            "model_override": r.get("model_override"),
            "routing_reason": r.get("routing_reason"),
            "camera_preset_id": r.get("camera_preset_id"),
        }
        for r in (rows or [])
    ]
    return _text_result({"video_id": video_id, "scenes": scenes})


async def _call_get_script(tenant_id, arguments: dict[str, Any]) -> dict[str, Any]:
    video_id = arguments.get("video_id")
    if not video_id:
        return _error_result("get_script requires a video_id argument")
    owned = await actions.video_summary(tenant_id, str(video_id))
    if owned is None:
        return _error_result(f"No video {video_id} found for this tenant")
    rows = await fetch_all(
        "SELECT scene, scene_text, script_status, voice_status, tone "
        "FROM scripts WHERE video_id = $1 AND tenant_id = $2 ORDER BY scene NULLS FIRST",
        video_id, tenant_id,
    )
    scenes = [
        {
            "scene": r.get("scene"),
            "text": r.get("scene_text"),
            "status": r.get("script_status"),
            "voice_status": r.get("voice_status"),
            "tone": r.get("tone"),
        }
        for r in (rows or [])
    ]
    return _text_result({"video_id": video_id, "scenes": scenes})


async def _call_get_ledger(tenant_id, arguments: dict[str, Any]) -> dict[str, Any]:
    video_id = arguments.get("video_id")
    if not video_id:
        return _error_result("get_ledger requires a video_id argument")
    from routes.videos import get_video_ledger
    try:
        result = await get_video_ledger(str(video_id), tenant_id=tenant_id)
    except HTTPException as e:
        return _error_result(e.detail if isinstance(e.detail, str) else "Video not found")
    return _text_result(result.model_dump())


async def _call_list_style_presets(tenant_id, arguments: dict[str, Any]) -> dict[str, Any]:
    from routes.style_presets import list_style_presets as _list_style_presets_route
    result = await _list_style_presets_route(tenant_id=tenant_id)
    payload = result.model_dump()
    # C25a hold (S5-1): strip preview_url explicitly rather than trust the
    # source not to carry one — same belt-and-suspenders posture C26 took
    # with get_video, even though video_summary() never had one either.
    for p in payload.get("presets", []):
        p.pop("preview_url", None)
    return _text_result(payload)


async def _call_list_models(tenant_id, arguments: dict[str, Any]) -> dict[str, Any]:
    from routes.model_registry import list_models as _list_models_route
    result = await _list_models_route(tenant_id=tenant_id)
    return _text_result(result.model_dump())


_READ_HANDLERS = {
    "list_videos": _call_list_videos,
    "get_video": _call_get_video,
    "get_scenes": _call_get_scenes,
    "get_script": _call_get_script,
    "get_ledger": _call_get_ledger,
    "list_style_presets": _call_list_style_presets,
    "list_models": _call_list_models,
}


async def _call_create_video(tenant_id, arguments: dict[str, Any],
                              background_tasks: Optional[BackgroundTasks]) -> dict[str, Any]:
    """Free (checklist P2.4b's explicit call: creating the row spends
    nothing — the first paid verb run against it is what gates on a quote).
    Reuses routes.videos.create_video verbatim — the SAME path the New Video
    form posts to — rather than a second INSERT with its own field list."""
    title = (arguments.get("title") or "").strip()
    if not title:
        return _error_result("create_video requires a title argument")
    if background_tasks is None:
        return _error_result("Internal error: no task runner available for this call")
    from models import CreateVideoRequest
    from routes.videos import create_video as _create_video_route

    try:
        body = CreateVideoRequest(
            title=title,
            framework_angle=arguments.get("framework_angle"),
            video_length_minutes=arguments.get("video_length_minutes") or 10,
            writer_guidance=arguments.get("writer_guidance"),
            visual_style=arguments.get("visual_style"),
            script_profile=arguments.get("script_profile"),
        )
    except Exception as e:  # noqa: BLE001 — a bad argument shape is a tool-input error, not a 500
        return _error_result(f"Couldn't create the video — invalid arguments: {e}")

    try:
        result = await _create_video_route(body, background_tasks, tenant_id=tenant_id)
    except HTTPException as e:
        return _error_result(f"Couldn't create the video — {e.detail}")
    payload = result.model_dump()
    payload.pop("thumbnail_url", None)  # C25a hold — belt-and-suspenders, see module docstring
    return _text_result(payload)


# =============================================================================
# VERB TOOLS — generated from actions.ACTIONS, one registry for every door.
# Free verbs (paid=False) execute immediately through
# routes.chat._run_pending_action. Paid verbs (paid=True) are quote-gated:
# the first call (no confirm_token) mints a quote + single-use token; the
# second call (with confirm_token) redeems it and dispatches through the
# SAME _run_pending_action. See module docstring for the full protocol.
# =============================================================================

_FREE_VERBS = tuple(v for v, cfg in actions.ACTIONS.items() if not cfg["paid"])
_PAID_VERBS = tuple(v for v, cfg in actions.ACTIONS.items() if cfg["paid"])


def _verb_tool_schema(*, paid: bool) -> dict[str, Any]:
    props: dict[str, Any] = {
        "video_id": {"type": "string", "description": "Video UUID."},
        "scene": {
            "type": "integer",
            "description": "Scene number, for scene-scoped verbs (e.g. approve_scene, camera_preset, animate). Omit for a whole-video action.",
        },
        "change": {
            "type": "string",
            "description": (
                "Free-text guidance for edit-capable verbs (script, images, thumbnail), or the "
                "specific move/style text for camera_preset (\"crash zoom\") / script_profile "
                "(\"investigative\") / budget_cap (\"$15\", or \"remove the cap\")."
            ),
        },
        "length_min": {
            "type": "number",
            "description": "New target length in minutes (the script verb only).",
        },
    }
    if paid:
        props["confirm_token"] = {
            "type": "string",
            "description": (
                "Omit on the first call to get a price quote back. Call this SAME tool again "
                "with the SAME arguments plus this confirm_token to actually run it. Tokens are "
                "single-use and expire after 10 minutes."
            ),
        }
    return {"type": "object", "properties": props, "required": ["video_id"]}


def _verb_tools() -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    for verb in _FREE_VERBS:
        cfg = actions.ACTIONS[verb]
        tools.append({
            "name": verb,
            "description": f"{cfg['label']} — free, executes immediately, no cost.",
            "inputSchema": _verb_tool_schema(paid=False),
        })
    for verb in _PAID_VERBS:
        cfg = actions.ACTIONS[verb]
        tools.append({
            "name": verb,
            "description": (
                f"{cfg['label']} — PAID. Call with no confirm_token first to get a price quote; "
                "call again with the returned confirm_token to actually run it."
            ),
            "inputSchema": _verb_tool_schema(paid=True),
        })
    return tools


# =============================================================================
# SETUP TOOLS (checklist C47 — decisions.md 2026-07-19 "MCP is the setup
# brain" entry): free config reads/writes onto the SAME functions/routes the
# StoryEngine UI/chat doors already call — no new logic, no parallel store.
# `script_profile`/`budget_cap` (per-video voice + spend cap) are NOT
# duplicated here — they already dispatch as MCP verb tools via
# `_verb_tools()` above (free ACTIONS verbs, same name), since they're
# "existing verbs/columns" the checklist explicitly says not to re-wrap.
# render_style/style_preset_id had no such existing verb — set_render_style/
# set_style_preset below wrap the generic `PATCH /api/videos/{id}` path
# instead (style_preset_id was ADDED to that route's allowlist this chunk,
# reusing its own pre-existing `_resolve_style_preset_id` validator verbatim
# — the same validator create_video already used, just never wired to the
# update path).
#
# None of these carry a confirm_token (free) — but every write is logged
# with its `caller` (the C27 attribution seam), and confirm_channel_pattern/
# retire_channel_pattern additionally stamp the REAL `confirmed_by` column
# those functions already accept (no new column needed there). learn_channel_
# start is the one exception that costs real (BYOK) money — its own
# description says so, honestly, same as the HTTP door's own ack message.
# =============================================================================

def _log_setup_write(tool: str, tenant_id, caller: str, detail: str = "") -> None:
    """Attribution for setup-tool writes that land on a table/column with no
    provenance field of its own (tenant_prompt_defaults, script_templates,
    videos.render_style/style_preset_id) — logged rather than invented as a
    new schema column past this chunk's scope. Where a REAL attribution
    column already exists (quality_rules.source, channel_patterns.
    confirmed_by) the handler passes `caller` into that column directly
    instead of only logging it."""
    logger.info("[mcp setup] %s tenant=%s caller=%s %s", tool, str(tenant_id)[:8], caller, detail)


def _clear_alias(text: Optional[str]) -> Optional[str]:
    """"auto"/"clear"/"none"/"" all mean "reset to unset" — same vocabulary
    the script_profile/camera_preset/budget_cap chat verbs already use for
    "give me the default back", so an agent that learned that convention
    from one tool doesn't have to guess a different one for these."""
    t = (text or "").strip().lower()
    return None if t in {"", "auto", "clear", "none", "default"} else text


_GET_CHANNEL_DNA_TOOL: dict[str, Any] = {
    "name": "get_channel_dna",
    "description": (
        "This channel's learned identity (voice, cadence, hooks, structure, "
        "research approach, thumbnail formula, visual format, reference-video "
        "style notes) plus WHO/WHEN taught each field (_sources) and a change "
        "history (_history) — the same provenance envelope the DNA digest "
        "card reads. No media URLs. Read-only, no cost."
    ),
    "inputSchema": {"type": "object", "properties": {}},
}

_LEARN_CHANNEL_START_TOOL: dict[str, Any] = {
    "name": "learn_channel_start",
    "description": (
        "Kick off channel-DNA learning: runs every learner (voice/hooks/"
        "structure from your top videos, house script format, visual format "
        "lock, an optional reference video's style, pattern proposals from "
        "your own analytics) in the background — takes 1-2 minutes. Costs "
        "roughly $0.10-0.30 of YOUR OWN configured API budget (BYOK — "
        "Anthropic/Firecrawl calls, not billed by StoryEngine), so it never "
        "needs a confirm_token. Poll learn_channel_status for the result."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "channel_url": {"type": "string", "description": "A YouTube channel URL to import first, if this isn't already the tenant's own imported channel."},
            "example_script_text": {"type": "string", "description": "An example script to distill the house format from."},
            "reference_video_url": {"type": "string", "description": "One YouTube video URL whose style should be folded in as reference_video_style."},
        },
    },
}

_LEARN_CHANNEL_STATUS_TOOL: dict[str, Any] = {
    "name": "learn_channel_status",
    "description": "Whether a learn_channel_start run is still working, and the last run's per-learner digest. Read-only, no cost.",
    "inputSchema": {"type": "object", "properties": {}},
}

_LIST_QUALITY_RULES_TOOL: dict[str, Any] = {
    "name": "list_quality_rules",
    "description": (
        "This channel's script quality-law rows (id, testable law text, "
        "severity, evidence, applies_to scope). Read-only, no cost."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {"active_only": {"type": "boolean", "description": "Only return active rules (default false — returns all)."}},
    },
}

_UPSERT_QUALITY_RULE_TOOL: dict[str, Any] = {
    "name": "upsert_quality_rule",
    "description": (
        "Create or edit-in-place a quality rule (same (tenant, rule_id) key "
        "-> update semantics as re-uploading a revised rules doc). Free, no "
        "cost — takes effect on the NEXT script write/submission this rule's "
        "applies_to scope matches."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "rule_id": {"type": "string", "description": "A short id, e.g. \"QL-12\"."},
            "law": {"type": "string", "description": "The testable rule text."},
            "severity": {"type": "string", "description": "hard_gate | warn | guidance (default guidance)."},
            "evidence": {"type": "string", "description": "Why this rule exists, optional."},
            "applies_to": {
                "type": "object",
                "description": "Scope, e.g. {\"all\": true} or {\"research\": true} or {\"story\": true} or {\"animated\": true} or {\"realistic\": true} or {\"channel_format\": \"...\"} or {\"dvsu_mode\": \"...\"}. Omit for {\"all\": true}.",
            },
        },
        "required": ["rule_id", "law"],
    },
}

_DEACTIVATE_QUALITY_RULE_TOOL: dict[str, Any] = {
    "name": "deactivate_quality_rule",
    "description": "Deactivate a quality rule by its internal id (from list_quality_rules). Free, no cost, reversible via upsert_quality_rule.",
    "inputSchema": {
        "type": "object",
        "properties": {"id": {"type": "string", "description": "The rule's internal id (list_quality_rules' \"id\" field, not rule_id)."}},
        "required": ["id"],
    },
}

_LIST_CHANNEL_PATTERNS_TOOL: dict[str, Any] = {
    "name": "list_channel_patterns",
    "description": (
        "This channel's proposed/confirmed/retired style patterns (anti- or "
        "good-polarity, with evidence) — machine-proposed from this "
        "channel's OWN analytics, never hardcoded, never cross-channel. "
        "Read-only, no cost."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "polarity": {"type": "string", "description": "Filter: \"anti\" or \"good\"."},
            "status": {"type": "string", "description": "Filter: \"proposed\", \"confirmed\", or \"retired\"."},
        },
    },
}

_CONFIRM_CHANNEL_PATTERN_TOOL: dict[str, Any] = {
    "name": "confirm_channel_pattern",
    "description": (
        "Confirm a proposed pattern — the ONLY transition that makes an "
        "anti-pattern actually exclude a video/style from future style-seed/"
        "few-shot sets. Free, no cost. Calling this on behalf of your owner "
        "IS the human confirm gate (OR-6) — it's attributed to you like "
        "every other MCP write."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {"id": {"type": "string", "description": "The pattern's internal id (from list_channel_patterns)."}},
        "required": ["id"],
    },
}

_RETIRE_CHANNEL_PATTERN_TOOL: dict[str, Any] = {
    "name": "retire_channel_pattern",
    "description": "Retire a confirmed (or reject a still-proposed) pattern — reverses its exclusion effect. Free, no cost.",
    "inputSchema": {
        "type": "object",
        "properties": {"id": {"type": "string", "description": "The pattern's internal id (from list_channel_patterns)."}},
        "required": ["id"],
    },
}

_GET_SCRIPT_TEMPLATE_TOOL: dict[str, Any] = {
    "name": "get_script_template",
    "description": "The channel's house script-format template(s) (format instructions distilled from an example, never the example's topic content). Read-only, no cost.",
    "inputSchema": {"type": "object", "properties": {}},
}

_SET_SCRIPT_TEMPLATE_TOOL: dict[str, Any] = {
    "name": "set_script_template",
    "description": (
        "Distill an example script's FORMAT (hook shape, structure, "
        "pacing, sign-off — never its topic) into the channel's house "
        "template. One Claude call, cheap. WARNING: only one house template "
        "is kept at a time — this REPLACES any existing one, it does not "
        "add a second."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "The full example script (40+ words)."},
            "name": {"type": "string", "description": "A label for this template, optional."},
        },
        "required": ["text"],
    },
}

_LIST_SCRIPT_PROFILES_TOOL: dict[str, Any] = {
    "name": "list_script_profiles",
    "description": (
        "The editorial-voice engine catalog (id, display name, description, "
        "best_for) for picking a script voice. To SET a video's voice, use "
        "the script_profile tool (free-text alias, e.g. \"investigative "
        "reveal\", or \"neutral\"/\"auto\" to clear). Read-only, no cost."
    ),
    "inputSchema": {"type": "object", "properties": {}},
}

_GET_SYSTEM_PROMPTS_TOOL: dict[str, Any] = {
    "name": "get_system_prompts",
    "description": "This tenant's 6 system prompts (script, thumbnail, video_motion, sound_curation, sound_generation, research) — custom override or pipeline default, with which is which flagged. Read-only, no cost.",
    "inputSchema": {"type": "object", "properties": {}},
}

_SET_SYSTEM_PROMPT_TOOL: dict[str, Any] = {
    "name": "set_system_prompt",
    "description": "Save a custom override for one system prompt key. Free, no cost — takes effect on the next run of that stage.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "One of: script, thumbnail, video_motion, sound_curation, sound_generation, research."},
            "prompt_text": {"type": "string", "description": "The full prompt text."},
        },
        "required": ["key", "prompt_text"],
    },
}

_SET_RENDER_STYLE_TOOL: dict[str, Any] = {
    "name": "set_render_style",
    "description": (
        "Set a video's channel-look routing guardrail (animated / "
        "realistic) — steers which clip-model tier the build routes to. "
        "Free, no cost. Pass \"auto\" to clear it back to undeclared."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "video_id": {"type": "string", "description": "Video UUID."},
            "render_style": {"type": "string", "description": "\"animated\", \"realistic\", or \"auto\" to clear."},
        },
        "required": ["video_id", "render_style"],
    },
}

_SET_STYLE_PRESET_TOOL: dict[str, Any] = {
    "name": "set_style_preset",
    "description": (
        "Set a video's visual-profile engine (see list_style_presets for "
        "ids) after creation. Free, no cost. Pass \"auto\" to clear it."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "video_id": {"type": "string", "description": "Video UUID."},
            "style_preset_id": {"type": "string", "description": "An id from list_style_presets, or \"auto\" to clear."},
        },
        "required": ["video_id", "style_preset_id"],
    },
}

_SETUP_TOOLS: list[dict[str, Any]] = [
    _GET_CHANNEL_DNA_TOOL, _LEARN_CHANNEL_START_TOOL, _LEARN_CHANNEL_STATUS_TOOL,
    _LIST_QUALITY_RULES_TOOL, _UPSERT_QUALITY_RULE_TOOL, _DEACTIVATE_QUALITY_RULE_TOOL,
    _LIST_CHANNEL_PATTERNS_TOOL, _CONFIRM_CHANNEL_PATTERN_TOOL, _RETIRE_CHANNEL_PATTERN_TOOL,
    _GET_SCRIPT_TEMPLATE_TOOL, _SET_SCRIPT_TEMPLATE_TOOL, _LIST_SCRIPT_PROFILES_TOOL,
    _GET_SYSTEM_PROMPTS_TOOL, _SET_SYSTEM_PROMPT_TOOL,
    _SET_RENDER_STYLE_TOOL, _SET_STYLE_PRESET_TOOL,
]


async def _call_get_channel_dna(tenant_id, arguments: dict[str, Any], caller: str) -> dict[str, Any]:
    from channel_dna import _current_identity
    identity = await _current_identity(tenant_id)
    return _text_result(identity)


async def _call_learn_channel_start(tenant_id, arguments: dict[str, Any], caller: str,
                                     background_tasks: Optional[BackgroundTasks]) -> dict[str, Any]:
    if background_tasks is None:
        return _error_result("Internal error: no task runner available for this call")
    from routes.channel_dna import LearnChannelRequest, start_learn_channel
    _log_setup_write("learn_channel_start", tenant_id, caller)
    body = LearnChannelRequest(
        channel_url=arguments.get("channel_url"),
        example_script_text=arguments.get("example_script_text"),
        reference_video_url=arguments.get("reference_video_url"),
    )
    result = await start_learn_channel(body, background_tasks, tenant_id=tenant_id)
    return _text_result(result.model_dump())


async def _call_learn_channel_status(tenant_id, arguments: dict[str, Any], caller: str) -> dict[str, Any]:
    from routes.channel_dna import get_learn_channel_status
    result = await get_learn_channel_status(tenant_id=tenant_id)
    return _text_result(result.model_dump())


async def _call_list_quality_rules(tenant_id, arguments: dict[str, Any], caller: str) -> dict[str, Any]:
    import quality_rules
    rows = await quality_rules.list_all_rules(tenant_id, active_only=bool(arguments.get("active_only")))
    return _text_result({"rules": rows})


async def _call_upsert_quality_rule(tenant_id, arguments: dict[str, Any], caller: str) -> dict[str, Any]:
    import quality_rules
    rule_id = (arguments.get("rule_id") or "").strip()
    law = (arguments.get("law") or "").strip()
    if not rule_id or not law:
        return _error_result("upsert_quality_rule requires rule_id and law")
    severity = arguments.get("severity") or "guidance"
    if severity not in quality_rules.SEVERITIES:
        return _error_result(f"severity must be one of {sorted(quality_rules.SEVERITIES)}")
    _log_setup_write("upsert_quality_rule", tenant_id, caller, detail=rule_id)
    row = await quality_rules.create_rule(
        tenant_id, rule_id=rule_id, law=law, severity=severity,
        evidence=arguments.get("evidence"), applies_to=arguments.get("applies_to"),
        source="mcp_agent",
    )
    return _text_result({"rule": row})


async def _call_deactivate_quality_rule(tenant_id, arguments: dict[str, Any], caller: str) -> dict[str, Any]:
    import quality_rules
    rule_id = arguments.get("id")
    if not rule_id:
        return _error_result("deactivate_quality_rule requires an id argument")
    _log_setup_write("deactivate_quality_rule", tenant_id, caller, detail=str(rule_id))
    ok = await quality_rules.deactivate_rule(tenant_id, str(rule_id))
    if not ok:
        return _error_result(f"No quality rule {rule_id} found for this tenant")
    return _text_result({"status": "deactivated", "id": rule_id})


async def _call_list_channel_patterns(tenant_id, arguments: dict[str, Any], caller: str) -> dict[str, Any]:
    import channel_patterns
    rows = await channel_patterns.list_patterns(
        tenant_id, polarity=arguments.get("polarity"), status=arguments.get("status"),
    )
    return _text_result({"patterns": rows})


async def _call_confirm_channel_pattern(tenant_id, arguments: dict[str, Any], caller: str) -> dict[str, Any]:
    import channel_patterns
    pattern_id = arguments.get("id")
    if not pattern_id:
        return _error_result("confirm_channel_pattern requires an id argument")
    row = await channel_patterns.confirm_pattern(tenant_id, str(pattern_id), confirmed_by=caller)
    if row is None:
        return _error_result(f"No pattern {pattern_id} found for this tenant")
    return _text_result({"pattern": row})


async def _call_retire_channel_pattern(tenant_id, arguments: dict[str, Any], caller: str) -> dict[str, Any]:
    import channel_patterns
    pattern_id = arguments.get("id")
    if not pattern_id:
        return _error_result("retire_channel_pattern requires an id argument")
    row = await channel_patterns.retire_pattern(tenant_id, str(pattern_id), confirmed_by=caller)
    if row is None:
        return _error_result(f"No pattern {pattern_id} found for this tenant")
    return _text_result({"pattern": row})


async def _call_get_script_template(tenant_id, arguments: dict[str, Any], caller: str) -> dict[str, Any]:
    from routes.script_templates import list_templates as _list_templates_route
    result = await _list_templates_route(tenant_id=tenant_id)
    return _text_result(result)


async def _call_set_script_template(tenant_id, arguments: dict[str, Any], caller: str) -> dict[str, Any]:
    text = (arguments.get("text") or "").strip()
    if not text:
        return _error_result("set_script_template requires text")
    from routes.script_templates import analyze_and_save_template
    existing = await fetch_one("SELECT id FROM script_templates WHERE tenant_id = $1 LIMIT 1", tenant_id)
    _log_setup_write("set_script_template", tenant_id, caller)
    try:
        tpl = await analyze_and_save_template(tenant_id, text, str(arguments.get("name") or ""))
    except ValueError as e:
        return _error_result(str(e))
    return _text_result({
        "status": "replaced" if existing else "saved",
        "template": tpl,
    })


async def _call_list_script_profiles(tenant_id, arguments: dict[str, Any], caller: str) -> dict[str, Any]:
    from routes.script_profiles import list_script_profiles as _list_script_profiles_route
    result = await _list_script_profiles_route(tenant_id=tenant_id)
    return _text_result(result.model_dump())


async def _call_get_system_prompts(tenant_id, arguments: dict[str, Any], caller: str) -> dict[str, Any]:
    from routes.system_prompts import list_prompts as _list_prompts_route
    result = await _list_prompts_route(tenant_id=tenant_id)
    return _text_result({"prompts": result})


async def _call_set_system_prompt(tenant_id, arguments: dict[str, Any], caller: str) -> dict[str, Any]:
    key = (arguments.get("key") or "").strip()
    prompt_text = arguments.get("prompt_text")
    if not key or not prompt_text:
        return _error_result("set_system_prompt requires key and prompt_text")
    from routes.system_prompts import PromptUpdate, upsert_prompt as _upsert_prompt_route
    _log_setup_write("set_system_prompt", tenant_id, caller, detail=key)
    try:
        result = await _upsert_prompt_route(key, PromptUpdate(prompt_text=prompt_text), tenant_id=tenant_id)
    except HTTPException as e:
        return _error_result(e.detail if isinstance(e.detail, str) else "Couldn't save that prompt")
    return _text_result(result)


async def _call_set_render_style(tenant_id, arguments: dict[str, Any], caller: str) -> dict[str, Any]:
    video_id = arguments.get("video_id")
    if not video_id:
        return _error_result("set_render_style requires a video_id argument")
    value = _clear_alias(arguments.get("render_style"))
    from routes.videos import update_video as _update_video_route
    _log_setup_write("set_render_style", tenant_id, caller, detail=f"video={video_id}")
    try:
        result = await _update_video_route(str(video_id), {"render_style": value}, tenant_id=tenant_id)
    except HTTPException as e:
        return _error_result(e.detail if isinstance(e.detail, str) else "Couldn't set render_style")
    return _text_result(result)


async def _call_set_style_preset(tenant_id, arguments: dict[str, Any], caller: str) -> dict[str, Any]:
    video_id = arguments.get("video_id")
    if not video_id:
        return _error_result("set_style_preset requires a video_id argument")
    value = _clear_alias(arguments.get("style_preset_id"))
    from routes.videos import update_video as _update_video_route
    _log_setup_write("set_style_preset", tenant_id, caller, detail=f"video={video_id}")
    try:
        result = await _update_video_route(str(video_id), {"style_preset_id": value}, tenant_id=tenant_id)
    except HTTPException as e:
        return _error_result(e.detail if isinstance(e.detail, str) else "Couldn't set style_preset_id")
    return _text_result(result)


_SETUP_READ_HANDLERS = {
    "get_channel_dna": _call_get_channel_dna,
    "learn_channel_status": _call_learn_channel_status,
    "list_quality_rules": _call_list_quality_rules,
    "list_channel_patterns": _call_list_channel_patterns,
    "get_script_template": _call_get_script_template,
    "list_script_profiles": _call_list_script_profiles,
    "get_system_prompts": _call_get_system_prompts,
}

_SETUP_WRITE_HANDLERS = {
    "upsert_quality_rule": _call_upsert_quality_rule,
    "deactivate_quality_rule": _call_deactivate_quality_rule,
    "confirm_channel_pattern": _call_confirm_channel_pattern,
    "retire_channel_pattern": _call_retire_channel_pattern,
    "set_script_template": _call_set_script_template,
    "set_system_prompt": _call_set_system_prompt,
    "set_render_style": _call_set_render_style,
    "set_style_preset": _call_set_style_preset,
}


# =============================================================================
# AUTOPILOT PROPOSAL TOOLS (checklist C52, P4.2-c — the read/decide surface
# for C51's propose_only dry-run loop, autopilot_proposals.py). Every write
# here calls the SAME routes.autopilot.accept_proposal/dismiss_proposal
# functions the HTTP door (POST /api/autopilot/proposals/{id}/accept|dismiss)
# calls — no parallel accept/dismiss logic.
#
# Classification per this module's money-gate house rules (see docstring
# above): accept_autopilot_proposal is NOT wrapped with a confirm_token.
# Per the checklist's own instruction this needed a real judgment call, not
# just following the create_video precedent blindly — accept_proposal does
# MORE than create_video (which only inserts a row): it calls
# launch_candidate, which ALSO kicks off a background loop that runs
# research and then auto-advances through pipeline stages
# (routes/autopilot.py's `_run_full_pipeline`) until a stage fails, needs
# approval, or goes idle. The reason this still classifies as free rather
# than PAID-confirm-gated: (1) it is not an actions.ACTIONS verb at all —
# the confirm_token gate in `_call_verb` only wraps that specific registry;
# (2) launch_candidate is an EXISTING endpoint a human's "Launch" button
# already calls with zero gate, and C51 already calls it unguarded for
# auto_draft/full_auto dial tenants — accept_autopilot_proposal adds no new
# unguarded path, it only lets a human (or an agent acting for one) trigger
# that SAME existing path for one specific proposal; (3) every individual
# PAID stage the background loop reaches (images, clips, thumbnail, ...)
# still enforces its own confirm-token/needs_approval gate when reached
# through any OTHER door — this tool doesn't touch or bypass those, it only
# starts the SAME research-then-advance loop launch_candidate already runs
# unconditionally today. Attribution is the fixed literal 'mcp_agent' (the
# checklist's explicit choice here, unlike the dynamic `caller` name used
# elsewhere in this file) — kept simple since accept/dismiss are tenant-
# scoped single-proposal actions, not a durable content-authorship column.
# =============================================================================

_LIST_AUTOPILOT_PROPOSALS_TOOL: dict[str, Any] = {
    "name": "list_autopilot_proposals",
    "description": (
        "List autopilot's propose_only picks awaiting a decision: candidate title, "
        "confidence score + breakdown, when it was proposed, and its status. "
        "Read-only, no cost."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "description": "Filter by status (default 'proposed'). Pass 'all' for every status.",
            },
        },
    },
}

_ACCEPT_AUTOPILOT_PROPOSAL_TOOL: dict[str, Any] = {
    "name": "accept_autopilot_proposal",
    "description": (
        "Accept a propose_only candidate — free, no confirm_token (see module docstring "
        "for why). Calls the SAME launch_candidate path a human clicking Launch already "
        "uses unguarded: creates a video and starts the pipeline in the background. Every "
        "PAID stage the pipeline reaches still enforces its own confirm/needs_approval "
        "gate — this does not bypass those. Refuses if the autopilot kill switch is "
        "tripped. A proposal already accepted/dismissed cannot be re-accepted."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "proposal_id": {"type": "string", "description": "autopilot_proposals row id."},
        },
        "required": ["proposal_id"],
    },
}

_DISMISS_AUTOPILOT_PROPOSAL_TOOL: dict[str, Any] = {
    "name": "dismiss_autopilot_proposal",
    "description": (
        "Dismiss a propose_only candidate without launching it — free, no video created, "
        "no confirm_token."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "proposal_id": {"type": "string", "description": "autopilot_proposals row id."},
        },
        "required": ["proposal_id"],
    },
}

_AUTOPILOT_PROPOSAL_TOOLS: list[dict[str, Any]] = [
    _LIST_AUTOPILOT_PROPOSALS_TOOL, _ACCEPT_AUTOPILOT_PROPOSAL_TOOL, _DISMISS_AUTOPILOT_PROPOSAL_TOOL,
]


async def _call_list_autopilot_proposals(tenant_id, arguments: dict[str, Any], caller: str) -> dict[str, Any]:
    import autopilot_proposals
    status = arguments.get("status") or "proposed"
    filter_status = None if str(status).lower() == "all" else status
    rows = await autopilot_proposals.list_proposals(tenant_id, status=filter_status, limit=50)
    return _text_result({"proposals": rows})


async def _call_accept_autopilot_proposal(tenant_id, arguments: dict[str, Any], caller: str,
                                           background_tasks: Optional[BackgroundTasks]) -> dict[str, Any]:
    proposal_id = arguments.get("proposal_id")
    if not proposal_id:
        return _error_result("accept_autopilot_proposal requires a proposal_id argument")
    if background_tasks is None:
        return _error_result("Internal error: no task runner available for this call")
    from routes.autopilot import accept_proposal
    try:
        result = await accept_proposal(
            tenant_id, str(proposal_id), background_tasks, decided_by="mcp_agent",
        )
    except HTTPException as e:
        return _error_result(e.detail if isinstance(e.detail, str) else "Couldn't accept the proposal")
    return _text_result(result.model_dump())


async def _call_dismiss_autopilot_proposal(tenant_id, arguments: dict[str, Any], caller: str) -> dict[str, Any]:
    proposal_id = arguments.get("proposal_id")
    if not proposal_id:
        return _error_result("dismiss_autopilot_proposal requires a proposal_id argument")
    from routes.autopilot import dismiss_proposal
    try:
        result = await dismiss_proposal(tenant_id, str(proposal_id), decided_by="mcp_agent")
    except HTTPException as e:
        return _error_result(e.detail if isinstance(e.detail, str) else "Couldn't dismiss the proposal")
    return _text_result(result.model_dump())


_AUTOPILOT_PROPOSAL_READ_HANDLERS = {
    "list_autopilot_proposals": _call_list_autopilot_proposals,
}

_AUTOPILOT_PROPOSAL_WRITE_HANDLERS = {
    "dismiss_autopilot_proposal": _call_dismiss_autopilot_proposal,
}


# =============================================================================
# AUTOPILOT DIAL TOOLS (checklist C54, P4.2-e — the dial finally becomes
# settable, and a tripped kill switch finally becomes clearable, from MCP).
# Both writes go through the EXISTING route functions
# (routes.autopilot.update_config / routes.autopilot.reset_kill_switch) the
# SAME way set_render_style/set_style_preset above call routes.videos.
# update_video directly — no parallel write logic.
#
# Classification (this module's money-gate house rules, see docstring above):
#   - set_autopilot_dial: FREE, no confirm_token. Same bucket as set_render_
#     style/set_style_preset — a routing/config guardrail, not a spend
#     itself. Setting dial_level to auto_draft/full_auto does not spend
#     anything AT THIS CALL; it only changes which branch the NEXT autopilot
#     tick takes, and that tick still runs launch_candidate (same gates as a
#     human "Launch" click) and still enforces its own weekly-budget check
#     (autopilot_launch.py's auto_draft branch, C54) before anything paid
#     happens. weekly_budget_cap is a ceiling, never a spend trigger.
#
#     C54b (orchestrator hardening pass) is WHY free-with-no-confirm is
#     still safe here even though this tool alone could otherwise raise the
#     dial with no ceiling: this handler dispatches straight through
#     `routes.autopilot.update_config`, which enforces `autopilot_dial.
#     validate_dial_change` — the ONE shared "no autonomy without a
#     ceiling" invariant — before writing anything. A rogue/injected call
#     that tries `set_autopilot_dial(dial_level="auto_draft")` with no cap
#     anywhere gets a 400-equivalent `_error_result` back, not a silent
#     uncapped auto_draft tenant. No parallel validation lives here; this
#     handler is deliberately a thin pass-through so the invariant can't
#     drift between the HTTP door and this one.
#   - reset_autopilot_kill_switch: FREE, no confirm_token — the checklist
#     flagged this as a real judgment call ("re-arms spending automation"),
#     not a rubber-stamp. Decided FREE by the SAME precedent already used
#     for accept_autopilot_proposal above: (1) it is not an actions.ACTIONS
#     verb, so the confirm_token gate in `_call_verb` structurally doesn't
#     wrap it; (2) clearing the switch re-arms EXISTING unattended paths
#     (auto_draft launches, queue drain) that already run ungated by this
#     module today — it adds no new unguarded path, it only lets automation
#     that was already unguarded resume; (3) every individual PAID stage
#     those paths reach still enforces its own confirm-token/needs_approval
#     gate through any other door, AND (C54's own new gate) the weekly
#     budget is re-checked on every subsequent tick regardless — clearing
#     the switch does not bypass a future re-trip if spend is still over
#     cap. It is a control-plane switch (same shape as toggle_autopilot's
#     enable/disable, which has never been confirm-gated), not a quoted
#     paid action. C54b sharpens the worst-case bound further: because
#     `validate_dial_change` guarantees any elevated dial_level already has
#     an explicit, human-set ceiling, the WORST an agent calling this tool
#     (rogue or not) can do is let spend resume up to a ceiling a human
#     already chose — never uncapped. C54b also makes the tool's response
#     carry `previous_kill_switch_reason`/`previous_kill_switch_tripped_at`
#     (the trip it just cleared) so the calling agent is forced to see —
#     and can be made to surface to the human — WHAT went wrong, not just
#     that the switch is now clear.
# =============================================================================

_SET_AUTOPILOT_DIAL_TOOL: dict[str, Any] = {
    "name": "set_autopilot_dial",
    "description": (
        "Set the autopilot autonomy dial and/or the weekly spend ceiling. Free, no "
        "confirm_token (see module docstring's classification note — this changes routing "
        "for the NEXT autopilot tick, it doesn't spend anything itself; every paid stage "
        "reached from auto_draft/full_auto still enforces its own gates). dial_level: "
        "'propose_only' (autopilot only proposes, a human launches — today's default), "
        "'auto_draft' (autopilot may create a video/draft unattended), 'full_auto' (reserved, "
        "treated identically to auto_draft today). weekly_budget_cap: dollar ceiling on "
        "weekly autopilot spend; pass null to remove an existing cap. Provide either or both. "
        "INVARIANT: dial_level cannot be set above 'propose_only' unless weekly_budget_cap is "
        "already set on the account OR supplied in this SAME call — set both together the "
        "first time you raise the dial. Likewise, an existing cap cannot be cleared while "
        "dial_level is (or stays) elevated; lower dial_level to 'propose_only' in the same "
        "call if you want to remove the cap."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "dial_level": {"type": "string", "description": "One of: propose_only, auto_draft, full_auto."},
            "weekly_budget_cap": {
                "type": ["number", "null"],
                "description": "Dollar ceiling on weekly autopilot spend, or null to remove the cap.",
            },
        },
    },
}

_RESET_AUTOPILOT_KILL_SWITCH_TOOL: dict[str, Any] = {
    "name": "reset_autopilot_kill_switch",
    "description": (
        "Re-enable autopilot after an automatic kill-switch trip (e.g. a weekly budget "
        "breach). Free, no confirm_token — see module docstring's classification note: this "
        "only re-arms EXISTING automation paths (auto_draft launches, queue drain), each of "
        "which still enforces its own gates when it actually reaches a paid stage; it does "
        "not itself spend anything, and any elevated dial_level is guaranteed to already carry "
        "a human-set weekly_budget_cap (see set_autopilot_dial), so re-armed spend is always "
        "capped. Calling this when the switch isn't tripped is a harmless no-op. Attributed to "
        "the calling agent. The response carries previous_kill_switch_reason/_tripped_at — the "
        "trip THIS call just cleared — surface that to the human, don't just report success."
    ),
    "inputSchema": {"type": "object", "properties": {}},
}

_AUTOPILOT_DIAL_TOOLS: list[dict[str, Any]] = [
    _SET_AUTOPILOT_DIAL_TOOL, _RESET_AUTOPILOT_KILL_SWITCH_TOOL,
]


async def _call_set_autopilot_dial(tenant_id, arguments: dict[str, Any], caller: str) -> dict[str, Any]:
    from autopilot_dial import DIAL_LEVELS

    dial_level = arguments.get("dial_level")
    cap_provided = "weekly_budget_cap" in arguments
    weekly_budget_cap = arguments.get("weekly_budget_cap")

    if dial_level is None and not cap_provided:
        return _error_result("set_autopilot_dial requires dial_level and/or weekly_budget_cap")
    if dial_level is not None and dial_level not in DIAL_LEVELS:
        return _error_result(f"dial_level must be one of {DIAL_LEVELS}")
    if cap_provided and weekly_budget_cap is not None:
        try:
            weekly_budget_cap = float(weekly_budget_cap)
        except (TypeError, ValueError):
            return _error_result("weekly_budget_cap must be a number or null")
        if weekly_budget_cap <= 0:
            return _error_result("weekly_budget_cap must be greater than 0 (or null to remove the cap)")

    from routes.autopilot import ConfigUpdate
    from routes.autopilot import update_config as _update_config_route

    body_kwargs: dict[str, Any] = {}
    if dial_level is not None:
        body_kwargs["dial_level"] = dial_level
    if cap_provided:
        body_kwargs["weekly_budget_cap"] = weekly_budget_cap

    _log_setup_write("set_autopilot_dial", tenant_id, caller, detail=str(body_kwargs))
    try:
        result = await _update_config_route(ConfigUpdate(**body_kwargs), tenant_id=tenant_id)
    except HTTPException as e:
        return _error_result(e.detail if isinstance(e.detail, str) else "Couldn't set the autopilot dial")
    return _text_result(result)


async def _call_reset_autopilot_kill_switch(tenant_id, arguments: dict[str, Any], caller: str) -> dict[str, Any]:
    from auth import AuthUser
    from routes.autopilot import reset_kill_switch as _reset_kill_switch_route

    _log_setup_write("reset_autopilot_kill_switch", tenant_id, caller)
    user = AuthUser(id="mcp_agent", email=caller)
    result = await _reset_kill_switch_route(user=user, tenant_id=tenant_id)
    return _text_result(result.model_dump())


_AUTOPILOT_DIAL_WRITE_HANDLERS = {
    "set_autopilot_dial": _call_set_autopilot_dial,
    "reset_autopilot_kill_switch": _call_reset_autopilot_kill_switch,
}


# =============================================================================
# INGEST TOOLS (checklist C47 — decisions.md 2026-07-19 "MCP economics"
# entry): the connected agent does research/scripting on the user's OWN
# Claude subscription and hands StoryEngine the RESULT through the SAME
# validated store+advance paths run_research/run_script use — thinking is
# free (the agent's subscription), only the media pipeline that follows
# spends BYOK API keys. Neither tool carries a confirm_token: submitting
# your own already-done thinking doesn't itself spend StoryEngine-billed
# money (same "free — writes only" posture as the setup tools above), and
# `videos.script`/`research_payload` were never anything a confirm_token
# gated in the first place (the `research`/`script` PAID verbs gate the
# COST of having the platform's OWN Claude call do the work, which these
# tools skip entirely).
# =============================================================================

_SUBMIT_RESEARCH_TOOL: dict[str, Any] = {
    "name": "submit_research",
    "description": (
        "Submit research YOU did (on your own Claude subscription) for this "
        "video, instead of paying for StoryEngine's own `research` verb to "
        "do it. Validated against the same shape run_research itself "
        "produces and the SAME deterministic roster-completeness gate a "
        "real research run applies for machine-roster/documentary titles — "
        "a rejection returns the concrete warnings so you can fix your "
        "research and resubmit. On acceptance, saved and the video advances "
        "exactly like a platform-run research pass. Free — no cost to run "
        "this tool itself."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "video_id": {"type": "string", "description": "Video UUID."},
            "payload": {
                "type": "object",
                "description": (
                    "The research payload. Common fields: headline, thesis, "
                    "executive_hook. For a machine-roster/documentary title, "
                    "also: unit_roster (list), unit_research_cards (list), "
                    "machine_discovery_buckets (object), recommended_final_roster "
                    "(list), gap_hunt_matrix (list), edge_case_matrix (list), "
                    "roster_audit (object), roster_contract (string), "
                    "counter_arguments (string)."
                ),
            },
        },
        "required": ["video_id", "payload"],
    },
}

_SUBMIT_SCRIPT_TOOL: dict[str, Any] = {
    "name": "submit_script",
    "description": (
        "Submit a script YOU wrote (on your own Claude subscription) for "
        "this video, instead of paying for StoryEngine's own `script` verb "
        "to write it. Runs through the SAME quality-rules critic a "
        "platform-generated script faces (verdict-only, no server-side "
        "edit loop — this is not the creator's own verbatim text, so it "
        "doesn't get that bypass, but it's also not ours to silently "
        "rewrite). A hard-gate/universal-gate failure REJECTS with the "
        "rule-by-rule violations so you can fix your script and resubmit; "
        "a pass (warnings aside) saves and advances the video exactly like "
        "a platform-written script. Free — no cost to run this tool itself."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "video_id": {"type": "string", "description": "Video UUID."},
            "scenes": {
                "type": "array",
                "description": "Ordered scenes: [{\"text\": \"...\"}, ...]. Scene numbers are assigned 1..N from this order.",
                "items": {
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
            },
        },
        "required": ["video_id", "scenes"],
    },
}

_INGEST_TOOLS: list[dict[str, Any]] = [_SUBMIT_RESEARCH_TOOL, _SUBMIT_SCRIPT_TOOL]


async def _call_submit_research(tenant_id, arguments: dict[str, Any], caller: str) -> dict[str, Any]:
    video_id = arguments.get("video_id")
    if not video_id:
        return _error_result("submit_research requires a video_id argument")
    payload = arguments.get("payload")
    import research_ingest
    try:
        result = await research_ingest.accept_submitted_research(
            tenant_id, str(video_id), payload, source=caller,
        )
    except ValueError as e:
        return _error_result(str(e))
    return _text_result(result)


async def _call_submit_script(tenant_id, arguments: dict[str, Any], caller: str) -> dict[str, Any]:
    video_id = arguments.get("video_id")
    if not video_id:
        return _error_result("submit_script requires a video_id argument")
    scenes = arguments.get("scenes")
    import user_script
    try:
        result = await user_script.accept_external_script(
            tenant_id, str(video_id), scenes, source="agent_submitted",
        )
    except ValueError as e:
        return _error_result(str(e))
    return _text_result(result)


_INGEST_HANDLERS = {
    "submit_research": _call_submit_research,
    "submit_script": _call_submit_script,
}


TOOLS: list[dict[str, Any]] = (
    _READ_TOOLS + [_CREATE_VIDEO_TOOL] + _verb_tools() + _SETUP_TOOLS
    + _AUTOPILOT_PROPOSAL_TOOLS + _AUTOPILOT_DIAL_TOOLS + _INGEST_TOOLS
)

# Names only — used by tests to pin the surface never silently grows a
# remember/forget (memory-writing, S5-2) tool, and that every paid verb in
# actions.ACTIONS actually appears quote-gated.
TOOL_NAMES = frozenset(t["name"] for t in TOOLS)


async def _call_verb(tenant_id, verb: str, arguments: dict[str, Any],
                      background_tasks: Optional[BackgroundTasks], caller: str) -> dict[str, Any]:
    cfg = actions.ACTIONS[verb]
    video_id = arguments.get("video_id")
    if not video_id:
        return _error_result(f"{verb} requires a video_id argument")
    video_id = str(video_id)
    scene = _coerce_scene(arguments.get("scene"))
    change = (arguments.get("change") or "").strip() or None
    length_min = arguments.get("length_min")

    summary = await actions.video_summary(tenant_id, video_id)
    if summary is None:
        return _error_result(f"No video {video_id} found for this tenant")

    blocked = actions.blocked_reason(verb, summary)
    if blocked:
        return _error_result(f"Can't {cfg['label'].lower()} yet — {blocked}")

    pending: dict[str, Any] = {"verb": verb, "scene": scene, "change": change, "length_min": length_min}
    target = None
    if verb == "build":
        target = "pictures" if summary["status"] in actions.BUILD_TO_PICTURES else "finish"
        pending["target"] = target

    if background_tasks is None:
        return _error_result("Internal error: no task runner available for this call")

    from routes.chat import _run_pending_action

    if not cfg["paid"]:
        line = await _run_pending_action(tenant_id, video_id, pending, background_tasks, caller=caller)
        return _text_result({"status": "done", "verb": verb, "scene": scene, "message": line})

    # --- PAID: the money gate -------------------------------------------
    phash = confirm_tokens.params_hash(verb, scene, change, length_min, target)
    confirm_token = arguments.get("confirm_token")

    # C16e (S7-9): the same "already uploaded" short-circuit chat's confirm-
    # card path applies, checked before minting a fresh quote/token so a
    # repeat "upload" call never gets a new confirm_token for a second draft.
    if verb == "upload":
        already = await actions.already_uploaded_reply(tenant_id, video_id)
        if already:
            return _text_result({"status": "already_done", "verb": verb, "message": already})

    if not confirm_token:
        cost, cost_text = await actions.estimate_cost(tenant_id, video_id, verb, scene, summary)
        breakdown = await actions.cost_breakdown(tenant_id, video_id, verb, scene, summary)
        token = await confirm_tokens.create(tenant_id, video_id, verb, phash)
        quote: dict[str, Any] = {
            "status": "quote",
            "verb": verb,
            "scene": scene,
            "cost": cost,
            "cost_text": cost_text,
            "confirm_token": token,
            "expires_in_seconds": confirm_tokens.TTL_SECONDS,
            "note": "Call this same tool again with these SAME arguments plus confirm_token to run it.",
        }
        if breakdown:
            quote["breakdown"] = breakdown
        # C36 (checklist §3.3 item 3): same optional per-video budget cap
        # chat.py's confirm card surfaces — the quote says so honestly
        # instead of silently minting a confirm_token as if nothing were
        # different; the agent still gets a valid token and can proceed
        # (redeeming it IS the explicit override), it's just told first.
        budget_warning = actions.budget_check(summary, cost)
        if budget_warning:
            quote["budget_warning"] = budget_warning
        return _text_result(quote)

    ok = await confirm_tokens.redeem(tenant_id, video_id, verb, phash, confirm_token)
    if not ok:
        return _error_result(
            "confirm_token is invalid, expired, already used, or doesn't match these exact "
            "arguments — call this tool again WITHOUT confirm_token to get a fresh quote."
        )
    line = await _run_pending_action(tenant_id, video_id, pending, background_tasks, caller=caller)
    return _text_result({"status": "started", "verb": verb, "scene": scene, "message": line})


async def _dispatch(method: str, params: dict[str, Any], tenant_id,
                     background_tasks: Optional[BackgroundTasks] = None,
                     caller: str = "agent") -> Any:
    if method == "initialize":
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        }
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        name = (params or {}).get("name")
        arguments = (params or {}).get("arguments") or {}
        if name in _READ_HANDLERS:
            return await _READ_HANDLERS[name](tenant_id, arguments)
        if name == "create_video":
            return await _call_create_video(tenant_id, arguments, background_tasks)
        if name in actions.ACTIONS:
            return await _call_verb(tenant_id, name, arguments, background_tasks, caller)
        if name == "learn_channel_start":
            return await _call_learn_channel_start(tenant_id, arguments, caller, background_tasks)
        if name in _SETUP_READ_HANDLERS:
            return await _SETUP_READ_HANDLERS[name](tenant_id, arguments, caller)
        if name in _SETUP_WRITE_HANDLERS:
            return await _SETUP_WRITE_HANDLERS[name](tenant_id, arguments, caller)
        if name == "accept_autopilot_proposal":
            return await _call_accept_autopilot_proposal(tenant_id, arguments, caller, background_tasks)
        if name in _AUTOPILOT_PROPOSAL_READ_HANDLERS:
            return await _AUTOPILOT_PROPOSAL_READ_HANDLERS[name](tenant_id, arguments, caller)
        if name in _AUTOPILOT_PROPOSAL_WRITE_HANDLERS:
            return await _AUTOPILOT_PROPOSAL_WRITE_HANDLERS[name](tenant_id, arguments, caller)
        if name in _AUTOPILOT_DIAL_WRITE_HANDLERS:
            return await _AUTOPILOT_DIAL_WRITE_HANDLERS[name](tenant_id, arguments, caller)
        if name in _INGEST_HANDLERS:
            return await _INGEST_HANDLERS[name](tenant_id, arguments, caller)
        return _error_result(f"Unknown tool: {name}")
    raise ValueError(f"Unknown method: {method}")


@router.post("")
async def mcp_rpc(request: Request, background_tasks: BackgroundTasks,
                   tenant_id=Depends(get_agent_tenant_id)):
    """Single JSON-RPC 2.0 endpoint. See module docstring for the protocol
    shape this implements (initialize / tools/list / tools/call only)."""
    body = await request.json()
    rpc_id = body.get("id")
    method = body.get("method")
    params = body.get("params") or {}

    # Attribution (C27 seam for C28's "via agent" chip) — resolve the calling
    # token's display name. Fail-soft: name_for_token never raises, and a
    # miss just falls back to the generic "agent" marker, never blocks the call.
    auth_header = request.headers.get("authorization", "")
    token = auth_header[len("Bearer "):].strip() if auth_header.startswith("Bearer ") else ""
    agent_name = await agent_tokens.name_for_token(token)
    caller = f"agent:{agent_name}" if agent_name else "agent"

    try:
        result = await _dispatch(method, params, tenant_id, background_tasks, caller)
    except ValueError as e:
        return JSONResponse({
            "jsonrpc": "2.0", "id": rpc_id,
            "error": {"code": -32601, "message": str(e)},
        })
    except Exception as e:
        return JSONResponse({
            "jsonrpc": "2.0", "id": rpc_id,
            "error": {"code": -32000, "message": str(e)},
        })
    return {"jsonrpc": "2.0", "id": rpc_id, "result": result}
