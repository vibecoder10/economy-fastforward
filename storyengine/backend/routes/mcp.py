"""StoryEngine MCP server — the "talk to it from Claude" door (checklist
P2.4a/P2.4b, chunks C26/C27; tasks/storyengine-copilot-ux-map.md §7, "the
Higgsfield-killer door").

DARK BY DEFAULT: this router only registers in main.py when
`MCP_ENABLED=true`. Default/unset -> these routes structurally do not exist
(404, not "exists but blocked") — see main.py's registration comment. C25a's
media-proxy tenant-auth fix (the signed `?token=` gate on routes/media.py)
merged and deployed 2026-07-21 (tasks/decisions.md same date) — that's what
unblocked TOOL SURFACE v6 (C48) below, which is the first version of this
server allowed to put a (signed, short-lived) media URL in a tool result.

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
    get_channel_dna, get_channel_identity_context (P1 chat channel-identity
    rebuild — the composed identity POOL: dna + locked cast + format + this
    channel's OWN median runtime + confirmed title patterns + the script-
    profile catalog + any custom script prompt, see channel_identity_
    context.py), learn_channel_start (the one tool here with a real,
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

TOOL SURFACE v6 (C48 — checklist "Media-bearing MCP tools + creation-
walkthrough recipe", now unblocked: C25a's signed tenant-scoped media proxy
merged+deployed 2026-07-21, tasks/decisions.md same date "PROCESS-AWARE"
entry): the blanket "no media URL" rule below is LIFTED for exactly one
shape — a SIGNED, SHORT-LIVED media-proxy URL, never a raw Drive/storage
link. Four read tools + one staged convenience tool:
  get_scene_boards (a scene's drawn pictures, or a no-image per-scene count
    summary when `scene` is omitted — the MCP twin of chat.py's C15b "show"
    op, `_handle_show_op`), get_character_sheets (a video's designed cast,
    or the channel-level locked cast when `video_id` is omitted —
    routes.characters.list_characters / routes.projects.get_channel_cast),
    get_environment_images (routes.environments.list_environments),
    get_thumbnail_image (videos.thumbnail_url). Every one signs its URL(s)
    via `_sign_media_url` below, which is a THIN wrapper over
    `shared.clients.image_client._kie_fetchable_url` — the EXACT same
    signing call Kie's own image-to-image ingestion already uses
    (C25a-fix2) — not a parallel signing scheme. TTL is whatever
    `routes.media.mint_media_token`'s own default (60 minutes) is; every
    result's `note` field states it so the calling agent relays it instead
    of caching a URL past its life.
  quick_demo_video: the one-off "demonstrate quickly" convenience path
    (Ryan 2026-07-19). STAGED, not one-shot — it does not weaken the money
    gate. Call 1 (no video_id): create_video verbatim (free). Call 2+
    (video_id, no confirm_token): a price quote. Final call (+
    confirm_token): starts. Calls 2/3 are a THIN pass-through to `_call_verb`
    with verb="build" — the SAME existing meta-verb (script + cast +
    pictures, auto-advances to the pictures checkpoint) every button/chat
    "build it" already uses; no new pipeline logic, no new gate.

Explicitly EXCLUDED from v1 (docs/reports/2026-07-17-storyengine-agent-
audit-findings.md §S5):
  - Any memory-writing tool (remember/forget) — S5-2 says MCP v1 must
    EXCLUDE memory-writing tools outright. Not in actions.ACTIONS at all,
    so there is nothing to wrap; pinned by a test regardless.
  - Any UNSIGNED media/asset URL in any tool result. get_scenes/get_script
    are hand-written queries that never SELECT an *_url column; get_ledger's
    kie_task_id is an opaque provider job id, not a URL;
    list_style_presets' preview_url is explicitly stripped before return
    (belt-and-suspenders — same posture C26 took with get_video). The C48
    media tools above are the sole exception, and even they only ever
    return a SIGNED, short-lived proxy URL — never the raw stored link.

Auth: get_agent_tenant_id (auth_agent.py) — the DISTINCT agent-token
dependency (S5-4), never auth.verify_token/get_tenant_id.
"""
from __future__ import annotations

import asyncio
import json
import secrets
from typing import Any, AsyncIterator, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

import logging

import actions
import agent_tokens
import confirm_tokens
import production_guide
from auth_agent import get_agent_tenant_id
from database import fetch_all, fetch_one

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mcp", tags=["mcp"])

PROTOCOL_VERSION = "2025-06-18"
# C25a-fix11: versions this server can honestly claim to speak over THIS
# transport (single-POST JSON-RPC + the notifications/GET-listen additions
# this chunk adds). 2024-11-05 is deliberately excluded — that revision
# means the OLD separate HTTP+SSE transport (a different endpoint shape),
# not this one; claiming it would be a lie the spec's own backwards-
# compatibility section would catch a client out on.
SUPPORTED_PROTOCOL_VERSIONS = {"2025-06-18", "2025-03-26"}
SERVER_INFO = {"name": "storyengine", "version": "1.0.0"}

# C25a-fix13 (tasks/decisions.md 2026-07-19 "MCP economics"): the initialize
# result's optional `instructions` field is the one place this server can
# hand a connected client global operating guidance BEFORE it ever reads a
# single tool description — set it here so the economics rule survives even
# if a client only skims tools/list. Per-tool detail still lives on each
# tool's own description (the "[USES WORKSPACE API KEYS]" marker below); this
# is the one-paragraph version of the same rule.
SERVER_INSTRUCTIONS = (
    "Cost model: this workspace pays for every tool marked \"[USES WORKSPACE "
    "API KEYS]\" in tools/list out of its own paid API keys (Anthropic/"
    "kie.ai/ElevenLabs/etc) — that includes the research, script, and seo "
    "verbs, plus improve_prompt, regenerate_scene_text, suggest_video_"
    "titles, generate_modeled_ideas, and generate_gap_titles. For that "
    "pure-text thinking work, you are usually just as good and strictly "
    "cheaper: do the thinking yourself, in this chat, on your own "
    "subscription, then hand StoryEngine the RESULT through a free write "
    "tool — submit_research, submit_script, edit_publish_info, "
    "edit_scene_text, or edit_shot_image_prompt/edit_shot_motion_prompt — "
    "instead of calling the paid tool. Treat the paid LLM tools as a "
    "fallback for when you'd rather StoryEngine's own model do it, not the "
    "default. Tools that produce an actual media asset (pictures, clips, "
    "voice, thumbnails, render) are real provider spend either way and have "
    "no free substitute — call those directly, no special handling needed."
)


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
# C48 media signing — see the module docstring's "TOOL SURFACE v6" section.
# =============================================================================

def _media_token_ttl_minutes() -> int:
    """The real TTL a signed media URL carries — read off
    `routes.media.mint_media_token`'s own default parameter rather than a
    second hardcoded literal, so this number can never drift from what the
    token actually carries."""
    import inspect
    from routes.media import mint_media_token
    return inspect.signature(mint_media_token).parameters["minutes"].default


def _sign_media_url(url: Optional[str], tenant_id) -> Optional[str]:
    """Sign a stored asset URL (Drive-hosted or otherwise) for a short-lived
    MCP fetch — the C48 exception to the blanket "no media URL" rule.

    Reuses `shared.clients.image_client._kie_fetchable_url` UNCHANGED — the
    exact function Kie's own image-to-image ingestion calls to turn a stored
    Drive link into this backend's tenant-scoped media-proxy URL
    (C25a-fix2), not a second/parallel signing scheme. That function already:
      - mints a `mint_media_token(tenant_id)` (60-minute default TTL) and
        appends it as `?token=`,
      - passes non-Drive URLs (e.g. Supabase Storage) through unchanged —
        those were never proxied and have their own auth model, same
        precedent as chat.py's `_media_proxy_url`,
      - returns None/falsy input unchanged.
    `_ensure_pipeline_on_path()` is the SAME sys.path shim
    `_resolve_tenant_anthropic_client` already uses to reach
    skills/video-pipeline's `shared.clients.*` package from this route."""
    if not url:
        return None
    _ensure_pipeline_on_path()
    from shared.clients.image_client import _kie_fetchable_url
    return _kie_fetchable_url(url, tenant_id)


