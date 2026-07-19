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

import actions
import agent_tokens
import confirm_tokens
from auth_agent import get_agent_tenant_id
from database import fetch_all

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


TOOLS: list[dict[str, Any]] = _READ_TOOLS + [_CREATE_VIDEO_TOOL] + _verb_tools()

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
