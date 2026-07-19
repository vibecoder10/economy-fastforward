"""StoryEngine MCP server — the "talk to it from Claude" door (checklist
P2.4a, chunk C26; tasks/storyengine-copilot-ux-map.md §7, "the
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
header. This server has zero server-initiated notifications and no
long-running tool in v1, so there is nothing the fuller "Streamable HTTP"
transport would buy today. Whether a real external MCP client (Claude
Desktop, Claude Code's `mcp add`) needs the fuller transport instead of a
bare JSON-RPC POST is exactly the open question C29's live-client loop test
answers (tasks/live-verification-queue.md §C26) — deferred, not decided
here.

Tool surface v1 (deliberately minimal — C27 expands it with the money-gated
paid verbs):
  - list_videos: id/title/status, tenant-scoped, read-only.
  - get_video: actions.video_summary() as-is, tenant-scoped, read-only.

Explicitly EXCLUDED from v1 (docs/reports/2026-07-17-storyengine-agent-
audit-findings.md §S5):
  - Any paid/generation verb (create_video, draft_pass, finalize,
    upload_draft_to_youtube, ...) — no quote/confirm_token money gate exists
    in this chunk yet; that is C27's whole job. Zero paid tools ship here.
  - Any memory-writing tool (remember/forget) — S5-2 says MCP v1 must
    EXCLUDE memory-writing tools outright, not merely confirm-gate them.
  - Any media/asset URL in a tool result — C25a (the Drive media-proxy
    tenant-auth fix) is HELD pending a coordinated deploy. video_summary()
    never returns image/video URLs (it's title/status/counts/spend only) so
    this falls out for free today, but is called out explicitly so a future
    chunk doesn't "helpfully" add one before C25a ships.

Auth: get_agent_tenant_id (auth_agent.py) — the DISTINCT agent-token
dependency (S5-4), never auth.verify_token/get_tenant_id.
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

import actions
from auth_agent import get_agent_tenant_id
from database import fetch_all

router = APIRouter(prefix="/api/mcp", tags=["mcp"])

PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "storyengine", "version": "1.0.0"}

# Read-only, tenant-scoped, no paid verbs, no memory writes (S5-2), no media
# URLs (C25a not deployed yet) — see module docstring for the full rationale.
TOOLS: list[dict[str, Any]] = [
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
        "inputSchema": {
            "type": "object",
            "properties": {
                "video_id": {"type": "string", "description": "Video UUID."},
            },
            "required": ["video_id"],
        },
    },
]

# Names only — used by tests to pin the surface never silently grows a
# write/paid/memory tool.
TOOL_NAMES = frozenset(t["name"] for t in TOOLS)


def _text_result(payload: Any) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(payload)}], "isError": False}


def _error_result(message: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": message}], "isError": True}


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


_TOOL_HANDLERS = {
    "list_videos": _call_list_videos,
    "get_video": _call_get_video,
}


async def _dispatch(method: str, params: dict[str, Any], tenant_id) -> Any:
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
        handler = _TOOL_HANDLERS.get(name)
        if handler is None:
            return _error_result(f"Unknown tool: {name}")
        return await handler(tenant_id, arguments)
    raise ValueError(f"Unknown method: {method}")


@router.post("")
async def mcp_rpc(request: Request, tenant_id=Depends(get_agent_tenant_id)):
    """Single JSON-RPC 2.0 endpoint. See module docstring for the protocol
    shape this implements (initialize / tools/list / tools/call only)."""
    body = await request.json()
    rpc_id = body.get("id")
    method = body.get("method")
    params = body.get("params") or {}
    try:
        result = await _dispatch(method, params, tenant_id)
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