def _media_expiry_note(noun: str = "URLs") -> str:
    return (f"{noun} are signed and expire in {_media_token_ttl_minutes()} minutes — "
            "call this tool again for fresh links.")


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
    {
        "name": "get_workspace_info",
        "description": (
            "Whoami for this connector: which channel workspace it speaks for (per the "
            "C61 ruling, one workspace = one channel = one tenant), its niche/style summary, "
            "autopilot dial level + kill-switch state, and the account's plan. Call this "
            "when you're not sure which channel you're acting on — with several StoryEngine "
            "connectors configured (one per channel workspace), this is how Claude always "
            "disambiguates which channel a given connector's tool calls apply to. Read-only, "
            "no cost, no media URLs, no secrets (never OAuth tokens or key material)."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_production_guide",
        "description": (
            "THE process brain (checklist C66) — call this BEFORE acting on any video "
            "and again after each stage completes, so a silent step (environment design, "
            "a character-presence check) never gets skipped. Returns the canonical stage "
            "checklist for THIS video — research -> script -> voice -> characters -> "
            "environments -> storyboards -> images -> sound -> video -> thumbnail -> "
            "render -> upload — derived from status_map.py's real status machine plus "
            "pipeline_executor.py's character/environment gates, honoring this video's "
            "actual format/stage plan (a stage the creator or a static-documentary format "
            "skipped reads skipped_by_format, never a fake done). Each stage carries a "
            "state (done / in_progress / not_started / skipped_by_format), a one-line "
            "detail, and — where cheaply computable from already-stored data — concrete "
            "gaps (character/location names in the Story Bible with no design yet, "
            "designed characters/environments with no portrait, unapproved environments "
            "which HARD-BLOCK storyboard generation, scenes with no storyboard grid). "
            "Ends with next_step, the same 'what's the one next thing' the app's own "
            "guided-next-step banner answers. No media URLs in this tool — use "
            "get_scene_boards / get_character_sheets / get_environment_images / "
            "get_thumbnail_image for those. Read-only, no cost."
        ),
        "inputSchema": _VIDEO_ID_SCHEMA,
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


async def _call_get_workspace_info(tenant_id, arguments: dict[str, Any]) -> dict[str, Any]:
    """Whoami (C61b). Deliberately builds the response as an explicit named-field
    dict rather than ever spreading a DB row — that's the no-secrets guard: even if
    the underlying query or table gained a token/key column tomorrow, this handler
    physically can't leak it because it only ever reads the four fields it names
    below, never `dict(row)`. No media URLs (nothing here has one to leak).

    Field sources:
      - workspace/channel name: channel_profiles.channel_name, falling back to
        tenants.name — the SAME "name or channel_name" precedence
        routes/workspaces.py's list_workspaces uses for the UI switcher, so this
        tool reports the identical label a human sees there.
      - niche/style summary: channel_profiles.niche / .style_description — the
        cheap plain columns, not the full channel_identity DNA blob (that JSONB
        is get_channel_dna's job; duplicating it here would be redundant and
        heavier than a whoami call should be).
      - autopilot: dial_level + kill-switch state via autopilot_dial.
        get_autopilot_dial (the one shared accessor every other autopilot
        reader/writer in this file already uses).
      - plan: routes.billing._get_tenant_plan (the same tenant->account plan
        resolution require_plan()/check_plan_limits() use).
    """
    from autopilot_dial import get_autopilot_dial
    from routes.billing import _get_tenant_plan

    row = await fetch_one(
        """SELECT t.name AS tenant_name, cp.channel_name, cp.niche, cp.style_description
           FROM tenants t
           LEFT JOIN channel_profiles cp ON cp.tenant_id = t.id
           WHERE t.id = $1""",
        tenant_id,
    )
    row = row or {}
    dial = await get_autopilot_dial(tenant_id)
    plan = await _get_tenant_plan(tenant_id)

    return _text_result({
        "workspace_name": row.get("channel_name") or row.get("tenant_name") or "Workspace",
        "niche": row.get("niche") or None,
        "style_summary": row.get("style_description") or None,
        "autopilot": {
            "dial_level": dial.dial_level,
            "kill_switch_tripped": dial.kill_switch_tripped_at is not None,
            "kill_switch_reason": dial.kill_switch_reason,
        },
        "plan": plan,
    })


async def _call_get_production_guide(tenant_id, arguments: dict[str, Any]) -> dict[str, Any]:
    """C66: thin wrapper over production_guide.get_production_guide — the
    ONE place this query lives (no parallel stage logic here)."""
    video_id = arguments.get("video_id")
    if not video_id:
        return _error_result("get_production_guide requires a video_id argument")
    guide = await production_guide.get_production_guide(tenant_id, str(video_id))
    if guide is None:
        return _error_result(f"No video {video_id} found for this tenant")
    return _text_result(guide)


_READ_HANDLERS = {
    "list_videos": _call_list_videos,
    "get_video": _call_get_video,
    "get_scenes": _call_get_scenes,
    "get_script": _call_get_script,
    "get_ledger": _call_get_ledger,
    "list_style_presets": _call_list_style_presets,
    "list_models": _call_list_models,
    "get_workspace_info": _call_get_workspace_info,
    "get_production_guide": _call_get_production_guide,
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


# C25a-fix13 (tasks/decisions.md 2026-07-19 "MCP economics" — live evidence
# tonight: a connected Claude session picked this generic PAID description
# for `research` with nothing telling it a free path existed, and spent the
# workspace's Anthropic key). Traced every PAID verb to its own executor to
# classify honestly, not by guessing from the label:
#   - "script" -> pipeline_executor.run_script (writer + critic, both
#     Claude calls on the tenant's own key) -> text only, no media asset.
#   - "research" -> pipeline_executor.run_research (Claude research pass)
#     -> text only, no media asset.
#   - "seo" -> actions._runner_seo -> youtube_publish.generate_and_store_seo
#     -> ONE Claude call that writes title/description/tags -> text only.
# Every OTHER paid verb (characters/storyboards/images/voice/animate/
# draft_pass/finalize/sound/thumbnail/render/upload/build) makes or moves an
# actual media asset (a drawn picture, a synthesized voice line, a rendered
# clip, an uploaded video) through a real paid provider (kie.ai/ElevenLabs/
# grok/YouTube) — that spend is real no matter who does the thinking, so
# those verbs keep the plain PAID description untouched.
_LLM_PAID_VERB_STEER: dict[str, str] = {
    "script": (
        "[USES WORKSPACE API KEYS — prefer doing this thinking yourself: draft the "
        "script in this chat, on your own Claude subscription, then call "
        "submit_script instead (free, runs the SAME quality gates). Use this tool "
        "only as a fallback, when you want StoryEngine's own writer to do it "
        "instead.] "
    ),
    "research": (
        "[USES WORKSPACE API KEYS — prefer doing this thinking yourself: research "
        "the topic in this chat, on your own Claude subscription, then call "
        "submit_research instead (free, runs the SAME roster/shape validation). "
        "Use this tool only as a fallback, when you want StoryEngine's own "
        "researcher to do it instead.] "
    ),
    "seo": (
        "[USES WORKSPACE API KEYS — prefer doing this thinking yourself: write the "
        "title/description/tags in this chat, then call edit_publish_info instead "
        "(free, saves them directly, no AI call). Use this tool only as a "
        "fallback, when you want StoryEngine's own writer to do it instead.] "
    ),
}


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
                _LLM_PAID_VERB_STEER.get(verb, "") +
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

_GET_CHANNEL_IDENTITY_CONTEXT_TOOL: dict[str, Any] = {
    "name": "get_channel_identity_context",
    "description": (
        "THE channel-identity POOL (checklist P1) — one call that composes "
        "the learned DNA, the locked cast (name + one-line description), the "
        "locked visual format, this channel's OWN median video runtime "
        "(computed from its own catalog, NOT a competitor's), any confirmed "
        "title/performance patterns, the available script-voice profile "
        "catalog, and any custom script system-prompt override. This is the "
        "single source every surface (chat, MCP, pipeline) is meant to drink "
        "from, rather than each re-deriving its own idea of the channel. "
        "Read-only, no cost."
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
                "description": "Scope, e.g. {\"all\": true} or {\"research\": true} or {\"story\": true} or {\"animated\": true} or {\"realistic\": true} or {\"channel_format\": \"...\"} or {\"dvsu_mode\": \"...\"} or {\"board\": true}. Omit for {\"all\": true}. {\"board\": true} is its OWN axis (BOARD-LAWS.md) — a rule scoped this way is read into the storyboard/coverage planner's prompt instead of the script critic's, and \"all\" does NOT also match it (it must be set explicitly).",
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
    _GET_CHANNEL_DNA_TOOL, _GET_CHANNEL_IDENTITY_CONTEXT_TOOL,
    _LEARN_CHANNEL_START_TOOL, _LEARN_CHANNEL_STATUS_TOOL,
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


async def _call_get_channel_identity_context(tenant_id, arguments: dict[str, Any], caller: str) -> dict[str, Any]:
    from channel_identity_context import build_identity_pool
    pool = await build_identity_pool(tenant_id)
    return _text_result(pool)


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
    "get_channel_identity_context": _call_get_channel_identity_context,
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
# FEATURE BOARD TOOLS (checklist C65, tasks/decisions.md 2026-07-20 "Feature
# board" entry): the platform's FIRST deliberately CROSS-TENANT surface — the
# same suggest/upvote board every StoryEngine customer sees, not scoped to
# this connector's own tenant. Both writes are attributed per ACCOUNT
# (accounts.id), same as the HTTP door — but an MCP agent token only carries
# a tenant identity, not a user one, so these three handlers resolve a
# representative account via routes.feature_board.account_id_for_tenant()
# (owner preferred, else any member) and construct a synthetic AuthUser to
# call the SAME route functions (list_feature_board/create_feature_request/
# vote_feature_request) the HTTP door uses — no parallel logic, no separate
# rate-limit/validation path. No status-change tool here on purpose (the
# checklist's explicit call): status changes are operator-UI-only.
# =============================================================================

_LIST_FEATURE_REQUESTS_TOOL: dict[str, Any] = {
    "name": "list_feature_requests",
    "description": (
        "List the platform feature board: every customer's suggestions, vote "
        "counts, whether you voted, and status (under_review, planned, "
        "building, in_beta, shipped, declined). CROSS-TENANT by design — this "
        "is the SAME board every StoryEngine customer sees, not scoped to "
        "your workspace. Read-only, no cost."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "description": "Filter: one of under_review, planned, building, in_beta, shipped, declined.",
            },
        },
    },
}

_SUGGEST_FEATURE_TOOL: dict[str, Any] = {
    "name": "suggest_feature",
    "description": (
        "Suggest a new platform feature — free, no cost. Posted to the SAME "
        "cross-tenant feature board every customer sees, attributed to your "
        "account. Limited to 5 suggestions per day."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Short title (max 120 characters)."},
            "body": {"type": "string", "description": "Details, optional (max 2000 characters)."},
            "channel_archetype": {
                "type": "string",
                "description": "What kind of channel you run, optional (e.g. \"talking-head explainer\").",
            },
        },
        "required": ["title"],
    },
}

_VOTE_FEATURE_REQUEST_TOOL: dict[str, Any] = {
    "name": "vote_feature_request",
    "description": (
        "Upvote a feature-board suggestion — free, no cost, idempotent "
        "(voting twice has no extra effect; one vote per account per idea)."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "request_id": {
                "type": "string",
                "description": "feature_requests row id (from list_feature_requests).",
            },
        },
        "required": ["request_id"],
    },
}

_FEATURE_BOARD_TOOLS: list[dict[str, Any]] = [
    _LIST_FEATURE_REQUESTS_TOOL, _SUGGEST_FEATURE_TOOL, _VOTE_FEATURE_REQUEST_TOOL,
]


async def _call_list_feature_requests(tenant_id, arguments: dict[str, Any]) -> dict[str, Any]:
    from auth import AuthUser
    from routes.feature_board import account_id_for_tenant, list_feature_board

    account_id = await account_id_for_tenant(tenant_id)
    if not account_id:
        return _error_result("Couldn't resolve an account for this connector's tenant")
    user = AuthUser(id=account_id, email="mcp")
    try:
        result = await list_feature_board(status=arguments.get("status"), user=user)
    except HTTPException as e:
        return _error_result(e.detail if isinstance(e.detail, str) else "Couldn't list the feature board")
    return _text_result(result.model_dump())


async def _call_suggest_feature(tenant_id, arguments: dict[str, Any], caller: str) -> dict[str, Any]:
    from auth import AuthUser
    from routes.feature_board import CreateFeatureRequestBody, account_id_for_tenant, create_feature_request

    account_id = await account_id_for_tenant(tenant_id)
    if not account_id:
        return _error_result("Couldn't resolve an account for this connector's tenant")
    try:
        body = CreateFeatureRequestBody(
            title=arguments.get("title") or "",
            body=arguments.get("body"),
            channel_archetype=arguments.get("channel_archetype"),
        )
    except Exception as e:  # noqa: BLE001 — a bad argument shape is a tool-input error, not a 500
        return _error_result(f"Couldn't submit that suggestion — invalid arguments: {e}")
    user = AuthUser(id=account_id, email=caller)
    _log_setup_write("suggest_feature", tenant_id, caller, detail=(body.title or "")[:40])
    try:
        result = await create_feature_request(body, user=user)
    except HTTPException as e:
        return _error_result(e.detail if isinstance(e.detail, str) else "Couldn't submit that suggestion")
    return _text_result(result.model_dump())


async def _call_vote_feature_request(tenant_id, arguments: dict[str, Any], caller: str) -> dict[str, Any]:
    from auth import AuthUser
    from routes.feature_board import account_id_for_tenant, vote_feature_request

    request_id = arguments.get("request_id")
    if not request_id:
        return _error_result("vote_feature_request requires a request_id argument")
    account_id = await account_id_for_tenant(tenant_id)
    if not account_id:
        return _error_result("Couldn't resolve an account for this connector's tenant")
    user = AuthUser(id=account_id, email=caller)
    _log_setup_write("vote_feature_request", tenant_id, caller, detail=str(request_id))
    try:
        result = await vote_feature_request(str(request_id), user=user)
    except HTTPException as e:
        return _error_result(e.detail if isinstance(e.detail, str) else "Couldn't vote for that suggestion")
    return _text_result(result.model_dump())


_FEATURE_BOARD_READ_HANDLERS = {
    "list_feature_requests": _call_list_feature_requests,
}

_FEATURE_BOARD_WRITE_HANDLERS = {
    "suggest_feature": _call_suggest_feature,
    "vote_feature_request": _call_vote_feature_request,
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
        "THE STANDARD WAY to get research onto this video: do the research "
        "yourself, right here in this chat, on your own Claude subscription "
        "(zero API-key cost to the workspace), then hand StoryEngine the "
        "result with this tool. Validated against the exact same shape "
        "run_research itself produces and the SAME deterministic "
        "roster-completeness gate a platform research run applies for "
        "machine-roster/documentary titles — identical quality bar, no "
        "shortcuts; a rejection returns the concrete warnings so you can fix "
        "your research and resubmit. On acceptance, saved and the video "
        "advances exactly like a platform-run research pass. The `research` "
        "verb tool (which spends the workspace's own Anthropic key) is the "
        "fallback — use it only when you'd rather StoryEngine's own "
        "researcher do the thinking."
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
        "THE STANDARD WAY to get a script onto this video: write it "
        "yourself, right here in this chat, on your own Claude subscription "
        "(zero API-key cost to the workspace), then hand StoryEngine the "
        "result with this tool. Runs through the SAME quality-rules critic a "
        "platform-generated script faces (verdict-only, no server-side edit "
        "loop — this is not the creator's own verbatim text, so it doesn't "
        "get that bypass, but it's also not ours to silently rewrite) — "
        "identical quality bar, no shortcuts. A hard-gate/universal-gate "
        "failure REJECTS with the rule-by-rule violations so you can fix "
        "your script and resubmit; a pass (warnings aside) saves and "
        "advances the video exactly like a platform-written script. The "
        "`script` verb tool (which spends the workspace's own Anthropic "
        "key) is the fallback — use it only when you'd rather StoryEngine's "
        "own writer do the thinking.\n\n"
        "STORY LAW S3 — ONE SCENE, ONE LOCATION: give every scene a single "
        "'location' field naming the one physical place it happens in "
        "(e.g. \"the garage\"). A scene missing a location is REJECTED "
        "before the quality critic even runs — split any beat that moves "
        "somewhere new, or into a distinct new phase of action, into its "
        "own scene instead. (A scene's text naming another scene's "
        "location is fine and often required — see S1 below — so that "
        "alone is never rejected, only flagged as an advisory warning.)\n\n"
        "STORY LAW S1 — NARRATE EVERY LOCATION CHANGE: when consecutive "
        "scenes have different 'location' values, actually write the move "
        "somewhere in that pair of scenes — the door, the threshold, the "
        "travel, the arrival. Don't just end one scene's text and start "
        "the next scene in a different place with nothing narrated between "
        "them; a location change with no transit narrated anywhere nearby "
        "comes back as an advisory warning (never a rejection).\n\n"
        "STORY LAW S6 — THE SCRIPT IS THE ORIGIN OF TRUTH: whatever you "
        "submit here becomes this video's canonical script, and every "
        "downstream artifact (cast, environments, boards) is generated FROM "
        "it. Write the full truth into your scenes — every character, "
        "everything about how they look or where they are that the story "
        "needs — rather than assuming an existing cast sheet or environment "
        "design still covers what you leave out; anything built from an "
        "older script is treated as stale the moment this submission lands."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "video_id": {"type": "string", "description": "Video UUID."},
            "scenes": {
                "type": "array",
                "description": (
                    "Ordered scenes: [{\"text\": \"...\", \"location\": \"...\"}, ...]. "
                    "Scene numbers are assigned 1..N from this order. `location` is "
                    "REQUIRED (S3) — the single physical place that scene happens in; "
                    "if omitted, a `LOCATION: <place>` line at the very start of `text` "
                    "is parsed instead (and left in place — `text` is never rewritten)."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "location": {
                            "type": "string",
                            "description": "This scene's single physical location (S3, STORY-LAWS.md).",
                        },
                    },
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


# =============================================================================
# ATOMIC-SURFACE TOOLS (C49 — checklist "MCP atomic-surface completion",
# decisions.md 2026-07-19's "model this video" extension): thin wrappers over
# EXISTING endpoints/functions for the shot-level, script-surgery, character-
# granularity, voice-control, pre-publish, analytics-read, and reference-
# modeling-read atomic operations C26/C27/C47 didn't already cover. Same
# registry discipline as every earlier surface:
#   - PAID (redraw_shot, redo_character_sheet, redo_dialogue_scene_voice)
#     reuses the EXACT SAME confirm_tokens.py gate every other paid tool
#     uses (create/redeem/params_hash, same mcp_confirm_tokens table) via
#     `_paid_gate` below — just keyed by this tool's own name instead of an
#     actions.ACTIONS verb (these ops have no verb of their own), and by a
#     subject id (asset_id/char_id) instead of a scene number. No new money
#     mechanism, no new pipeline logic — every PAID tool below dispatches
#     through the SAME route function the HTTP door already calls.
#   - FREE writes are attributed via `caller` (routes/mcp.py's `_log_setup_
#     write`, same as C47) and call the SAME route/module function the
#     existing HTTP endpoint or verb calls — no parallel UPDATE statements.
#   - READS never carry a media/asset URL (C25a hold) — see each read
#     tool's docstring for exactly which existing field was stripped/
#     replaced and why.
# =============================================================================

async def _paid_gate(tenant_id, video_id: str, tool: str, subject: Optional[str],
                      quote_cost: float, quote_label: str,
                      confirm_token: Optional[str]) -> tuple[bool, dict[str, Any]]:
    """Generic confirm_token quote/redeem cycle for a C49 atomic paid tool
    that has no actions.ACTIONS verb of its own. Reuses confirm_tokens.py's
    EXACT create()/redeem()/params_hash() — the identical single-use,
    10-minute, params-bound token every ACTIONS-verb paid tool mints via
    `_call_verb` above — just keyed by this tool's name (in the `verb`
    column) and by `subject` (in the `change` column) instead of a scene
    number, so a token minted for "redraw asset A" cannot be replayed
    against asset B, a different tool, video, or tenant.

    Returns (ready, result): ready=True means the caller should proceed with
    the actual paid work; ready=False means `result` IS the tool's final
    return value (a quote or a confirm-token error) and the caller must
    return it unchanged.
    """
    phash = confirm_tokens.params_hash(tool, None, subject, None, None)
    if not confirm_token:
        token = await confirm_tokens.create(tenant_id, video_id, tool, phash)
        return False, _text_result({
            "status": "quote", "tool": tool, "cost": quote_cost, "cost_text": quote_label,
            "confirm_token": token, "expires_in_seconds": confirm_tokens.TTL_SECONDS,
            "note": "Call this same tool again with these SAME arguments plus confirm_token to run it.",
        })
    ok = await confirm_tokens.redeem(tenant_id, video_id, tool, phash, confirm_token)
    if not ok:
        return False, _error_result(
            "confirm_token is invalid, expired, already used, or doesn't match these exact "
            "arguments — call this tool again WITHOUT confirm_token to get a fresh quote."
        )
    return True, {}


# --- Shot-level -------------------------------------------------------------

_GET_SHOTS_TOOL: dict[str, Any] = {
    "name": "get_shots",
    "description": (
        "Shot-level (per-asset) detail for a video: each asset's id, scene, "
        "index, current image_prompt/video_prompt text, manual model_override "
        "and camera_preset_id, routed_model, shot_type, and status. This is "
        "where the asset_id every shot-level write tool needs (edit_shot_"
        "image_prompt, edit_shot_motion_prompt, set_shot_model_override, "
        "redraw_shot) comes from. Wraps the SAME query GET /api/videos/"
        "{id}/assets uses (routes.videos.get_video_assets) — image_url/"
        "video_clip_url stripped (C25a hold). Read-only, no cost."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "video_id": {"type": "string", "description": "Video UUID."},
            "scene": {"type": "integer", "description": "Only this scene's shots, optional."},
        },
        "required": ["video_id"],
    },
}

_EDIT_SHOT_IMAGE_PROMPT_TOOL: dict[str, Any] = {
    "name": "edit_shot_image_prompt",
    "description": (
        "Edit one shot's image prompt (the box under each picture in the "
        "Scenes workspace). Free, no cost — redraw_shot is what actually "
        "spends money against this prompt."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "asset_id": {"type": "string", "description": "Asset UUID (from get_shots)."},
            "image_prompt": {"type": "string", "description": "The new image prompt text."},
        },
        "required": ["asset_id", "image_prompt"],
    },
}

_EDIT_SHOT_MOTION_PROMPT_TOOL: dict[str, Any] = {
    "name": "edit_shot_motion_prompt",
    "description": (
        "Edit one shot's motion (clip) prompt. Free, no cost — the next "
        "animate/clip regen on this shot is what actually spends money."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "asset_id": {"type": "string", "description": "Asset UUID (from get_shots)."},
            "video_prompt": {"type": "string", "description": "The new motion prompt text."},
        },
        "required": ["asset_id", "video_prompt"],
    },
}

_SET_SHOT_MODEL_OVERRIDE_TOOL: dict[str, Any] = {
    "name": "set_shot_model_override",
    "description": (
        "Set or clear one shot's manual clip-model override (checklist "
        "§1.2/C14's endpoint — PATCH /api/assets/{id}/model-override) — the "
        "next animate/quote for this shot honors this pick over the "
        "router's own recommendation. Pass \"\" or omit model_override to "
        "clear it back to the router's pick. Free, no cost."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "asset_id": {"type": "string", "description": "Asset UUID (from get_shots)."},
            "model_override": {"type": "string", "description": "A wired MODEL_REGISTRY id (see list_models), or omit/\"\" to clear."},
        },
        "required": ["asset_id"],
    },
}

_IMPROVE_PROMPT_TOOL: dict[str, Any] = {
    "name": "improve_prompt",
    "description": (
        "[USES WORKSPACE API KEYS — prefer doing this thinking yourself: "
        "write the stronger prompt directly in this chat, then call "
        "edit_shot_image_prompt/edit_shot_motion_prompt/edit_scene_text "
        "with it (free, no tenant-key spend). Use this tool only as a "
        "fallback, when you want the platform's own rewriter to do it "
        "instead.] Ask the SAME prompt-studio rewriter the UI's \"improve\" "
        "button uses (POST /api/pipeline/improve-prompt/{id}) for a "
        "stronger prompt. Returns the proposed text only — nothing is "
        "saved; follow up with edit_shot_image_prompt/edit_shot_motion_"
        "prompt (or edit_scene_text for surface=\"script\") to apply it. No "
        "confirm_token — uses the tenant's own configured Claude/kie.ai key."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "video_id": {"type": "string", "description": "Video UUID."},
            "surface": {"type": "string", "description": "image | motion | thumbnail | script."},
            "current": {"type": "string", "description": "The current prompt/text, if any."},
            "direction": {"type": "string", "description": "Free-text direction for the rewrite, e.g. \"make it more ominous\"."},
        },
        "required": ["video_id", "surface"],
    },
}

_REDRAW_SHOT_TOOL: dict[str, Any] = {
    "name": "redraw_shot",
    "description": (
        "Redraw ONE picture from its (edited) image_prompt, anchored on the "
        "locked cast sheets — the SAME background job POST /api/pipeline/"
        "redraw-image/{id} runs. PAID (one image, GPT Image 2 tier). Call "
        "with no confirm_token first to get a price quote; call again with "
        "the returned confirm_token to actually run it."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "video_id": {"type": "string", "description": "Video UUID."},
            "asset_id": {"type": "string", "description": "Asset UUID (from get_shots)."},
            "confirm_token": {"type": "string", "description": "Omit on the first call to get a quote; pass it back to run."},
        },
        "required": ["video_id", "asset_id"],
    },
}

_SHOT_TOOLS: list[dict[str, Any]] = [
    _GET_SHOTS_TOOL, _EDIT_SHOT_IMAGE_PROMPT_TOOL, _EDIT_SHOT_MOTION_PROMPT_TOOL,
    _SET_SHOT_MODEL_OVERRIDE_TOOL, _IMPROVE_PROMPT_TOOL, _REDRAW_SHOT_TOOL,
]


async def _call_get_shots(tenant_id, arguments: dict[str, Any]) -> dict[str, Any]:
    video_id = arguments.get("video_id")
    if not video_id:
        return _error_result("get_shots requires a video_id argument")
    from routes.videos import get_video_assets as _get_video_assets_route
    try:
        rows = await _get_video_assets_route(str(video_id), tenant_id=tenant_id)
    except HTTPException as e:
        return _error_result(e.detail if isinstance(e.detail, str) else "Video not found")
    scene = _coerce_scene(arguments.get("scene"))
    shots = []
    for r in (rows or []):
        row = dict(r)
        row.pop("image_url", None)
        row.pop("video_clip_url", None)  # C25a hold
        if scene is not None and row.get("scene") != scene:
            continue
        row["id"] = str(row["id"])
        row["video_id"] = str(row["video_id"])
        shots.append(row)
    return _text_result({"video_id": video_id, "shots": shots})


async def _call_edit_shot_image_prompt(tenant_id, arguments: dict[str, Any], caller: str) -> dict[str, Any]:
    asset_id = arguments.get("asset_id")
    text = arguments.get("image_prompt")
    if not asset_id or not text:
        return _error_result("edit_shot_image_prompt requires asset_id and image_prompt")
    from routes.assets import ImagePromptUpdate, update_image_prompt as _update_image_prompt_route
    try:
        result = await _update_image_prompt_route(str(asset_id), ImagePromptUpdate(image_prompt=text), tenant_id=tenant_id)
    except HTTPException as e:
        return _error_result(e.detail if isinstance(e.detail, str) else "Asset not found")
    _log_setup_write("edit_shot_image_prompt", tenant_id, caller, detail=str(asset_id))
    return _text_result(result)


async def _call_edit_shot_motion_prompt(tenant_id, arguments: dict[str, Any], caller: str) -> dict[str, Any]:
    asset_id = arguments.get("asset_id")
    text = arguments.get("video_prompt")
    if not asset_id or not text:
        return _error_result("edit_shot_motion_prompt requires asset_id and video_prompt")
    from routes.assets import VideoPromptUpdate, update_video_prompt as _update_video_prompt_route
    try:
        result = await _update_video_prompt_route(str(asset_id), VideoPromptUpdate(video_prompt=text), tenant_id=tenant_id)
    except HTTPException as e:
        return _error_result(e.detail if isinstance(e.detail, str) else "Asset not found")
    _log_setup_write("edit_shot_motion_prompt", tenant_id, caller, detail=str(asset_id))
    return _text_result(result)


async def _call_set_shot_model_override(tenant_id, arguments: dict[str, Any], caller: str) -> dict[str, Any]:
    asset_id = arguments.get("asset_id")
    if not asset_id:
        return _error_result("set_shot_model_override requires an asset_id")
    from routes.assets import ModelOverrideUpdate, update_model_override as _update_model_override_route
    try:
        result = await _update_model_override_route(
            str(asset_id), ModelOverrideUpdate(model_override=arguments.get("model_override")), tenant_id=tenant_id)
    except HTTPException as e:
        return _error_result(e.detail if isinstance(e.detail, str) else "Asset not found")
    _log_setup_write("set_shot_model_override", tenant_id, caller, detail=str(asset_id))
    return _text_result(result)


async def _call_improve_prompt(tenant_id, arguments: dict[str, Any], caller: str) -> dict[str, Any]:
    video_id = arguments.get("video_id")
    surface = arguments.get("surface")
    if not video_id or not surface:
        return _error_result("improve_prompt requires video_id and surface")
    from routes.pipeline import ImprovePromptRequest, improve_prompt as _improve_prompt_route
    try:
        body = ImprovePromptRequest(surface=surface, current=arguments.get("current"), direction=arguments.get("direction"))
    except Exception as e:  # noqa: BLE001 — bad tool-input shape, not a 500
        return _error_result(f"Bad arguments for improve_prompt: {e}")
    try:
        result = await _improve_prompt_route(str(video_id), body, tenant_id=tenant_id)
    except HTTPException as e:
        return _error_result(e.detail if isinstance(e.detail, str) else "Couldn't improve that prompt")
    _log_setup_write("improve_prompt", tenant_id, caller, detail=surface)
    return _text_result(result)


async def _call_redraw_shot(tenant_id, arguments: dict[str, Any],
                             background_tasks: Optional[BackgroundTasks], caller: str) -> dict[str, Any]:
    video_id = arguments.get("video_id")
    asset_id = arguments.get("asset_id")
    if not video_id or not asset_id:
        return _error_result("redraw_shot requires video_id and asset_id")
    video_id = str(video_id)
    asset = await fetch_one(
        "SELECT id FROM assets WHERE id = $1 AND video_id = $2 AND tenant_id = $3",
        str(asset_id), video_id, tenant_id,
    )
    if not asset:
        return _error_result(f"No asset {asset_id} found on video {video_id} for this tenant")
    if background_tasks is None:
        return _error_result("Internal error: no task runner available for this call")
    ready, result = await _paid_gate(
        tenant_id, video_id, "redraw_shot", str(asset_id),
        actions.PICTURE_COST, f"${actions.PICTURE_COST:.2f} (one GPT Image 2 picture)",
        arguments.get("confirm_token"),
    )
    if not ready:
        return result
    from routes.pipeline import run_redraw_image as _run_redraw_image_route
    try:
        resp = await _run_redraw_image_route(video_id, background_tasks, str(asset_id), tenant_id=tenant_id)
    except HTTPException as e:
        return _error_result(e.detail if isinstance(e.detail, str) else "Couldn't start the redraw")
    _log_setup_write("redraw_shot", tenant_id, caller, detail=str(asset_id))
    return _text_result({"status": "started", "video_id": video_id, "asset_id": asset_id, "message": resp.message})


# --- Script surgery ----------------------------------------------------------

_GET_SCENE_SCRIPT_TOOL: dict[str, Any] = {
    "name": "get_scene_script",
    "description": "ONE scene's narration text/status from get_script, filtered server-side. Read-only, no cost.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "video_id": {"type": "string", "description": "Video UUID."},
            "scene": {"type": "integer", "description": "Scene number."},
        },
        "required": ["video_id", "scene"],
    },
}

_EDIT_SCENE_TEXT_TOOL: dict[str, Any] = {
    "name": "edit_scene_text",
    "description": (
        "Directly overwrite ONE scene's narration text (no AI rewrite — "
        "for when you already have the exact words). Wraps PATCH /api/"
        "videos/{id}/scenes/{scene}/text. Free, no cost."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "video_id": {"type": "string", "description": "Video UUID."},
            "scene": {"type": "integer", "description": "Scene number."},
            "text": {"type": "string", "description": "The full replacement narration text for this scene."},
        },
        "required": ["video_id", "scene", "text"],
    },
}

_REGENERATE_SCENE_TEXT_TOOL: dict[str, Any] = {
    "name": "regenerate_scene_text",
    "description": (
        "[USES WORKSPACE API KEYS — prefer doing this thinking yourself: "
        "rewrite the scene's narration in this chat, then call "
        "edit_scene_text with it instead (free, no AI call, applied "
        "verbatim). Use this tool only as a fallback, when you want "
        "StoryEngine's own rewriter to do it instead.] AI-rewrite ONE "
        "scene's narration in place (POST /api/videos/{id}/scenes/{scene}/"
        "rewrite) — dial in a single scene without re-rolling the whole "
        "script. Clears that scene's voice so the next voice run only "
        "re-records this scene. No confirm_token — uses the tenant's own "
        "configured Anthropic key directly (not billed by StoryEngine), "
        "same as learn_channel_start."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "video_id": {"type": "string", "description": "Video UUID."},
            "scene": {"type": "integer", "description": "Scene number."},
        },
        "required": ["video_id", "scene"],
    },
}

_SCRIPT_SURGERY_TOOLS: list[dict[str, Any]] = [
    _GET_SCENE_SCRIPT_TOOL, _EDIT_SCENE_TEXT_TOOL, _REGENERATE_SCENE_TEXT_TOOL,
]


async def _call_get_scene_script(tenant_id, arguments: dict[str, Any]) -> dict[str, Any]:
    video_id = arguments.get("video_id")
    scene = _coerce_scene(arguments.get("scene"))
    if not video_id or scene is None:
        return _error_result("get_scene_script requires video_id and scene")
    full = await _call_get_script(tenant_id, {"video_id": video_id})
    if full.get("isError"):
        return full
    payload = json.loads(full["content"][0]["text"])
    match = next((s for s in payload.get("scenes", []) if s.get("scene") == scene), None)
    if match is None:
        return _error_result(f"No scene {scene} found for video {video_id}")
    return _text_result({"video_id": video_id, "scene": match})


async def _call_edit_scene_text(tenant_id, arguments: dict[str, Any], caller: str) -> dict[str, Any]:
    video_id = arguments.get("video_id")
    scene = _coerce_scene(arguments.get("scene"))
    text = arguments.get("text")
    if not video_id or scene is None or not text:
        return _error_result("edit_scene_text requires video_id, scene, and text")
    from models import SceneTextUpdate
    from routes.videos import update_scene_text as _update_scene_text_route
    try:
        result = await _update_scene_text_route(str(video_id), scene, SceneTextUpdate(text=text), tenant_id=tenant_id)
    except HTTPException as e:
        return _error_result(e.detail if isinstance(e.detail, str) else "Scene not found")
    _log_setup_write("edit_scene_text", tenant_id, caller, detail=f"scene {scene}")
    return _text_result(result)


async def _call_regenerate_scene_text(tenant_id, arguments: dict[str, Any], caller: str) -> dict[str, Any]:
    video_id = arguments.get("video_id")
    scene = _coerce_scene(arguments.get("scene"))
    if not video_id or scene is None:
        return _error_result("regenerate_scene_text requires video_id and scene")
    from routes.videos import rewrite_scene_text as _rewrite_scene_text_route
    try:
        result = await _rewrite_scene_text_route(str(video_id), scene, tenant_id=tenant_id)
    except HTTPException as e:
        return _error_result(e.detail if isinstance(e.detail, str) else "Couldn't rewrite that scene")
    _log_setup_write("regenerate_scene_text", tenant_id, caller, detail=f"scene {scene}")
    return _text_result(result)


# --- Character granularity ---------------------------------------------------

_GET_CHARACTERS_TOOL: dict[str, Any] = {
    "name": "get_characters",
    "description": (
        "This video's cast: each character's id, name, description, status, "
        "source, and whether the cast is approved. Wraps GET /api/videos/"
        "{id}/characters — reference_url stripped (C25a hold). Read-only, "
        "no cost."
    ),
    "inputSchema": _VIDEO_ID_SCHEMA,
}

_EDIT_CHARACTER_TOOL: dict[str, Any] = {
    "name": "edit_character",
    "description": "Edit a character's name, description and/or identity_tag. Free, no cost.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "video_id": {"type": "string", "description": "Video UUID."},
            "char_id": {"type": "string", "description": "Character UUID (from get_characters)."},
            "name": {"type": "string", "description": "New name, optional."},
            "description": {"type": "string", "description": "New description, optional."},
            "identity_tag": {
                "type": "string",
                "description": (
                    "Short locked identity tag (2-4 words of wardrobe/build, e.g. "
                    "'red jacket, undercut, mid-20s'), optional. Read verbatim into "
                    "every storyboard's CHARACTER block instead of a truncated "
                    "description."
                ),
            },
        },
        "required": ["video_id", "char_id"],
    },
}

_REDO_CHARACTER_SHEET_TOOL: dict[str, Any] = {
    "name": "redo_character_sheet",
    "description": (
        "Redesign one character's model-sheet portrait from its current "
        "description (POST /api/videos/{id}/characters/{char_id}/"
        "regenerate). PAID (one GPT Image 2 tier image). Call with no "
        "confirm_token first to get a price quote; call again with the "
        "returned confirm_token to actually run it."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "video_id": {"type": "string", "description": "Video UUID."},
            "char_id": {"type": "string", "description": "Character UUID (from get_characters)."},
            "confirm_token": {"type": "string", "description": "Omit on the first call to get a quote; pass it back to run."},
        },
        "required": ["video_id", "char_id"],
    },
}

_CHARACTER_TOOLS: list[dict[str, Any]] = [
    _GET_CHARACTERS_TOOL, _EDIT_CHARACTER_TOOL, _REDO_CHARACTER_SHEET_TOOL,
]


async def _call_get_characters(tenant_id, arguments: dict[str, Any]) -> dict[str, Any]:
    video_id = arguments.get("video_id")
    if not video_id:
        return _error_result("get_characters requires a video_id argument")
    from routes.characters import list_characters as _list_characters_route
    try:
        result = await _list_characters_route(str(video_id), tenant_id=tenant_id)
    except HTTPException as e:
        return _error_result(e.detail if isinstance(e.detail, str) else "Video not found")
    characters = []
    for c in (result.get("characters") or []):
        c = dict(c)
        c.pop("reference_url", None)  # C25a hold
        characters.append(c)
    return _text_result({"video_id": video_id, "characters": characters, "approved_at": result.get("approved_at")})


async def _call_edit_character(tenant_id, arguments: dict[str, Any], caller: str) -> dict[str, Any]:
    video_id = arguments.get("video_id")
    char_id = arguments.get("char_id")
    if not video_id or not char_id:
        return _error_result("edit_character requires video_id and char_id")
    from routes.characters import CharacterUpdate, update_character as _update_character_route
    try:
        result = await _update_character_route(
            str(video_id), str(char_id),
            CharacterUpdate(name=arguments.get("name"), description=arguments.get("description"),
                            identity_tag=arguments.get("identity_tag")),
            tenant_id=tenant_id,
        )
    except HTTPException as e:
        return _error_result(e.detail if isinstance(e.detail, str) else "Character not found")
    _log_setup_write("edit_character", tenant_id, caller, detail=str(char_id))
    return _text_result(result)


async def _call_redo_character_sheet(tenant_id, arguments: dict[str, Any],
                                      background_tasks: Optional[BackgroundTasks], caller: str) -> dict[str, Any]:
    video_id = arguments.get("video_id")
    char_id = arguments.get("char_id")
    if not video_id or not char_id:
        return _error_result("redo_character_sheet requires video_id and char_id")
    video_id = str(video_id)
    char = await fetch_one(
        "SELECT id FROM video_characters WHERE id = $1 AND video_id = $2 AND tenant_id = $3",
        str(char_id), video_id, tenant_id,
    )
    if not char:
        return _error_result(f"No character {char_id} found on video {video_id} for this tenant")
    if background_tasks is None:
        return _error_result("Internal error: no task runner available for this call")
    ready, result = await _paid_gate(
        tenant_id, video_id, "redo_character_sheet", str(char_id),
        actions.PICTURE_COST, f"${actions.PICTURE_COST:.2f} (one GPT Image 2 tier portrait)",
        arguments.get("confirm_token"),
    )
    if not ready:
        return result
    from routes.characters import regenerate_character as _regenerate_character_route
    try:
        resp = await _regenerate_character_route(video_id, str(char_id), background_tasks, tenant_id=tenant_id)
    except HTTPException as e:
        return _error_result(e.detail if isinstance(e.detail, str) else "Couldn't start the redesign")
    _log_setup_write("redo_character_sheet", tenant_id, caller, detail=str(char_id))
    return _text_result({"status": "started", "video_id": video_id, "char_id": char_id, "message": resp.get("message")})


# =============================================================================
# MEDIA TOOLS (C48 — see module docstring "TOOL SURFACE v6"): the C25a-hold's
# "no media URL" ban is lifted for exactly one shape — a SIGNED, SHORT-LIVED
# `_sign_media_url` proxy URL, never a raw Drive/storage link. Every read
# below is tenant-scoped (via the SAME existing route/module function the
# HTTP door already uses, so ownership is enforced once, not re-implemented
# here) and capped.
# =============================================================================

_MAX_BOARD_IMAGES = 6  # same UX ceiling as chat.py's C15b _MAX_SHOW_IMAGES (kept as an independent constant — this module doesn't import chat.py's private one)
_MAX_CHARACTER_SHEETS = 12  # generous cap above characters.MAX_CHARACTERS(8)/a channel cast's real size — belt-and-suspenders, not the real limiter
_MAX_ENVIRONMENT_IMAGES = 12  # matches routes.environments.MAX_ENVIRONMENTS

_GET_SCENE_BOARDS_TOOL: dict[str, Any] = {
    "name": "get_scene_boards",
    "description": (
        "The MCP twin of chat's \"show me scene N's boards\" (C15b's "
        "_handle_show_op): actual drawn pictures for a video, each a SIGNED, "
        "SHORT-LIVED media-proxy URL (C48) + asset id + a prompt snippet. "
        "Pass `scene` for that scene's pictures (capped at "
        f"{_MAX_BOARD_IMAGES}); omit it for a compact per-scene picture-count "
        "summary across the whole video (no images in that mode — call again "
        "with a scene number to actually see them). Tenant+video+scene scoped."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "video_id": {"type": "string", "description": "Video UUID."},
            "scene": {"type": "integer", "description": "Only this scene's pictures; omit for a per-scene count summary (no images)."},
        },
        "required": ["video_id"],
    },
}

_GET_CHARACTER_SHEETS_TOOL: dict[str, Any] = {
    "name": "get_character_sheets",
    "description": (
        "Character/model-sheet portraits, signed (C48). Pass `video_id` for "
        "that video's designed cast (wraps GET /api/videos/{id}/characters); "
        "omit it for the channel-level LOCKED cast every new video starts "
        "from instead (wraps GET /api/projects/current/cast). Tenant-scoped, "
        "capped, no cost."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "video_id": {"type": "string", "description": "Omit for the channel-level locked cast instead of one video's designed characters."},
        },
    },
}

_GET_ENVIRONMENT_IMAGES_TOOL: dict[str, Any] = {
    "name": "get_environment_images",
    "description": (
        "This video's designed location/environment reference images, "
        "signed (C48). Wraps GET /api/videos/{id}/environments "
        "(routes/environments.py) — same query, reference_url signed instead "
        "of stripped. Tenant-scoped, capped, no cost."
    ),
    "inputSchema": _VIDEO_ID_SCHEMA,
}

_GET_THUMBNAIL_IMAGE_TOOL: dict[str, Any] = {
    "name": "get_thumbnail_image",
    "description": (
        "This video's current thumbnail, signed (C48) — a single short-lived "
        "media-proxy URL for videos.thumbnail_url. Tenant-scoped, no cost."
    ),
    "inputSchema": _VIDEO_ID_SCHEMA,
}

_QUICK_DEMO_VIDEO_TOOL: dict[str, Any] = {
    "name": "quick_demo_video",
    "description": (
        "One-off convenience path for a quick demo (Ryan 2026-07-19): create "
        "a video and auto-advance it through script + cast + pictures with "
        "minimal ceremony — no need to call script/characters/images "
        "separately. STAGED, not one-shot — the money gate is NEVER "
        "weakened, so this takes up to 3 calls. (1) Call with a `title` and "
        "no `video_id` to create the video (free). (2) Call again with that "
        "`video_id` and no `confirm_token` to get the SAME price quote the "
        "\"build\" verb/button would show (script + cast + pictures, "
        "whatever model is wired). (3) Call once more with that "
        "`confirm_token` to actually start it — it runs in the background "
        "and stops at the pictures checkpoint for review; poll get_video for "
        "status, then call get_scene_boards to see the pictures. Thin "
        "wrapper: step 1 is create_video, steps 2-3 are the EXISTING "
        "\"build\" verb (the same confirm_tokens gate every other paid tool "
        "uses) — no new pipeline logic, no bypass of the quote/confirm dance."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "video_id": {"type": "string", "description": "Omit on the first call to create a new video; pass it back on later calls to continue building that same video."},
            "title": {"type": "string", "description": "The video's working title/topic (required when video_id is omitted)."},
            "visual_style": {"type": "string", "description": "Free-text visual style, or an id from list_style_presets. Optional, only used when creating."},
            "video_length_minutes": {"type": "integer", "description": "Target runtime in minutes (default 10). Only used when creating."},
            "confirm_token": {"type": "string", "description": "Omit on the first two calls; pass back the token from the price-quote call to actually start the build."},
        },
    },
}

_MEDIA_TOOLS: list[dict[str, Any]] = [
    _GET_SCENE_BOARDS_TOOL, _GET_CHARACTER_SHEETS_TOOL,
    _GET_ENVIRONMENT_IMAGES_TOOL, _GET_THUMBNAIL_IMAGE_TOOL,
    _QUICK_DEMO_VIDEO_TOOL,
]


async def _call_get_scene_boards(tenant_id, arguments: dict[str, Any]) -> dict[str, Any]:
    video_id = arguments.get("video_id")
    if not video_id:
        return _error_result("get_scene_boards requires a video_id argument")
    video_id = str(video_id)
    owned = await actions.video_summary(tenant_id, video_id)
    if owned is None:
        return _error_result(f"No video {video_id} found for this tenant")

    scene = _coerce_scene(arguments.get("scene"))
    if scene is None:
        rows = await fetch_all(
            "SELECT scene, count(*) FILTER (WHERE image_url IS NOT NULL OR drive_image_url IS NOT NULL) AS pics "
            "FROM assets WHERE video_id = $1 AND tenant_id = $2 AND scene IS NOT NULL "
            "GROUP BY scene ORDER BY scene",
            video_id, tenant_id,
        )
        scenes = [{"scene": r.get("scene"), "pics": int(r.get("pics") or 0)} for r in (rows or [])]
        return _text_result({
            "video_id": video_id, "scenes": scenes,
            "note": "Compact summary, no images — call again with a scene number to see its pictures.",
        })

    rows = await fetch_all(
        "SELECT id, image_index, image_url, drive_image_url, image_prompt FROM assets "
        "WHERE video_id=$1 AND tenant_id=$2 AND scene=$3 "
        "AND (image_url IS NOT NULL OR drive_image_url IS NOT NULL) "
        "ORDER BY image_index LIMIT $4",
        video_id, tenant_id, scene, _MAX_BOARD_IMAGES,
    )
    images = []
    # Defense-in-depth: cap client-side too, not just via the SQL LIMIT —
    # same belt-and-suspenders posture as chat.py's C15b _handle_show_op.
    for r in (rows or [])[:_MAX_BOARD_IMAGES]:
        signed = _sign_media_url(r.get("image_url") or r.get("drive_image_url"), tenant_id)
        if not signed:
            continue
        prompt = (r.get("image_prompt") or "").strip()
        snippet = prompt[:140] + ("…" if len(prompt) > 140 else "")
        images.append({
            "asset_id": str(r["id"]), "scene": scene, "index": r.get("image_index"),
            "url": signed, "prompt_snippet": snippet,
        })
    if not images:
        return _text_result({"video_id": video_id, "scene": scene, "images": [],
                             "note": f"Scene {scene} has no pictures yet."})
    return _text_result({
        "video_id": video_id, "scene": scene, "images": images,
        "note": _media_expiry_note(),
    })


async def _call_get_character_sheets(tenant_id, arguments: dict[str, Any]) -> dict[str, Any]:
    video_id = arguments.get("video_id")
    if video_id:
        video_id = str(video_id)
        from routes.characters import list_characters as _list_characters_route
        try:
            result = await _list_characters_route(video_id, tenant_id=tenant_id)
        except HTTPException as e:
            return _error_result(e.detail if isinstance(e.detail, str) else "Video not found")
        chars = (result.get("characters") or [])[:_MAX_CHARACTER_SHEETS]
        sheets = [
            {"char_id": c.get("id"), "name": c.get("name"), "status": c.get("status"),
             "url": _sign_media_url(c.get("reference_url"), tenant_id)}
            for c in chars
        ]
        return _text_result({"video_id": video_id, "characters": sheets, "note": _media_expiry_note()})

    from routes.projects import get_channel_cast as _get_channel_cast_route
    result = await _get_channel_cast_route(tenant_id=tenant_id)
    chars = (result.get("characters") or [])[:_MAX_CHARACTER_SHEETS]
    sheets = [
        {"name": c.get("name"), "url": _sign_media_url(c.get("reference_url"), tenant_id)}
        for c in chars
    ]
    return _text_result({
        "channel_cast_locked": bool(result.get("cast_locked")), "characters": sheets,
        "note": _media_expiry_note(),
    })


async def _call_get_environment_images(tenant_id, arguments: dict[str, Any]) -> dict[str, Any]:
    video_id = arguments.get("video_id")
    if not video_id:
        return _error_result("get_environment_images requires a video_id argument")
    video_id = str(video_id)
    from routes.environments import list_environments as _list_environments_route
    try:
        result = await _list_environments_route(video_id, tenant_id=tenant_id)
    except HTTPException as e:
        return _error_result(e.detail if isinstance(e.detail, str) else "Video not found")
    envs = (result.get("environments") or [])[:_MAX_ENVIRONMENT_IMAGES]
    images = [
        {"env_id": e.get("id"), "name": e.get("name"), "status": e.get("status"),
         "url": _sign_media_url(e.get("reference_url"), tenant_id)}
        for e in envs
    ]
    return _text_result({
        "video_id": video_id, "environments": images,
        "approved_at": result.get("approved_at"), "note": _media_expiry_note(),
    })


async def _call_get_thumbnail_image(tenant_id, arguments: dict[str, Any]) -> dict[str, Any]:
    video_id = arguments.get("video_id")
    if not video_id:
        return _error_result("get_thumbnail_image requires a video_id argument")
    video_id = str(video_id)
    row = await fetch_one(
        "SELECT thumbnail_url FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if row is None:
        return _error_result(f"No video {video_id} found for this tenant")
    url = row.get("thumbnail_url")
    if not url:
        return _text_result({"video_id": video_id, "url": None, "note": "No thumbnail yet."})
    return _text_result({
        "video_id": video_id, "url": _sign_media_url(url, tenant_id),
        "note": _media_expiry_note(noun="The URL"),
    })


async def _call_quick_demo_video(tenant_id, arguments: dict[str, Any],
                                  background_tasks: Optional[BackgroundTasks], caller: str) -> dict[str, Any]:
    """Staged (module docstring "TOOL SURFACE v6"): step 1 creates the video
    (free, via the SAME _call_create_video every create_video call uses);
    once a video_id exists, every further call is a THIN pass-through to
    `_call_verb(..., "build", ...)` — the exact existing meta-verb dispatcher
    (quote first, dispatch only after a redeemed confirm_token) every other
    paid tool/button already goes through. No new money logic lives here."""
    video_id = arguments.get("video_id")
    if not video_id:
        title = (arguments.get("title") or "").strip()
        if not title:
            return _error_result("quick_demo_video requires a title to create the video (first call, no video_id).")
        create_args = {"title": title}
        if arguments.get("visual_style") is not None:
            create_args["visual_style"] = arguments["visual_style"]
        if arguments.get("video_length_minutes") is not None:
            create_args["video_length_minutes"] = arguments["video_length_minutes"]
        created = await _call_create_video(tenant_id, create_args, background_tasks)
        if created.get("isError"):
            return created
        payload = json.loads(created["content"][0]["text"])
        payload["next_step"] = (
            "Call quick_demo_video again with this video_id (no confirm_token) to get a price "
            "quote for the build (script + cast + pictures)."
        )
        return _text_result(payload)

    # video_id given -> delegate to the EXACT SAME "build" verb dispatcher
    # every other paid tool/button uses (quote, then dispatch on a redeemed
    # confirm_token). No parallel quote math, no parallel confirm_tokens use.
    result = await _call_verb(tenant_id, "build", {**arguments, "video_id": str(video_id)},
                              background_tasks, caller)
    if not result.get("isError"):
        payload = json.loads(result["content"][0]["text"])
        if payload.get("status") == "started":
            payload["next_step"] = (
                "This runs in the background — poll get_video for status, then call "
                "get_scene_boards once pictures exist."
            )
            result = _text_result(payload)
    return result


# =============================================================================
# ENVIRONMENTS TOOLS (C66 — checklist "MCP process brain", tasks/decisions.md
# 2026-07-21 "MCP co-pilot must be PROCESS-AWARE": environment design was the
# NAMED skipped step in Ryan's live-driving session — it had no confirm-
# tokened MCP door at all (unlike "characters", which is a paid actions.
# ACTIONS verb already; environment DESIGN never got that verb, only
# approve_environments/skip_environments did). Every tool below wraps the
# EXISTING routes/environments.py endpoint of the same shape — no new
# generation logic, no parallel DB writes. get_environment_images (C48) is
# the read side and already covers this family's non-image metadata; it is
# NOT duplicated here.
# =============================================================================

_DESIGN_ENVIRONMENTS_TOOL: dict[str, Any] = {
    "name": "design_environments",
    "description": (
        "Design one reference image per Story Bible/script location for "
        "this video (routes/environments.py's POST /{id}/environments/"
        "design) — background job, poll get_video / get_environment_images "
        "for progress. Storyboard generation is HARD-BLOCKED "
        "(pipeline_executor._environments_ready_gate) until every video "
        "either does this (then approve_environments) or explicitly calls "
        "skip_environments. PAID — one GPT Image 2 tier picture per "
        "location. Call with no confirm_token first for a price quote; "
        "call again with the returned confirm_token to actually run it."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "video_id": {"type": "string", "description": "Video UUID."},
            "confirm_token": {"type": "string", "description": "Omit on the first call to get a quote; pass it back to run."},
        },
        "required": ["video_id"],
    },
}

_REDO_ENVIRONMENT_TOOL: dict[str, Any] = {
    "name": "redo_environment",
    "description": (
        "Regenerate ONE environment's reference image (routes/"
        "environments.py's POST /{id}/environments/{env_id}/regenerate) — "
        "the same redo an Environments tab card runs. PAID (one GPT Image "
        "2 tier picture). Call with no confirm_token first for a price "
        "quote; call again with the returned confirm_token to actually "
        "run it."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "video_id": {"type": "string", "description": "Video UUID."},
            "env_id": {"type": "string", "description": "Environment UUID (from get_environment_images)."},
            "confirm_token": {"type": "string", "description": "Omit on the first call to get a quote; pass it back to run."},
        },
        "required": ["video_id", "env_id"],
    },
}

_EDIT_ENVIRONMENT_TOOL: dict[str, Any] = {
    "name": "edit_environment",
    "description": (
        "Edit one environment's name/description/prop manifest (routes/"
        "environments.py's PATCH /{id}/environments/{env_id}). Free, no "
        "cost — redo_environment is what actually spends money against "
        "the new description. props is the C4 canonical prop manifest "
        "(6-8 {name, position} objects) injected verbatim into every "
        "scene's planning and draw prompts for this location — pass the "
        "full replacement list (an empty list clears it back to no "
        "manifest); omit to leave it untouched. material_map (D6-1) states "
        "which surfaces of this location are solid vs transparent and "
        "where the boundary runs — injected verbatim and wins over any "
        "per-scene guess."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "video_id": {"type": "string", "description": "Video UUID."},
            "env_id": {"type": "string", "description": "Environment UUID (from get_environment_images)."},
            "name": {"type": "string", "description": "New name, if changing."},
            "description": {"type": "string", "description": "New description, if changing."},
            "props": {
                "type": "array",
                "description": "Full replacement prop manifest, max 10 items. Omit to leave unchanged.",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "position": {"type": "string"},
                    },
                    "required": ["name", "position"],
                },
            },
            "material_map": {
                "type": "string",
                "description": (
                    "Which surfaces of this ONE location are solid vs transparent and "
                    "where the boundary runs, e.g. 'the outer wall is glass from floor "
                    "to shoulder height; everything above is solid metal.' Omit to "
                    "leave unchanged; empty string clears it back to no canonical map."
                ),
            },
        },
        "required": ["video_id", "env_id"],
    },
}

_DELETE_ENVIRONMENT_TOOL: dict[str, Any] = {
    "name": "delete_environment",
    "description": (
        "Delete one environment (routes/environments.py's DELETE /{id}/"
        "environments/{env_id}) — e.g. a duplicate location design made in "
        "error. Free, no cost, not reversible."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "video_id": {"type": "string", "description": "Video UUID."},
            "env_id": {"type": "string", "description": "Environment UUID (from get_environment_images)."},
        },
        "required": ["video_id", "env_id"],
    },
}

_ENVIRONMENT_TOOLS: list[dict[str, Any]] = [
    _DESIGN_ENVIRONMENTS_TOOL, _REDO_ENVIRONMENT_TOOL,
    _EDIT_ENVIRONMENT_TOOL, _DELETE_ENVIRONMENT_TOOL,
]


async def _call_design_environments(tenant_id, arguments: dict[str, Any],
                                     background_tasks: Optional[BackgroundTasks], caller: str) -> dict[str, Any]:
    video_id = arguments.get("video_id")
    if not video_id:
        return _error_result("design_environments requires a video_id argument")
    video_id = str(video_id)
    if background_tasks is None:
        return _error_result("Internal error: no task runner available for this call")
    # Quote scales with the CURRENT designed-environment count — the SAME
    # "real count, or a small default guess" pattern actions.estimate_cost's
    # own "characters" branch uses (actions.py ~L729-734), at the SAME
    # PICTURE_COST every other picture-generating tool quotes.
    row = await fetch_one(
        "SELECT count(*) AS n FROM video_environments WHERE video_id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    n = int((row or {}).get("n") or 0) or 4
    quote_cost = round(n * actions.PICTURE_COST, 2)
    ready, result = await _paid_gate(
        tenant_id, video_id, "design_environments", None,
        quote_cost, f"~${quote_cost:.2f} ({n} location(s) x ${actions.PICTURE_COST:.2f})",
        arguments.get("confirm_token"),
    )
    if not ready:
        return result
    from routes.environments import design_environments as _design_environments_route
    try:
        resp = await _design_environments_route(video_id, background_tasks, tenant_id=tenant_id)
    except HTTPException as e:
        return _error_result(e.detail if isinstance(e.detail, str) else "Couldn't start environment design")
    _log_setup_write("design_environments", tenant_id, caller, detail=video_id)
    return _text_result({"status": "started", "video_id": video_id, "message": resp.get("message")})


async def _call_redo_environment(tenant_id, arguments: dict[str, Any],
                                  background_tasks: Optional[BackgroundTasks], caller: str) -> dict[str, Any]:
    video_id = arguments.get("video_id")
    env_id = arguments.get("env_id")
    if not video_id or not env_id:
        return _error_result("redo_environment requires video_id and env_id")
    video_id = str(video_id)
    env = await fetch_one(
        "SELECT id FROM video_environments WHERE id = $1 AND video_id = $2 AND tenant_id = $3",
        str(env_id), video_id, tenant_id,
    )
    if not env:
        return _error_result(f"No environment {env_id} found on video {video_id} for this tenant")
    if background_tasks is None:
        return _error_result("Internal error: no task runner available for this call")
    ready, result = await _paid_gate(
        tenant_id, video_id, "redo_environment", str(env_id),
        actions.PICTURE_COST, f"${actions.PICTURE_COST:.2f} (one GPT Image 2 tier reference)",
        arguments.get("confirm_token"),
    )
    if not ready:
        return result
    from routes.environments import regenerate_environment as _regenerate_environment_route
    try:
        resp = await _regenerate_environment_route(video_id, str(env_id), background_tasks, tenant_id=tenant_id)
    except HTTPException as e:
        return _error_result(e.detail if isinstance(e.detail, str) else "Couldn't start the redesign")
    _log_setup_write("redo_environment", tenant_id, caller, detail=str(env_id))
    return _text_result({"status": "started", "video_id": video_id, "env_id": env_id, "message": resp.get("message")})


async def _call_edit_environment(tenant_id, arguments: dict[str, Any], caller: str) -> dict[str, Any]:
    video_id = arguments.get("video_id")
    env_id = arguments.get("env_id")
    if not video_id or not env_id:
        return _error_result("edit_environment requires video_id and env_id")
    from routes.environments import EnvironmentUpdate, update_environment as _update_environment_route
    try:
        props_arg = arguments.get("props")
        result = await _update_environment_route(
            str(video_id), str(env_id),
            EnvironmentUpdate(
                name=arguments.get("name"), description=arguments.get("description"),
                props=props_arg if props_arg is not None else None,
                material_map=arguments.get("material_map"),
            ),
            tenant_id=tenant_id,
        )
    except HTTPException as e:
        return _error_result(e.detail if isinstance(e.detail, str) else "Environment not found")
    except ValueError as e:
        return _error_result(f"Invalid props: {e}")
    _log_setup_write("edit_environment", tenant_id, caller, detail=str(env_id))
    return _text_result(result)


async def _call_delete_environment(tenant_id, arguments: dict[str, Any], caller: str) -> dict[str, Any]:
    video_id = arguments.get("video_id")
    env_id = arguments.get("env_id")
    if not video_id or not env_id:
        return _error_result("delete_environment requires video_id and env_id")
    from routes.environments import delete_environment as _delete_environment_route
    try:
        result = await _delete_environment_route(str(video_id), str(env_id), tenant_id=tenant_id)
    except HTTPException as e:
        return _error_result(e.detail if isinstance(e.detail, str) else "Environment not found")
    _log_setup_write("delete_environment", tenant_id, caller, detail=str(env_id))
    return _text_result(result)


_ENVIRONMENT_FREE_HANDLERS = {
    "edit_environment": _call_edit_environment,
    "delete_environment": _call_delete_environment,
}
_ENVIRONMENT_PAID_HANDLERS = {
    "design_environments": _call_design_environments,
    "redo_environment": _call_redo_environment,
}


# --- Voice control ------------------------------------------------------------

_SET_NARRATOR_VOICE_TOOL: dict[str, Any] = {
    "name": "set_narrator_voice",
    "description": (
        "Set this tenant's ElevenLabs narrator voice id (Settings → API "
        "Keys' elevenlabs_voice_id — docs/env-vars.md). Wraps the SAME "
        "vault write POST /api/settings/keys/elevenlabs_voice_id uses, "
        "restricted to only this one key (not a general secret-setter). "
        "Free, no cost — takes effect on the next voice run."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {"voice_id": {"type": "string", "description": "An ElevenLabs voice id."}},
        "required": ["voice_id"],
    },
}

_REDO_DIALOGUE_SCENE_VOICE_TOOL: dict[str, Any] = {
    "name": "redo_dialogue_scene_voice",
    "description": (
        "Re-synthesize ONE scene's dialogue-mode voice segments (narrator + "
        "cast lines) — POST /api/pipeline/dialogue-voice/{id}?scene=N. For "
        "narration-only videos, use the existing `voice` tool with a scene "
        "argument instead (this tool is specifically the dialogue_segments "
        "path). Resume-safe — already-voiced segments are skipped. PAID. "
        "Call with no confirm_token first to get a price quote; call again "
        "with the returned confirm_token to actually run it."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "video_id": {"type": "string", "description": "Video UUID."},
            "scene": {"type": "integer", "description": "Scene number."},
            "confirm_token": {"type": "string", "description": "Omit on the first call to get a quote; pass it back to run."},
        },
        "required": ["video_id", "scene"],
    },
}

_VOICE_TOOLS: list[dict[str, Any]] = [_SET_NARRATOR_VOICE_TOOL, _REDO_DIALOGUE_SCENE_VOICE_TOOL]


async def _call_set_narrator_voice(tenant_id, arguments: dict[str, Any], caller: str) -> dict[str, Any]:
    voice_id = (arguments.get("voice_id") or "").strip()
    if not voice_id:
        return _error_result("set_narrator_voice requires a voice_id argument")
    from routes.settings import SetKeyRequest, set_api_key as _set_api_key_route
    try:
        result = await _set_api_key_route("elevenlabs_voice_id", SetKeyRequest(value=voice_id), tenant_id=tenant_id)
    except HTTPException as e:
        return _error_result(e.detail if isinstance(e.detail, str) else "Couldn't save that voice id")
    _log_setup_write("set_narrator_voice", tenant_id, caller)
    return _text_result(result)


async def _call_redo_dialogue_scene_voice(tenant_id, arguments: dict[str, Any],
                                           background_tasks: Optional[BackgroundTasks], caller: str) -> dict[str, Any]:
    video_id = arguments.get("video_id")
    scene = _coerce_scene(arguments.get("scene"))
    if not video_id or scene is None:
        return _error_result("redo_dialogue_scene_voice requires video_id and scene")
    video_id = str(video_id)
    summary = await actions.video_summary(tenant_id, video_id)
    if summary is None:
        return _error_result(f"No video {video_id} found for this tenant")
    if background_tasks is None:
        return _error_result("Internal error: no task runner available for this call")
    # Reuses actions.estimate_cost's OWN "voice" pricing (real per-character
    # ElevenLabs estimate when the script exists, flat fallback otherwise) —
    # the same honest quote math the `voice` ACTIONS verb already gives,
    # just for the dialogue-voice endpoint instead of run_voice.
    cost, cost_text = await actions.estimate_cost(tenant_id, video_id, "voice", scene, summary)
    ready, result = await _paid_gate(
        tenant_id, video_id, "redo_dialogue_scene_voice", str(scene), cost, cost_text,
        arguments.get("confirm_token"),
    )
    if not ready:
        return result
    from routes.pipeline import run_dialogue_voice as _run_dialogue_voice_route
    try:
        resp = await _run_dialogue_voice_route(video_id, background_tasks, scene=scene, tenant_id=tenant_id)
    except HTTPException as e:
        return _error_result(e.detail if isinstance(e.detail, str) else "Couldn't start the voice run")
    _log_setup_write("redo_dialogue_scene_voice", tenant_id, caller, detail=f"scene {scene}")
    return _text_result({"status": "started", "video_id": video_id, "scene": scene, "message": resp.message})


# --- Pre-publish ---------------------------------------------------------------

_GET_PUBLISH_INFO_TOOL: dict[str, Any] = {
    "name": "get_publish_info",
    "description": (
        "This video's publish-facing fields: title, seo_description, "
        "seo_tags, seo_hashtags, seo_category_id. No media URLs. "
        "Read-only, no cost."
    ),
    "inputSchema": _VIDEO_ID_SCHEMA,
}

_EDIT_PUBLISH_INFO_TOOL: dict[str, Any] = {
    "name": "edit_publish_info",
    "description": (
        "Edit title/SEO description/tags/category before upload — wraps "
        "PATCH /api/videos/{id}/seo (title/description/tags) plus the "
        "category_id field this chunk added to youtube_publish.save_seo "
        "(previously write-only from generate_and_store_seo's own Claude "
        "call, no manual edit path existed). category accepts a friendly "
        "name (education/entertainment/howto/people/news/science/film/"
        "music/gaming) or a raw YouTube videoCategory id. Free, no cost — "
        "does not upload anything."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "video_id": {"type": "string", "description": "Video UUID."},
            "title": {"type": "string", "description": "New title, optional."},
            "description": {"type": "string", "description": "New SEO description, optional."},
            "tags": {"type": "array", "items": {"type": "string"}, "description": "New tag list, optional."},
            "category": {"type": "string", "description": "A friendly category name or raw YouTube category id, optional."},
        },
        "required": ["video_id"],
    },
}

_PUBLISH_TOOLS: list[dict[str, Any]] = [_GET_PUBLISH_INFO_TOOL, _EDIT_PUBLISH_INFO_TOOL]


async def _call_get_publish_info(tenant_id, arguments: dict[str, Any]) -> dict[str, Any]:
    video_id = arguments.get("video_id")
    if not video_id:
        return _error_result("get_publish_info requires a video_id argument")
    row = await fetch_one(
        "SELECT video_title, seo_description, seo_tags, seo_hashtags, seo_category_id "
        "FROM videos WHERE id = $1 AND tenant_id = $2",
        str(video_id), tenant_id,
    )
    if not row:
        return _error_result(f"No video {video_id} found for this tenant")
    return _text_result({
        "video_id": video_id, "title": row.get("video_title"),
        "seo_description": row.get("seo_description"), "seo_tags": row.get("seo_tags"),
        "seo_hashtags": row.get("seo_hashtags"), "seo_category_id": row.get("seo_category_id"),
    })


async def _call_edit_publish_info(tenant_id, arguments: dict[str, Any], caller: str) -> dict[str, Any]:
    video_id = arguments.get("video_id")
    if not video_id:
        return _error_result("edit_publish_info requires a video_id argument")
    from youtube_publish import save_seo as _save_seo
    body: dict[str, Any] = {}
    if arguments.get("title") is not None:
        body["title"] = arguments["title"]
    if arguments.get("description") is not None:
        body["description"] = arguments["description"]
    if arguments.get("tags") is not None:
        body["tags"] = arguments["tags"]
    if arguments.get("category") is not None:
        body["category_id"] = arguments["category"]
    if not body:
        return _error_result("edit_publish_info needs at least one of title/description/tags/category")
    video = await fetch_one("SELECT id FROM videos WHERE id = $1 AND tenant_id = $2", str(video_id), tenant_id)
    if not video:
        return _error_result(f"No video {video_id} found for this tenant")
    result = await _save_seo(str(video_id), tenant_id, **body)
    _log_setup_write("edit_publish_info", tenant_id, caller, detail=",".join(body.keys()))
    return _text_result(result)


# --- Analytics reads -----------------------------------------------------------

_GET_STYLE_PERFORMANCE_TOOL: dict[str, Any] = {
    "name": "get_style_performance",
    "description": (
        "Performance grouped by the creative choice that produced it — "
        "visual style preset, render look, script voice, and dominant clip "
        "model (GET /api/analytics/by-style, same aggregation the copilot's "
        "channel_data tool reads). Read-only, no cost."
    ),
    "inputSchema": {"type": "object", "properties": {}},
}

_GET_TOP_CHANNEL_VIDEOS_TOOL: dict[str, Any] = {
    "name": "get_top_channel_videos",
    "description": (
        "This tenant's OWN top-performing published videos, ranked by view "
        "count, each with views-per-hour (VPH, own_vph.compute_own_vph — "
        "the SAME math the competitor side uses) and CTR/retention — the "
        "'model this video' recipe's own-channel data feed (decisions.md "
        "2026-07-19). Wraps GET /api/analytics/videos. No media URLs — "
        "thumbnail_url dropped, watch_url replaced with youtube_video_id. "
        "Read-only, no cost."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {"top_n": {"type": "integer", "description": "How many, ranked by views (default 10, max 50)."}},
    },
}

_ANALYTICS_TOOLS: list[dict[str, Any]] = [_GET_STYLE_PERFORMANCE_TOOL, _GET_TOP_CHANNEL_VIDEOS_TOOL]


async def _call_get_style_performance(tenant_id, arguments: dict[str, Any]) -> dict[str, Any]:
    from routes.analytics import get_by_style_performance as _get_by_style_performance_route
    result = await _get_by_style_performance_route(tenant_id=tenant_id)
    return _text_result(result.model_dump())


async def _call_get_top_channel_videos(tenant_id, arguments: dict[str, Any]) -> dict[str, Any]:
    from routes.analytics import get_channel_videos as _get_channel_videos_route
    raw_n = arguments.get("top_n") or 10
    try:
        top_n = max(1, min(int(raw_n), 50))
    except (TypeError, ValueError):
        top_n = 10
    rows = await _get_channel_videos_route(limit=200, tenant_id=tenant_id)
    ranked = sorted(rows, key=lambda r: r.get("views") or 0, reverse=True)[:top_n]
    videos = []
    for r in ranked:
        row = dict(r)
        row.pop("thumbnail_url", None)  # C25a hold
        row.pop("watch_url", None)      # C25a hold — youtube_video_id is the reference, not a media link
        videos.append(row)
    return _text_result({"videos": videos, "total_on_channel": len(rows)})


# --- Reference-modeling reads ("model this video" ingredients) ----------------

_PULL_REFERENCE_VIDEO_TOOL: dict[str, Any] = {
    "name": "pull_reference_video_metadata",
    "description": (
        "Pull a YouTube video's metadata + transcript via yt-dlp — the SAME "
        "extraction Model-A-Video's own reference-video ingestion uses "
        "(routes.niche._extract_video_info), exposed as a plain read so an "
        "agent can look at a reference video BEFORE committing to the full "
        "paid POST /api/model-video flow. Runs synchronously (a single-"
        "video pull is seconds, not the multi-minute learn_channel_start "
        "case — kept a plain read rather than a start/poll shape; if a live "
        "run shows this actually stalls the request, that decision should "
        "flip). No thumbnail image (C25a hold) — title, channel, "
        "description, view/like counts, upload date, duration, and a "
        "transcript excerpt (first 4000 chars) only. Read-only, no cost "
        "(yt-dlp, not a paid API)."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {"video_url": {"type": "string", "description": "A YouTube video URL or bare 11-character video id."}},
        "required": ["video_url"],
    },
}

_GET_CHANNEL_TOP_PERFORMERS_TOOL: dict[str, Any] = {
    "name": "get_channel_top_performers",
    "description": (
        "Top-performing scraped videos for ONE tracked competitor/reference "
        "channel, ranked by views — the 'model this video' recipe's "
        "top-performer-analysis step (decisions.md 2026-07-19: 'title ideas "
        "based on looking at a channel's top 3 videos'). Wraps GET /api/"
        "niche/videos with sort=views_desc, filtered to `channel`. No media "
        "URLs — thumbnail_url/url/channel_url dropped, video_id kept as the "
        "reference. Read-only, no cost."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "channel": {"type": "string", "description": "A tracked channel name (see list_channels' GET /api/niche/channels for the catalog)."},
            "top_n": {"type": "integer", "description": "How many, ranked by views (default 3, max 25)."},
        },
        "required": ["channel"],
    },
}

_SCORE_TITLE_GAP_STRUCTURES_TOOL: dict[str, Any] = {
    "name": "score_title_gap_structures",
    "description": (
        "Score a story (hook/thesis/facts) against the 5 curiosity-gap "
        "title structures (hidden_flaw, asymmetric_dg, time_bomb, "
        "paradigm_shift, illusion_control) — the SAME deterministic scorer "
        "title_idea/curiosity_gap/gap_title_engine.score_structures uses "
        "before it ever calls Claude, exposed here as a pure, free, no-cost "
        "step you can reason over yourself (writing the actual title text "
        "is suggest_video_titles or your own judgment) — the engine's "
        "Claude-calling half needs a tenant-scoped key it doesn't have in "
        "this codebase (see the C49 report's 'no existing seam' note), so "
        "only the scoring half is wrapped. Free, no cost — pure scoring, no "
        "API call."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "hook": {"type": "string", "description": "The story's hook/cold-open line."},
            "thesis": {"type": "string", "description": "The story's core thesis/claim."},
            "facts": {"type": "array", "items": {"type": "string"}, "description": "Key supporting facts."},
        },
        "required": ["hook", "thesis"],
    },
}

_SUGGEST_VIDEO_TITLES_TOOL: dict[str, Any] = {
    "name": "suggest_video_titles",
    "description": (
        "[USES WORKSPACE API KEYS — prefer doing this thinking yourself: "
        "brainstorm titles in this chat (score_title_gap_structures is a "
        "free, deterministic scorer you can run yourself to check your "
        "ideas against the 5 curiosity-gap structures). Use this tool only "
        "as a fallback, when you want the platform's own generator to do it "
        "instead.] Generate title options for a topic (POST /api/videos/"
        "suggest-titles) — the platform-native title generator "
        "(curiosity-driven, channel-aware). Pair with "
        "score_title_gap_structures if you want to reason about WHICH "
        "curiosity-gap angle to write toward first. No confirm_token — "
        "uses the tenant's own configured Claude/kie.ai key."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "topic": {"type": "string", "description": "The video topic."},
            "context": {"type": "string", "description": "Extra context/angle, optional."},
            "count": {"type": "integer", "description": "How many titles (default 5)."},
        },
        "required": ["topic"],
    },
}

_GENERATE_MODELED_IDEAS_TOOL: dict[str, Any] = {
    "name": "generate_modeled_ideas",
    "description": (
        "[USES WORKSPACE API KEYS — prefer doing this thinking yourself: "
        "decompose the seed titles into formula patterns and rebuild them "
        "with your own niche variables right here in this chat, no tool "
        "call needed. Use this tool only as a fallback, when you want the "
        "platform's own engine to do it instead.] Generate new video title "
        "ideas by decomposing proven titles into reusable formula patterns, "
        "then rebuilding them with your own niche variables — "
        "title_idea/idea_modeling.py's brain (the same engine "
        "trending_idea_bot.py's format-library step runs), wired here as a "
        "thin wrap: decompose_title per seed title -> extract_format -> "
        "generate_modeled_ideas, no new pipeline logic (C59). No "
        "confirm_token — uses the tenant's OWN configured Anthropic key "
        "directly (BYOK, not billed by StoryEngine), same as "
        "regenerate_scene_text/suggest_video_titles."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "seed_titles": {
                "type": "array", "items": {"type": "string"},
                "description": "2+ proven/high-performing titles to decompose into reusable formula patterns.",
            },
            "niche_variables": {
                "type": "object",
                "description": "Key -> list of niche variables to rebuild formats with, e.g. {\"topics\": [...], \"entities\": [...]}.",
            },
            "num_ideas": {"type": "integer", "description": "How many ideas to generate (default 5)."},
        },
        "required": ["seed_titles", "niche_variables"],
    },
}

_GENERATE_GAP_TITLES_TOOL: dict[str, Any] = {
    "name": "generate_gap_titles",
    "description": (
        "[USES WORKSPACE API KEYS — prefer doing this thinking yourself: "
        "score your hook/thesis/facts with the free score_title_gap_"
        "structures tool, then write the titles + thumbnail text/approach "
        "+ reasoning yourself in this chat. Use this tool only as a "
        "fallback, when you want the platform's own engine to do it "
        "instead.] Generate full curiosity-gap titles (text + thumbnail "
        "text/approach + reasoning) for a story — GapTitleEngine's complete "
        "generation pass (title_idea/curiosity_gap/gap_title_engine.py), "
        "the Claude-calling half score_title_gap_structures deliberately "
        "leaves unwrapped. Pair with score_title_gap_structures if you "
        "first want the pure scoring read on the same hook/thesis/facts. No "
        "confirm_token — uses the tenant's OWN configured Anthropic key "
        "directly (BYOK, not billed by StoryEngine), same as "
        "regenerate_scene_text/suggest_video_titles."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "hook": {"type": "string", "description": "The story's hook/cold-open line."},
            "thesis": {"type": "string", "description": "The story's core thesis/claim."},
            "facts": {"type": "array", "items": {"type": "string"}, "description": "Key supporting facts."},
            "target_count": {"type": "integer", "description": "How many titles to generate (default 3)."},
        },
        "required": ["hook", "thesis"],
    },
}

_REFERENCE_MODELING_TOOLS: list[dict[str, Any]] = [
    _PULL_REFERENCE_VIDEO_TOOL, _GET_CHANNEL_TOP_PERFORMERS_TOOL,
    _SCORE_TITLE_GAP_STRUCTURES_TOOL, _SUGGEST_VIDEO_TITLES_TOOL,
    _GENERATE_MODELED_IDEAS_TOOL, _GENERATE_GAP_TITLES_TOOL,
]


def _looks_like_youtube_id(s: str) -> bool:
    return len(s) == 11 and all(c.isalnum() or c in "_-" for c in s)


def _ensure_pipeline_on_path() -> None:
    """Put skills/video-pipeline on sys.path so the legacy title-modeling
    modules (title_idea.*) are importable from this SaaS-backend route.
    Idempotent — same insertion _call_score_title_gap_structures already
    did inline; factored out here since C59 needs it in two more places."""
    import sys as _sys
    from pathlib import Path as _Path
    pipeline_root = _Path(__file__).resolve().parent.parent.parent.parent / "skills" / "video-pipeline"
    if str(pipeline_root) not in _sys.path:
        _sys.path.insert(0, str(pipeline_root))


async def _resolve_tenant_anthropic_client(tenant_id):
    """Tenant-scoped BYOK Anthropic client for the two C59 tools below,
    whose underlying skills/video-pipeline functions (idea_modeling's
    decompose_title/generate_modeled_ideas, GapTitleEngine) take a raw
    client OBJECT — not an api_key string — as their injection point. Same
    vault-key resolution routes/videos.py::rewrite_scene_text uses for
    regenerate_scene_text (get_secret("anthropic_api_key", tenant_id)).
    Returns None if the tenant has no key configured; callers turn that
    into the same error wording rewrite_scene_text raises.
    """
    from vault import get_secret
    api_key = await get_secret("anthropic_api_key", tenant_id)
    if not api_key:
        return None
    _ensure_pipeline_on_path()
    from shared.clients.anthropic_client import AnthropicClient
    return AnthropicClient(api_key=api_key)


_NO_ANTHROPIC_KEY_ERROR = "Anthropic API key required. Configure it in Settings > API Keys."


async def _call_pull_reference_video_metadata(tenant_id, arguments: dict[str, Any]) -> dict[str, Any]:
    raw = (arguments.get("video_url") or "").strip()
    if not raw:
        return _error_result("pull_reference_video_metadata requires a video_url argument")
    from routes.model_video import _parse_youtube_id
    from routes.niche import _extract_video_info
    video_id = _parse_youtube_id(raw) or (raw if _looks_like_youtube_id(raw) else None)
    if not video_id:
        return _error_result("Couldn't parse a YouTube video id from that URL")
    info = await asyncio.to_thread(_extract_video_info, video_id)
    if not info:
        return _error_result(
            "Couldn't fetch that video — it may be private/deleted, or this server's egress IP is "
            "bot-blocked by YouTube (see YTDLP_COOKIES_FILE/YTDLP_PROXY in docs/env-vars.md)."
        )
    return _text_result({
        "video_id": info.get("video_id"), "title": info.get("title"), "channel": info.get("channel"),
        "description": info.get("description"), "views": info.get("views"), "likes": info.get("likes"),
        "comment_count": info.get("comment_count"), "published_at": info.get("published_at"),
        "duration_seconds": info.get("duration_seconds"), "transcript_excerpt": (info.get("transcript") or "")[:4000],
    })


async def _call_get_channel_top_performers(tenant_id, arguments: dict[str, Any]) -> dict[str, Any]:
    channel = (arguments.get("channel") or "").strip()
    if not channel:
        return _error_result("get_channel_top_performers requires a channel argument")
    raw_n = arguments.get("top_n") or 3
    try:
        top_n = max(1, min(int(raw_n), 25))
    except (TypeError, ValueError):
        top_n = 3
    from routes.niche import list_videos as _list_videos_route
    result = await _list_videos_route(limit=top_n, offset=0, channel=channel, sort="views_desc", tenant_id=tenant_id)
    videos = []
    for r in (result.get("videos") or []):
        row = dict(r)
        row.pop("thumbnail_url", None)  # C25a hold
        row.pop("url", None)
        row.pop("channel_url", None)
        videos.append(row)
    return _text_result({"channel": channel, "videos": videos, "total_for_channel": result.get("total")})


async def _call_score_title_gap_structures(tenant_id, arguments: dict[str, Any]) -> dict[str, Any]:
    _ensure_pipeline_on_path()
    from title_idea.curiosity_gap.gap_title_engine import score_structures
    story_context = {
        "hook": arguments.get("hook") or "", "thesis": arguments.get("thesis") or "",
        "facts": arguments.get("facts") or [],
    }
    scored = score_structures(story_context)
    return _text_result({
        "structures": [
            {"structure": s.structure.value, "confidence": s.confidence, "reasoning": s.reasoning}
            for s in scored
        ],
    })


async def _call_suggest_video_titles(tenant_id, arguments: dict[str, Any], caller: str) -> dict[str, Any]:
    topic = (arguments.get("topic") or "").strip()
    if not topic:
        return _error_result("suggest_video_titles requires a topic argument")
    from routes.videos import SuggestTitlesRequest, suggest_titles as _suggest_titles_route
    body = SuggestTitlesRequest(topic=topic, context=arguments.get("context"), count=int(arguments.get("count") or 5))
    try:
        result = await _suggest_titles_route(body, tenant_id=tenant_id)
    except HTTPException as e:
        return _error_result(e.detail if isinstance(e.detail, str) else "Couldn't generate title ideas")
    _log_setup_write("suggest_video_titles", tenant_id, caller, detail=topic)
    return _text_result(result)


async def _call_generate_modeled_ideas(tenant_id, arguments: dict[str, Any], caller: str) -> dict[str, Any]:
    seed_titles = arguments.get("seed_titles") or []
    niche_variables = arguments.get("niche_variables") or {}
    if not isinstance(seed_titles, list) or not seed_titles:
        return _error_result("generate_modeled_ideas requires a seed_titles array (2+ proven titles)")
    if not isinstance(niche_variables, dict) or not niche_variables:
        return _error_result("generate_modeled_ideas requires a niche_variables object")
    try:
        num_ideas = max(1, min(int(arguments.get("num_ideas") or 5), 20))
    except (TypeError, ValueError):
        num_ideas = 5

    client = await _resolve_tenant_anthropic_client(tenant_id)
    if client is None:
        return _error_result(_NO_ANTHROPIC_KEY_ERROR)

    from title_idea.idea_modeling import decompose_title, extract_format, generate_modeled_ideas

    decomposed = []
    for title in seed_titles:
        d = await decompose_title(str(title), client)
        if d:
            decomposed.append(d)
    if not decomposed:
        return _error_result("Couldn't decompose any of the given seed_titles into a formula pattern — try clearer, more concrete titles")

    formats = extract_format(decomposed)
    ideas = await generate_modeled_ideas(formats, {"niche_variables": niche_variables}, client, num_ideas=num_ideas)
    _log_setup_write("generate_modeled_ideas", tenant_id, caller, detail=f"{len(seed_titles)} seeds -> {len(ideas)} ideas")
    return _text_result({"formats_extracted": len(formats), "ideas": ideas})


async def _call_generate_gap_titles(tenant_id, arguments: dict[str, Any], caller: str) -> dict[str, Any]:
    hook = (arguments.get("hook") or "").strip()
    thesis = (arguments.get("thesis") or "").strip()
    if not hook or not thesis:
        return _error_result("generate_gap_titles requires hook and thesis")
    try:
        target_count = max(1, min(int(arguments.get("target_count") or 3), 10))
    except (TypeError, ValueError):
        target_count = 3

    client = await _resolve_tenant_anthropic_client(tenant_id)
    if client is None:
        return _error_result(_NO_ANTHROPIC_KEY_ERROR)

    from title_idea.curiosity_gap.gap_title_engine import GapTitleEngine

    story_context = {"hook": hook, "thesis": thesis, "facts": arguments.get("facts") or []}
    engine = GapTitleEngine(client)
    titles = await engine.generate_titles(story_context, target_count=target_count)
    _log_setup_write("generate_gap_titles", tenant_id, caller, detail=f"{len(titles)} titles")
    return _text_result({
        "titles": [
            {
                "text": t.text, "structure": t.structure.value, "confidence": t.structure_confidence,
                "thumbnail_text": t.thumbnail_text, "thumbnail_approach": t.thumbnail_approach,
                "reasoning": t.reasoning,
            }
            for t in titles
        ],
    })


_ATOMIC_TOOLS: list[dict[str, Any]] = (
    _SHOT_TOOLS + _SCRIPT_SURGERY_TOOLS + _CHARACTER_TOOLS + _VOICE_TOOLS
    + _PUBLISH_TOOLS + _ANALYTICS_TOOLS + _REFERENCE_MODELING_TOOLS
)

# Reads (no tenant-scoped extra args beyond video_id, or none at all).
_ATOMIC_READ_HANDLERS = {
    "get_shots": _call_get_shots,
    "get_scene_script": _call_get_scene_script,
    "get_characters": _call_get_characters,
    "get_publish_info": _call_get_publish_info,
    "get_style_performance": _call_get_style_performance,
    "get_top_channel_videos": _call_get_top_channel_videos,
    "pull_reference_video_metadata": _call_pull_reference_video_metadata,
    "get_channel_top_performers": _call_get_channel_top_performers,
    "score_title_gap_structures": _call_score_title_gap_structures,
}

# Free writes needing (tenant_id, arguments, caller).
_ATOMIC_FREE_HANDLERS = {
    "edit_shot_image_prompt": _call_edit_shot_image_prompt,
    "edit_shot_motion_prompt": _call_edit_shot_motion_prompt,
    "set_shot_model_override": _call_set_shot_model_override,
    "improve_prompt": _call_improve_prompt,
    "edit_scene_text": _call_edit_scene_text,
    "regenerate_scene_text": _call_regenerate_scene_text,
    "edit_character": _call_edit_character,
    "set_narrator_voice": _call_set_narrator_voice,
    "edit_publish_info": _call_edit_publish_info,
    "suggest_video_titles": _call_suggest_video_titles,
    "generate_modeled_ideas": _call_generate_modeled_ideas,
    "generate_gap_titles": _call_generate_gap_titles,
}

# Paid tools needing (tenant_id, arguments, background_tasks, caller).
_ATOMIC_PAID_HANDLERS = {
    "redraw_shot": _call_redraw_shot,
    "redo_character_sheet": _call_redo_character_sheet,
    "redo_dialogue_scene_voice": _call_redo_dialogue_scene_voice,
}

# C48 media reads: (tenant_id, arguments) — same shape as _ATOMIC_READ_HANDLERS.
_MEDIA_READ_HANDLERS = {
    "get_scene_boards": _call_get_scene_boards,
    "get_character_sheets": _call_get_character_sheets,
    "get_environment_images": _call_get_environment_images,
    "get_thumbnail_image": _call_get_thumbnail_image,
}

# C48 quick_demo_video: (tenant_id, arguments, background_tasks, caller) — same
# shape as _ATOMIC_PAID_HANDLERS (it needs background_tasks for both the free
# create_video step and the "build" verb pass-through).
_MEDIA_STAGED_HANDLERS = {
    "quick_demo_video": _call_quick_demo_video,
}


TOOLS: list[dict[str, Any]] = (
    _READ_TOOLS + [_CREATE_VIDEO_TOOL] + _verb_tools() + _SETUP_TOOLS
    + _AUTOPILOT_PROPOSAL_TOOLS + _AUTOPILOT_DIAL_TOOLS + _INGEST_TOOLS
    + _ATOMIC_TOOLS + _FEATURE_BOARD_TOOLS + _MEDIA_TOOLS + _ENVIRONMENT_TOOLS
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
        # Streamable HTTP spec, lifecycle/initialize: the server negotiates
        # protocolVersion, it doesn't just parrot its own preferred value —
        # a client that sent an older-but-still-Streamable-HTTP version
        # (e.g. 2025-03-26) and gets back a version string it's never heard
        # of ("2025-06-18") is free to treat that as a mismatch and bail.
        # Echo the client's request when it's one of the versions this
        # transport can honestly speak; otherwise fall back to our own
        # default (the spec's own guidance when the requested version isn't
        # supported: respond with a version the server DOES support).
        requested = (params or {}).get("protocolVersion")
        negotiated = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else PROTOCOL_VERSION
        return {
            "protocolVersion": negotiated,
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
            # C66: the process paragraph is built LIVE from production_guide.
            # GUIDE_STAGES on every initialize call (never baked into a module
            # constant) — the single source the get_production_guide tool
            # itself reads. A test that monkeypatches GUIDE_STAGES and
            # re-dispatches "initialize" proves this stays one source, not a
            # hand-typed copy that can drift from the tool's real behavior.
            "instructions": SERVER_INSTRUCTIONS + "\n\n" + production_guide.build_process_instructions(),
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
        if name in _ATOMIC_READ_HANDLERS:
            return await _ATOMIC_READ_HANDLERS[name](tenant_id, arguments)
        if name in _ATOMIC_FREE_HANDLERS:
            return await _ATOMIC_FREE_HANDLERS[name](tenant_id, arguments, caller)
        if name in _ATOMIC_PAID_HANDLERS:
            return await _ATOMIC_PAID_HANDLERS[name](tenant_id, arguments, background_tasks, caller)
        if name in _MEDIA_READ_HANDLERS:
            return await _MEDIA_READ_HANDLERS[name](tenant_id, arguments)
        if name in _MEDIA_STAGED_HANDLERS:
            return await _MEDIA_STAGED_HANDLERS[name](tenant_id, arguments, background_tasks, caller)
        if name in _ENVIRONMENT_FREE_HANDLERS:
            return await _ENVIRONMENT_FREE_HANDLERS[name](tenant_id, arguments, caller)
        if name in _ENVIRONMENT_PAID_HANDLERS:
            return await _ENVIRONMENT_PAID_HANDLERS[name](tenant_id, arguments, background_tasks, caller)
        if name in _FEATURE_BOARD_READ_HANDLERS:
            return await _FEATURE_BOARD_READ_HANDLERS[name](tenant_id, arguments)
        if name in _FEATURE_BOARD_WRITE_HANDLERS:
            return await _FEATURE_BOARD_WRITE_HANDLERS[name](tenant_id, arguments, caller)
        return _error_result(f"Unknown tool: {name}")
    raise ValueError(f"Unknown method: {method}")


def _new_session_id() -> str:
    """Streamable HTTP spec, Session Management point 1: 'SHOULD be globally
    unique and cryptographically secure ... MUST only contain visible ASCII
    characters (0x21-0x7E)'. `token_urlsafe`'s alphabet (A-Za-z0-9-_) is a
    strict subset of that range. Stateless by design (module docstring/task
    brief): this is never stored or looked up server-side — any value we
    handed out on a prior `initialize` is accepted back verbatim on later
    requests because nothing here validates it against anything. That's the
    whole contract: a session id a client can round-trip, not a session the
    server tracks."""
    return secrets.token_urlsafe(24)


@router.post("")
async def mcp_rpc(request: Request, background_tasks: BackgroundTasks,
                   tenant_id=Depends(get_agent_tenant_id)):
    """Single JSON-RPC 2.0 endpoint. See module docstring for the protocol
    shape this implements (initialize / tools/list / tools/call only).

    C25a-fix11: also speaks the two other things the Streamable HTTP spec
    (2025-03-26 "Sending Messages to the Server") requires of THIS half of
    the transport — everything else (Accept-header tolerance, the GET listen
    stream, Mcp-Session-Id issuance) is either already true by omission or
    added below/alongside this handler; see that section of the module
    docstring... actually see the two additions inline here:
      1. A JSON-RPC *notification* (no `id` key at all — distinct from a
         request whose `id` happens to be null) gets HTTP 202 Accepted with
         NO body, never a JSON-RPC envelope. This was the actual break: the
         official MCP client sends `notifications/initialized` right after
         `initialize` succeeds, and this endpoint used to run it through the
         same `_dispatch` as every request, which doesn't recognize that
         method and raised -> a 200 carrying a JSON-RPC `-32601` error body
         where the client expected a bare 202. Confirmed by curl against
         prod pre-fix (see chunk report) and matches the spec's own point 4
         verbatim.
      2. `Mcp-Session-Id` is issued (not required) on `initialize`'s
         response header, per Session Management point 1.
    """
    body = await request.json()
    is_notification = "id" not in body
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

    if is_notification:
        # Best-effort dispatch, result discarded either way — a notification
        # never gets a JSON-RPC response of any shape (success OR error).
        # notifications/initialized (the only one a tool-calling client
        # sends today) has nothing for this stateless server to do; any
        # other/unknown notification method is equally a no-op here, not a
        # -32601 — the whole point of a notification is the sender doesn't
        # want a reply.
        try:
            await _dispatch(method, params, tenant_id, background_tasks, caller)
        except Exception:
            pass
        return Response(status_code=202)

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

    response = JSONResponse({"jsonrpc": "2.0", "id": rpc_id, "result": result})
    if method == "initialize":
        response.headers["Mcp-Session-Id"] = _new_session_id()
    return response


@router.get("")
async def mcp_listen(tenant_id=Depends(get_agent_tenant_id)) -> StreamingResponse:
    """Streamable HTTP spec, "Listening for Messages from the Server": a
    client MAY GET the MCP endpoint to open a standalone SSE stream for
    server-initiated messages. The bare single-POST endpoint this chunk
    started from had no GET route at all, so FastAPI's own routing 405'd it
    — spec-legal (point 3: "MUST either return text/event-stream ... or
    else 405"), but the official MCP TypeScript SDK (what Claude Code's
    client is built on) opens this GET listen stream unconditionally right
    after `initialize`/`notifications/initialized` succeed, as a normal part
    of connecting — not an optional probe it shrugs off. A real SSE stream
    here, even an empty one, is the honest v1: `get_agent_tenant_id` still
    gates it (same 401 as POST for a missing/invalid/revoked token — the
    dependency runs, and 401s, before a single byte of the stream body is
    written), and since this server has no server-initiated JSON-RPC
    messages to push (no sampling, no server-initiated notifications), the
    stream opens and closes cleanly rather than holding the connection open
    forever for pushes that will never come — spec point "The server MAY
    close the SSE stream at any time" covers exactly this."""
    async def _stream() -> AsyncIterator[bytes]:
        yield b": storyengine mcp - no server-initiated messages\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")
